"""Final native V4 S002 definition with independent explicit observation warmup."""
from pathlib import Path
from datetime import date,datetime,time
from dataclasses import replace
from zoneinfo import ZoneInfo
import json
import sys
import pandas as pd
ROOT=Path.cwd()
sys.path.insert(0,str(ROOT))
from research.S002.runtime_upgrade_v4.build import build_candidate
from dataflows import (InstrumentId,MarketId,AssetClass,SourceRef,TradingSession,TimeInterval,BarFrequency,
    EquitySourceCoverage,EquityFrequencyFacts,versioned_equity_bindings,ProviderConfig,
    Dataflows,DataSpace,ProviderBinding,PreparePolicy,Dataset)
from strategy_runtime import EquityStrategyCandidate,ExecutionResources
from czsc_trader.application import RepositoryContext,create_research_context,create_experiment,ExperimentRequest,publish_evidence
from czsc_trader.research_tools import (ResearchBatchRef,EquitySources,EquityEvaluationRequest,
    EvaluationBenchmark,EquityBuyHold,ResearchExecutionSession,EvaluationEvidenceWrite,ExperimentRef)
from czsc_trader.research_tools.equity_replay import materialize_equity
OUT=ROOT/'.tmp/rsch-frozen-v4-upgrade/S001_S002'
ZONE=ZoneInfo('Asia/Shanghai')
def at(day,h,m=0):return datetime.combine(day,time(h,m),ZONE)
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def main():
    candidate=build_candidate()
    declaration=candidate.definition.observation_inputs[0]
    start,end=date(2026,7,21),date(2026,9,2)
    calendar=pd.read_parquet(OUT/'S002-original-trading_calendar.parquet')
    dates=pd.to_datetime(calendar.loc[calendar.IsOpen==1,'Date']).dt.date.tolist()
    next_day={a:b for a,b in zip(dates,dates[1:])}
    sessions=tuple(TradingSession(d,str(ZONE),(TimeInterval(at(d,9,30),at(d,11,30)),TimeInterval(at(d,13),at(d,15))))
        for d in dates if start<=d<=end)
    raw=pd.read_parquet(OUT/'S002-raw-execution-full.parquet')
    raw=raw.loc[pd.to_datetime(raw.Date).dt.date.between(start,end)].copy()
    local=pd.to_datetime(raw.Date).dt.date.tolist()
    raw['Date']=[at(d,15) for d in local]
    raw['BarStart']=[at(d,9,30) for d in local]
    raw['AvailableDate']=[at(d,17) for d in local]
    limits=pd.read_parquet(OUT/'S002-price-limits.parquet')
    limits.index=pd.to_datetime(limits.Date).dt.date
    rules=pd.DataFrame({'Date':raw.BarStart,'AvailableDate':raw.BarStart,'QuantityStep':100,'PriceTick':.001,
        'Tradable':True,'SellRemainderPolicy':'FULL_LIQUIDATION','PriceLimitPolicy':'DATED_LIMITS',
        'PriceLimitLower':[float(limits.loc[d,'DownLimit']) for d in local],
        'PriceLimitUpper':[float(limits.loc[d,'UpLimit']) for d in local],
        'BuySellableAt':[at(next_day[d],9,30) for d in local],'SettlementAt':raw.Date})
    # Source verification is supplied by the parent RSCH task, recorded explicitly;
    # no-action coverage starts after July's ex-date and payment, never at HFQ warmup.
    receipt={'coverage_start':str(start),'coverage_end':str(end),'instrument':'510500.SH',
        'verified_by':'RSCH parent task 2026-11-06','cash_dividend_history':'Tushare fund_div cross-checked with Eastmoney',
        'source':'https://fundf10.eastmoney.com/fhsp_510500.html',
        'preceding_ex_date':'2026-07-15','preceding_cash_per_share':.149,'preceding_pay_date':'2026-07-20',
        'last_split':'2022-08-26','next_action_through_2026_11_05':None,
        'boundary':'No ex-date/split in declared RAW source window; no prior account holdings or dividend receivables'}
    save(OUT/'S002-no-action-source.json',receipt)
    actions=pd.DataFrame([{'Date':at(start,9,30),'AvailableDate':at(start,9,30),
        'EventId':'S002-verified-no-actions-20260721-20260902','Kind':'NONE','Ratio':1.,'CashPerShare':0.,'PayAt':None}])
    instrument=InstrumentId(MarketId.CN,AssetClass.ETF,'510500.SH')
    source=SourceRef('s002-v4-audited-raw','20261106-v1')
    bindings=versioned_equity_bindings(instrument=instrument,source=source,
        coverage=EquitySourceCoverage(start,end,json.dumps(receipt,sort_keys=True),True,True),
        sessions=sessions,frequencies=(EquityFrequencyFacts(BarFrequency.DAILY,raw,rules),),actions=actions)
    observation_request=declaration.request(date(2025,3,5),end,source_root=candidate.source_root)
    context=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S002'),
        providers=ProviderConfig(env_file=ROOT/'.env',equity_bindings=bindings),
        execution_spec=candidate.definition.execution_spec,resources=ExecutionResources(1,1,17))
    expfile=OUT/'S002-final-experiment.json'
    if expfile.exists():
        saved=json.loads(expfile.read_text(encoding='utf-8'))
        experiment=ExperimentRef(saved['strategy_id'],saved['experiment_id'])
    else:
        experiment=create_experiment(context,ExperimentRequest('冻结S002原生V4最终定义等价性验证',
            '独立观察预热请求保持最终策略定义，默认DFLS观察产品能否复现原账户成交与净值？',date(2026,11,6)))
        save(expfile,experiment.to_dict())
    request=EquityEvaluationRequest(experiment,candidate,TimeInterval(at(date(2026,7,22),9,30),at(end,15)),start,
        EquitySources(source,source,source,source),100000.,.0005,
        benchmark=EvaluationBenchmark(EquityBuyHold(candidate.definition.execution_spec)),
        drawdown_basis='SESSION_CLOSE',concentration_basis='TOP_DECILE',window_id='MATCHED_NO_ACTION',scenario_id='STANDARD',observation_requests=(observation_request,))
    with ResearchExecutionSession(context,experiment=experiment) as execution:
        prepared=context.evaluation.prepare(request,execution=execution)
        outcome,=context.evaluation.evaluate_many((prepared,),execution=execution)
        if outcome.result is None:raise ValueError(str(outcome.error))
        result=outcome.result
        full=materialize_equity(result).payload
        save(OUT/'S002-final-account.json',full)
        saved=OUT/'S002-final-account-closure'
        saved.mkdir(exist_ok=True)
        (saved/'result.json').write_bytes(result.content)
        for artifact in result.artifacts:
            (saved/(artifact.sha256+'.json')).write_bytes(artifact.content)
        save(saved/'manifest.json',{'request_hash':result.request_hash,'result_sha256':result.result_hash,
            'artifacts':[a.reference() for a in result.artifacts]})
        reference=None
        if '--publish' in sys.argv:
            reference=publish_evidence(context,EvaluationEvidenceWrite(experiment,'s002-native-final-matched',prepared,result),execution=execution)
            save(OUT/'S002-final-account-ref.json',reference.to_dict())
    run=full['runs']['candidate']
    oldroot=ROOT/'research/S002/experiments/EX002_20261026/others/S002-v1/published_equivalence'
    old=pd.read_csv(oldroot/'old_CONTINUOUS_account_daily.csv')
    old=old.loc[pd.to_datetime(old.date).dt.date>=date(2026,7,22)].reset_index(drop=True)
    new=pd.DataFrame(run['account_daily'])
    assert len(old)==len(new),(len(old),len(new))
    delta={k:float((old[k].astype(float)-new[k].astype(float)).abs().max()) for k in ('cash','quantity','close','equity')}
    fills=pd.read_csv(oldroot/'old_CONTINUOUS_fills.csv')
    newfills=pd.DataFrame(run['fills'])
    assert fills.side.tolist()==newfills.side.tolist()
    assert pd.to_datetime(fills.fill_time).dt.date.tolist()==pd.to_datetime(newfills.interval_start,utc=True).dt.tz_convert(ZONE).dt.date.tolist()
    fill_delta={k:float((fills[k].astype(float)-newfills[k].astype(float)).abs().max()) for k in ('quantity','price','fees')}
    report={'status':'PASS' if max(*delta.values(),*fill_delta.values())<=1e-8 else 'FAIL',
        'candidate':candidate.candidate_id,'content_sha256':candidate.content_identity.content_sha256,
        'final_upgrade_identity_tested':True,'definition_observation_history_start':declaration.history_start,
        'explicit_observation_start':observation_request.start,'default_dfls_observation_provider':True,
        'daily_rows':len(new),'fills':len(newfills),'max_daily_differences':delta,'max_fill_differences':fill_delta,
        'evidence':None if reference is None else reference.to_dict(),'experiment':experiment.to_dict()}
    save(OUT/'S002-final-account-comparison.json',report)
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if '--inspect' in sys.argv:
        from inspect_s002 import inspect
        inspect(context,candidate,experiment,prepared.request,reference,full)

if __name__=='__main__':main()
