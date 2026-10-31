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
    for key,p in PARAMETERS.items():
        entry=datetime(2019,1,3,10,tzinfo=zone);last=datetime(2019,1,3,10,30,tzinfo=zone);now=datetime(2019,1,3,11,tzinfo=zone)
        record=StateRecord((('holding_bars',p['max_holding_bars']),('last_completed_at',last),('exit_due',True)))
        state=SimpleNamespace(cycle=SimpleNamespace(entry_at=entry,values=record))
        values={k:1. for k in OUTPUTS}
        mock=SimpleNamespace(parameters=p,features=SimpleNamespace(get=lambda k:ReadyValue(values[k])),events=(),portfolio=SimpleNamespace(quantity=1,cash=0.,reference_price_scale=1.,cycle_entry=entry,cycle_cost=1.),history=SimpleNamespace(last=lambda:{'Date':now}))
        result=step(mock,state)
        assert result.decision.target==0 and dict(result.cycle_values.values)['exit_due'] is True,'Blocked exit must remain latched beyond horizon'
    results={}
    for key in PARAMETERS:
        a=replay(key,bars); b=replay(key,changed)
        assert prefix(a.execution_result)==prefix(b.execution_result)
        horizon=PARAMETERS[key]['max_holding_bars'];triggers=0;latched=False
        import json
        for row in json.loads(a.execution_result.decisions.to_json(orient='records')):
            f={i['key']:i['text'] for i in row['explanation']['basis']}
            if f['held']=='False':latched=False;continue
            if latched:assert f['exit_trigger']!='None' and row['target']==0
            if f['exit_trigger']!='None':
                assert int(f['holding_bars'])>=horizon;triggers+=1;latched=True
            else:assert int(f['holding_bars'])<horizon
        assert triggers>0,'Holding boundary must actually be exercised'
        first=a.execution_result.account_points.iloc[0]
        assert first.cash>=0 # First completed point can hold after a valid first-interval buy.
        assert len(a.execution_result.fills)>0,'Synthetic fixture must actually trade'
        assert (a.execution_result.account_points.cash>=0).all()
        average_bytes=len(a.execution_result.decisions.to_json(orient='records').encode())/len(a.execution_result.decisions)
        assert average_bytes<20000,'Explanation payload exceeds engineering budget'
        results[key]={'average_decision_bytes':average_bytes,'prefix_invariance':'PASS','fills':len(a.execution_result.fills),'module_loads':a.statistics.module_loads}
    save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'synthetic_only':True,'accounts':results,'limitations':'No real return evidence or nonempty corporate action claim; original confirmed-state mechanism is exercised by public runtime.'})
    print('PUBLIC_SYNTHETIC_PRECHECK_PASS',flush=True)
if __name__=='__main__':main()
