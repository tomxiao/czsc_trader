"""Two fixed causal daily-price interactions; no data/account/platform access."""
from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

COMPONENTS = ('negative_gap_repair', 'positive_gap_fade')
PRICE_COLUMNS = ('Open', 'High', 'Low', 'Close')


def _dates(value: pd.DatetimeIndex, name: str) -> None:
    if (not isinstance(value, pd.DatetimeIndex) or len(value) == 0
            or value.tz is not None or value.hasnans or value.has_duplicates
            or not value.is_monotonic_increasing or not value.equals(value.normalize())):
        raise ValueError(f'{name} requires unique increasing finite timezone-naive session dates')


def build_features(daily: pd.DataFrame, signal_sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Build only T-close observations, using previous full-history daily Close.

    Caller authenticates HFQ units and complete trading calendar. One real prior
    session must precede the first requested signal; no missing value is filled.
    """
    if not isinstance(daily, pd.DataFrame):
        raise TypeError('daily must be a DataFrame')
    _dates(daily.index, 'daily')
    _dates(signal_sessions, 'signal_sessions')
    if daily.columns.has_duplicates or not set(PRICE_COLUMNS).issubset(daily.columns):
        raise ValueError('Unique Open/High/Low/Close columns required')
    for column in PRICE_COLUMNS:
        if not is_numeric_dtype(daily[column]) or is_bool_dtype(daily[column]) or np.iscomplexobj(daily[column]):
            raise ValueError('Prices must be real numeric values, not boolean/complex/object')
    full = daily.loc[:, PRICE_COLUMNS].to_numpy(dtype=float)
    if not np.isfinite(full).all() or not (full > 0).all():
        raise ValueError('All prices must be finite and strictly positive')
    o, h, low, c = full.T
    if (h < np.maximum(o, c)).any() or (low > np.minimum(o, c)).any() or (h < low).any():
        raise ValueError('Illegal OHLC; no price repair is permitted')
    if not signal_sessions.isin(daily.index).all():
        raise ValueError('Every signal session requires an existing complete daily bar')
    # Shift on complete history before selecting requested sessions.
    previous = daily['Close'].shift(1).reindex(signal_sessions).to_numpy(dtype=float)
    if not np.isfinite(previous).all() or not (previous > 0).all():
        raise ValueError('Every signal requires a real finite positive previous-session Close')
    o, h, low, c = daily.loc[signal_sessions, PRICE_COLUMNS].to_numpy(dtype=float).T
    with np.errstate(over='raise', invalid='raise', divide='raise'):
        tr = np.maximum.reduce((h - low, np.abs(h - previous), np.abs(low - previous)))
        repair_numerator = np.where(o < previous, np.maximum(0., np.minimum(c, previous) - o), 0.)
        fade_numerator = np.where(o > previous, np.maximum(0., o - np.maximum(c, previous)), 0.)
        # Legal OHLC makes TR==0 a genuinely flat price bar; do not use epsilon.
        flat = tr == 0.
        if (flat & ((o != previous) | (h != previous) | (low != previous) | (c != previous))).any():
            raise ValueError('Zero TR requires entirely flat bar and unchanged previous Close')
        repair = np.divide(repair_numerator, tr, out=np.zeros(len(tr)), where=~flat)
        fade = np.divide(fade_numerator, tr, out=np.zeros(len(tr)), where=~flat)
    values = np.column_stack((repair, fade))
    if not np.isfinite(values).all() or (values < 0.).any() or (values > 1.).any():
        raise ValueError('Invalid feature arithmetic; no clipping/fallback is permitted')
    return pd.DataFrame(values, index=signal_sessions.copy(), columns=COMPONENTS)
