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
    values={k:1. for k in OUTPUTS};values.update(close=110.,low=107.,previous_low=105.,low2=108.,previous_close=106.,previous_open=107.,previous_high=108.,previous_volume=1.5,same_slot_median20=1.,previous_tr=1.,atr_before_prior=1.)
    current=datetime(2019,1,3,11,tzinfo=zone);entry=datetime(2019,1,3,9,30,tzinfo=zone);last=current-timedelta(minutes=30)
    def record(support=100.,due=False):return StateRecord((('holding_bars',2),('last_completed_at',last),('exit_due',due),('initial_support',100.),('support',support),('support_raises',0),('exit_reason','INITIAL_SUPPORT_BREAK' if due else 'NONE')))
    def call(policy,rec=None):
        held=rec is not None;state=SimpleNamespace(cycle=None if not held else SimpleNamespace(entry_at=entry,values=rec))
        frame=pd.DataFrame({'BarStart':[current-timedelta(minutes=m) for m in (90,60,30)],'Date':[current-timedelta(minutes=m) for m in (60,30,0)]})
        ctx=SimpleNamespace(parameters={'policy':policy},events=(),features=SimpleNamespace(get=lambda k:ReadyValue(values[k])),portfolio=SimpleNamespace(quantity=int(held),cash=0. if held else 100000.,reference_price_scale=1.,cycle_entry=entry if held else None,cycle_cost=100. if held else 0.),history=SimpleNamespace(last=lambda:{'Date':current},to_frame=lambda tail:frame.tail(tail)))
        return step(ctx,state)
    pending=call('STATIC_SUPPORT');assert dict(pending.cycle_values.values)['initial_support']==105. and dict(pending.cycle_values.values)['support']==105.
    assert dict(call('CONFIRMED_SUPPORT',record()).cycle_values.values)['support']==105.
    entry=datetime(2019,1,3,10,tzinfo=zone);assert dict(call('CONFIRMED_SUPPORT',record()).cycle_values.values)['support']==100.,'Partial entry bar cannot seed post-fill pivot'
    entry=datetime(2019,1,3,9,30,tzinfo=zone)
    values['low2']=105.;assert dict(call('CONFIRMED_SUPPORT',record()).cycle_values.values)['support']==100.;values['low2']=108.
    values['low']=105.;assert dict(call('CONFIRMED_SUPPORT',record()).cycle_values.values)['support']==100.;values['low']=107.
    assert dict(call('CONFIRMED_SUPPORT',record(support=105.)).cycle_values.values)['support_raises']==0
    locked=call('CONFIRMED_SUPPORT',record(due=True));assert locked.decision.target==0 and dict(locked.cycle_values.values)['support']==100.,'Due cannot raise or reverse'
    values['close']=100.;assert call('STATIC_SUPPORT',record()).decision.target==1,'Close support equality holds'
    values['close']=99.99;assert call('STATIC_SUPPORT',record()).decision.target==0
    values.update(close=104.,previous_close=107.,previous_open=106.,previous_low=105.)
    assert call('OPPOSING_PRESSURE',record()).decision.target==0,'Original volume/TR equality boundaries count'
    assert call('STATIC_SUPPORT',record()).decision.target==1,'Mirror is an independent extra failure'
    values['close']=105.;assert call('OPPOSING_PRESSURE',record()).decision.target==1,'PrevLow equality not pressure'
    values['close']=99.;assert dict(call('OPPOSING_PRESSURE',record()).cycle_values.values)['exit_reason']=='INITIAL_SUPPORT_BREAK','Floor reason wins if both fail'
    values.update(close=110.,previous_close=106.,previous_open=107.,previous_low=105.);assert call('STATIC_SUPPORT').decision.target==1
    results={}
    for key in PARAMETERS:
        a=replay(key,bars);b=replay(key,changed);assert prefix(a.execution_result)==prefix(b.execution_result)
        assert len(a.execution_result.fills)>0 and (a.execution_result.account_points.cash>=0).all()
        rows=json.loads(a.execution_result.decisions.to_json(orient='records',date_format='iso'));facts=[{v['key']:v['text'] for v in row['explanation']['basis']} for row in rows]
        assert facts[0]['portfolio_quantity']=='0' and facts[0]['cycle_present']=='False'
        exits={f['exit_trigger'] for f in facts if f['exit_trigger']!='NONE'};raised=sum(f['support_raised']=='True' for f in facts)
        if PARAMETERS[key]['policy']=='STATIC_SUPPORT':assert 'INITIAL_SUPPORT_BREAK' in exits
        if PARAMETERS[key]['policy']=='CONFIRMED_SUPPORT':assert raised>0
        if PARAMETERS[key]['policy']=='OPPOSING_PRESSURE':assert 'OPPOSING_PRESSURE' in exits
        if PARAMETERS[key]['policy']=='DIAGNOSTIC26':assert 'DIAGNOSTIC_26' in exits
        average=len(a.execution_result.decisions.to_json(orient='records',date_format='iso').encode())/len(rows);assert average<20000
        results[key]={'average_decision_bytes':average,'price_and_volume_prefix_invariance':'PASS','fills':len(a.execution_result.fills),'module_loads':a.statistics.module_loads,'observed_exit_reasons':sorted(exits),'support_raise_decisions':raised}
    save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'synthetic_only':True,'accounts':results,'direct_boundaries':['signal floor frozen proposal','close=floor holds','strict pivot left/right equality','pivot=floor not raised','all3 BarStart after actual fill','due no pivot reversal','mirror prevVol/prevTR equal boundaries','close=prevLow not pressure','floor priority when both fail'],'limitations':'Public replay/price+volume future suffix and direct boundaries, not every calendar/corporate event or economic validity.'})
    print('PUBLIC_FINANCIAL_STATE_PRECHECK_PASS',flush=True)
if __name__=='__main__':main()
