"""Same deep-repair entry, competing frozen target, original structure, accepted structure."""
from strategy_runtime import (AccountDecision,AccountStepResult,BarField,FeatureGraph,Lag,
    Mean,RawField,ReadyValue,StateField,StateRecord,StateValueType,StrategyStateSchema,TrueRange)

OUTPUTS=('close','high','low','low2','previous_close','previous_high','previous_low','previous_mean65','previous_atr13')


def feature_graph():
    return FeatureGraph((RawField('close',BarField.CLOSE),RawField('high',BarField.HIGH),
        RawField('low',BarField.LOW),Lag('low2','low',2),Lag('previous_close','close',1),
        Lag('previous_high','high',1),Lag('previous_low','low',1),Mean('mean65','close',65),
        Lag('previous_mean65','mean65',1),TrueRange('tr','high','low','close'),
        Mean('atr13','tr',13),Lag('previous_atr13','atr13',1)),OUTPUTS)


def state_schema():
    fields=(('signal_at',StateValueType.DATETIME),('frozen_target',StateValueType.FLOAT),
        ('initial_support',StateValueType.FLOAT),('last_completed_at',StateValueType.DATETIME),
        ('exit_due',StateValueType.BOOL),('exit_reason',StateValueType.STR),
        ('support',StateValueType.FLOAT),('support_raises',StateValueType.INT),
        ('peak',StateValueType.FLOAT),('peak_before_last',StateValueType.FLOAT),
        ('pending_support',StateValueType.BOOL),('candidate_low',StateValueType.FLOAT),
        ('candidate_high',StateValueType.FLOAT),('candidate_at',StateValueType.DATETIME),
        ('accepted_low',StateValueType.FLOAT),('accepted_high',StateValueType.FLOAT))
    return StrategyStateSchema(cycle_fields=tuple(StateField(k,t) for k,t in fields))


def step(ctx,state):
    if set(ctx.parameters)!={'policy'} or ctx.parameters['policy'] not in ('FROZEN_CENTER_REPAIR','INITIAL_STRUCTURE_ONLY','ACCEPTED_HIGHER_SUPPORT'):
        raise ValueError('Three predeclared deep-repair holding policies only')
    policy=ctx.parameters['policy'];p=ctx.portfolio
    if p.reference_price_scale!=1. or ctx.events:raise ValueError('Retained RAW NONE-event contract only')
    v={}
    for k in OUTPUTS:
        x=ctx.features.get(k)
        if type(x) is not ReadyValue:raise ValueError('Completed ready features required')
        v[k]=float(x.value)
    current=ctx.history.last()['Date'];held=p.quantity>0;proposal=None
    raw=v['previous_close']<=v['previous_mean65']-2*v['previous_atr13'] and v['close']>v['previous_high']
    room=v['close']<v['previous_mean65'];signal=raw and room
    facts={**v,'raw_c':bool(raw),'target_room':bool(room),'entry_signal':bool(signal),'policy':policy,
        'held':held,'portfolio_quantity':p.quantity,'portfolio_cash':p.cash,'cycle_present':state.cycle is not None,
        'exit_due':False,'exit_trigger':'NONE','pivot_confirmed':False,'candidate_created':False,
        'candidate_cancelled':False,'candidate_accepted':False,'support_raised':False}
    if held:
        if state.cycle is None or state.cycle.entry_at!=p.cycle_entry or p.cycle_cost<=0:raise ValueError('Actual activated holding required')
        s=dict(state.cycle.values.values)
        if current<=s['last_completed_at']:raise ValueError('Completed observation must advance')
        s['last_completed_at']=current
        if not s['exit_due']:
            if policy=='ACCEPTED_HIGHER_SUPPORT':
                eligible=False
                if v['previous_low']<v['low2'] and v['previous_low']<v['low'] and v['previous_low']>s['support']:
                    three=ctx.history.to_frame(tail=3)
                    if len(three)!=3 or not three.Date.is_monotonic_increasing or three.Date.duplicated().any() or three.Date.iloc[-1]!=current:raise ValueError('Last three completed observations required')
                    eligible=three.BarStart.iloc[0]>p.cycle_entry
                facts['pivot_confirmed']=bool(eligible)
                if s['pending_support'] and v['low']<s['candidate_low']:
                    s['pending_support']=False;facts['candidate_cancelled']=True
                if eligible and not s['pending_support']:
                    if s['peak_before_last']<=0:raise ValueError('Completed held left-peak required')
                    s.update(pending_support=True,candidate_low=v['previous_low'],candidate_high=s['peak_before_last'],candidate_at=current);facts['candidate_created']=True
                if s['pending_support'] and v['close']>s['candidate_high']:
                    if not s['candidate_low']>s['support']:raise ValueError('Accepted support must rise')
                    s.update(support=s['candidate_low'],support_raises=s['support_raises']+1,
                        pending_support=False,accepted_low=s['candidate_low'],accepted_high=s['candidate_high'])
                    facts.update(candidate_accepted=True,support_raised=True)
            if v['close']<s['support']:
                s['exit_due']=True;s['exit_reason']='INITIAL_STRUCTURE_FAILED' if s['support_raises']==0 else 'ACCEPTED_SUPPORT_FAILED'
            elif policy=='FROZEN_CENTER_REPAIR' and v['close']>=s['frozen_target']:
                s['exit_due']=True;s['exit_reason']='TARGET_REACHED'
            if policy=='ACCEPTED_HIGHER_SUPPORT' and ctx.history.last()['BarStart']>p.cycle_entry:
                s['peak_before_last']=s['peak'];s['peak']=max(s['peak'],v['high'])
        target=int(not s['exit_due']);proposal=StateRecord(tuple(s.items()))
        facts.update({k:s[k] for k in ('signal_at','frozen_target','initial_support','support','support_raises','peak','peak_before_last','pending_support','candidate_low','candidate_high','candidate_at','accepted_low','accepted_high','exit_due')})
        facts.update(exit_trigger=s['exit_reason'],actual_cycle_cost=p.cycle_cost,
            target_estimated_net_space=p.quantity*s['frozen_target']*.999-p.cycle_cost,
            actual_cycle_net_mark=p.quantity*v['close']*.999-p.cycle_cost)
    else:
        target=int(signal)
        if target:
            floor=min(v['previous_low'],v['low']);goal=v['previous_mean65']
            if not floor<v['close']<goal:raise ValueError('Positive repair structure required')
            vals=dict(signal_at=current,frozen_target=goal,initial_support=floor,last_completed_at=current,
                exit_due=False,exit_reason='NONE',support=floor,support_raises=0,peak=0.,peak_before_last=0.,
                pending_support=False,candidate_low=0.,candidate_high=0.,candidate_at=current,accepted_low=0.,accepted_high=0.)
            proposal=StateRecord(tuple(vals.items()));facts.update(signal_at=current,frozen_target=goal,initial_support=floor)
    return AccountStepResult(AccountDecision.from_facts(target,'Deep reclaim repair versus continuing recovery',facts=facts,
        next_watch='Only completed close can end frozen repair/original or accepted structure; no time cap; due locks',capital_mode='full_available_cash'),StateRecord(),proposal)
