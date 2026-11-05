"""Explicit technical RAW ledger comparisons, using independently checked source coverage."""
from pathlib import Path
from datetime import date,datetime,time,timedelta
from zoneinfo import ZoneInfo
from dataclasses import asdict
import json
import sys
import pandas as pd
from dataflows import (Dataflows,DataSpace,ProviderConfig,PreparePolicy,DataRequest,Dataset,MoneyflowParameters,
    EquityDataRequest,EquityQuery,EquityProduct,SourceRef,BarFrequency,TimeInterval,TradingSession,
    EquitySourceCoverage,EquityFrequencyFacts,versioned_equity_bindings,tushare_equity_observation_bindings)
from strategy_runtime import (EquityInputBinding,EquityAuxiliaryBinding,ExecutionInputBinding,
    DatasetObservationBinding,StrategyRuntime,StrategyInit,TradableWindow,ExecutionPricing)
from strategy_runtime.deployment import validate_release_package
from czsc_trader.application import EquityInspectionReplay
from czsc_trader.application.equity_inspection import replay_account
from strategy_manager import freeze_contracts as f
from trading_execution_engine import HistoricalExecutor

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from research.S003.runtime_upgrade_v4.build_candidate import build_candidate as s003
from research.S007.runtime_upgrade_v4.build_candidate import build_candidate as s007
DATA=ROOT/'.tmp/rsch-frozen-v4-upgrade/s003_s007_data'
OUT=ROOT/'.tmp/rsch-frozen-v4-upgrade/s003_s007_accounts';OUT.mkdir(exist_ok=True)
zone=ZoneInfo('Asia/Shanghai')
start,end=date(2026,8,1),date(2026,11,5)
evidence=json.loads((ROOT/'.tmp/rsch-frozen-v4-upgrade/action_coverage.json').read_text(encoding='utf-8'))
calendar=pd.read_csv(DATA/'calendar_aug_nov.csv')
days=tuple(pd.to_datetime(calendar.loc[pd.to_numeric(calendar.IsOpen).eq(1),'Date']).dt.date)
def clock(day,hour,minute=0):return datetime.combine(day,time(hour,minute),zone)
sessions=tuple(TradingSession(day,str(zone),(TimeInterval(clock(day,9,30),clock(day,11,30)),TimeInterval(clock(day,13),clock(day,15)))) for day in days if start<=day<=end)
nextday={a:b for a,b in zip(days,days[1:])}

def bars_and_rules(family,frequency):
    name='daily' if frequency is BarFrequency.DAILY else 'm30'
    frame=pd.read_csv(DATA/(family.lower()+'_raw_'+name+'.csv'))
    stamps=pd.to_datetime(frame.Date)
    grid=tuple(period for session in sessions for period in session.bars(frequency))
    observed=[value.date() if frequency is BarFrequency.DAILY else value.to_pydatetime() for value in stamps]
    expected=[period.end.date() if frequency is BarFrequency.DAILY else period.end.astimezone(zone).replace(tzinfo=None) for period in grid]
    assert observed==expected
    frame['Date']=[p.end for p in grid];frame['BarStart']=[p.start for p in grid]
    frame['AvailableDate']=frame.Date
    limits=pd.read_csv(DATA/(family.lower()+'_limits.csv')).set_index('Date')
    rules=pd.DataFrame([dict(Date=p.start,AvailableDate=clock(p.start.date(),9,30),QuantityStep=100,PriceTick=.001,
        Tradable=True,PriceLimitPolicy='DATED_LIMITS',PriceLimitLower=float(limits.loc[p.start.date().isoformat(),'DownLimit']),
        PriceLimitUpper=float(limits.loc[p.start.date().isoformat(),'UpLimit']),BuySellableAt=clock(nextday[p.start.date()],9,30),
        SellRemainderPolicy='FULL_LIQUIDATION',SettlementAt=p.end) for p in grid])
    return frame,rules

