"""Frozen multi-full context and g: direct boundaries plus real public execution."""
from datetime import date,datetime,timedelta
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

sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
mod=import_module('research.S017.experiments.'+WORK.name+'.src.strategy')
step,OUTPUTS=mod.step,mod.OUTPUTS
negative_run=import_module('research.S017.experiments.'+WORK.name+'.src.negative_run').negative_run
ZONE=ZoneInfo('America/New_York')


def direct():
    ends=pd.date_range('2024-03-08T15:00Z',periods=261,freq='30min')
    frame=pd.DataFrame(dict(Date=ends,BarStart=ends-pd.Timedelta(minutes=30),Open=100.,Close=100.,High=101.,Low=99.))
    frame.loc[257,['Open','Close','High','Low']]=[100.,100.,999.,99.]
    frame.loc[258,['Open','Close','High','Low']]=[102.,101.,103.,100.]
    frame.loc[259,['Open','Close','High','Low']]=[100.,99.,101.,98.]
    frame.loc[260,['Open','Close','High','Low']]=[104.,104.,999.,103.]
    now=ends[-1].to_pydatetime();point=DecisionPoint(now,now,TimeInterval(now,now+timedelta(minutes=30)))
    r=negative_run(SimpleNamespace(to_frame=lambda tail:frame.tail(tail)),point)
    assert r['length']==2 and r['high']==103.
    assert r['terminator_at']==ends[257] and r['run_start_at']==ends[258]
    bad=frame.copy();bad['Open']=bad['Close']+1
    try:negative_run(SimpleNamespace(to_frame=lambda tail:bad.tail(tail)),point)
    except ValueError as e:assert 'LEFT_CENSORED' in str(e)
    else:raise AssertionError('No real terminator was silently truncated')
    v={k:1. for k in OUTPUTS};v.update(close=104.,high=105.,low=103.,previous_low=98.,low2=100.,previous_close=99.,previous_open=100.,previous_high=101.,previous_volume=1.,same_slot_median20=1.,previous_tr=1.,atr_before_prior=1.,previous_ma65=90.,previous_ma260=80.)
    def call(key,u=True,kind='MF',cycle=None):
        f=frame.copy();current=now if cycle is None else now+timedelta(minutes=30)
        if cycle is not None:f['Date']+=pd.Timedelta(minutes=30);f['BarStart']+=pd.Timedelta(minutes=30)
        if kind=='SINGLE':f.loc[258,['Open','Close']]=[101.,101.]
        values=dict(v);values['previous_ma65']=90. if u else 110.
        if kind=='EQUAL':values['close']=103.
        if kind=='MP':values['close']=102.
        p=DecisionPoint(current,current,TimeInterval(current,current+timedelta(minutes=30)))
        ctx=SimpleNamespace(parameters=PARAMETERS[key],events=(),point=p,features=SimpleNamespace(get=lambda k:ReadyValue(values[k])),portfolio=SimpleNamespace(quantity=int(cycle is not None),cash=0. if cycle else 100000.,reference_price_scale=1.,cycle_entry=now if cycle else None,cycle_cost=100. if cycle else 0.),history=SimpleNamespace(last=lambda:{'Date':current,'BarStart':current-timedelta(minutes=30)},to_frame=lambda tail:f.tail(tail)))
        return step(ctx,SimpleNamespace(cycle=None if cycle is None else SimpleNamespace(entry_at=now,values=StateRecord(tuple(cycle.items())))))
    for u in (True,False):
        for key,expected in (('C0335',.75 if u else 0.),('C0336',0.),('C0337',.75)):
            out=call(key,u);s=dict(out.cycle_values.values)
            assert s['entry_multi_full'] and s['entry_negative_run_length']==2 and s['entry_negative_run_high']==103. and s['cycle_g']==expected
            for kind in ('SINGLE','MP','EQUAL'):
                q=dict(call(key,u,kind).cycle_values.values)
                assert not q['entry_multi_full'] and q['cycle_g']==(.75 if u else 0.)
            held=call(key,not u,'SINGLE',s);z=dict(held.cycle_values.values)
            assert z['entry_multi_full'] and z['cycle_g']==expected and z['entry_negative_run_high']==103.
            assert z['peak']==0.,'Whole actual entry interval is excluded'
            due=dict(s);due.update(exit_due=True,exit_reason='INITIAL_SUPPORT_BREAK')
            locked=dict(call(key,not u,'MP',due).cycle_values.values)
            assert locked['exit_due'] and locked['entry_multi_full'] and locked['cycle_g']==expected
    return dict(MF_U_route_matrix=True,SINGLE_MP_and_R_equality_keep_original=True,current_U_MF_does_not_change_entry=True,original_due_frozen=True,entry_interval_excluded=True,actual_terminator_current_high_excluded=True,leftcensor_explicit_error=True)


