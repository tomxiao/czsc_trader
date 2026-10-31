"""M005 entry with confirmed-fill 26 or 65 completed-bar holding."""
from strategy_runtime import (AccountDecision, AccountStepResult, BarField, FeatureGraph,
    Lag, Mean, RawField, ReadyValue, SameLocalSlotMedian, StateField, StateRecord,
    StateValueType, StrategyStateSchema, TrueRange)

OUTPUTS = ('close', 'previous_close', 'previous_open', 'previous_high',
    'previous_volume', 'previous_tr', 'atr_before_prior', 'same_slot_median20')


def feature_graph():
    nodes = (RawField('close', BarField.CLOSE), RawField('opening', BarField.OPEN),
        RawField('high', BarField.HIGH), RawField('low', BarField.LOW), RawField('volume', BarField.VOLUME),
        Lag('previous_close', 'close', 1), Lag('previous_open', 'opening', 1),
        Lag('previous_high', 'high', 1), Lag('previous_volume', 'volume', 1),
        TrueRange('tr', 'high', 'low', 'close'), Mean('atr13', 'tr', 13),
        Lag('previous_tr', 'tr', 1), Lag('atr_before_prior', 'atr13', 2),
        SameLocalSlotMedian('same_slot_median20', 'volume', 20, 1))
    return FeatureGraph(nodes, OUTPUTS)


def state_schema():
    return StrategyStateSchema(cycle_fields=(StateField('holding_bars', StateValueType.INT),
        StateField('last_completed_at', StateValueType.DATETIME), StateField('exit_due', StateValueType.BOOL)))


def step(ctx, state):
    parameters, portfolio = ctx.parameters, ctx.portfolio
    mechanism, horizon = parameters.get('entry_mechanism'), parameters.get('max_holding_bars')
    if (set(parameters) != {'entry_mechanism', 'max_holding_bars'}
            or mechanism != 'S017-M005' or type(horizon) is not int or horizon not in (26,65)):
        raise ValueError('Only M005 with fixed 26 or 65 completed bars is allowed')
    if portfolio.reference_price_scale != 1. or ctx.events:
        raise ValueError('This retained NONE-action RAW study cannot interpret new economic events')
    values = {}
    for key in OUTPUTS:
        result = ctx.features.get(key)
        if type(result) is not ReadyValue:
            raise ValueError('Certified S017 population requires fully ready entry features')
        values[key] = float(result.value)
    base = (values['previous_close'] < values['previous_open']
        and values['close'] > values['previous_high']
        and values['previous_volume'] >= 1.5 * values['same_slot_median20'])
    narrow = values['previous_tr'] <= values['atr_before_prior']
    signal = base and narrow
    current = ctx.history.last()
    held, proposal = portfolio.quantity > 0, None
    facts = {**values, 'entry_signal': bool(signal), 'entry_ready': True,
        'entry_mechanism': mechanism, 'narrow': bool(narrow), 'held': held,
        'portfolio_quantity':portfolio.quantity,'portfolio_cash':portfolio.cash,'cycle_present':state.cycle is not None,
        'holding_bars': 0, 'max_holding_bars': horizon, 'exit_trigger': None}
    if held:
        if state.cycle is None or state.cycle.entry_at != portfolio.cycle_entry or portfolio.cycle_cost <= 0:
            raise ValueError('Confirmed holding must have the actual activated cycle')
        saved = dict(state.cycle.values.values)
        if current['Date'] <= saved['last_completed_at']:
            raise ValueError('Completed bars must advance monotonically')
        saved['holding_bars'] += 1
        saved['last_completed_at'] = current['Date']
        saved['exit_due'] = saved['exit_due'] or saved['holding_bars'] >= horizon
        proposal = StateRecord(tuple(saved.items()))
        target = int(not saved['exit_due'])
        facts.update(holding_bars=saved['holding_bars'], actual_entry=state.cycle.entry_at.isoformat(),
            exit_trigger=('S017-M009' if horizon==65 else 'S017-M041') if saved['exit_due'] else None)
        reason = f'完成{horizon}柱要求退出' if saved['exit_due'] else '数天修复继续持有'
    else:
        target = int(signal)
        reason = mechanism + ('入场' if target else '未触发')
        if target:
            proposal = StateRecord((('holding_bars', 0), ('last_completed_at', current['Date']), ('exit_due', False)))
    decision = AccountDecision.from_facts(target, reason, facts=facts,
        next_watch='下一完成柱复核；实际成交启动计时，到期后持续退出', capital_mode='full_available_cash')
    return AccountStepResult(decision, StateRecord(), proposal)