def native(family,builder,trade_start,fee,*,prepare_only=False):
    raw_source=SourceRef('tushare-reviewed-raw',family.lower()+'-20261106')
    hfq_source=SourceRef('tushare','native-v4-observation-20261106')
    candidate=builder(raw_source if family=='S003' else hfq_source)
    dates=tuple(day.isoformat() for day in days if date(2026,9,9)<=day<=end)
    frequencies=[BarFrequency.DAILY]+([BarFrequency.M30] if family=='S003' else [])
    facts=tuple(EquityFrequencyFacts(freq,*bars_and_rules(family,freq)) for freq in frequencies)
    stamp=sessions[0].segments[0].start
    action=pd.DataFrame([dict(Date=stamp,AvailableDate=stamp,EventId=family+'-verified-none-aug-nov2026',Kind='NONE',Ratio=1.,CashPerShare=0.,PayAt=None)])
    proof={'corporate_actions':evidence,'symbol':candidate.instrument.symbol,
        'data_preparation':json.loads((DATA/'preparation.json').read_text()),
        'rules':'Tushare dated etf_limit; SSE independent trade_cal; mainland ETF 100-share unit, .001 tick, T+1 sellability; immediate research cash; observed complete bars.'}
    providers=versioned_equity_bindings(instrument=candidate.instrument,source=raw_source,
        coverage=EquitySourceCoverage(start,end,json.dumps(proof,default=str),True,True),sessions=sessions,frequencies=facts,actions=action)
    providers.update(tushare_equity_observation_bindings(source=hfq_source,env_file=ROOT/'.env'))
    flow=Dataflows(base_dir=ROOT,space=DataSpace(Path('.tmp/rsch-frozen-v4-upgrade/s003_s007-data-space')),
        providers=ProviderConfig(env_file=ROOT/'.env',equity_bindings=providers))
    queries={product.name.lower():EquityDataRequest(candidate.instrument,raw_source,EquityQuery(product,start,end,BarFrequency.DAILY)) for product in EquityProduct}
    for item in candidate.definition.auxiliary_inputs:
        queries.update({item.data_key(q.parameters.query.product):q for q in item.requests(start,end)})
    if candidate.definition.execution_input:
        item=candidate.definition.execution_input
        queries.update({item.data_key(q.parameters.query.product):q for q in item.requests(start,end)})
    observations={item.name:item.request(start,end,source_root=candidate.source_root,trading_dates=dates if item.dataset is Dataset.STOCK_MONEYFLOW else ()) for item in candidate.definition.observation_inputs}
    queries.update({'observation:'+name:q for name,q in observations.items()})
    requests=tuple(dict.fromkeys(queries.values()))
    prepared=flow.prepare(requests,policy=PreparePolicy.REUSE)
    if not prepared.ready:raise RuntimeError([(i.request.dataset,str(i.status),str(i.error)) for i in prepared.items if str(i.status)!='READY'])
    hashes={key:flow.fetch(query,prepared=prepared.reference).identity.content_sha256 for key,query in queries.items()}
    auxiliary=tuple(EquityAuxiliaryBinding(item,hashes[item.data_key(EquityProduct.BARS)],hashes[item.data_key(EquityProduct.SESSIONS)]) for item in candidate.definition.auxiliary_inputs)
    execution=None
    if candidate.definition.execution_input:
        item=candidate.definition.execution_input
        execution=ExecutionInputBinding(item,hashes[item.data_key(EquityProduct.BARS)],hashes[item.data_key(EquityProduct.SESSIONS)])
    obs=tuple(DatasetObservationBinding(item,observations[item.name],hashes[item.data_key()]) for item in candidate.definition.observation_inputs)
    binding=EquityInputBinding(prepared.reference,candidate.instrument,candidate.execution_spec_hash,
        tuple((key,hashes[key]) for key in ('bars','actions','constraints','sessions')),candidate.warmup_bars,
        auxiliary,execution,tuple((key,query.parameters) for key,query in queries.items() if not key.startswith('observation:')),obs)
    replay=EquityInspectionReplay(f.InspectionCoordinate('migration','standard'),binding,requests,
        TimeInterval(clock(trade_start,9,30),clock(end,15)),100000.,fee)
    (OUT/(family+'-definition.json')).write_text(json.dumps(candidate.definition.to_dict(),indent=2),encoding='utf-8')
    (OUT/(family+'-binding.json')).write_text(json.dumps(binding.to_dict(),indent=2,default=str),encoding='utf-8')
    if prepare_only:return candidate,flow,providers,replay
    result=replay_account(candidate,flow,replay)
    (OUT/(family+'-native.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(family,'NATIVE',len(result['facts']['fills']),flush=True)
    return result,flow

def old_account(family,flow,trade_start):
    package=validate_release_package(ROOT/'strategies',family+'-v1')
    runtime=StrategyRuntime(ROOT/'strategies',dataflows=flow)
    instance=runtime.create(StrategyInit(package.release,TradableWindow(trade_start,end),OUT/(family+'-legacy-runtime'),
        source_root=package.source_root,runtime_binding=package.runtime_binding))
    instance.prepare_data(policy=PreparePolicy.REUSE,persist=False)
    def old_frame(name):
        frame=pd.read_csv(DATA/(family.lower()+'_raw_'+name+'.csv')).rename(columns={'Date':'dt','Open':'open','High':'high','Low':'low','Close':'close','Volume':'vol','Amount':'amount'})
        frame['dt']=pd.to_datetime(frame.dt)
        return frame
    definition=instance.definition
    executor=HistoricalExecutor(strategy_reference=family+'-v1',symbol=definition.tradable_symbol,
        execution_daily=old_frame('daily'),execution_intraday=old_frame('m30'),
        evaluation_start=pd.Timestamp(trade_start),evaluation_end=pd.Timestamp(end),initial_cash=100000.,
        execution_policy=definition.execution,order_types=definition.capabilities.order_types,
        checkpoints=definition.capabilities.checkpoints,
        execution_five_minute=old_frame('m5') if family=='S003' else None,pricing=ExecutionPricing())
    result=instance.run_window(executor=executor)
    print(family,'OLD RESULT',type(result),flush=True)
    for key in ('fills','orders','daily','account_daily','decisions'):
        frame=getattr(result,key,None)
        if isinstance(frame,pd.DataFrame):frame.to_csv(OUT/(family+'-legacy-'+key+'.csv'),index=False)
    return result

if __name__=='__main__':
    for family,builder,first,fee in [('S003',s003,date(2026,9,10),.00012),('S007',s007,date(2026,9,3),.001)]:
        if len(sys.argv)>1 and family != sys.argv[1]:continue
        result,flow=native(family,builder,first,fee)
        old=old_account(family,flow,first)
