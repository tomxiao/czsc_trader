"""Fixed numbered entry hypotheses; only completed, observed RTH bars are used."""

import numpy as np
import pandas as pd

NAMES = ('S017-M003', 'S017-M004', 'S017-M005')


def _validate(bars):
    if not bars.Date.is_monotonic_increasing or bars.Date.duplicated().any():
        raise ValueError('Require unique chronological completed bars')
    if not bars.BarStart.is_monotonic_increasing or bars.BarStart.duplicated().any():
        raise ValueError('Require unique chronological BarStart')
    if bars.BarStart.dt.tz is None or bars.Date.dt.tz is None:
        raise ValueError('Require timezone-aware timestamps')
    if (bars.Date <= bars.BarStart).any():
        raise ValueError('Require completed-bar Date after BarStart')
    values = bars[['Open', 'High', 'Low', 'Close', 'Volume']].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:, 4] < 0).any():
        raise ValueError('Require finite OHLCV and nonnegative volume')
    if ((values[:, 1] < np.maximum(values[:, 0], values[:, 3])).any()
            or (values[:, 2] > np.minimum(values[:, 0], values[:, 3])).any()):
        raise ValueError('Require consistent OHLC')
    local = bars.BarStart.dt.tz_convert('America/New_York')
    slots = local.dt.hour * 60 + local.dt.minute
    if ((slots < 570) | (slots >= 960) | ((slots - 570) % 30 != 0)
            | (local.dt.second != 0) | (local.dt.microsecond != 0)).any():
        raise ValueError('Require 30-minute RTH BarStart slots')
    days = local.dt.strftime('%Y-%m-%d')
    if pd.DataFrame({'day': days, 'slot': slots}).duplicated().any():
        raise ValueError('Require at most one observed bar per local day and slot')
    return days, slots


def compute(bars):
    """Return numbered flags, common complete-history mask, and feature facts.

    Volume reference comprises the last 20 observed distinct local trading days
    at the prior candle's slot, strictly before that candle's local date. Missing
    half-day slots contribute no observation. Readiness does not depend on shape.
    """
    days, slots = _validate(bars)
    previous_close = bars.Close.shift(1)
    tr = pd.concat([bars.High - bars.Low, (bars.High - previous_close).abs(),
                    (bars.Low - previous_close).abs()], axis=1).max(axis=1)
    if len(tr):
        tr.iloc[0] = np.nan
    atr = tr.rolling(13, min_periods=13).mean()
    slot_volume = bars.Volume.groupby(slots, sort=False)
    median = slot_volume.transform(lambda series: series.shift(1).rolling(20).median())
    count = slot_volume.cumcount().clip(upper=20)
    down = (bars.Close < previous_close).astype(float).where(previous_close.notna())
    facts = pd.DataFrame({
        'close': bars.Close, 'open': bars.Open, 'previous_close': previous_close,
        'previous_open': bars.Open.shift(1), 'close_t4': bars.Close.shift(4),
        'previous_high': bars.High.shift(1), 'previous_atr': atr.shift(1),
        'previous_tr1': tr.shift(1), 'previous_tr2': tr.shift(2),
        'previous_tr3': tr.shift(3),
        'down_count3': down.shift(1).rolling(3, min_periods=3).sum(),
        'prior_volume': bars.Volume.shift(1),
        'same_slot_volume_median20': median.shift(1),
        'same_slot_history_count': count.shift(1),
        'atr_before_prior': atr.shift(2),
        'prior_local_day': days.shift(1), 'prior_local_slot_minutes': slots.shift(1),
    }, index=bars.index)
    ready = facts.drop(columns=['prior_local_day']).notna().all(axis=1)
    ready.name = 'ready'
    flags = pd.DataFrame({
        NAMES[0]: ((facts.close_t4 - facts.previous_close >= facts.previous_atr)
                   & (facts.close > (facts.close_t4 + facts.previous_close) / 2)),
        NAMES[1]: ((facts.down_count3 >= 2) & (facts.previous_close < facts.close_t4)
                   & (facts.previous_tr3 > facts.previous_tr2)
                   & (facts.previous_tr2 > facts.previous_tr1)
                   & (facts.close > facts.previous_high)),
        NAMES[2]: ((facts.previous_close < facts.previous_open)
                   & (facts.prior_volume >= 1.5 * facts.same_slot_volume_median20)
                   & (facts.previous_tr1 <= facts.atr_before_prior)
                   & (facts.close > facts.previous_high)),
    }, index=bars.index)
    return flags.where(ready, False), ready, facts


def prepare_scalar(bars):
    """Copy raw observations only; no vector-computed features enter the oracle."""
    values = bars[['Open', 'High', 'Low', 'Close', 'Volume']].to_numpy(
        dtype=float, copy=True)
    local = bars.BarStart.dt.tz_convert('America/New_York')
    days = local.dt.strftime('%Y%m%d').to_numpy(dtype=np.int64, copy=True)
    slots = (local.dt.hour * 60 + local.dt.minute).to_numpy(dtype=np.int64, copy=True)
    for array in (values, days, slots):
        array.setflags(write=False)
    return values, days, slots


def scalar_at(bars, i, prepared=None):
    """Independent positional oracle, using bounded historical loops only."""
    if not 0 <= i < len(bars):
        raise IndexError(i)
    if i < 15:
        return None
    values, days, slots = prepare_scalar(bars) if prepared is None else prepared
    if len(values) != len(bars) or len(days) != len(bars) or len(slots) != len(bars):
        raise ValueError('Prepared observations must match bars length')
    prior_date = days[i - 1]
    prior_slot = slots[i - 1]
    observed = []
    seen_days = set()
    for j in range(i - 2, -1, -1):
        day = days[j]
        if (day < prior_date and day not in seen_days
                and slots[j] == prior_slot):
            observed.append(values[j, 4])
            seen_days.add(day)
            if len(observed) == 20:
                break
    if len(observed) != 20:
        return None
    ranges = {}
    for j in range(i - 14, i):
        ranges[j] = max(values[j, 1] - values[j, 2],
                        abs(values[j, 1] - values[j - 1, 3]),
                        abs(values[j, 2] - values[j - 1, 3]))
    previous_atr = sum(ranges[j] for j in range(i - 13, i)) / 13
    atr_before_prior = sum(ranges[j] for j in range(i - 14, i - 1)) / 13
    down_count = sum(values[j, 3] < values[j - 1, 3] for j in range(i - 3, i))
    return {
        NAMES[0]: bool(values[i - 4, 3] - values[i - 1, 3] >= previous_atr
                       and values[i, 3] > (values[i - 4, 3] + values[i - 1, 3]) / 2),
        NAMES[1]: bool(down_count >= 2 and values[i - 1, 3] < values[i - 4, 3]
                       and ranges[i - 3] > ranges[i - 2] > ranges[i - 1]
                       and values[i, 3] > values[i - 1, 1]),
        NAMES[2]: bool(values[i - 1, 3] < values[i - 1, 0]
                       and values[i - 1, 4] >= 1.5 * float(np.median(observed))
                       and ranges[i - 1] <= atr_before_prior
                       and values[i, 3] > values[i - 1, 1]),
    }
