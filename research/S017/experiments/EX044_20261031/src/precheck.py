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
    def call(policy,record=None,armed=False):
        held=record is not None;state=SimpleNamespace(account=StateRecord((('armed',armed),)),cycle=None if not held else SimpleNamespace(entry_at=entry,values=record))
        ctx=SimpleNamespace(parameters={'policy':policy},events=(),features=SimpleNamespace(get=lambda k:ReadyValue(values[k])),portfolio=SimpleNamespace(quantity=int(held),cash=0. if held else 100000.,reference_price_scale=1.,cycle_entry=entry if held else None,cycle_cost=100. if held else 0.),history=SimpleNamespace(last=lambda:{'Date':current}))
        return step(ctx,state)
    def record(bars=25,active=False,due=False,origin='M005'):
        return StateRecord((('holding_bars',bars),('last_completed_at',last),('exit_due',due),('origin',origin),('trend_active',active),('promoted',False),('exit_reason','PAUSE_NOT_U' if due else 'NONE')))
    pending=call('FAST_RESUME');assert not dict(pending.account.values)['armed'] and dict(pending.cycle_values.values)['origin']=='M005','Buy proposal never grants qualification'
    values['previous_open']=99.;assert call('FAST_RESUME').decision.target==0,'U alone without real promotion cannot enter'
    values['previous_open']=101.
    promoted=call('FAST_RESUME',record());assert dict(promoted.account.values)['armed'] and dict(promoted.cycle_values.values)['promoted']
    restored=call('FAST_RESUME',armed=True);assert dict(restored.cycle_values.values)['origin']=='RESTORE','Armed U wins over simultaneous M005'
    assert not dict(call('FAST_RESUME',record(origin='RESTORE',active=True)).account.values)['armed'],'Restore source26 cannot grant qualification'
    values['close']=101.5
    neutral=call('FAST_RESUME',record(active=True),armed=True);assert neutral.decision.target==0 and dict(neutral.account.values)['armed'],'Neutral pauses but preserves qualified background'
    assert call('CONTROL_SLOW',record(active=True)).decision.target==1
    ordinary=call('FAST_RESUME',armed=True);assert dict(ordinary.cycle_values.values)['origin']=='M005' and not dict(ordinary.cycle_values.values)['trend_active'],'Neutral ordinary M005 must wait26'
    no_promotion=call('FAST_RESUME',record());assert no_promotion.decision.target==0 and not dict(no_promotion.account.values)['armed']
    values['close']=103.;current+=timedelta(minutes=30)
    blocked=call('FAST_RESUME',neutral.cycle_values,armed=True);assert blocked.decision.target==0 and dict(blocked.account.values)['armed'],'Due cannot cancel before actual flat'
    late=call('FAST_RESUME',no_promotion.cycle_values);assert late.decision.target==0 and not dict(late.account.values)['armed'],'Failed26 cannot promote27'
    assert call('FAST_RESUME',armed=True).decision.target==1,'Only actual flat may resume'
    values['close']=99.
    cleared=call('FAST_RESUME',neutral.cycle_values,armed=True);assert not dict(cleared.account.values)['armed'] and cleared.decision.target==0,'F clears while exit is blocked'
    assert call('FAST_RESUME',record(bars=10),armed=True).decision.target==1,'F clears armed but does not cut M005 before26'
    values['close']=103.;values['previous_open']=99.;assert call('FAST_RESUME').decision.target==0,'After F a fresh U cannot bypass M005 anchor'
    values['previous_open']=101.;values['close']=102.
    assert call('FAST_EXIT',record(active=True)).decision.target==0,'notU includes equality'
    results={}
    import json
    for key in PARAMETERS:
        a=replay(key,bars);b=replay(key,changed);assert prefix(a.execution_result)==prefix(b.execution_result)
        assert len(a.execution_result.fills)>0 and (a.execution_result.account_points.cash>=0).all()
        rows=json.loads(a.execution_result.decisions.to_json(orient='records',date_format='iso'));facts=[{v['key']:v['text'] for v in d['explanation']['basis']} for d in rows]
        assert facts[0]['portfolio_quantity']=='0' and facts[0]['armed']=='False' and facts[0]['cycle_present']=='False'
        average=len(a.execution_result.decisions.to_json(orient='records',date_format='iso').encode())/len(rows);assert average<20000
        results[key]={'average_decision_bytes':average,'prefix_invariance':'PASS','fills':len(a.execution_result.fills),'module_loads':a.statistics.module_loads,'restore_held_decisions':sum(f.get('cycle_origin')=='RESTORE' for f in facts),'armed_decisions':sum(f['armed']=='True' for f in facts)}
    save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'synthetic_only':True,'accounts':results,'direct_boundaries':['unfilled proposal cannot arm','actual26 arms','restore priority','restore26 cannot grant','neutral armed pauses','neutral M005 waits26','blocked exit cannot reverse','failed26 cannot reverse27','F clears flat/blocked and before26','notU equality exits'],'limitations':'Actual public replay plus direct state boundary tests; not every calendar boundary or nonempty corporate action claim.'})
    print('PUBLIC_SYNTHETIC_PRECHECK_PASS',flush=True)
if __name__=='__main__':main()
