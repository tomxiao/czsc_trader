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
    changed=bars.copy(); changed.loc[520:,['Open','High','Low','Close']]*=1.7; changed.loc[520:,'Amount']*=1.7
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
    values={k:1. for k in OUTPUTS};values.update(close=103.,ma65=102.,ma260=100.,previous_close=100.,previous_open=101.,previous_high=101.,previous_volume=3.,same_slot_median20=1.,previous_tr=.5,atr_before_prior=1.)
    current=datetime(2019,1,3,11,tzinfo=zone);entry=datetime(2019,1,3,10,tzinfo=zone);last=datetime(2019,1,3,10,30,tzinfo=zone)
    def call(policy,record=None):
        held=record is not None
        state=SimpleNamespace(cycle=None if not held else SimpleNamespace(entry_at=entry,values=record))
        ctx=SimpleNamespace(parameters={'policy':policy},events=(),features=SimpleNamespace(get=lambda k:ReadyValue(values[k])),portfolio=SimpleNamespace(quantity=int(held),cash=0. if held else 100000.,reference_price_scale=1.,cycle_entry=entry if held else None,cycle_cost=100. if held else 0.),history=SimpleNamespace(last=lambda:{'Date':current}))
        return step(ctx,state)
    def record(bars=25,active=False,due=False,origin='M005'):
        return StateRecord((('holding_bars',bars),('last_completed_at',last),('exit_due',due),('origin',origin),('trend_active',active),('promoted',False),('exit_reason','FIXED_26' if due else 'NONE')))
    assert dict(call('PARALLEL_ORIGIN').cycle_values.values)['origin']=='TREND','Simultaneous U must win'
    assert dict(call('M005_PROMOTION').cycle_values.values)['origin']=='M005','Promotion must wait for actual26'
    promoted=call('M005_PROMOTION',record());assert promoted.decision.target==1 and dict(promoted.cycle_values.values)['promoted'] is True
    assert call('PARALLEL_ORIGIN',record()).decision.target==0,'Parallel M005 source must not promote'
    values['close']=101.
    assert call('TREND_ONLY',record(active=True,origin='TREND')).decision.target==1,'Neutral region holds'
    failed26=call('M005_PROMOTION',record());assert failed26.decision.target==0
    values['close']=103.;current+=timedelta(minutes=30)
    no_reversal=call('M005_PROMOTION',failed26.cycle_values);assert no_reversal.decision.target==0 and not dict(no_reversal.cycle_values.values)['promoted'],'Day27 cannot reverse due'
    assert call('TREND_ONLY').decision.target==1,'Flat U can reenter after exit'
    values['close']=99.
    assert call('M005_PROMOTION',record(bars=10)).decision.target==1,'F before26 does not cut M005'
    assert call('TREND_ONLY',record(active=True,origin='TREND')).decision.target==0
    values['close']=100.
    assert call('TREND_ONLY',record(active=True,origin='TREND')).decision.target==1,'Equality to MA260 does not fail'
    values['close']=103.;values['ma65']=100.
    assert call('TREND_ONLY').decision.target==0,'U equality cannot enter'
    assert call('TREND_ONLY',record(active=True,origin='TREND')).decision.target==1,'MA equality holding region'
    results={}
    import json
    for key in PARAMETERS:
        a=replay(key,bars);b=replay(key,changed)
        assert prefix(a.execution_result)==prefix(b.execution_result)
        assert len(a.execution_result.fills)>0
        assert (a.execution_result.account_points.cash>=0).all()
        rows=json.loads(a.execution_result.decisions.to_json(orient='records',date_format='iso'))
        first={v['key']:v['text'] for v in rows[0]['explanation']['basis']}
        assert first['portfolio_quantity']=='0' and first['cycle_present']=='False' and float(first['portfolio_cash'])==100000.
        average=len(a.execution_result.decisions.to_json(orient='records',date_format='iso').encode())/len(rows);assert average<20000
        results[key]={'average_decision_bytes':average,'prefix_invariance':'PASS','fills':len(a.execution_result.fills),'module_loads':a.statistics.module_loads}
    save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'synthetic_only':True,'accounts':results,'direct_boundaries':['U priority','promotion only actual26','parallel origin unchanged','neutral and equality holding','failed26 cannot reverse27','F before26 does not cut M005','F trend exit','flat U reentry'],'limitations':'No nonempty corporate action or every calendar boundary claim; direct state checks do not replace actual public replay.'})
    print('PUBLIC_SYNTHETIC_PRECHECK_PASS',flush=True)
if __name__=='__main__':main()
