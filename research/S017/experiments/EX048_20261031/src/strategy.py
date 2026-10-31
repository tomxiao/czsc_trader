"""M005 post-reclaim continuation with explicit structural failure, no time exit for new policies."""
from strategy_runtime import (AccountDecision, AccountStepResult, BarField, FeatureGraph,
    Lag, Mean, RawField, ReadyValue, SameLocalSlotMedian, StateField, StateRecord,
    StateValueType, StrategyStateSchema, TrueRange)

OUTPUTS = ('close', 'previous_close', 'previous_open', 'previous_high',
    'previous_volume', 'previous_tr', 'atr_before_prior', 'same_slot_median20','low','previous_low','low2')


def feature_graph():
    nodes = (RawField('close', BarField.CLOSE), RawField('opening', BarField.OPEN),
        RawField('high', BarField.HIGH), RawField('low', BarField.LOW), RawField('volume', BarField.VOLUME),
        Lag('previous_close', 'close', 1), Lag('previous_open', 'opening', 1),
        Lag('previous_high', 'high', 1), Lag('previous_volume', 'volume', 1),
        TrueRange('tr', 'high', 'low', 'close'), Mean('atr13', 'tr', 13),
        Lag('previous_tr', 'tr', 1), Lag('atr_before_prior', 'atr13', 2),
        SameLocalSlotMedian('same_slot_median20', 'volume', 20, 1),Lag('previous_low','low',1),Lag('low2','low',2))
    return FeatureGraph(nodes, OUTPUTS)


def state_schema():
    return StrategyStateSchema(cycle_fields=(StateField('holding_bars',StateValueType.INT),StateField('last_completed_at',StateValueType.DATETIME),StateField('exit_due',StateValueType.BOOL),StateField('initial_support',StateValueType.FLOAT),StateField('support',StateValueType.FLOAT),StateField('support_raises',StateValueType.INT),StateField('exit_reason',StateValueType.STR)))

def step(ctx,state):
    if set(ctx.parameters)!={'policy'} or ctx.parameters['policy'] not in ('DIAGNOSTIC26','STATIC_SUPPORT','CONFIRMED_SUPPORT','OPPOSING_PRESSURE'):raise ValueError('Declared diagnostic/three financial policies only')
    policy=ctx.parameters['policy'];portfolio=ctx.portfolio
    if portfolio.reference_price_scale!=1. or ctx.events:raise ValueError('Retained RAW NONE-event contract only')
    v={}
    for key in OUTPUTS:
        item=ctx.features.get(key)
        if type(item) is not ReadyValue:raise ValueError('Full ready observations required')
        v[key]=float(item.value)
    liquid=v['previous_volume']>=1.5*v['same_slot_median20'];narrow=v['previous_tr']<=v['atr_before_prior']
    signal=v['previous_close']<v['previous_open'] and liquid and narrow and v['close']>v['previous_high']
    opposing=v['previous_close']>v['previous_open'] and liquid and narrow and v['close']<v['previous_low']
    current=ctx.history.last()['Date'];held=portfolio.quantity>0;proposal=None
    facts={**v,'entry_signal':bool(signal),'opposing_pressure':bool(opposing),'policy':policy,'held':held,'portfolio_quantity':portfolio.quantity,'portfolio_cash':portfolio.cash,'cycle_present':state.cycle is not None,'holding_bars':0,'exit_due':False,'exit_trigger':'NONE','support_raised':False}
    if held:
        if state.cycle is None or state.cycle.entry_at!=portfolio.cycle_entry or portfolio.cycle_cost<=0:raise ValueError('Actual activated holding required')
        saved=dict(state.cycle.values.values)
        if current<=saved['last_completed_at']:raise ValueError('Complete observation must advance')
        saved['holding_bars']+=1;saved['last_completed_at']=current
        if not saved['exit_due']:
            pivot=v['previous_low']<v['low2'] and v['previous_low']<v['low'] and v['previous_low']>saved['support']
            if policy=='CONFIRMED_SUPPORT' and pivot:
                three=ctx.history.to_frame(tail=3)
                if len(three)!=3 or not three.Date.is_monotonic_increasing or three.Date.duplicated().any() or three.Date.iloc[-1]!=current:raise ValueError('Exactly last three completed observations required')
                if three.BarStart.iloc[0]>=portfolio.cycle_entry:
                    saved['support']=v['previous_low'];saved['support_raises']+=1;facts['support_raised']=True
            broken=v['close']<saved['support']
            if policy=='DIAGNOSTIC26':due=saved['holding_bars']>=26;reason='DIAGNOSTIC_26'
            else:
                due=broken or (policy=='OPPOSING_PRESSURE' and opposing)
                reason=('INITIAL_SUPPORT_BREAK' if saved['support']==saved['initial_support'] else 'CONFIRMED_HIGHER_SUPPORT_BREAK') if broken else 'OPPOSING_PRESSURE'
            if due:saved['exit_due']=True;saved['exit_reason']=reason
        target=int(not saved['exit_due']);proposal=StateRecord(tuple(saved.items()));facts.update(holding_bars=saved['holding_bars'],exit_due=saved['exit_due'],exit_trigger=saved['exit_reason'],initial_support=saved['initial_support'],support=saved['support'],support_raises=saved['support_raises'],support_broken=v['close']<saved['support'])
    else:
        target=int(signal)
        if target:
            floor=min(v['previous_low'],v['low']);proposal=StateRecord((('holding_bars',0),('last_completed_at',current),('exit_due',False),('initial_support',floor),('support',floor),('support_raises',0),('exit_reason','NONE')))
    return AccountStepResult(AccountDecision.from_facts(target,'Post-reclaim continuation and explicit failure',facts=facts,next_watch='Use completed post-fill structure, execute next interval; due never reverses',capital_mode='full_available_cash'),StateRecord(),proposal)
