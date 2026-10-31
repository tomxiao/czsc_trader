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
    q=c+.35;bars.loc[274,['Open','High','Low','Close']]=[q-.01,q+.02,q-.02,q]
    bars.loc[275,['Open','High','Low','Close']]=[q*1.02,q*1.025,q*.995,q*1.005]
    changed=bars.copy(); changed.loc[520:,['Open','High','Low','Close']]*=1.7; changed.loc[520:,'Amount']*=1.7; changed.loc[520:,'Volume']*=3
    def replay(key,frame):
        c=candidate(key,None if key=='C0163' else cases[key]); p=PreparedReplay.from_frames(frame,constraints,c.definition.feature_graph,frequency=BarFrequency.M30,timezone=str(zone),sessions=calendar,trading_sessions=sessions)
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
    base={'alpha':0.,'initial_fraction':0.,'accepted_fraction':0.,'g_when_u':0.,'g_when_other':0.}
    cases={'C0163':None,'C0166':base,'C0167':PARAMETERS['C0219'],'C0168':PARAMETERS['C0220'],'C9901':{**base,'g_when_u':1.,'g_when_other':1.},'C9902':{**base,'accepted_fraction':1.,'g_when_u':1.,'g_when_other':1.},'C9903':{**base,'g_when_u':.5,'g_when_other':.5},'C9904':PARAMETERS['C0221'],'C9905':PARAMETERS['C0222']}
    v={k:1. for k in OUTPUTS};v.update(close=110.,high=111.,low=107.,previous_low=105.,low2=108.,previous_close=106.,previous_open=107.,previous_high=108.,previous_volume=1.5,same_slot_median20=1.,previous_tr=1.,atr_before_prior=1.)
    current=datetime(2019,1,3,11,tzinfo=zone);entry=datetime(2019,1,3,9,0,tzinfo=zone);last=current-timedelta(minutes=30)
    def record(**extra):
        s=dict(holding_bars=2,last_completed_at=last,exit_due=False,initial_support=100.,support=100.,support_raises=0,exit_reason='NONE',peak=125.,peak_before_last=120.,pending_support=False,candidate_low=0.,candidate_high=0.,candidate_at=last,raw_s0=100.,reclaimed_level=108.,accepted_active=False,accepted_low=0.,accepted_high=0.,accepted_peak_close=0.,entry_scale=1.,signal_reference_close=110.,entry_u=False);s.update(extra);return StateRecord(tuple(s.items()))
    def call(pars=base,rec=None):
        if rec is not None and 'cycle_g' not in dict(rec.values):
            vals=dict(rec.values);vals['cycle_g']=float(pars['g_when_u'] if vals['entry_u'] else pars['g_when_other']);rec=StateRecord(tuple(vals.items()))
        frame=pd.DataFrame({'BarStart':[current-timedelta(minutes=m) for m in (90,60,30)],'Date':[current-timedelta(minutes=m) for m in (60,30,0)]})
        ctx=SimpleNamespace(parameters=pars,events=(),features=SimpleNamespace(get=lambda k:ReadyValue(v[k])),portfolio=SimpleNamespace(quantity=int(rec is not None),cash=100000. if rec is None else 0.,reference_price_scale=1.,cycle_entry=entry if rec is not None else None,cycle_cost=100. if rec is not None else 0.),history=SimpleNamespace(last=lambda:{'Date':current,'BarStart':current-timedelta(minutes=30)},to_frame=lambda tail:frame.tail(tail)))
        return step(ctx,SimpleNamespace(cycle=None if rec is None else SimpleNamespace(entry_at=entry,values=rec)))
    def saved(x):return dict(x.cycle_values.values)
    v.update(previous_ma65=105.,previous_ma260=104.)
    mapping={**base,'g_when_u':0.,'g_when_other':.75}
    first=saved(call(mapping));assert first['entry_u'] is True and first['cycle_g']==0.,'Entry U chooses g0 proposal'
    v.update(previous_ma65=107.,previous_ma260=108.)
    second=saved(call(mapping));assert second['entry_u'] is False and second['cycle_g']==.75,'Unfilled prior proposal not inherited by next flat setup'
    v.update(previous_ma65=106.,previous_ma260=105.);assert saved(call(mapping))['entry_u'] is False,'Previous Close equals MA65 is non-U'
    v.update(previous_ma65=105.,previous_ma260=105.);assert saved(call(mapping))['entry_u'] is False,'MA65 equals MA260 is non-U'
    v.update(close=125.,high=126.,low=120.,previous_low=118.,low2=119.)
    held=record(entry_u=True,cycle_g=.75,accepted_active=True,accepted_low=100.,accepted_high=110.,accepted_peak_close=120.,support=110.,support_raises=1)
    a=saved(call(mapping,held));b=saved(call({**mapping,'g_when_u':1.,'g_when_other':0.},held));assert a['cycle_g']==b['cycle_g']==.75 and a['support']==b['support'],'Current background/parameters do not change activated cycle g'
    v.update(previous_ma65=105.,previous_ma260=104.);c=saved(call(mapping,held));assert c['cycle_g']==.75 and c['support']==a['support'],'Current U flip does not change cycle g'
    blocked=record(entry_u=False,cycle_g=.75,exit_due=True,exit_reason='CONFIRMED_HIGHER_SUPPORT_BREAK',accepted_active=True,accepted_low=100.,accepted_high=110.,accepted_peak_close=120.,support=117.5,support_raises=1)
    blocked_after=saved(call(mapping,blocked));assert blocked_after['cycle_g']==.75 and blocked_after['support']==117.5 and blocked_after['accepted_peak_close']==120.,'Blocked due freezes cycle g and price state'
    v.update(close=110.,high=111.,low=107.,previous_low=105.,low2=108.,previous_ma65=1.,previous_ma260=1.)
    z=saved(call());assert z['raw_s0']==105. and z['initial_support']==105. and z['reclaimed_level']==108. and z['entry_scale']==1. and z['signal_reference_close']==110.
    assert saved(call({**base,'initial_fraction':1.}))['initial_support']==108.
    assert saved(call({**base,'initial_fraction':.5}))['initial_support']==106.5
    assert call({**base,'alpha':2.}).decision.target==0,'Strict alpha threshold equality rejects'
    assert call({**base,'alpha':1.999}).decision.target==1
    v['atr_before_prior']=0.;assert call({**base,'alpha':2.}).decision.target==1,'Zero scale uses multiplication, no epsilon or division';v['atr_before_prior']=1.
    x=call(rec=record());s=saved(x);assert s['support']==100. and s['pending_support'] and s['candidate_high']==120. and s['candidate_low']==105.
    v['close']=120.;assert saved(call(rec=record()))['support']==100.,'High equality not acceptance'
    v.update(close=120.01,high=121.);x=call({**base,'accepted_fraction':1.},record());s=saved(x);assert s['support']==120. and x.decision.target==1 and s['accepted_low']==105. and s['accepted_high']==120.,'b=1 freezes H without samebar self-exit'
    x=call({**base,'accepted_fraction':.5},record());assert saved(x)['support']==112.5
    v.update(close=110.,high=111.);s=saved(call({**base,'initial_fraction':1.},record(initial_support=108.,support=108.)));assert not s['pending_support'],'Tighter current line changes pivot population explicitly'
    v.update(close=131.,high=132.,low=104.,previous_low=106.,low2=109.);x=call(rec=record(pending_support=True,candidate_low=105.,candidate_high=130.));assert saved(x)['support']==100. and not saved(x)['pending_support']
    v.update(close=125.,high=126.,low=110.,previous_low=108.,low2=111.);s=saved(call(rec=record(pending_support=True,candidate_low=105.,candidate_high=130.,accepted_active=True,accepted_low=101.,accepted_high=115.,accepted_peak_close=126.)));assert s['candidate_high']==130. and s['accepted_high']==115. and s['accepted_low']==101.,'Pending never overwrites accepted pair'
    v.update(close=110.,high=111.,low=107.,previous_low=105.,low2=108.);entry=datetime(2019,1,3,9,30,tzinfo=zone);assert not saved(call(rec=record()))['pending_support'],'Whole entry interval excluded even OPEN'
    entry=current;z=saved(call(rec=record(peak=0.,peak_before_last=0.)));assert z['peak']==0.
    entry=datetime(2019,1,3,9,0,tzinfo=zone);v['low2']=105.;assert not saved(call(rec=record()))['pending_support'];v['low2']=108.
    v['low']=105.;assert not saved(call(rec=record()))['pending_support'];v['low']=107.
    assert not saved(call(rec=record(support=105.)))['pending_support']
    v['close']=108.;assert call({**base,'initial_fraction':1.},record(initial_support=108.,support=108.)).decision.target==1
    v['close']=107.99;x=call({**base,'initial_fraction':1.},record(initial_support=108.,support=108.));assert saved(x)['exit_reason']=='INITIAL_SUPPORT_BREAK','a>0 first exit is still initial, not raised'
    v.update(close=140.,high=141.);x=call(rec=record(exit_due=True,exit_reason='INITIAL_SUPPORT_BREAK',pending_support=True,candidate_low=105.,candidate_high=130.));assert x.decision.target==0 and saved(x)['support']==100. and saved(x)['peak']==125.
    v.update(close=130.,high=131.,low=125.,previous_low=124.,low2=126.)
    x=call({**base,'accepted_fraction':1.,'g_when_u':1.,'g_when_other':1.},record(accepted_active=True,accepted_low=100.,accepted_high=110.,accepted_peak_close=120.,support=120.,support_raises=1));assert x.decision.target==1 and saved(x)['support']==130.,'New peak equality never self-exits at b1/g1'
    v.update(close=119.,high=130.,low=118.)
    x=call({**base,'accepted_fraction':1.,'g_when_u':1.,'g_when_other':1.},record(accepted_active=True,accepted_low=100.,accepted_high=110.,accepted_peak_close=130.,support=130.,support_raises=1,pending_support=True,candidate_low=111.,candidate_high=115.));assert x.decision.target==0 and not saved(x)['support_raises']>1,'Oldline due dominates even adversarial pending break'
    v.update(close=125.,high=126.,low=119.,previous_low=111.,low2=113.)
    x=call({**base,'g_when_u':1.,'g_when_other':1.},record(accepted_active=True,accepted_low=100.,accepted_high=110.,accepted_peak_close=120.,support=110.,support_raises=1,pending_support=True,candidate_low=112.,candidate_high=118.));assert x.decision.target==1 and saved(x)['support']==115. and not saved(x)['pending_support'],'Dynamic line over candidate Low revokes qualification before acceptance'
    v.update(close=112.,high=113.,low=111.,previous_low=110.,low2=112.)
    x=call({**base,'g_when_u':1.,'g_when_other':1.},record(accepted_active=True,accepted_low=100.,accepted_high=110.,accepted_peak_close=125.,support=115.,support_raises=1));assert x.decision.target==0,'Dynamic-only failure above base still exits, no net-profit gate'
    v.update(close=130.,high=140.,low=125.)
    x=call({**base,'accepted_fraction':1.,'g_when_u':1.,'g_when_other':1.},record(exit_due=True,exit_reason='CONFIRMED_HIGHER_SUPPORT_BREAK',accepted_active=True,accepted_low=100.,accepted_high=110.,accepted_peak_close=120.,support=120.,support_raises=1,peak=125.,pending_support=True,candidate_low=121.,candidate_high=125.));assert x.decision.target==0 and saved(x)['support']==120. and saved(x)['accepted_peak_close']==120. and saved(x)['peak']==125. and saved(x)['pending_support'],'Blocked due financial state frozen'
    results={}
    for key in cases:
        a=replay(key,bars);b=replay(key,changed);assert prefix(a.execution_result)==prefix(b.execution_result)
        assert len(a.execution_result.fills)>0 and (a.execution_result.account_points.cash>=0).all()
        rows=json.loads(a.execution_result.decisions.to_json(orient='records',date_format='iso'));facts=[{v['key']:v['text'] for v in row['explanation']['basis']} for row in rows]
        assert facts[0]['portfolio_quantity']=='0' and facts[0]['cycle_present']=='False'
        fills=a.execution_result.fills.to_dict('records');firstbuy=next(f for f in fills if f['side']=='BUY');assert str(firstbuy['time_precision']).endswith('BAR_INTERVAL')
        assert pd.Timestamp(firstbuy['interval_start'])==starts[275] and pd.Timestamp(firstbuy['executed_at'])==ends[275]
        firsttrade=a.execution_result.trades.to_dict('records')[0];assert pd.Timestamp(firsttrade['entry_at'])==starts[275]
        firstheld=next(f for f in facts if f['held']=='True');assert float(firstheld['peak'])==0.
        average=len(a.execution_result.decisions.to_json(orient='records',date_format='iso').encode())/len(rows);assert average<20000
        results[key]={'parameters':cases[key],'average_decision_bytes':average,'price_and_volume_prefix_invariance':'PASS','fills':len(a.execution_result.fills),'support_raises':sum(f['support_raised']=='True' for f in facts),'forced_public_first_buy_precision':'BAR_INTERVAL','first_held_peak':float(firstheld['peak'])}
    failed_frame=bars.copy();failed_frame.loc[275,['Open','High','Low','Close']]=[q*1.02,q*1.025,q*1.015,q*1.02]
    failed=replay('C9904',failed_frame).execution_result
    failed_fills=failed.fills.to_dict('records');first_actual=next(f for f in failed_fills if f['side']=='BUY');assert pd.Timestamp(first_actual['interval_start'])>starts[275],'First proposal must genuinely fail to buy'
    failed_rows=json.loads(failed.decisions.to_json(orient='records',date_format='iso'));before_buy=[r for r in failed_rows if pd.Timestamp(r['decision_at'])<pd.Timestamp(first_actual['interval_start'])]
    assert before_buy and all({x['key']:x['text'] for x in r['explanation']['basis']}['cycle_present']=='False' for r in before_buy),'Failed buy cannot activate entry background or cycle g'
    results['FAILED_BUY_PUBLIC']={'first_intended_interval':starts[275].isoformat(),'first_actual_buy':str(first_actual['interval_start']),'cycle_absent_until_real_fill':True}
    save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'control_source_hashes':{'C0163':digest(WORK.parents[0]/'EX051_20261031/src/strategy.py'),'static_controls':digest(WORK.parents[0]/'EX055_20261031/src/strategy.py')},'synthetic_old_controls':['C0163'],'synthetic_only':True,'accounts':results,'direct_boundaries':['entry U true/false and strict equalities;real public failed buy no cycle before actual fill','current U and parameter flips preserve frozen cycle g','blocked due freezes selected g and price state','alpha strict equality and scale0 multiplication','a0/S0 a1/R and midpoint','b0/L b1/H and midpoint','no accepted samebar selfexit','no implicit max/line naturally rises','rawS0 vs actual initial line vs accepted pair distinct','pending cannot overwrite last accepted pair','current line changes eligible pivot population','whole entry interval excluded even OPEN','genuine public BAR_INTERVAL timing inspected','support equality holds','a>0 firstexit initial reason','g1/b1 newpeak equality','dynamic-only failure vs base failure distinct','pending L<=dynamic line revoked','adversarial pending cannot reverse oldline due','blocked due financial state frozen','g protects confirmed price advance not net cycle profit'],'limitations':'Synthetic only; two static mapping complete24 economic projections;two fixed enqueued new mappings only'})
    print('PUBLIC_STAGE3_STATE_PRECHECK_PASS',flush=True)
if __name__=='__main__':main()
