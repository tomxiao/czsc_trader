"""Deep-deviation reclaim: repair to frozen prior mean, fail original structure; no clock."""
from strategy_runtime import (AccountDecision, AccountStepResult, BarField, FeatureGraph,
    Lag, Mean, RawField, ReadyValue, StateField, StateRecord, StateValueType,
    StrategyStateSchema, TrueRange)

OUTPUTS=('close','low','previous_close','previous_high','previous_low','previous_mean65','previous_atr13')


def feature_graph():
    return FeatureGraph((RawField('close',BarField.CLOSE),RawField('high',BarField.HIGH),
        RawField('low',BarField.LOW),Lag('previous_close','close',1),
        Lag('previous_high','high',1),Lag('previous_low','low',1),
        Mean('mean65','close',65),Lag('previous_mean65','mean65',1),
        TrueRange('tr','high','low','close'),Mean('atr13','tr',13),
        Lag('previous_atr13','atr13',1)),OUTPUTS)


def state_schema():
    return StrategyStateSchema(cycle_fields=(StateField('signal_at',StateValueType.DATETIME),
        StateField('frozen_target',StateValueType.FLOAT),StateField('initial_support',StateValueType.FLOAT),
        StateField('last_completed_at',StateValueType.DATETIME),StateField('exit_due',StateValueType.BOOL),
        StateField('exit_reason',StateValueType.STR)))


def step(ctx,state):
    if dict(ctx.parameters)!={'policy':'FROZEN_CENTER_REPAIR'}:
        raise ValueError('Only frozen-center repair policy permitted')
    p=ctx.portfolio
    if p.reference_price_scale!=1. or ctx.events:
        raise ValueError('Retained RAW NONE-event contract only')
    v={}
    for key in OUTPUTS:
        x=ctx.features.get(key)
        if type(x) is not ReadyValue:raise ValueError('Completed ready features required')
        v[key]=float(x.value)
    current=ctx.history.last()['Date'];held=p.quantity>0
    raw_c=v['previous_close']<=v['previous_mean65']-2*v['previous_atr13'] and v['close']>v['previous_high']
    room=v['close']<v['previous_mean65'];signal=raw_c and room
    facts={**v,'raw_c':bool(raw_c),'target_room':bool(room),'entry_signal':bool(signal),
        'held':held,'portfolio_quantity':p.quantity,'portfolio_cash':p.cash,
        'cycle_present':state.cycle is not None,'exit_due':False,'exit_trigger':'NONE'}
    proposal=None
    if held:
        if state.cycle is None or state.cycle.entry_at!=p.cycle_entry or p.cycle_cost<=0:
            raise ValueError('Actual activated holding required')
        saved=dict(state.cycle.values.values)
        if current<=saved['last_completed_at']:raise ValueError('Completed observation must advance')
        saved['last_completed_at']=current
        if not saved['exit_due']:
            if v['close']<saved['initial_support']:
                saved['exit_due']=True;saved['exit_reason']='INITIAL_STRUCTURE_FAILED'
            elif v['close']>=saved['frozen_target']:
                saved['exit_due']=True;saved['exit_reason']='TARGET_REACHED'
        target=int(not saved['exit_due']);proposal=StateRecord(tuple(saved.items()))
        facts.update(signal_at=saved['signal_at'],frozen_target=saved['frozen_target'],
            initial_support=saved['initial_support'],exit_due=saved['exit_due'],exit_trigger=saved['exit_reason'],
            actual_cycle_cost=p.cycle_cost,target_estimated_net_space=p.quantity*saved['frozen_target']*.999-p.cycle_cost,
            actual_cycle_net_mark=p.quantity*v['close']*.999-p.cycle_cost)
    else:
        target=int(signal)
        if target:
            floor=min(v['previous_low'],v['low']);goal=v['previous_mean65']
            if not floor<v['close']<goal:raise ValueError('Positive repair structure required')
            proposal=StateRecord((('signal_at',current),('frozen_target',goal),
                ('initial_support',floor),('last_completed_at',current),
                ('exit_due',False),('exit_reason','NONE')))
            facts.update(signal_at=current,frozen_target=goal,initial_support=floor)
    return AccountStepResult(AccountDecision.from_facts(target,'Deep reclaim to frozen original center',
        facts=facts,next_watch='Completed close reaches frozen target or breaks original structure; execute next interval; no time cap',
        capital_mode='full_available_cash'),StateRecord(),proposal)
