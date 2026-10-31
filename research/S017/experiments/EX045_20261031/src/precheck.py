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
    values={k:101. for k in OUTPUTS};values.update(close=102.,previous_close=100.,previous_open=101.,previous_high=101.,previous_volume=3.,same_slot_median20=1.,previous_tr=.5,atr_before_prior=1.)
    current=datetime(2019,1,3,11,tzinfo=zone);entry=datetime(2019,1,3,10,tzinfo=zone);last=datetime(2019,1,3,10,30,tzinfo=zone)
    def call(policy,record=None):
        held=record is not None;state=SimpleNamespace(cycle=None if not held else SimpleNamespace(entry_at=entry,values=record))
        ctx=SimpleNamespace(parameters={'policy':policy},events=(),features=SimpleNamespace(get=lambda k:ReadyValue(values[k])),portfolio=SimpleNamespace(quantity=int(held),cash=0. if held else 100000.,reference_price_scale=1.,cycle_entry=entry if held else None,cycle_cost=100. if held else 0.),history=SimpleNamespace(last=lambda:{'Date':current,'High':999.}))
        return step(ctx,state)
    assert call('BREAKOUT65').decision.target==1,'Current High must not enter prior window'
    assert dict(call('UNION26').cycle_values.values)['origin']=='M005','Union simultaneous M005 priority'
    values['high65']=103.;assert call('BREAKOUT65').decision.target==0,'65th lag must be included'
    values['close']=103.;assert call('BREAKOUT65').decision.target==0,'Breakout equality false'
    values['close']=103.01;assert call('BREAKOUT65').decision.target==1
    rec=StateRecord((('holding_bars',25),('last_completed_at',last),('exit_due',False),('origin','BREAKOUT65')))
    due=call('UNION26',rec);assert due.decision.target==0 and dict(due.cycle_values.values)['holding_bars']==26
    current+=timedelta(minutes=30);assert call('UNION26',due.cycle_values).decision.target==0,'Exit remains locked even new breakout'
    results={}
    import json
    for key in PARAMETERS:
        a=replay(key,bars);b=replay(key,changed);assert prefix(a.execution_result)==prefix(b.execution_result)
        assert len(a.execution_result.fills)>0 and (a.execution_result.account_points.cash>=0).all()
        rows=json.loads(a.execution_result.decisions.to_json(orient='records',date_format='iso'));facts=[{v['key']:v['text'] for v in d['explanation']['basis']} for d in rows];first=facts[0]
        assert first['portfolio_quantity']=='0' and first['cycle_present']=='False'
        assert any(f['exit_trigger']=='FIXED26' and f['holding_bars']=='26' for f in facts)
        average=len(a.execution_result.decisions.to_json(orient='records',date_format='iso').encode())/len(rows);assert average<20000
        results[key]={'average_decision_bytes':average,'prefix_invariance':'PASS','fills':len(a.execution_result.fills),'module_loads':a.statistics.module_loads}
    save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'synthetic_only':True,'accounts':results,'direct_boundaries':['strict breakout equality','include true65th lag','exclude current high','union M005 priority','actual26 expiry','locked exit despite fresh signal'],'limitations':'Synthetic public runtime plus direct boundaries; not a new economic account or full calendar/rights-event validation.'})
    print('PUBLIC_SYNTHETIC_PRECHECK_PASS',flush=True)
if __name__=='__main__':main()
