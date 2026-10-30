"""Research-only vector expressions for two prior-only repair confirmations."""
import numpy as np
import pandas as pd

NAMES = ('S017-M017', 'S017-M019', 'S017-M020')


def compute(bars):
    close, high, low = (bars[name].astype(float) for name in ('Close', 'High', 'Low'))
    prior_mean = close.rolling(65, min_periods=65).mean().shift(1)
    older_mean = close.rolling(65, min_periods=65).mean().shift(14)
    background = close.shift(1) < prior_mean
    breakout = close > high.shift(1).rolling(6, min_periods=6).max()
    mean_rising = prior_mean > older_mean
    low_holding = low.shift(1).rolling(6, min_periods=6).min() >= low.shift(7).rolling(6, min_periods=6).min()
    base = background & breakout
    flags = pd.DataFrame({NAMES[0]: base, NAMES[1]: base & mean_rising, NAMES[2]: base & low_holding}, index=bars.index)
    parents = pd.DataFrame({NAMES[0]: background, NAMES[1]: background & mean_rising,
                            NAMES[2]: background & low_holding}, index=bars.index)
    regimes = pd.Series(np.where(prior_mean.isna(), 'UNREADY', np.where(close.shift(1) < prior_mean,
        'below65', np.where(close.shift(1) > prior_mean, 'above65', 'equal65'))), index=bars.index)
    return flags, parents, regimes
