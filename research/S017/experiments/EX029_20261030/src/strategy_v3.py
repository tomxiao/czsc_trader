"""V3 expression of the frozen EX029 mechanisms and actual-fill timed exits."""
from strategy_runtime import (BarField, EquityDecision, FeatureGraph, Lag, Mean, RawField,
    ReadyValue, StateField, StateRecord, StateValueType, StepResult, StrategyStateSchema)

NAMES = ('S017-M012', 'S017-M017', 'S017-M018')


def feature_graph():
    # There is no public rolling-Max node: six declared Lag values suffice.
    nodes = (RawField('close', BarField.CLOSE), RawField('high', BarField.HIGH),
        Mean('mean65', 'close', 65), Lag('prior_sma65', 'mean65', 1),
        Lag('previous_close', 'close', 1),
        *(Lag(f'high_lag{lag}', 'high', lag) for lag in range(1, 7)))
    return FeatureGraph(nodes, ('close', 'previous_close', 'prior_sma65',
        *(f'high_lag{lag}' for lag in range(1, 7))))


def state_schema():
    return StrategyStateSchema(cycle_fields=(
        StateField('holding_bars', StateValueType.INT),
        StateField('last_completed_at', StateValueType.DATETIME),
        StateField('exit_due', StateValueType.BOOL)))


def step(ctx, state):
    parameters, portfolio = ctx.parameters, ctx.portfolio
    mechanism, horizon = parameters.get('entry_mechanism'), parameters.get('max_holding_bars')
    if (set(parameters) != {'entry_mechanism', 'max_holding_bars'} or mechanism not in NAMES
            or type(horizon) is not int or horizon not in (6, 13)):
        raise ValueError('Require frozen mechanism and 6/13 completed holding bars')
    if portfolio.reference_price_scale != 1.:
        raise ValueError('RAW prototype requires reference price scale == 1')
    values = {}
    for key in ('close', 'previous_close', 'prior_sma65', *(f'high_lag{lag}' for lag in range(1, 7))):
        result = ctx.features.get(key)
        if type(result) is not ReadyValue:
            raise ValueError('EX029 certified decision population requires all features ready')
        values[key] = float(result.value)
    current = ctx.history.last()
    close, previous, prior_mean = values['close'], values['previous_close'], values['prior_sma65']
    high6 = max(values[f'high_lag{lag}'] for lag in range(1, 7))
    background, breakout = previous < prior_mean, close > high6
    signal = {NAMES[0]: breakout, NAMES[1]: background and breakout, NAMES[2]: background}[mechanism]
    facts = {'entry_signal': bool(signal), 'entry_ready': True, 'entry_mechanism': mechanism,
        'close': close, 'previous_close': previous, 'prior_sma65': prior_mean,
        'low_background': bool(background), 'breakout_high6': high6}
    held, cycle_values = portfolio.quantity > 0, None
    facts.update(held=held, holding_bars=0, max_holding_bars=horizon, exit_trigger=None)
    if held:
        if (state.cycle is None or state.cycle.entry_at != portfolio.cycle_entry
                or portfolio.cycle_cost <= 0):
            raise ValueError('Confirmed held quantity must match its actual activated cycle')
        saved = dict(state.cycle.values.values)
        if current['Date'] <= saved['last_completed_at']:
            raise ValueError('EX029 observed input requires a new completed interval per decision')
        saved['holding_bars'] += 1
        saved['last_completed_at'] = current['Date']
        saved['exit_due'] = saved['exit_due'] or saved['holding_bars'] >= horizon
        facts.update(holding_bars=saved['holding_bars'], actual_entry=state.cycle.entry_at.isoformat(),
            exit_trigger='FIXED_HOLD' if saved['exit_due'] else None)
        target = int(not saved['exit_due'])
        reason = f'{mechanism}固定{horizon}柱退出' if saved['exit_due'] else f'{mechanism}继续持有'
        cycle_values = StateRecord(tuple(saved.items()))
    else:
        target = int(signal)
        reason = f'{mechanism}入场' if target else f'{mechanism}未触发'
        if target:
            # The platform activates this proposal only after an actual BUY.
            cycle_values = StateRecord((('holding_bars', 0), ('last_completed_at', current['Date']), ('exit_due', False)))
    decision = EquityDecision.from_facts(target, reason, facts=facts,
        next_watch='下一完整30分钟柱复核；以实际成交计时，到期退出持续至清仓')
    return StepResult(decision, StateRecord(), cycle_values)
