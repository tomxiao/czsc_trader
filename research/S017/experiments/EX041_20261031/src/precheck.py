"""Synthetic public V4 prefix invariance and confirmed-state contract checks."""
from datetime import date,datetime,timedelta
import json
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
    for k,j in enumerate([j for j,t in enumerate(starts.tz_convert(zone)) if t.hour==9 and t.minute==30 and j>0]):
        previous=float(bars.loc[j-1,'Close']);opening=previous-.8;closing=previous+.2
        bars.loc[j,['Open','Close','High','Low']]=[opening,closing,max(opening,closing)+.08,min(opening,closing)-.08]
    bars.loc[273,'Open']=float(bars.loc[272,'Close'])-.01
    j=275;c=float(bars.loc[j,'Close']);bars.loc[j,['Open','High','Low','Volume']]=[c+.03,c+.07,c-.06,3000000.]
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
    values={k:1. for k in OUTPUTS};values.update(close=102.,previous_close=100.,previous_open=101.,previous_high=101.,previous_volume=3.,previous_tr=.5,atr_before_prior=1.,same_slot_median20=1.,opening=99.,low=98.,atr13=1.,atr_prior=1.)
    current={'Date':datetime(2019,1,3,10,tzinfo=zone),'BarStart':datetime(2019,1,3,9,30,tzinfo=zone)};previous={'Date':datetime(2019,1,2,16,tzinfo=zone)}
    mock=SimpleNamespace(parameters=next(iter(PARAMETERS.values())),features=SimpleNamespace(get=lambda k:ReadyValue(values[k])),events=(),portfolio=SimpleNamespace(quantity=0,reference_price_scale=1.),history=SimpleNamespace(last=lambda offset=0:previous if offset else current))
    untouched=SimpleNamespace(cycle=None);proposal=step(mock,untouched)
    assert dict(proposal.cycle_values.values)['origin']=='M005','Conflict must prefer M005'
    assert untouched.cycle is None,'Proposal must not preactivate actual cycle'
    values['previous_open']=99.;proposal=step(mock,untouched)
    assert dict(proposal.cycle_values.values)['origin']=='GAP','Unfilled proposal must not lock next origin'
    results={}
    for key in PARAMETERS:
        a=replay(key,bars); b=replay(key,changed)
        assert prefix(a.execution_result)==prefix(b.execution_result)
        origins=set()
        for row in json.loads(a.execution_result.decisions.to_json(orient='records')):
            f={i['key']:i['text'] for i in row['explanation']['basis']}
            if f.get('holding_bars')=='1': origins.add(f['cycle_origin'])
        assert origins=={'M005','GAP'},origins
        assert len(a.execution_result.fills)>0,'Synthetic fixture must actually trade'
        assert (a.execution_result.account_points.cash>=0).all()
        average_bytes=len(a.execution_result.decisions.to_json(orient='records').encode())/len(a.execution_result.decisions)
        assert average_bytes<20000,'Explanation payload exceeds engineering budget'
        results[key]={'average_decision_bytes':average_bytes,'prefix_invariance':'PASS','fills':len(a.execution_result.fills),'module_loads':a.statistics.module_loads}
    save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'synthetic_only':True,'accounts':results,'limitations':'No real return evidence or nonempty corporate action claim; original confirmed-state mechanism is exercised by public runtime.'})
    print('PUBLIC_SYNTHETIC_PRECHECK_PASS',flush=True)
if __name__=='__main__':main()
