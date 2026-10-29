"""Three fixed, completed-bar hypotheses that prices resist further decline."""
import numpy as np
import pandas as pd

NAMES = ('B', 'C', 'F', 'T', 'H')


def predicates(background, current_d, close, previous_high, low, reference_low,
               reference_low_index, index, post_low_high, previous_atr,
               recent_low3, prior_low3, prior_high3):
    """Scalar/array compatible inequalities; empty post-low intervals cannot pass T."""
    return {'B': background, 'C': current_d & (close > previous_high),
            'F': background & (low < reference_low) & (close > reference_low),
            'T': background & (reference_low_index <= index-3)
                 & (post_low_high >= reference_low+previous_atr)
                 & (low >= reference_low) & (low <= reference_low+.5*previous_atr)
                 & (close > previous_high),
            'H': background & (recent_low3 > prior_low3) & (close > prior_high3)}


def compute(bars):
    """Return flag DataFrame, complete-history Series, and auditable feature facts.

    Positional indices identify historical bars, irrespective of the DataFrame's
    index labels. post_low_high is NaN if no bar lies after the last low and
    before the current bar; this is T inapplicability, not population exclusion.
    """
    if not bars.Date.is_monotonic_increasing or bars.Date.duplicated().any():
        raise ValueError('Require unique chronological completed bars')
    values = bars[['High', 'Low', 'Close']].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:, 0] < values[:, 1]).any():
        raise ValueError('Require finite observed OHLC prices')
    previous_close = bars.Close.shift(1)
    previous_mean = bars.Close.rolling(65, min_periods=65).mean().shift(1)
    tr = pd.concat([bars.High-bars.Low, (bars.High-previous_close).abs(),
                    (bars.Low-previous_close).abs()], axis=1).max(axis=1)
    tr.iloc[0] = np.nan
    atr = tr.rolling(13, min_periods=13).mean().shift(1)
    d = (previous_close <= previous_mean-2*atr).astype(float)
    d = d.where(previous_mean.notna() & atr.notna())
    background = d.rolling(13, min_periods=13).max()
    reference = bars.Low.shift(1).rolling(13, min_periods=13).min()
    positions = np.full(len(bars), -1, dtype=int)
    post_high = np.full(len(bars), np.nan, dtype=float)
    post_count = np.zeros(len(bars), dtype=int)
    low_values, high_values = values[:, 1], values[:, 0]
    for i in range(13, len(bars)):
        window = low_values[i-13:i]
        # Last occurrence is deliberate: repeated touches do not invent an old test.
        p = i-13+int(np.flatnonzero(window == window.min())[-1])
        positions[i] = p
        post_count[i] = i-p-1
        if post_count[i]:
            post_high[i] = float(high_values[p+1:i].max())
    facts = pd.DataFrame({'close': bars.Close, 'low': bars.Low,
        'previous_close': previous_close, 'previous_high': bars.High.shift(1),
        'previous_mean': previous_mean, 'previous_atr': atr, 'D': d,
        'background': background, 'reference_low': reference,
        'reference_low_index': positions, 'post_low_high': post_high,
        'post_low_bars': post_count, 'recent_low3': bars.Low.rolling(3, min_periods=3).min(),
        'prior_low3': bars.Low.shift(3).rolling(3, min_periods=3).min(),
        'prior_high3': bars.High.shift(1).rolling(3, min_periods=3).max()}, index=bars.index)
    required = ['previous_mean', 'previous_atr', 'background', 'reference_low',
                'previous_high', 'recent_low3', 'prior_low3', 'prior_high3']
    ready = facts[required].notna().all(axis=1) & (atr > 0)
    output = predicates(background.eq(1), d.eq(1), facts.close, facts.previous_high,
        facts.low, facts.reference_low, facts.reference_low_index, np.arange(len(bars)),
        facts.post_low_high, facts.previous_atr, facts.recent_low3, facts.prior_low3, facts.prior_high3)
    flags = pd.DataFrame(output, index=bars.index).astype(bool)
    flags.loc[~ready, :] = False
    return flags.loc[:, NAMES], ready, facts


def scalar_at(bars, i):
    """Independent bounded-loop definition; return None without complete history."""
    if i < 77:
        return None
    high = bars.High.to_numpy(dtype=float)
    low = bars.Low.to_numpy(dtype=float)
    close = bars.Close.to_numpy(dtype=float)
    def atr_at(j):
        total = 0.0
        for k in range(j-13, j):
            total += max(high[k]-low[k], abs(high[k]-close[k-1]), abs(low[k]-close[k-1]))
        return total/13
    def d_at(j):
        mean = sum(close[k] for k in range(j-65, j))/65
        return close[j-1] <= mean-2*atr_at(j)
    atr = atr_at(i)
    if not np.isfinite(atr) or atr <= 0:
        return None
    background = any(d_at(j) for j in range(i-12, i+1))
    support = min(low[j] for j in range(i-13, i))
    p = max(j for j in range(i-13, i) if low[j] == support)
    t = False
    if p <= i-3:
        rebound = max(high[j] for j in range(p+1, i))
        t = (rebound >= support+atr and support <= low[i] <= support+.5*atr
             and close[i] > high[i-1])
    return {'B': bool(background), 'C': bool(d_at(i) and close[i] > high[i-1]),
            'F': bool(background and low[i] < support and close[i] > support),
            'T': bool(background and t),
            'H': bool(background and min(low[j] for j in range(i-2, i+1)) >
                      min(low[j] for j in range(i-5, i-2)) and
                      close[i] > max(high[j] for j in range(i-3, i)))}
