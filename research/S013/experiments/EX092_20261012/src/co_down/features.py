"""Fixed20 centered overnight/body negative dependence, using known O/C only.

This compresses existing authorized prices; it is not independent market data.
No labels, annual outcomes, volume, High/Low, or strategy state are consumed.
"""
import numpy as np
import pandas as pd

WINDOW = 20
COLUMNS = ('co_down_dependence20', 'mean_a20', 'mean_b20', 'rms_a20', 'rms_b20', 'freq_a20', 'freq_b20')


def _axis(index, name):
    if not isinstance(index, pd.DatetimeIndex) or index.tz is not None or index.hasnans or not index.is_unique or not index.is_monotonic_increasing or not index.equals(index.normalize()) or not len(index):
        raise ValueError(name + ' must be nonempty unique ordered naive midnight dates')


def validate(prices, axis, calendar):
    _axis(calendar, 'calendar')
    _axis(axis, 'axis')
    _axis(prices.index, 'prices')
    if not prices.index.equals(calendar):
        raise ValueError('Prices must exactly cover the full declared trading calendar')
    positions = calendar.get_indexer(axis)
    if (positions < 0).any() or (np.diff(positions) != 1).any():
        raise ValueError('Signal axis must be a complete contiguous calendar interval')
    if prices.columns.has_duplicates or not {'open', 'close'}.issubset(prices.columns):
        raise ValueError('Unique lowercase open/close columns required')
    values = prices.loc[:, ['open', 'close']].to_numpy(float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('Finite strictly positive Open/Close required; no fill or repair')
    return values, positions


def build(prices, axis, calendar):
    values, positions = validate(prices, axis, calendar)
    log_open, log_close = np.log(values[:, 0]), np.log(values[:, 1])
    gap = np.r_[np.nan, log_open[1:] - log_close[:-1]]
    body = log_close - log_open
    a, b = np.maximum(-gap, 0.), np.maximum(-body, 0.)
    output = np.full((len(axis), len(COLUMNS)), np.nan)
    traces = []
    for row, (date, location) in enumerate(zip(axis, positions)):
        complete = location >= WINDOW
        window = np.arange(location - WINDOW + 1, location + 1) if complete else np.array([], dtype=int)
        predecessor = int(window[0] - 1) if complete else None
        reason, numerator, denominator = 'INSUFFICIENT_HISTORY', None, None
        if complete:
            aa, bb = a[window], b[window]
            mean_a, mean_b = float(aa.mean()), float(bb.mean())
            energy_a, energy_b = float(np.mean(aa ** 2)), float(np.mean(bb ** 2))
            numerator = float(np.mean(aa * bb) - mean_a * mean_b)
            denominator = float(np.sqrt(energy_a * energy_b))
            output[row, 1:] = [mean_a, mean_b, np.sqrt(energy_a), np.sqrt(energy_b), float((aa > 0).mean()), float((bb > 0).mean())]
            if energy_a == 0 or energy_b == 0:
                reason = 'ZERO_NEGATIVE_ENERGY_DENOMINATOR'
            else:
                output[row, 0] = numerator / denominator
                reason = 'AVAILABLE'
        traces.append({'signal_date': date.isoformat(), 'calendar_position': int(location),
                       'window_complete': bool(complete), 'available': reason == 'AVAILABLE', 'reason': reason,
                       'window_positions': [int(i) for i in window],
                       'window_dates': [calendar[i].isoformat() for i in window],
                       'predecessor_position': predecessor,
                       'predecessor_date': calendar[predecessor].isoformat() if predecessor is not None else None,
                       'numerator': numerator, 'denominator': denominator,
                       'max_observation_date': date.isoformat() if complete else None})
    return pd.DataFrame(output, index=axis, columns=COLUMNS), traces
