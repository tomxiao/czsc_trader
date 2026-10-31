"""M005 or prior65-high breakout entries, fixed26 completed-bar holding."""
from strategy_runtime import (AccountDecision, AccountStepResult, BarField, FeatureGraph,
    Lag, Mean, RawField, ReadyValue, SameLocalSlotMedian, StateField, StateRecord,
    StateValueType, StrategyStateSchema, TrueRange)

OUTPUTS = ('close', 'previous_close', 'previous_open', 'previous_high',
    'previous_volume', 'previous_tr', 'atr_before_prior', 'same_slot_median20',*(f'high{i}' for i in range(1,66)))


def feature_graph():
    nodes = (RawField('close', BarField.CLOSE), RawField('opening', BarField.OPEN),
        RawField('high', BarField.HIGH), RawField('low', BarField.LOW), RawField('volume', BarField.VOLUME),
        Lag('previous_close', 'close', 1), Lag('previous_open', 'opening', 1),
        Lag('previous_high', 'high', 1), Lag('previous_volume', 'volume', 1),
        TrueRange('tr', 'high', 'low', 'close'), Mean('atr13', 'tr', 13),
        Lag('previous_tr', 'tr', 1), Lag('atr_before_prior', 'atr13', 2),
        SameLocalSlotMedian('same_slot_median20', 'volume', 20, 1),*(Lag(f'high{i}','high',i) for i in range(1,66)))
    return FeatureGraph(nodes, OUTPUTS)


def state_schema():
    return StrategyStateSchema(cycle_fields=(StateField('holding_bars',StateValueType.INT),StateField('last_completed_at',StateValueType.DATETIME),StateField('exit_due',StateValueType.BOOL),StateField('origin',StateValueType.STR)))

def step(ctx,state):
    if set(ctx.parameters)!={'policy'} or ctx.parameters['policy'] not in ('BASELINE','BREAKOUT65','UNION26'):raise ValueError('Only declared fixed26 policies')
    policy=ctx.parameters['policy'];portfolio=ctx.portfolio
    if portfolio.reference_price_scale!=1. or ctx.events:raise ValueError('Retained RAW NONE-event contract only')
    values={}
    for key in OUTPUTS:
        item=ctx.features.get(key)
        if type(item) is not ReadyValue:raise ValueError('Full warmup required')
        values[key]=float(item.value)
    high65=max(values[f'high{i}'] for i in range(1,66))
    m005=(values['previous_close']<values['previous_open'] and values['previous_volume']>=1.5*values['same_slot_median20'] and values['previous_tr']<=values['atr_before_prior'] and values['close']>values['previous_high'])
    breakout=values['close']>high65
    signal=m005 if policy=='BASELINE' else breakout if policy=='BREAKOUT65' else m005 or breakout
    origin='M005' if m005 and policy!='BREAKOUT65' else 'BREAKOUT65'
    current=ctx.history.last()['Date'];held=portfolio.quantity>0;proposal=None
    facts={k:v for k,v in values.items() if not k.startswith('high')};facts.update(high65=high65,entry_signal=bool(signal),m005_signal=bool(m005),breakout_signal=bool(breakout),policy=policy,held=held,portfolio_quantity=portfolio.quantity,portfolio_cash=portfolio.cash,cycle_present=state.cycle is not None,holding_bars=0,exit_due=False,exit_trigger='NONE',signal_origin=origin if signal else 'NONE')
    if held:
        if state.cycle is None or state.cycle.entry_at!=portfolio.cycle_entry or portfolio.cycle_cost<=0:raise ValueError('Actual activated cycle required')
        saved=dict(state.cycle.values.values)
        if current<=saved['last_completed_at']:raise ValueError('Observation must advance')
        saved['holding_bars']+=1;saved['last_completed_at']=current;saved['exit_due']=saved['exit_due'] or saved['holding_bars']>=26
        target=int(not saved['exit_due']);proposal=StateRecord(tuple(saved.items()));facts.update(holding_bars=saved['holding_bars'],exit_due=saved['exit_due'],exit_trigger='FIXED26' if saved['exit_due'] else 'NONE',cycle_origin=saved['origin'])
    else:
        target=int(signal)
        if target:proposal=StateRecord((('holding_bars',0),('last_completed_at',current),('exit_due',False),('origin',origin)))
    return AccountStepResult(AccountDecision.from_facts(target,'Fixed26 source comparison',facts=facts,next_watch='Actual fill starts26; locked exit; next interval execution',capital_mode='full_available_cash'),StateRecord(),proposal)
