"""DEV-only V3 equivalent of the frozen M005 three-exit research prototype."""
from zoneinfo import ZoneInfo

from strategy_runtime import (BarField, EquityDecision, FeatureGraph, Lag, Mean,
    RawField, ReadyValue, SameLocalSlotMedian, StateField, StateRecord,
    StateValueType, StepResult, StrategyStateSchema, TrueRange)


def feature_graph():
    return FeatureGraph((RawField('open', BarField.OPEN), RawField('high', BarField.HIGH),
        RawField('low', BarField.LOW), RawField('close', BarField.CLOSE), RawField('volume', BarField.VOLUME),
        TrueRange('tr', 'high', 'low', 'close'), Mean('atr', 'tr', 13),
        Lag('previous_tr1', 'tr', 1), Lag('atr_before_prior', 'atr', 2),
        SameLocalSlotMedian('same_slot_volume_median20', 'volume', 20, 1)),
        ('previous_tr1', 'atr_before_prior', 'atr', 'same_slot_volume_median20'))


def state_schema():
    fields = (('anchor', StateValueType.STR, False), ('anchor_signal_close', StateValueType.FLOAT, False),
        ('anchor_structural_low', StateValueType.FLOAT, False), ('frozen_atr', StateValueType.FLOAT, False),
        ('peak_completed_close', StateValueType.FLOAT, False), ('holding_bars', StateValueType.INT, False),
        ('last_completed_at', StateValueType.DATETIME, False), ('exit_trigger', StateValueType.STR, True),
        ('exit_trigger_at', StateValueType.STR, True))
    return StrategyStateSchema(cycle_fields=tuple(StateField(*item) for item in fields))


def step(ctx, state):
    mechanism = ctx.parameters['exit_mechanism']
    expected = {'exit_mechanism', 'max_holding_bars'}
    if mechanism == 'S017-M011':
        expected.add('trailing_atr_multiple')
    if (mechanism not in ('S017-M009', 'S017-M010', 'S017-M011')
            or set(ctx.parameters) != expected or type(ctx.parameters['max_holding_bars']) is not int
            or ctx.parameters['max_holding_bars'] != 65
            or (mechanism == 'S017-M011' and ctx.parameters['trailing_atr_multiple'] != 3.)):
        raise ValueError('Require the fixed three-exit DEV contract')
    if ctx.portfolio.reference_price_scale != 1.:
        raise ValueError('RAW prototype rejects changed price scale')
    current, prior = ctx.history.last(), ctx.history.last(1)
    values = {}
    for key in ('previous_tr1', 'atr_before_prior', 'atr', 'same_slot_volume_median20'):
        value = ctx.features.get(key)
        if type(value) is not ReadyValue:
            raise ValueError('The authenticated EX027 decision population requires complete features')
        values[key] = value.value
    prior_local = prior['BarStart'].astimezone(ZoneInfo('America/New_York'))
    signal = (prior['Close'] < prior['Open'] and current['Close'] > prior['High']
              and prior['Volume'] >= 1.5 * values['same_slot_volume_median20']
              and values['previous_tr1'] <= values['atr_before_prior'])
    facts = {'entry_signal': bool(signal), 'entry_ready': True,
        'close': float(current['Close']), 'previous_close': float(prior['Close']),
        'previous_open': float(prior['Open']), 'previous_high': float(prior['High']),
        'prior_volume': float(prior['Volume']), 'previous_tr1': values['previous_tr1'],
        'atr_before_prior': values['atr_before_prior'], 'atr': values['atr'],
        'same_slot_history_count': 20, 'same_slot_volume_median20': values['same_slot_volume_median20'],
        'prior_local_day': prior_local.date().isoformat(),
        'prior_local_slot_minutes': prior_local.hour * 60 + prior_local.minute}
    held = ctx.portfolio.quantity > 0
    facts.update(held=held, exit_mechanism=mechanism, holding_bars=0,
                 exit_trigger=None, anchor=None, max_holding_bars=65)
    cycle_values = None
    if held:
        if state.cycle is None or state.cycle.entry_at != ctx.portfolio.cycle_entry:
            raise ValueError('Actual entry does not match owned cycle state')
        saved = dict(state.cycle.values.values)
        if current['Date'] <= saved['last_completed_at']:
            raise ValueError('This observed-bar fixture requires one new completed interval per step')
        saved['holding_bars'] += 1
        saved['last_completed_at'] = current['Date']
        saved['peak_completed_close'] = max(saved['peak_completed_close'], float(current['Close']))
        threshold = (saved['anchor_structural_low'] if mechanism == 'S017-M010' else
                     saved['peak_completed_close'] - 3. * saved['frozen_atr'] if mechanism == 'S017-M011' else None)
        if saved['exit_trigger'] is None:
            if saved['holding_bars'] >= 65:
                saved['exit_trigger'] = 'S017-M009'
            elif threshold is not None and current['Close'] < threshold:
                saved['exit_trigger'] = mechanism
            if saved['exit_trigger'] is not None:
                saved['exit_trigger_at'] = current['Date'].isoformat()
        facts.update(holding_bars=saved['holding_bars'], exit_trigger=saved['exit_trigger'],
            exit_trigger_at=saved['exit_trigger_at'], actual_entry=state.cycle.entry_at.isoformat(),
            anchor=saved['anchor'], anchor_signal_close=saved['anchor_signal_close'],
            anchor_structural_low=saved['anchor_structural_low'], frozen_atr=saved['frozen_atr'],
            peak_completed_close=saved['peak_completed_close'], exit_threshold=threshold)
        target = int(saved['exit_trigger'] is None)
        reason = f'{mechanism}持仓继续' if target else f'{saved["exit_trigger"]}退出已锁存'
        cycle_values = StateRecord(tuple(saved.items()))
    else:
        target = int(signal)
        reason = 'S017-M005入场' if target else 'S017-M005未触发入场'
        if target:
            cycle_values = StateRecord((('anchor', current['Date'].isoformat()),
                ('anchor_signal_close', float(current['Close'])),
                ('anchor_structural_low', float(min(current['Low'], prior['Low']))),
                ('frozen_atr', values['atr']), ('peak_completed_close', float(current['Close'])),
                ('holding_bars', 0), ('last_completed_at', current['Date']),
                ('exit_trigger', None), ('exit_trigger_at', None)))
    decision = EquityDecision.from_facts(target, reason, facts=facts,
        next_watch='下一完整30分钟柱复核；目标交由下一交易区间执行，退出锁存至实际清仓')
    return StepResult(decision, StateRecord(), cycle_values)
