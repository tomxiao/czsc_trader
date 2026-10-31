"""Synthetic public V4 prefix invariance and confirmed-state contract checks."""
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace
import numpy as np
import pandas as pd
from dataflows import BarFrequency,TradingSession,TimeInterval
from strategy_runtime import PreparedReplay,run_replay,ReadyValue,AccountStrategyState,CycleState,StateRecord
from trading_execution_engine import PortfolioHistoricalExecutor
from common import WORK,PARAMETERS,SPEC,candidate,save,digest
from strategy import step,OUTPUTS

def main():
    zone=ZoneInfo('America/New_York'); day=date(2019,1,2); days=[]
    while len(days)<50:
        if day.weekday()<5: days.append(day)
        day+=timedelta(days=1)
    sessions=tuple(TradingSession(d,str(zone),(TimeInterval(datetime(d.year,d.month,d.day,9,30,tzinfo=zone),datetime(d.year,d.month,d.day,16,tzinfo=zone)),)) for d in days)
    periods=[p for s in sessions for p in s.bars(BarFrequency.M30)]
    starts=pd.DatetimeIndex([p.start for p in periods]).tz_convert('UTC'); ends=pd.DatetimeIndex([p.end for p in periods]).tz_convert('UTC')
    i=np.arange(len(periods)); prices=100+.04*i+1.5*np.sin(i/6)
    bars=pd.DataFrame({'BarStart':starts,'Date':ends,'AvailableDate':ends,'Open':prices-.03,'High':prices+.08,'Low':prices-.08,'Close':prices,'Volume':1000000.,'Amount':prices*1000000})
    constraints=pd.DataFrame({'Date':starts,'AvailableDate':starts,'QuantityStep':1,'PriceTick':.01,'Tradable':True,'PriceLimitPolicy':'EXPLICIT_UNBOUNDED','PriceLimitLower':None,'PriceLimitUpper':None,'BuySellableAt':starts,'SettlementAt':starts,'SellRemainderPolicy':'STRICT_STEP'})
    actions=pd.DataFrame([{'Date':starts[0],'AvailableDate':starts[0],'EventId':'synthetic-none','Kind':'NONE','Ratio':1.,'CashPerShare':0.,'PayAt':None}])
    calendar=pd.DataFrame({'Date':[s.segments[0].start for s in sessions],'AvailableDate':[s.segments[0].start for s in sessions],'SessionDate':[s.session_date.isoformat() for s in sessions]})
    for j in range(37,len(bars)-1,37):
        c=float(bars.loc[j,'Close']);bars.loc[j,['Open','High','Low','Volume']]=[c+.03,c+.07,c-.06,3000000.]
        n=max(float(bars.loc[j+1,'Close']),c+.12);bars.loc[j+1,['Open','High','Low','Close']]=[n-.03,n+.08,n-.08,n]
        bars.loc[j+2,['Open','High','Low','Close']]=[c+.08,c+.22,c+.05,c+.18]
    j=390;c=float(bars.loc[j-1,'Close'])+.04;bars.loc[j,['Open','High','Low','Close','Volume']]=[c-.03,c+.07,c-.06,c,3000000.]
    q=c-.16;bars.loc[j+1,['Open','High','Low','Close']]=[q+.03,q+.1,q-.08,q]
    bars.loc[400,['Open','High','Low','Close']]=[80.03,80.1,79.9,80.]
    changed=bars.copy(); changed.loc[520:,['Open','High','Low','Close']]*=1.7; changed.loc[520:,'Amount']*=1.7; changed.loc[520:,'Volume']*=3
    def replay(key,frame):
        c=candidate(key); p=PreparedReplay.from_frames(frame,constraints,c.definition.feature_graph,frequency=BarFrequency.M30,timezone=str(zone),sessions=calendar,trading_sessions=sessions)
        executor=PortfolioHistoricalExecutor(specification=SPEC,initial_cash=100000.,fee_rate=.001,actions=actions,price_basis='RAW')
        return run_replay(p,c,executor,start=starts[274].to_pydatetime(),end=ends[-1].to_pydatetime(),fee_rate=.001)
    def prefix(result):
        output={}
        for name,field in {'decisions':'decision_at','orders':'valid_start','fills':'interval_start','account_points':'time','account_daily':'time','trades':'exit_at'}.items():
            f=getattr(result,name)
            if f.empty: output[name]='[]'; continue
            f=f[pd.to_datetime(f[field],utc=True)<starts[520]]
            f=f.drop(columns=[c for c in f if c.endswith('_id')])
            output[name]=f.to_json(orient='records',date_format='iso',double_precision=15)
        return output
    import json
    values={k:1. for k in OUTPUTS};values.update(close=110.,opening=109.,low=107.,previous_low=105.,previous_close=106.,previous_open=107.,previous_high=108.,previous_volume=1.5,same_slot_median20=1.,previous_tr=1.,atr_before_prior=1.)
    current=datetime(2019,1,3,11,tzinfo=zone);entry=datetime(2019,1,3,9,30,tzinfo=zone);last=current-timedelta(minutes=30)
    empty=StateRecord((('pending',False),('anchor_at',last),('reclaimed_level',0.),('original_support',0.)))
    def call(policy,account=empty,cycle=None):
        state=SimpleNamespace(account=account,cycle=None if cycle is None else SimpleNamespace(entry_at=entry,values=cycle))
        ctx=SimpleNamespace(parameters={'policy':policy},events=(),features=SimpleNamespace(get=lambda k:ReadyValue(values[k])),portfolio=SimpleNamespace(quantity=int(cycle is not None),cash=100000. if cycle is None else 0.,reference_price_scale=1.,cycle_entry=entry if cycle is not None else None,cycle_cost=100. if cycle is not None else 0.),history=SimpleNamespace(last=lambda:{'Date':current}))
        return step(ctx,state)
    assert call('STATIC_SUPPORT').decision.target==1
    assert call('BULLISH_RECLAIM').decision.target==1
    values['opening']=110.;assert call('BULLISH_RECLAIM').decision.target==0;values['opening']=109.
    x=call('RETEST_ORIGINAL');assert x.decision.target==0 and dict(x.account.values)['pending']
    setup=x.account;anchor=current;current+=timedelta(minutes=30);values.update(previous_close=107.,previous_open=106.,close=109.,opening=108.,low=108.)
    x=call('RETEST_ORIGINAL',setup);assert x.decision.target==1 and dict(x.cycle_values.values)['support']==105.
    assert dict(x.account.values)['pending'],'Proposal/failed buy does not consume pending'
    values['low']=104.;x=call('RETEST_LOW',setup);assert dict(x.cycle_values.values)['support']==104.,'Retest Low can be below S0, no truncation'
    values['close']=108.;assert call('RETEST_LOW',setup).decision.target==0,'Close=R not acceptance'
    values.update(close=109.,opening=109.);assert call('RETEST_LOW',setup).decision.target==0,'Doji not upward acceptance'
    values.update(close=105.,opening=104.,low=104.);x=call('RETEST_LOW',setup);assert dict(x.account.values)['pending'],'S0 equality preserves'
    values['close']=104.99;x=call('RETEST_LOW',setup);assert not dict(x.account.values)['pending']
    values.update(close=110.,opening=109.,low=107.,previous_close=106.,previous_open=107.)
    x=call('RETEST_LOW',setup);assert x.decision.target==0 and dict(x.account.values)['anchor_at']==current,'New signal replaces and cannot confirm same bar'
    rec=StateRecord((('holding_bars',2),('last_completed_at',current-timedelta(minutes=30)),('exit_due',False),('support',105.),('original_support',105.),('anchor_at',anchor),('confirmation_at',anchor),('exit_reason','NONE')))
    values['close']=105.;x=call('RETEST_LOW',setup,rec);assert x.decision.target==1 and not dict(x.account.values)['pending']
    values['close']=104.;x=call('RETEST_LOW',setup,rec);assert x.decision.target==0
    rec=StateRecord(tuple((k,current-timedelta(minutes=30) if k=='last_completed_at' else v) for k,v in x.cycle_values.values));values['close']=110.;x=call('RETEST_LOW',setup,rec);assert x.decision.target==0,'Due cannot reverse or rebuild pending'
    results={}
    for key in PARAMETERS:
        a=replay(key,bars);b=replay(key,changed);assert prefix(a.execution_result)==prefix(b.execution_result)
        assert len(a.execution_result.fills)>0 and (a.execution_result.account_points.cash>=0).all()
        rows=json.loads(a.execution_result.decisions.to_json(orient='records',date_format='iso'));facts=[{v['key']:v['text'] for v in row['explanation']['basis']} for row in rows]
        assert facts[0]['portfolio_quantity']=='0' and facts[0]['cycle_present']=='False'
        confirmations=sum(f['retest_confirmed']=='True' for f in facts)
        if PARAMETERS[key]['policy'].startswith('RETEST'):assert confirmations>0
        average=len(a.execution_result.decisions.to_json(orient='records',date_format='iso').encode())/len(rows);assert average<20000
        results[key]={'average_decision_bytes':average,'price_and_volume_prefix_invariance':'PASS','fills':len(a.execution_result.fills),'module_loads':a.statistics.module_loads,'retest_confirmations':confirmations,'support_exits':sum(f['exit_trigger']!='NONE' for f in facts)}
    save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'synthetic_only':True,'accounts':results,'direct_boundaries':['bullish strict close>open','same signal never retest','newM005 replaces before oldcancel/no samebar buy','pending survives proposed/failed buy','fresh confirmation required','close=R not confirmation','Low=R confirmation','doji no confirmation','close=S0 pending holds','belowS0 cancels','retestLow belowS0 retained','realheld clears pending','support equality holds','due exit cannot reverse/rebuild'],'limitations':'Focused public replay and price/volume suffix, not every calendar/event or financial validity'})
    print('PUBLIC_ACCEPTANCE_STATE_PRECHECK_PASS',flush=True)
if __name__=='__main__':main()

