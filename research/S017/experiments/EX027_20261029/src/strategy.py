"""S017-M005 unchanged entry with three fixed, actual-fill anchored exits."""

import math
from statistics import median

from strategy_runtime.equity_definition import EquityDecision


def entry_facts(history):
    """Evaluate the current completed bar from raw observations, without caches.

    The small price window and adaptive volume window precede all calculations.
    Missing same-slot sessions are skipped, never filled with synthetic zeros.
    """
    if len(history) < 16:
        return {'entry_signal': False, 'entry_ready': False,
                'same_slot_history_count': 0}
    tail = history.iloc[-16:]
    prices = tail[['Open', 'High', 'Low', 'Close', 'Volume']].to_numpy(dtype=float)
    for opening, high, low, close, volume in prices:
        if (not all(math.isfinite(float(value)) for value in
                    (opening, high, low, close, volume))
                or min(opening, high, low, close) <= 0 or volume < 0
                or high < max(opening, close) or low > min(opening, close)):
            raise ValueError('M005 requires finite consistent raw OHLCV')
    ranges = [max(float(prices[j, 1] - prices[j, 2]),
                  abs(float(prices[j, 1] - prices[j - 1, 3])),
                  abs(float(prices[j, 2] - prices[j - 1, 3])))
              for j in range(1, len(prices))]
    before_prior = sum(ranges[-15:-2]) / 13
    prior = history.iloc[-2]
    prior_local = prior.BarStart.tz_convert('America/New_York')
    prior_day = prior_local.date()
    prior_slot = prior_local.hour * 60 + prior_local.minute
    size = min(len(history), 300)
    while True:
        volume_window = history.iloc[-size:]
        local = volume_window.BarStart.dt.tz_convert('America/New_York')
        days = local.dt.date
        selected = volume_window.loc[(days < prior_day)
            & ((local.dt.hour * 60 + local.dt.minute) == prior_slot)]
        if len(selected) >= 20 or size == len(history):
            break
        size = min(len(history), size * 2)
    selected = selected.iloc[-20:]
    selected_days = selected.BarStart.dt.tz_convert('America/New_York').dt.date
    if selected_days.duplicated().any():
        raise ValueError('M005 requires distinct historical local days at each slot')
    volumes = [float(value) for value in selected.Volume]
    if any(not math.isfinite(value) or value < 0 for value in volumes):
        raise ValueError('M005 requires finite nonnegative historical volume')
    ready = len(volumes) == 20
    volume_median = float(median(volumes)) if ready else None
    signal = (ready and float(prior.Close) < float(prior.Open)
              and float(prices[-1, 3]) > float(prior.High)
              and float(prior.Volume) >= 1.5 * volume_median
              and ranges[-2] <= before_prior)
    return {'entry_signal': bool(signal), 'entry_ready': ready,
            'close': float(prices[-1, 3]), 'previous_close': float(prior.Close),
            'previous_open': float(prior.Open), 'previous_high': float(prior.High),
            'prior_volume': float(prior.Volume), 'previous_tr1': ranges[-2],
            'atr_before_prior': before_prior, 'atr': sum(ranges[-13:]) / 13,
            'same_slot_history_count': len(volumes),
            'same_slot_volume_median20': volume_median,
            'prior_local_day': prior_day.isoformat(),
            'prior_local_slot_minutes': prior_slot}


