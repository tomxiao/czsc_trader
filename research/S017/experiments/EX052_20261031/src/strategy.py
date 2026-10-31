"""Continuous reclaim strength and structural failure, exact C113 zero-point, no timing exits."""
from math import isfinite
from strategy_runtime import (AccountDecision,AccountStepResult,BarField,FeatureGraph,Lag,Mean,RawField,ReadyValue,SameLocalSlotMedian,StateField,StateRecord,StateValueType,StrategyStateSchema,TrueRange)
OUTPUTS=('close','high','low','previous_low','low2','previous_close','previous_open','previous_high','previous_volume','previous_tr','atr_before_prior','same_slot_median20')
def feature_graph():
    return FeatureGraph((RawField('close',BarField.CLOSE),RawField('opening',BarField.OPEN),RawField('high',BarField.HIGH),RawField('low',BarField.LOW),RawField('volume',BarField.VOLUME),Lag('previous_close','close',1),Lag('previous_open','opening',1),Lag('previous_high','high',1),Lag('previous_low','low',1),Lag('low2','low',2),Lag('previous_volume','volume',1),TrueRange('tr','high','low','close'),Mean('atr13','tr',13),Lag('previous_tr','tr',1),Lag('atr_before_prior','atr13',2),SameLocalSlotMedian('same_slot_median20','volume',20,1)),OUTPUTS)
def state_schema():
    fields=(('holding_bars',StateValueType.INT),('last_completed_at',StateValueType.DATETIME),('exit_due',StateValueType.BOOL),('initial_support',StateValueType.FLOAT),('support',StateValueType.FLOAT),('support_raises',StateValueType.INT),('exit_reason',StateValueType.STR),('peak',StateValueType.FLOAT),('peak_before_last',StateValueType.FLOAT),('pending_support',StateValueType.BOOL),('candidate_low',StateValueType.FLOAT),('candidate_high',StateValueType.FLOAT),('candidate_at',StateValueType.DATETIME),('raw_s0',StateValueType.FLOAT),('reclaimed_level',StateValueType.FLOAT),('accepted_active',StateValueType.BOOL),('accepted_low',StateValueType.FLOAT),('accepted_high',StateValueType.FLOAT),('accepted_peak_close',StateValueType.FLOAT),('entry_scale',StateValueType.FLOAT),('signal_reference_close',StateValueType.FLOAT))
    return StrategyStateSchema(cycle_fields=tuple(StateField(k,v) for k,v in fields))
