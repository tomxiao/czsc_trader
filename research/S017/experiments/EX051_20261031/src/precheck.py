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
    # Force a genuine public interval-touch fill at the first possible signal.
    c=float(bars.loc[273,'Close']);bars.loc[273,['Open','High','Low','Close','Volume']]=[c+.01,c+.02,c-.02,c,3000000.]
    q=c+.07;bars.loc[274,['Open','High','Low','Close']]=[q-.01,q+.02,q-.02,q]
    bars.loc[275,['Open','High','Low','Close']]=[q*1.02,q*1.025,q*.995,q*1.005]
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
    v={k:1. for k in OUTPUTS};v.update(close=110.,high=111.,low=107.,previous_low=105.,low2=108.,previous_close=106.,previous_open=107.,previous_high=108.,previous_volume=1.5,same_slot_median20=1.,previous_tr=1.,atr_before_prior=1.)
    current=datetime(2019,1,3,11,tzinfo=zone);entry=datetime(2019,1,3,9,0,tzinfo=zone);last=current-timedelta(minutes=30)
    def record(**extra):
        s=dict(holding_bars=2,last_completed_at=last,exit_due=False,initial_support=100.,support=100.,support_raises=0,exit_reason='NONE',peak=125.,peak_before_last=120.,pending_support=False,candidate_low=0.,candidate_high=0.,candidate_at=last);s.update(extra);return StateRecord(tuple(s.items()))
    def call(support='ACCEPTED',rec=None,entry_policy='M005'):
        frame=pd.DataFrame({'BarStart':[current-timedelta(minutes=m) for m in (90,60,30)],'Date':[current-timedelta(minutes=m) for m in (60,30,0)]})
        ctx=SimpleNamespace(parameters={'entry':entry_policy,'support':support},events=(),features=SimpleNamespace(get=lambda k:ReadyValue(v[k])),portfolio=SimpleNamespace(quantity=int(rec is not None),cash=100000. if rec is None else 0.,reference_price_scale=1.,cycle_entry=entry if rec is not None else None,cycle_cost=100. if rec is not None else 0.),history=SimpleNamespace(last=lambda:{'Date':current,'BarStart':current-timedelta(minutes=30)},to_frame=lambda tail:frame.tail(tail)))
        return step(ctx,SimpleNamespace(cycle=None if rec is None else SimpleNamespace(entry_at=entry,values=rec)))
    def saved(x):return dict(x.cycle_values.values)
    assert saved(call('IMMEDIATE',record()))['support']==105.
    x=call(rec=record());s=saved(x);assert s['support']==100. and s['pending_support'] and s['candidate_high']==120. and s['candidate_low']==105.,'Candidate freezes left-only high and is not support'
    v['close']=120.;assert saved(call(rec=record()))['support']==100.,'High equality not accepted'
    v.update(close=120.01,high=121.);x=call(rec=record());assert saved(x)['support']==105. and not saved(x)['pending_support'],'Same complete right bar may confirm and accept'
    v.update(close=131.,high=132.,low=104.,previous_low=106.,low2=109.);x=call(rec=record(pending_support=True,candidate_low=105.,candidate_high=130.));assert saved(x)['support']==100. and not saved(x)['pending_support'],'New lower Low cancels before close breakout'
    v.update(close=125.,high=126.,low=110.,previous_low=108.,low2=111.);s=saved(call(rec=record(pending_support=True,candidate_low=105.,candidate_high=130.)));assert s['candidate_low']==105. and s['candidate_high']==130.,'Higher small pivot cannot replace frozen candidate'
    v.update(close=110.,high=111.,low=107.,previous_low=105.,low2=108.);entry=datetime(2019,1,3,10,tzinfo=zone);assert not saved(call(rec=record()))['pending_support'],'Partial entry left bar cannot seed'
    entry=datetime(2019,1,3,9,30,tzinfo=zone);assert not saved(call(rec=record()))['pending_support'],'Entry interval cannot be pivot left even if OPEN'
    entry=current;z=saved(call(rec=record(peak=0.,peak_before_last=0.)));assert z['peak']==0. and z['peak_before_last']==0.,'Current pre-entry full interval high excluded'
    entry=datetime(2019,1,3,9,0,tzinfo=zone);v['low2']=105.;assert not saved(call(rec=record()))['pending_support'];v['low2']=108.
    v['low']=105.;assert not saved(call(rec=record()))['pending_support'];v['low']=107.
    assert not saved(call(rec=record(support=105.)))['pending_support']
    v['close']=100.;assert call(rec=record()).decision.target==1;v['close']=99.99;assert call(rec=record()).decision.target==0
    v.update(close=140.,high=141.);x=call(rec=record(exit_due=True,exit_reason='INITIAL_SUPPORT_BREAK',pending_support=True,candidate_low=105.,candidate_high=130.));assert x.decision.target==0 and saved(x)['support']==100.,'Due no upgrade/reversal'
    v.update(close=110.,high=111.,previous_volume=1.);assert call(entry_policy='M005').decision.target==0 and call(entry_policy='M006').decision.target==1,'M006 removes both volume and narrow TR restrictions'
    v.update(previous_volume=1.5,previous_tr=2.);assert call(entry_policy='M005').decision.target==0 and call(entry_policy='M006').decision.target==1;v['previous_tr']=1.
    x=call();assert saved(x)['peak']==0. and not saved(x)['pending_support'],'Unfilled proposal has no activated postfill peak'
    results={}
    for key in PARAMETERS:
        a=replay(key,bars);b=replay(key,changed);assert prefix(a.execution_result)==prefix(b.execution_result)
        assert len(a.execution_result.fills)>0 and (a.execution_result.account_points.cash>=0).all()
        rows=json.loads(a.execution_result.decisions.to_json(orient='records',date_format='iso'));facts=[{v['key']:v['text'] for v in row['explanation']['basis']} for row in rows]
        assert facts[0]['portfolio_quantity']=='0' and facts[0]['cycle_present']=='False'
        fills=a.execution_result.fills.to_dict('records');firstbuy=next(f for f in fills if f['side']=='BUY');assert str(firstbuy['time_precision']).endswith('BAR_INTERVAL'),firstbuy
        assert pd.Timestamp(firstbuy['interval_start'])==starts[275] and pd.Timestamp(firstbuy['executed_at'])==ends[275]
        firsttrade=a.execution_result.trades.to_dict('records')[0];assert pd.Timestamp(firsttrade['entry_at'])==starts[275]
        firstheld=next(f for f in facts if f['held']=='True');observed_peak=float(firstheld['peak'])
        assert (observed_peak>0 if key=='C0109' else observed_peak==0.),'Actual runtime interval-start clock must exclude entire entry bar in revised source'
        raises=sum(f['support_raised']=='True' for f in facts);assert raises>0
        if PARAMETERS[key]['support']=='ACCEPTED':assert sum(f['candidate_accepted']=='True' for f in facts)>0
        average=len(a.execution_result.decisions.to_json(orient='records',date_format='iso').encode())/len(rows);assert average<20000
        results[key]={'average_decision_bytes':average,'price_and_volume_prefix_invariance':'PASS','fills':len(a.execution_result.fills),'module_loads':a.statistics.module_loads,'support_raises':raises,'forced_public_first_buy_precision':'BAR_INTERVAL','cycle_entry_is_interval_start':True,'executed_at_is_interval_end':True,'first_held_peak':observed_peak,'candidate_created':sum(f['candidate_created']=='True' for f in facts),'candidate_cancelled':sum(f['candidate_cancelled']=='True' for f in facts),'candidate_accepted':sum(f['candidate_accepted']=='True' for f in facts),'support_exit_decisions':sum(f['exit_trigger']!='NONE' for f in facts)}
    save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'synthetic_only':True,'legacy_control_source_sha256':digest(WORK.parents[0]/'EX050_20261031/src/strategy.py'),'accounts':results,'direct_boundaries':['strict M006 removes volume/TR only','same completed right bar may accept','asof left highest High excludes middle/right','H frozen and higher pivot ignored','candidate lowerLow cancels before samebar close>H','strict Close>H','strict pivot equality','pivot=support no upgrade','truepostfill full left bars only','whole entry interval excluded even OPEN','genuine public BAR_INTERVAL actual entry/start and executed/end inspected','unfilled proposal no peak activation','support equality holds','due no candidate upgrade/reversal'],'limitations':'Focused synthetic/price+volume suffix/state boundaries, not all calendar/events or financial validity'})
    print('PUBLIC_PRICE_ACCEPTANCE_PRECHECK_PASS',flush=True)
if __name__=='__main__':main()