def cycle_facts(history, portfolio, mechanism):
    """Reconstruct the anchor and latched exit from this actual filled cycle."""
    entry = portfolio.cycle_entry
    if entry is None or portfolio.cycle_cost <= 0:
        raise ValueError('Held quantity requires a confirmed actual entry and cost')
    anchor_index = int(history.Date.searchsorted(entry, side='right')) - 1
    while anchor_index >= 0 and history.AvailableDate.iloc[anchor_index] > entry:
        anchor_index -= 1
    if anchor_index < 1:
        raise ValueError('Actual entry signal bar is unavailable')
    signal_history = history.iloc[:anchor_index + 1]
    signal = entry_facts(signal_history)
    if not signal['entry_signal']:
        raise ValueError('Actual entry anchor must reproduce S017-M005')
    frozen_atr = signal['atr']
    if not math.isfinite(frozen_atr) or frozen_atr <= 0:
        raise ValueError('Actual entry requires a positive frozen ATR13')
    structural_low = float(history.Low.iloc[anchor_index - 1:anchor_index + 1].min())
    peak = float(history.Close.iloc[anchor_index])
    first_held = int(history.Date.searchsorted(entry, side='right'))
    cycle = history.iloc[first_held:]
    if cycle.empty or cycle.BarStart.iloc[0] != entry:
        raise ValueError('Actual fill requires its complete first holding interval')
    trigger, first_trigger, threshold = None, None, None
    for count, row in enumerate(cycle.itertuples(), 1):
        close = float(row.Close)
        if not math.isfinite(close) or close <= 0:
            raise ValueError('Holding closes must be finite positive raw prices')
        peak = max(peak, close)
        if mechanism == 'S017-M010':
            threshold = structural_low
        elif mechanism == 'S017-M011':
            threshold = peak - 3. * frozen_atr
        if trigger is None:
            if count >= 65:
                trigger, first_trigger = 'S017-M009', row.Date.isoformat()
            elif threshold is not None and close < threshold:
                trigger, first_trigger = mechanism, row.Date.isoformat()
    return {'holding_bars': len(cycle), 'exit_trigger': trigger,
            'exit_trigger_at': first_trigger, 'actual_entry': entry.isoformat(),
            'anchor': history.Date.iloc[anchor_index].isoformat(),
            'anchor_signal_close': float(history.Close.iloc[anchor_index]),
            'anchor_structural_low': structural_low, 'frozen_atr': frozen_atr,
            'peak_completed_close': peak, 'exit_threshold': threshold}


def decide(ctx):
    parameters, history, portfolio = ctx.parameters, ctx.history, ctx.portfolio
    mechanism = parameters.get('exit_mechanism')
    expected = {'exit_mechanism', 'max_holding_bars'}
    if mechanism == 'S017-M011':
        expected.add('trailing_atr_multiple')
    if (mechanism not in ('S017-M009', 'S017-M010', 'S017-M011')
            or set(parameters) != expected or parameters['max_holding_bars'] != 65
            or type(parameters['max_holding_bars']) is not int
            or (mechanism == 'S017-M011' and
                (type(parameters['trailing_atr_multiple']) not in (int, float)
                 or parameters['trailing_atr_multiple'] != 3.))):
        raise ValueError('Require the frozen numbered exit mechanism parameters')
    if portfolio.reference_price_scale != 1.:
        raise ValueError('This RAW prototype rejects reference price scale != 1')
    if history.empty or not history.Date.is_monotonic_increasing or history.Date.duplicated().any():
        raise ValueError('Require unique chronological completed history')
    if (history.Date.iloc[-1] > ctx.point.observed_through
            or (history.AvailableDate > ctx.point.decision_at).any()):
        raise ValueError('Future or unavailable observations cannot enter a decision')
    facts = entry_facts(history)
    held = portfolio.quantity > 0
    facts.update(held=held, exit_mechanism=mechanism, holding_bars=0,
                 exit_trigger=None, anchor=None, max_holding_bars=65)
    if held:
        facts.update(cycle_facts(history, portfolio, mechanism))
        target = int(facts['exit_trigger'] is None)
        reason = f'{mechanism}持仓继续' if target else f'{facts["exit_trigger"]}退出已锁存'
    else:
        target = int(facts['entry_signal'])
        reason = 'S017-M005入场' if target else 'S017-M005未触发入场'
    return EquityDecision.from_facts(target, reason, facts=facts,
        next_watch='下一完整30分钟柱复核；目标交由下一交易区间执行，退出锁存至实际清仓')