def step(ctx,state):
    if set(ctx.parameters)!={'alpha','initial_fraction','accepted_fraction'}:raise ValueError('Three declared financial parameters required')
    pars={k:float(x) for k,x in ctx.parameters.items() if type(x) in (int,float)}
    if len(pars)!=3 or not all(isfinite(x) for x in pars.values()) or not 0<=pars['alpha'] or not all(0<=pars[k]<=1 for k in ('initial_fraction','accepted_fraction')):raise ValueError('Declared initial/extension and natural parameter domains only')
    p=ctx.portfolio
    if p.reference_price_scale!=1. or ctx.events:raise ValueError('RAW NONE contract only')
    v={}
    for k in OUTPUTS:
        x=ctx.features.get(k)
        if type(x) is not ReadyValue:raise ValueError('Ready complete observations required')
        v[k]=float(x.value)
    m006=v['previous_close']<v['previous_open'] and v['close']>v['previous_high'];m005=m006 and v['previous_volume']>=1.5*v['same_slot_median20'] and v['previous_tr']<=v['atr_before_prior']
    delta=v['close']-v['previous_high'];scale=v['atr_before_prior']
    if scale<0:raise ValueError('True range scale cannot be negative')
    signal=m006 and delta>pars['alpha']*scale
    current=ctx.history.last()['Date'];held=p.quantity>0;proposal=None
    facts={**v,'entry_signal':bool(signal),'m005_signal':bool(m005),'m006_signal':bool(m006),'alpha':pars['alpha'],'initial_fraction':pars['initial_fraction'],'accepted_fraction':pars['accepted_fraction'],'reclaim_margin_atr':delta/scale if scale>0 else None,'setup_risk_distance_atr':(v['close']-min(v['previous_low'],v['low']))/scale if scale>0 else None,'normalization_defined':scale>0,'held':held,'portfolio_quantity':p.quantity,'portfolio_cash':p.cash,'cycle_present':state.cycle is not None,'holding_bars':0,'exit_due':False,'exit_trigger':'NONE','support_raised':False,'pivot_confirmed':False,'candidate_cancelled':False,'candidate_created':False,'candidate_accepted':False}
    if held:
        if state.cycle is None or state.cycle.entry_at!=p.cycle_entry or p.cycle_cost<=0:raise ValueError('Actual activated cycle required')
        s=dict(state.cycle.values.values)
        if current<=s['last_completed_at']:raise ValueError('Complete observation must advance')
        s['holding_bars']+=1;s['last_completed_at']=current
        if not s['exit_due']:
            pivot=v['previous_low']<v['low2'] and v['previous_low']<v['low'] and v['previous_low']>s['support']
            eligible=False
            if pivot:
                three=ctx.history.to_frame(tail=3)
                if len(three)!=3 or not three.Date.is_monotonic_increasing or three.Date.duplicated().any() or three.Date.iloc[-1]!=current:raise ValueError('Exactly last three completed bars required')
                eligible=three.BarStart.iloc[0]>p.cycle_entry
            facts['pivot_confirmed']=bool(eligible)
            if s['pending_support'] and v['low']<s['candidate_low']:s['pending_support']=False;facts['candidate_cancelled']=True
            if eligible and not s['pending_support']:
                if s['peak_before_last']<=0:raise ValueError('Pre-pivot full held peak required')
                s.update(pending_support=True,candidate_low=v['previous_low'],candidate_high=s['peak_before_last'],candidate_at=current);facts['candidate_created']=True
            if s['pending_support'] and v['close']>s['candidate_high']:
                if not s['candidate_low']>s['support']:raise ValueError('Support only increases')
                L=s['candidate_low'];H=s['candidate_high']
                new_support=L+pars['accepted_fraction']*(H-L)
                if not new_support>s['support']:raise ValueError('New accepted line must increase naturally')
                s.update(support=new_support,accepted_active=True,accepted_low=L,accepted_high=H,accepted_peak_close=v['close']);s['support_raises']+=1;s['pending_support']=False;facts.update(support_raised=True,candidate_accepted=True)
            if v['close']<s['support']:s['exit_due']=True;s['exit_reason']='INITIAL_SUPPORT_BREAK' if s['support']==s['initial_support'] else 'CONFIRMED_HIGHER_SUPPORT_BREAK'
            if ctx.history.last()['BarStart']>p.cycle_entry:
                s['peak_before_last']=s['peak'];s['peak']=max(s['peak'],v['high'])
                if s['accepted_active']:s['accepted_peak_close']=max(s['accepted_peak_close'],v['close'])
        proposal=StateRecord(tuple(s.items()));target=int(not s['exit_due']);facts.update(holding_bars=s['holding_bars'],exit_due=s['exit_due'],exit_trigger=s['exit_reason'],initial_support=s['initial_support'],support=s['support'],support_raises=s['support_raises'],pending_support=s['pending_support'],candidate_low=s['candidate_low'],candidate_high=s['candidate_high'],candidate_at=s['candidate_at'],peak=s['peak'],peak_before_last=s['peak_before_last'],raw_s0=s['raw_s0'],reclaimed_level=s['reclaimed_level'],accepted_active=s['accepted_active'],accepted_low=s['accepted_low'],accepted_high=s['accepted_high'],initial_position=(v['close']-s['raw_s0'])/(s['reclaimed_level']-s['raw_s0']),entry_signal_risk_atr=(s['signal_reference_close']-s['raw_s0'])/s['entry_scale'] if s['entry_scale']>0 else None,entry_scale=s['entry_scale'],signal_reference_close=s['signal_reference_close'],actual_cycle_net_mark_return=(p.quantity*v['close']*.999-p.cycle_cost)/p.cycle_cost)
        if s['accepted_active']:
            D=s['accepted_high']-s['accepted_low']
            if D<=0:raise ValueError('Accepted H/L pair must have positive span')
            facts.update(accepted_position=(v['close']-s['accepted_low'])/D,accepted_progress=(s['accepted_peak_close']-s['accepted_high'])/D,accepted_retracement=(s['accepted_peak_close']-v['close'])/D)
    else:
        target=int(signal)
        if target:
            raw=min(v['previous_low'],v['low']);R=v['previous_high']
            if not R>raw:raise ValueError('Reclaim structure must have positive width')
            floor=raw+pars['initial_fraction']*(R-raw);proposal=StateRecord((('holding_bars',0),('last_completed_at',current),('exit_due',False),('initial_support',floor),('support',floor),('support_raises',0),('exit_reason','NONE'),('peak',0.),('peak_before_last',0.),('pending_support',False),('candidate_low',0.),('candidate_high',0.),('candidate_at',current),('raw_s0',raw),('reclaimed_level',R),('accepted_active',False),('accepted_low',0.),('accepted_high',0.),('accepted_peak_close',0.),('entry_scale',scale),('signal_reference_close',v['close'])))
    return AccountStepResult(AccountDecision.from_facts(target,'Reclaimed continuation, confirmed swing and price acceptance',facts=facts,next_watch='Only real complete held structure; candidate is not yet support, all exits next interval and locked',capital_mode='full_available_cash'),StateRecord(),proposal)

