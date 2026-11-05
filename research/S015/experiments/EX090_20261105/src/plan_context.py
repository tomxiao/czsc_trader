"""C9700 sample migration using existing public CN V4 interfaces only."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
from pathlib import Path
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from dataclasses import asdict
import json
from importlib.metadata import version
import pandas as pd
from dataflows import (InstrumentId,MarketId,AssetClass,SourceRef,TradingSession,TimeInterval,BarFrequency,
    EquitySourceCoverage,EquityFrequencyFacts,versioned_equity_bindings,ProviderConfig,ProviderBinding,EquityProduct)
from dataflows.equity_data import equity_metadata
from strategy_runtime import (ResearchExecutionSpec,CnEquitySpec,AccountPolicy,CashAvailabilityPolicy,
    EquityStrategyDefinition,EquityStrategyCandidate,equity_source_hash,EquityAuxiliaryInput,ExecutionResources)
from strategy_runtime.equity_replay import StrategyStateSchema,StateField,StateValueType,StateRecord
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.replay_contracts import StrategyComputation
from strategy_runtime.identity import ImplementationDependency
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import (ResearchBatchRef,ExperimentRef,EquitySources,EquityEvaluationRequest,
    EvaluationBenchmark,EquityBuyHold,ResearchExecutionSession,EvaluationEvidenceWrite,MaterialEvidenceWrite)

ROOT=Path(__file__).resolve().parents[5]
HOME=Path(__file__).resolve().parents[1]
OUT=HOME/'others'
OUT.mkdir(exist_ok=True)
INPUT=ROOT/'research/S015/experiments/EX087_20261105/others'
ZONE=ZoneInfo('Asia/Shanghai')
EXP=ExperimentRef('S015','EX090_20261105')

def read(p): return json.loads(p.read_text(encoding='utf-8'))
def save(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')
def at(d,h,m=0): return datetime.combine(d,time(h,m),ZONE)

def frozen_context():
    calendar=pd.read_parquet(INPUT/'calendar_extended.parquet')
    dates=pd.to_datetime(calendar.loc[calendar.IsOpen==1,'Date']).dt.date.tolist()
    last=date(2026,10,21)
    sessions=tuple(TradingSession(d,str(ZONE),(TimeInterval(at(d,9,30),at(d,11,30)),TimeInterval(at(d,13),at(d,15)))) for d in dates if d<=last)
    next_day={d:dates[i+1] for i,d in enumerate(dates[:-1])}
    instrument=InstrumentId(MarketId.CN,AssetClass.ETF,'159326.SZ')
    source=SourceRef('s015-saved-tushare-raw','ex087-v1')
    auxsource=SourceRef('s015-saved-tushare-observations','ex087-v1')
    raw=pd.read_parquet(INPUT/'raw_complete.parquet')
    hfq=pd.read_parquet(INPUT/'hfq_complete.parquet')
    minute=pd.read_parquet(INPUT/'intraday_complete.parquet')
    limits=pd.read_parquet(INPUT/'limits_complete.parquet')
    limits.index=pd.to_datetime(limits.Date).dt.date
    # Verify refreshed source overlap with the immutable old preparation.
    checks={}
    for oldname,new in [('execution',raw),('market',hfq),('intraday',minute)]:
        old=pd.read_parquet(INPUT/(oldname+'.parquet'))
        a=old.set_index(pd.to_datetime(old.Date)); b=new.set_index(pd.to_datetime(new.Date)).loc[a.index]
        difference=float((a[['Open','High','Low','Close','Volume','Amount']]-b[['Open','High','Low','Close','Volume','Amount']]).abs().max().max())
        checks[oldname]={'rows':len(a),'max_absolute_difference':difference}
        assert difference==0,(oldname,difference)
    save(OUT/'plan_input_overlap.json',checks)
    def bar_frame(frame,freq):
        f=frame.copy(); stamps=pd.to_datetime(f.Date)
        if freq is BarFrequency.DAILY:
            f['Date']=[at(d,15) for d in stamps.dt.date]
            f['BarStart']=[at(d,9,30) for d in stamps.dt.date]
            f['AvailableDate']=[at(d,17) for d in stamps.dt.date]
        else:
            f['Date']=stamps.dt.tz_localize(ZONE)
            f['BarStart']=f.Date-pd.Timedelta(minutes=30)
            f['AvailableDate']=f.Date
        return f
    rawbars=bar_frame(raw,BarFrequency.DAILY)
    hfqbars=bar_frame(hfq,BarFrequency.DAILY)
    minutebars=bar_frame(minute,BarFrequency.M30)
    rules=pd.DataFrame({'Date':rawbars.BarStart,'AvailableDate':rawbars.BarStart,'QuantityStep':100,'PriceTick':.001,
        'Tradable':True,'SellRemainderPolicy':'FULL_LIQUIDATION','PriceLimitPolicy':'DATED_LIMITS',
        'PriceLimitLower':[float(limits.loc[d,'DownLimit']) for d in pd.to_datetime(raw.Date).dt.date],
        'PriceLimitUpper':[float(limits.loc[d,'UpLimit']) for d in pd.to_datetime(raw.Date).dt.date],
        'BuySellableAt':[at(next_day[d],9,30) for d in pd.to_datetime(raw.Date).dt.date],
        'SettlementAt':rawbars.Date})
    receipt=read(ROOT/'research/S015/experiments/EX087_20261105/protocols/action_coverage.json')
    stamp=sessions[0].segments[0].start
    actions=pd.DataFrame([{'Date':stamp,'AvailableDate':stamp,'EventId':'159326-no-actions-in-declared-window',
        'Kind':'NONE','Ratio':1.,'CashPerShare':0.,'PayAt':None}])
    bindings=versioned_equity_bindings(instrument=instrument,source=source,
        coverage=EquitySourceCoverage(sessions[0].session_date,last,json.dumps(receipt,ensure_ascii=False),True,True),
        sessions=sessions,frequencies=(EquityFrequencyFacts(BarFrequency.DAILY,rawbars,rules),),actions=actions)
    def observation(request):
        q=request.parameters.query
        selected=tuple(s for s in sessions if q.start<=s.session_date<=q.end)
        meta=equity_metadata(request,selected,availability_basis='BAR_CLOSE_RESEARCH_ASSUMPTION')
        if q.product is EquityProduct.SESSIONS:
            frame=pd.DataFrame({'Date':[s.segments[0].start for s in selected],
                'AvailableDate':[s.segments[0].start for s in selected],'SessionDate':[s.session_date.isoformat() for s in selected]})
        else:
            frame=hfqbars if q.frequency is BarFrequency.DAILY else minutebars
            local=frame.Date.dt.tz_convert(ZONE).dt.date
            frame=frame.loc[(local>=q.start)&(local<=q.end)].copy()
        meta.update({'source_receipt':'input_sources.json and input_overlap.json','analysis_price':'HFQ' if q.frequency is BarFrequency.DAILY else 'RAW'})
        return frame,meta
    auxiliary=(EquityAuxiliaryInput('hfq',instrument,auxsource,BarFrequency.DAILY,1,86400*75,'HFQ'),
               EquityAuxiliaryInput('intraday',instrument,auxsource,BarFrequency.M30,1,86400*75,'RAW'))
    for item in auxiliary:
        for request in item.requests(date(2024,9,9),last):
            bindings[request.parameters.provider_key]=ProviderBinding(auxsource.provider,auxsource.revision,observation)
    spec=ResearchExecutionSpec(CnEquitySpec(),BarFrequency.DAILY,AccountPolicy('CNY',CashAvailabilityPolicy.IMMEDIATE_RESEARCH),100,.001,.01,0.)
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),
        providers=ProviderConfig(bindings={},equity_bindings=bindings),execution_spec=spec,resources=ExecutionResources(1,1,17))
    return ctx, EquitySources(source,source,source,source), spec