def public_synthetic():
    days=[d.date() for d in pd.bdate_range('2024-02-01',periods=30)]
    sessions=tuple(TradingSession(d,str(ZONE),(TimeInterval(datetime.combine(d,datetime.min.time().replace(hour=9,minute=30),ZONE),datetime.combine(d,datetime.min.time().replace(hour=16),ZONE)),)) for d in days)
    periods=[p for ss in sessions for p in ss.bars(BarFrequency.M30)]
    starts=pd.DatetimeIndex([p.start for p in periods]).tz_convert('UTC');ends=pd.DatetimeIndex([p.end for p in periods]).tz_convert('UTC')
    def fixture(slope):
        prices=100+slope*np.arange(len(periods));bars=pd.DataFrame(dict(BarStart=starts,Date=ends,AvailableDate=ends,Open=prices,High=prices+.1,Low=prices-.1,Close=prices,Volume=1000000.,Amount=prices*1000000.))
        c=float(bars.loc[271,'Close'])
        for j,vals in {272:[c+.8,c+.9,c+.4,c+.5],273:[c+.6,c+.7,c+.2,c+.3],274:[c+1.1,c+1.3,c+1.,c+1.2],275:[c+.85,c+1.4,c+.75,c+1.3],276:[c+2.,c+2.1,c+1.9,c+2.],277:[c+1.6,c+1.7,c+1.5,c+1.6],278:[c+2.3,c+2.4,c+2.2,c+2.3],279:[c+1.7,c+1.8,c+1.6,c+1.7],280:[c-1.,c-.9,c-1.1,c-1.]}.items():bars.loc[j,['Open','High','Low','Close']]=vals
        for j,kind in ((300,'MP'),(326,'SINGLE')):
            b=float(bars.loc[j-3,'Close'])
            if kind=='MP':bars.loc[j-2,['Open','High','Low','Close']]=[b+2.8,b+3.,b+1.1,b+1.2]
            bars.loc[j-1,['Open','High','Low','Close']]=[b+1.,b+1.1,b+.4,b+.5]
            bars.loc[j,['Open','High','Low','Close']]=[b+1.4,b+1.6,b+1.3,b+1.5]
            bars.loc[j+1,['Open','High','Low','Close']]=[b+1.5,b+1.6,b+1.4,b+1.5]
            bars.loc[j+2,['Open','High','Low','Close']]=[b-.5,b-.4,b-.6,b-.5]
        return bars
    bars=fixture(.005)
    constraints=pd.DataFrame(dict(Date=starts,AvailableDate=starts,QuantityStep=1,PriceTick=.01,Tradable=True,PriceLimitPolicy='EXPLICIT_UNBOUNDED',PriceLimitLower=None,PriceLimitUpper=None,BuySellableAt=starts,SettlementAt=starts,SellRemainderPolicy='STRICT_STEP'))
    actions=pd.DataFrame([dict(Date=starts[0],AvailableDate=starts[0],EventId='none',Kind='NONE',Ratio=1.,CashPerShare=0.,PayAt=None)])
    calendar=pd.DataFrame(dict(Date=[s.segments[0].start for s in sessions],AvailableDate=[s.segments[0].start for s in sessions],SessionDate=[s.session_date.isoformat() for s in sessions]))
    def replay(cand,frame,rules=constraints):
        p=PreparedReplay.from_frames(frame,rules,cand.definition.feature_graph,frequency=BarFrequency.M30,timezone=str(ZONE),sessions=calendar,trading_sessions=sessions)
        executor=PortfolioHistoricalExecutor(specification=SPEC,initial_cash=100000.,fee_rate=.001,actions=actions,price_basis='RAW')
        return run_replay(p,cand,executor,start=starts[274].to_pydatetime(),end=ends[-1].to_pydatetime(),fee_rate=.001).execution_result
    def decoded(result):
        rows=json.loads(result.decisions.to_json(orient='records',date_format='iso'));return rows,[{x['key']:x['text'] for x in r['explanation']['basis']} for r in rows]
    olddef=EquityStrategyDefinition.from_dict(read(ROOT/'research/S017/experiments/EX056_20261031/protocols/definitions.json')['C0222'])
    old=replay(EquityStrategyCandidate('S017','C0222',olddef,ROOT/'research/S017/experiments/EX056_20261031/src'),bars)
    results={};summary={};cut=340;future=bars.copy();future.loc[cut:,['Open','High','Low','Close']]*=1.7;future.loc[cut:,'Volume']*=2
    for key in PARAMETERS:
        base=replay(candidate(key),bars);suffix=replay(candidate(key),future);results[key]=base
        rows,ff=decoded(base);sources={r['decision_id']:f for r,f in zip(rows,ff)};orders={o['order_id']:o for o in base.orders.to_dict('records')};types=set();below=0
        for fill in base.fills.to_dict('records'):
            if fill['side']!='BUY':continue
            f=sources[orders[fill['order_id']]['decision_id']];length=int(f['current_negative_run_length']);mf=f['current_multi_full']=='True'
            types.add('MF' if mf else 'SINGLE' if length==1 else 'MP')
            if mf and float(fill['price'])<float(f['current_negative_run_high']):below+=1
        assert types=={'MF','MP','SINGLE'},(key,types)
        assert below>=1,'Real MF BUY below frozen runR retained'
        assert any(f['candidate_accepted']=='True' for f in ff)
        byorder={x['order_id']:x for x in base.orders.to_dict('records')};bydecision={x['decision_id']:f for x,f in zip(rows,ff)}
        for fill in base.fills.to_dict('records'):
            if fill['side']!='BUY':continue
            sf=bydecision[byorder[fill['order_id']]['decision_id']]
            first=next(f for r,f in zip(rows,ff) if pd.Timestamp(r['decision_at'])>=pd.Timestamp(fill['interval_end']) and f['held']=='True')
            assert (first['entry_multi_full'],first['entry_negative_run_length'],first['entry_negative_run_high'],first['cycle_g'])==(sf['current_multi_full'],sf['current_negative_run_length'],sf['current_negative_run_high'],sf['current_context_g'])
        for table,field in (('decisions','decision_at'),('orders','valid_start'),('fills','interval_start'),('account_points','time'),('account_daily','time'),('trades','exit_at')):
            def prefix(r):
                f=getattr(r,table)
                if f.empty:return '[]'
                f=f[pd.to_datetime(f[field],utc=True)<starts[cut]]
                return f.drop(columns=[c for c in f if c.endswith('_id')]).to_json(orient='records',date_format='iso',double_precision=15)
            assert prefix(base)==prefix(suffix),(key,table)
        summary[key]=dict(actual_contexts=sorted(types),MF_actual_buy_below_runR=below,source_proposal_inherited=True,real_accepted_raise=True,price_volume_suffix_prefix=True)
    for table in ('orders','fills','account_points','account_daily','trades'):
        def clean(r):
            f=getattr(r,table);return f.drop(columns=[c for c in f if c.endswith('_id')]).to_json(orient='records',date_format='iso',double_precision=15)
        assert clean(old)==clean(results['C0335']),table
    assert [r['target'] for r in decoded(old)[0]]==[r['target'] for r in decoded(results['C0335'])[0]]
    # A genuine failed first BUY creates no active cycle or frozen MF.
    failed=bars.copy();failed.loc[275,['Open','High','Low','Close']]=[110.,111.,109.,110.]
    failed_result=replay(candidate('C0337'),failed);rr,ff=decoded(failed_result);f=next(f for r,f in zip(rr,ff) if pd.Timestamp(r['observed_through'])==ends[275]);assert f['held']=='False' and f['cycle_present']=='False'
    assert any(o['side']=='BUY' and o['status']!='FILLED' for o in failed_result.orders.to_dict('records'))
    # Existing exit-due remains latched through a real blocked SELL interval.
    rr,ff=decoded(results['C0335']);trigger=next(r for r,f in zip(rr,ff) if f['exit_due']=='True');k=list(starts).index(pd.Timestamp(trigger['execution_start']))
    blocked_rules=constraints.copy();blocked_rules.loc[k:k+1,'Tradable']=False
    blocked_result=replay(candidate('C0335'),bars,blocked_rules);br,bf=decoded(blocked_result)
    assert any(o['side']=='SELL' and o['status']!='FILLED' for o in blocked_result.orders.to_dict('records'))
    locked=[f for r,f in zip(br,bf) if pd.Timestamp(r['decision_at']) in (starts[k],starts[k+1])]
    assert len(locked)==2 and all(f['exit_due']=='True' and f['entry_multi_full']=='True' and f['cycle_g']==locked[0]['cycle_g'] for f in locked)
    # Descending warmup makes the same actual MF context nonU; PROTECT still freezes .75.
    down=replay(candidate('C0337'),fixture(-.005));dr,df=decoded(down);initial=next(f for f in df if f['held']=='True')
    assert initial['entry_multi_full']=='True' and initial['entry_u']=='False' and float(initial['cycle_g'])==.75
    return dict(three_real_modes=summary,KEEP_old_five_economic_tables_and_decision_targets=True,real_failed_BUY_no_cycle=True,real_blocked_SELL_due_and_entry_context_latched=True,real_MF_nonU_forced_protection=True)


def main():
    bounds=direct();public=public_synthetic();counts=read(WORK/'others/context_branch_counts.json')
    if not counts['mf_clock48_equals_ex070']:raise ValueError('Original MF clock guard required')
    save(WORK/'others/precheck.json',dict(status='PASS',strategy_sha256=digest(WORK/'src/strategy.py'),helper_sha256=digest(WORK/'src/negative_run.py'),precheck_sha256=digest(WORK/'src/precheck.py'),direct=bounds,public_synthetic=public,all_clock_MF_matches_07048=True,context_branch_counts_sha256=digest(WORK/'others/context_branch_counts.json'),formal_account_compute=0,new_return_labels=0))
    print('ENTRY_FROZEN_MULTIFULL_G_PRECHECK_PASS')


if __name__=='__main__':main()
