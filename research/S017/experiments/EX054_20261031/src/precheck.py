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
    base={'entry_mode':'E0','alpha':0.,'initial_fraction':0.,'accepted_fraction':0.,'progress_protection':0.}
    cases={'C0163':None,'C0166':base,'C0167':PARAMETERS['C0209'],'C0168':PARAMETERS['C0210'],'C9901':{**base,'progress_protection':1.},'C9902':{**base,'accepted_fraction':1.,'progress_protection':1.},'C9903':{**base,'progress_protection':.5},'C9904':{**base,'entry_mode':'E1','progress_protection':.75}}
    v={k:1. for k in OUTPUTS};v.update(close=110.,high=111.,low=107.,previous_low=105.,low2=108.,previous_close=106.,previous_open=107.,previous_high=108.,previous_volume=1.5,same_slot_median20=1.,previous_tr=1.,atr_before_prior=1.)
    current=datetime(2019,1,3,11,tzinfo=zone);entry=datetime(2019,1,3,9,0,tzinfo=zone);last=current-timedelta(minutes=30)
    def record(**extra):
        s=dict(holding_bars=2,last_completed_at=last,exit_due=False,initial_support=100.,support=100.,support_raises=0,exit_reason='NONE',peak=125.,peak_before_last=120.,pending_support=False,candidate_low=0.,candidate_high=0.,candidate_at=last,raw_s0=100.,reclaimed_level=108.,accepted_active=False,accepted_low=0.,accepted_high=0.,accepted_peak_close=0.,entry_scale=1.,signal_reference_close=110.);s.update(extra);return StateRecord(tuple(s.items()))
    def call(pars=base,rec=None):
        frame=pd.DataFrame({'BarStart':[current-timedelta(minutes=m) for m in (90,60,30)],'Date':[current-timedelta(minutes=m) for m in (60,30,0)]})
        ctx=SimpleNamespace(parameters=pars,events=(),features=SimpleNamespace(get=lambda k:ReadyValue(v[k])),portfolio=SimpleNamespace(quantity=int(rec is not None),cash=100000. if rec is None else 0.,reference_price_scale=1.,cycle_entry=entry if rec is not None else None,cycle_cost=100. if rec is not None else 0.),history=SimpleNamespace(last=lambda:{'Date':current,'BarStart':current-timedelta(minutes=30)},to_frame=lambda tail:frame.tail(tail)))
        return step(ctx,SimpleNamespace(cycle=None if rec is None else SimpleNamespace(entry_at=entry,values=rec)))
    def saved(x):return dict(x.cycle_values.values)
    v.update(previous_close=108.,previous_open=107.);assert call(base).decision.target==0;assert call({**base,'entry_mode':'E1'}).decision.target==1,'E1 accepts prior bullish high breakout'
    v.update(previous_close=107.,previous_open=107.);assert call(base).decision.target==0;assert call({**base,'entry_mode':'E1'}).decision.target==1,'E1 accepts prior doji high breakout'
    assert call({**base,'entry_mode':'E1','alpha':2.}).decision.target==0,'E1 strict alpha equality rejects'
    v.update(close=108.);assert call({**base,'entry_mode':'E1'}).decision.target==0,'E1 strict previous-high equality rejects'
    v.update(previous_high=105.,previous_low=105.,previous_close=105.,previous_open=105.,low=106.,close=110.);assert call({**base,'entry_mode':'E1'}).decision.target==0,'Legal OHLC zero-width geometry excluded by common domain'
    v.update(previous_high=108.,previous_low=105.,low=107.,close=110.,previous_close=106.,previous_open=107.)
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
    x=call({**base,'accepted_fraction':1.,'progress_protection':1.},record(accepted_active=True,accepted_low=100.,accepted_high=110.,accepted_peak_close=120.,support=120.,support_raises=1));assert x.decision.target==1 and saved(x)['support']==130.,'New peak equality never self-exits at b1/g1'
    v.update(close=119.,high=130.,low=118.)
    x=call({**base,'accepted_fraction':1.,'progress_protection':1.},record(accepted_active=True,accepted_low=100.,accepted_high=110.,accepted_peak_close=130.,support=130.,support_raises=1,pending_support=True,candidate_low=111.,candidate_high=115.));assert x.decision.target==0 and not saved(x)['support_raises']>1,'Oldline due dominates even adversarial pending break'
    v.update(close=125.,high=126.,low=119.,previous_low=111.,low2=113.)
    x=call({**base,'progress_protection':1.},record(accepted_active=True,accepted_low=100.,accepted_high=110.,accepted_peak_close=120.,support=110.,support_raises=1,pending_support=True,candidate_low=112.,candidate_high=118.));assert x.decision.target==1 and saved(x)['support']==115. and not saved(x)['pending_support'],'Dynamic line over candidate Low revokes qualification before acceptance'
    v.update(close=112.,high=113.,low=111.,previous_low=110.,low2=112.)
    x=call({**base,'progress_protection':1.},record(accepted_active=True,accepted_low=100.,accepted_high=110.,accepted_peak_close=125.,support=115.,support_raises=1));assert x.decision.target==0,'Dynamic-only failure above base still exits, no net-profit gate'
    v.update(close=130.,high=140.,low=125.)
    x=call({**base,'accepted_fraction':1.,'progress_protection':1.},record(exit_due=True,exit_reason='CONFIRMED_HIGHER_SUPPORT_BREAK',accepted_active=True,accepted_low=100.,accepted_high=110.,accepted_peak_close=120.,support=120.,support_raises=1,peak=125.,pending_support=True,candidate_low=121.,candidate_high=125.));assert x.decision.target==0 and saved(x)['support']==120. and saved(x)['accepted_peak_close']==120. and saved(x)['peak']==125. and saved(x)['pending_support'],'Blocked due financial state frozen'
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
    save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'control_source_hashes':{'C0163':digest(WORK.parents[0]/'EX051_20261031/src/strategy.py'),'E0_original':digest(WORK.parents[0]/'EX053_20261031/src/strategy.py')},'synthetic_old_controls':['C0163'],'synthetic_only':True,'accounts':results,'direct_boundaries':['E1 previous bullish and doji both accepted; E0 rejects','E1 strict alpha and previous-high equalities reject','Legal prior zero-range OHLC yields zero structural width rejected','alpha strict equality and scale0 multiplication','a0/S0 a1/R and midpoint','b0/L b1/H and midpoint','no accepted samebar selfexit','no implicit max/line naturally rises','rawS0 vs actual initial line vs accepted pair distinct','pending cannot overwrite last accepted pair','current line changes eligible pivot population','whole entry interval excluded even OPEN','genuine public BAR_INTERVAL timing inspected','support equality holds','a>0 firstexit initial reason','g1/b1 newpeak equality','dynamic-only failure vs base failure distinct','pending L<=dynamic line revoked','adversarial pending cannot reverse oldline due','blocked due financial state frozen','g protects confirmed price advance not net cycle profit'],'limitations':'Synthetic only; E0 two complete training12 economic projections vs prior C168/C179 required; no search'})
    print('PUBLIC_STAGE3_STATE_PRECHECK_PASS',flush=True)
if __name__=='__main__':main()
