"""Causal opening-low risk role: direct boundaries and real public synthetic replay."""
from datetime import date,datetime,time,timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from importlib import import_module
import json
import sys
import numpy as np
import pandas as pd
from dataflows import BarFrequency,TradingSession,TimeInterval
from strategy_runtime import PreparedReplay,run_replay,ReadyValue,StateRecord,DecisionPoint,EquityStrategyDefinition,EquityStrategyCandidate
from trading_execution_engine import PortfolioHistoricalExecutor
from common import ROOT,WORK,PARAMETERS,SPEC,candidate,save,digest,read

sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
module=import_module('research.S017.experiments.'+WORK.name+'.src.strategy')
step,OUTPUTS=module.step,module.OUTPUTS
opening_reference=import_module('research.S017.experiments.'+WORK.name+'.src.opening_reference').opening_reference
ZONE=ZoneInfo('America/New_York')


def direct():
    day=date(2024,3,11);prior=date(2024,3,8)
    def make(day,close=16,level=100.):
        start=datetime.combine(day,time(9,30),ZONE);end=datetime.combine(day,time(close),ZONE)
        ss=TradingSession(day,str(ZONE),(TimeInterval(start,end),))
        rows=[dict(BarStart=p.start,Date=p.end,Open=level,High=level+1,Low=level-1,Close=level) for p in ss.bars(BarFrequency.M30)]
        return ss,rows
    ss,rows=make(day);_,past=make(prior);_,past2=make(date(2024,3,7))
    frame=pd.DataFrame(past2+past+rows[:3]);now=frame.Date.iloc[-1].to_pydatetime()
    v={k:1. for k in OUTPUTS};v.update(close=98.,high=99.,low=97.,previous_low=96.,low2=97.,previous_close=100.,previous_open=99.,previous_high=101.,atr_before_prior=1.,previous_ma65=95.,previous_ma260=94.,previous_volume=1.,same_slot_median20=1.)
    entry=datetime.combine(prior,time(14),ZONE)
    def rec(**kw):
        z=dict(opening_day='',opening_low=0.,opening_at=entry,opening_carryin=False,holding_bars=4,last_completed_at=now-timedelta(minutes=30),exit_due=False,initial_support=90.,support=90.,support_raises=0,exit_reason='NONE',peak=105.,peak_before_last=104.,pending_support=False,candidate_low=0.,candidate_high=0.,candidate_at=entry,raw_s0=89.,reclaimed_level=95.,accepted_active=False,accepted_low=0.,accepted_high=0.,accepted_peak_close=0.,entry_scale=1.,signal_reference_close=100.,entry_u=True,cycle_g=0.)
        z.update(kw);return z
    def call(key,state=None,when=None,data=None,session=None,cycle_entry=None):
        nonlocal now
        f=frame if data is None else data;t=f.Date.iloc[-1].to_pydatetime() if when is None else when
        e=entry if cycle_entry is None else cycle_entry;s=rec() if state is None else dict(state)
        s['last_completed_at']=t-timedelta(minutes=30)
        period=TimeInterval(t,t+timedelta(minutes=30))
        actual_session=ss if session is None else session
        if t.astimezone(ZONE).date()!=actual_session.session_date:period=actual_session.bars(BarFrequency.M30)[0]
        p=DecisionPoint(t,period.start,period)
        ctx=SimpleNamespace(parameters=PARAMETERS[key],events=(),features=SimpleNamespace(get=lambda k:ReadyValue(v[k])),portfolio=SimpleNamespace(quantity=1,cash=0.,reference_price_scale=1.,cycle_entry=e,cycle_cost=100.),point=p,session=actual_session,history=SimpleNamespace(last=lambda:{**f.iloc[-1].to_dict(),'Date':t},to_frame=lambda tail:f.tail(tail)))
        result=step(ctx,SimpleNamespace(cycle=SimpleNamespace(entry_at=e,values=StateRecord(tuple(s.items())))))
        return dict(result.cycle_values.values),{x.key:x.text for x in result.decision.explanation.basis}
    s,f=call('C0333');assert s['exit_reason']=='OVERNIGHT_OPENING_LOW_BREAK'
    eq=v['close'];v['close']=99.;s,_=call('C0333');assert not s['exit_due'];v['close']=eq
    accepted=rec(accepted_active=True,accepted_low=90.,accepted_high=95.,accepted_peak_close=100.,support=90.+PARAMETERS['C0333']['accepted_fraction']*5)
    s,_=call('C0333',accepted);assert not s['exit_due']
    s,_=call('C0334',accepted);assert s['exit_reason']=='OVERNIGHT_OPENING_LOW_BREAK'
    s,_=call('C0333',rec(support=98.5));assert s['exit_reason']=='INITIAL_SUPPORT_BREAK'
    pending=rec(pending_support=True,candidate_low=96.,candidate_high=97.)
    off,_=call('C0332',pending);on,_=call('C0333',pending)
    assert off['accepted_active'] and not on['accepted_active'] and on['exit_reason']=='OVERNIGHT_OPENING_LOW_BREAK','Start scope before a possible first acceptance'
    frozen=rec(exit_due=True,exit_reason='INITIAL_SUPPORT_BREAK',opening_day='old',opening_low=123.,opening_at=entry,opening_carryin=True)
    s,_=call('C0334',frozen);assert (s['opening_day'],s['opening_low'],s['exit_reason'])==('old',123.,'INITIAL_SUPPORT_BREAK')
    s,_=call('C0334',cycle_entry=rows[0]['BarStart']);assert not s['opening_carryin'] and not s['exit_due'],'Day first interval BUY is not carryin'
    # First bar can build the reference but cannot fail its own low.
    v.update(close=100.,low=99.,high=101.)
    first=pd.DataFrame(past2+past+rows[:1]);s,_=call('C0334',data=first);assert s['opening_low']==99. and not s['exit_due']
    # Last completed close is still checked against its observed-day reference at next open.
    v.update(close=98.,low=97.,high=99.)
    nextss,_=make(date(2024,3,12));full=pd.DataFrame(past2+past+rows)
    s,_=call('C0333',data=full,session=nextss);assert s['exit_reason']=='OVERNIGHT_OPENING_LOW_BREAK' and s['opening_day']==day.isoformat()
    # New observed day lower reference changes only the daily guard, not old support.
    nextss,nextrows=make(date(2024,3,12),level=95.);v.update(close=95.,low=94.,high=96.)
    s,_=call('C0333',rec(support=94.5,opening_day=day.isoformat(),opening_low=99.,opening_at=rows[0]['Date'],opening_carryin=True),data=pd.DataFrame(past+rows+nextrows[:1]),session=nextss)
    assert s['opening_low']==94. and s['support']==94.5 and not s['exit_due']
    for d,h in ((date(2024,3,8),16),(date(2024,3,11),16),(date(2024,11,29),13)):
        session,rr=make(d,h);_,older=make(d-timedelta(days=1));_,older2=make(d-timedelta(days=2))
        f=pd.DataFrame(older2+older+rr)
        point=DecisionPoint(rr[-1]['Date'],rr[-1]['Date'],TimeInterval(rr[-1]['Date'],rr[-1]['Date']+timedelta(minutes=30)))
        r=opening_reference(SimpleNamespace(to_frame=lambda tail:f.tail(tail)),point,session,rr[0]['BarStart']-timedelta(days=1));assert r['low']==99.
    return {'scope_start_not_post_acceptance':True,'strict_equality_and_first_bar':True,'original_due_first_and_blocked_freeze':True,'new_day_lower_reference_not_support':True,'new_cycle_same_day_no_carry':True,'old_observed_day_last_close_at_next_open':True,'halfday_DST_public_calendar':True}


def public_synthetic():
    days=[d.date() for d in pd.bdate_range('2024-10-24',periods=41) if d.date()!=date(2024,11,28)]
    sessions=tuple(TradingSession(d,str(ZONE),(TimeInterval(datetime.combine(d,time(9,30),ZONE),datetime.combine(d,time(13 if d==date(2024,11,29) else 16),ZONE)),)) for d in days)
    periods=[p for ss in sessions for p in ss.bars(BarFrequency.M30)]
    starts=pd.DatetimeIndex([p.start for p in periods]).tz_convert('UTC');ends=pd.DatetimeIndex([p.end for p in periods]).tz_convert('UTC')
    i=np.arange(len(periods));prices=100+.005*i+.15*np.sin(i/7)
    bars=pd.DataFrame(dict(BarStart=starts,Date=ends,AvailableDate=ends,Open=prices+.005,High=prices+.03,Low=prices-.03,Close=prices,Volume=1000000.,Amount=prices*1000000.))
    begin=22*13
    # E0 entry late in a session, carry to a higher opening range then reject its low.
    c=float(bars.loc[begin+9,'Close']);j=begin+9
    bars.loc[j,['Open','High','Low','Close']]=[c+.01,c+.02,c-.02,c]
    bars.loc[j+1,['Open','High','Low','Close']]=[c+.4,c+.65,c+.35,c+.6]
    bars.loc[j+2,['Open','High','Low','Close']]=[c+.61,c+.72,c+.6,c+.7]
    bars.loc[j+3,['Open','High','Low','Close']]=[c+.7,c+.8,c+.65,c+.75]
    bars.loc[j+4,['Open','High','Low','Close']]=[c+2.,c+2.2,c+1.8,c+2.1]
    bars.loc[j+5,['Open','High','Low','Close']]=[c+2.1,c+2.15,c+1.2,c+1.3]
    bars.loc[j+6,['Open','High','Low','Close']]=[c+1.25,c+1.4,c+1.1,c+1.3]
    constraints=pd.DataFrame(dict(Date=starts,AvailableDate=starts,QuantityStep=1,PriceTick=.01,Tradable=True,PriceLimitPolicy='EXPLICIT_UNBOUNDED',PriceLimitLower=None,PriceLimitUpper=None,BuySellableAt=starts,SettlementAt=starts,SellRemainderPolicy='STRICT_STEP'))
    actions=pd.DataFrame([dict(Date=starts[0],AvailableDate=starts[0],EventId='none',Kind='NONE',Ratio=1.,CashPerShare=0.,PayAt=None)])
    calendar=pd.DataFrame(dict(Date=[s.segments[0].start for s in sessions],AvailableDate=[s.segments[0].start for s in sessions],SessionDate=[s.session_date.isoformat() for s in sessions]))
    def replay(cand,frame,rules=constraints):
        p=PreparedReplay.from_frames(frame,rules,cand.definition.feature_graph,frequency=BarFrequency.M30,timezone=str(ZONE),sessions=calendar,trading_sessions=sessions)
        e=PortfolioHistoricalExecutor(specification=SPEC,initial_cash=100000.,fee_rate=.001,actions=actions,price_basis='RAW')
        return run_replay(p,cand,e,start=starts[begin].to_pydatetime(),end=ends[-1].to_pydatetime(),fee_rate=.001).execution_result
    def decode(result):
        rr=json.loads(result.decisions.to_json(orient='records',date_format='iso'));return rr,[{x['key']:x['text'] for x in r['explanation']['basis']} for r in rr]
    olddef=EquityStrategyDefinition.from_dict(read(ROOT/'research/S017/experiments/EX056_20261031/protocols/definitions.json')['C0222'])
    old=replay(EquityStrategyCandidate('S017','C0222',olddef,ROOT/'research/S017/experiments/EX056_20261031/src'),bars)
    results={};outputs={};cut=begin+25;changed=bars.copy();changed.loc[cut:,['Open','High','Low','Close']]*=1.5;changed.loc[cut:,'Volume']*=2
    tables=('orders','fills','account_points','account_daily','trades','decisions')
    for key in PARAMETERS:
        cand=candidate(key);base=replay(cand,bars);future=replay(cand,changed);results[key]=base
        rr,ff=decode(base)
        for table,field in (('orders','valid_start'),('fills','interval_start'),('account_points','time'),('account_daily','time'),('trades','exit_at'),('decisions','decision_at')):
            def prefix(r):
                x=getattr(r,table)
                if x.empty:return '[]'
                x=x[pd.to_datetime(x[field],utc=True)<starts[cut]]
                return x.drop(columns=[c for c in x if c.endswith('_id')]).to_json(orient='records',date_format='iso',double_precision=15)
            assert prefix(base)==prefix(future),(key,table,'future-prefix')
        if key!='C0332':assert any(f['opening_low_failure']=='True' for f in ff),(key,'real guard trigger')
        outputs[key]={'actual_buys':sum(x['side']=='BUY' for x in base.fills.to_dict('records')),'opening_low_due':sum(f['opening_low_failure']=='True' for f in ff),'real_cycles_no_new_entry_reference':True,'future_price_volume_prefix':True}
    economic=('orders','fills','account_points','account_daily','trades')
    for table in economic:
        def clean(r):
            f=getattr(r,table);return f.drop(columns=[c for c in f if c.endswith('_id')]).to_json(orient='records',date_format='iso',double_precision=15)
        assert clean(old)==clean(results['C0332']),(table,'disabled economic control')
    assert [x['target'] for x in decode(old)[0]]==[x['target'] for x in decode(results['C0332'])[0]]
    # Real failed BUY creates no cycle / opening reference. Real blocked SELL retains due.
    rr,ff=decode(results['C0333']);order=next(o for o in results['C0333'].orders.to_dict('records') if o['side']=='BUY');idx=list(starts).index(pd.Timestamp(order['valid_start']))
    failed=bars.copy();high=float(order['limit_price'])+1.;failed.loc[idx,['Open','High','Low','Close']]=[high,high+.1,high-.1,high]
    bad=replay(candidate('C0333'),failed);br,bf=decode(bad)
    assert any(o['side']=='BUY' and o['status']!='FILLED' for o in bad.orders.to_dict('records'))
    firstheld_afterfailed=next((f for r,f in zip(br,bf) if pd.Timestamp(r['observed_through'])==ends[idx]),None)
    assert firstheld_afterfailed is not None and firstheld_afterfailed['held']=='False' and firstheld_afterfailed['cycle_present']=='False'
    trigger=next(r for r,f in zip(rr,ff) if f['opening_low_failure']=='True');k=list(starts).index(pd.Timestamp(trigger['execution_start']))
    rules=constraints.copy();rules.loc[k:k+1,'Tradable']=False
    blocked=replay(candidate('C0333'),bars,rules);zr,zf=decode(blocked)
    assert any(o['side']=='SELL' and o['status']!='FILLED' for o in blocked.orders.to_dict('records'))
    latched=[f for r,f in zip(zr,zf) if pd.Timestamp(r['decision_at']) in (starts[k],starts[k+1])]
    assert len(latched)==2 and all(f['exit_due']=='True' and f['exit_trigger']=='OVERNIGHT_OPENING_LOW_BREAK' for f in latched)
    return {'three_real_policies':outputs,'disabled_old_source_five_tables_and_decision_targets':True,'real_failed_BUY_no_cycle':True,'real_blocked_SELL_due_latched':True,'halfday_and_DST_schedule_available':True}


def main():
    boundaries=direct();public=public_synthetic()
    save(WORK/'others/precheck.json',dict(status='PASS',strategy_sha256=digest(WORK/'src/strategy.py'),helper_sha256=digest(WORK/'src/opening_reference.py'),precheck_sha256=digest(WORK/'src/precheck.py'),direct=boundaries,public_synthetic=public,formal_account_compute=0,new_return_labels=0))
    print('OPENING_LOW_RISK_PRECHECK_PASS')


if __name__=='__main__':main()
