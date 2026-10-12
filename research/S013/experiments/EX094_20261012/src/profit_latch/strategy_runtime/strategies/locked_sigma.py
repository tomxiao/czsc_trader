"""Known T log-close-change RMS; full window, genuine zero, no data I/O."""
import numpy as np
import pandas as pd


def sigma_known(close_full, sessions, window):
    if type(window) is not int or not 10 <= window <= 60:
        raise ValueError('Declared integer RMS window10..60 required')
    if not isinstance(close_full, pd.Series) or not isinstance(close_full.index, pd.DatetimeIndex):
        raise ValueError('Explicit full daily close Series required')
    for axis in (close_full.index, sessions):
        if not isinstance(axis, pd.DatetimeIndex) or not len(axis) or axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()):
            raise ValueError('Nonempty unique increasing naive midnight dates required')
    values = close_full.to_numpy(float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('Finite positive closes required, no filling')
    positions = close_full.index.get_indexer(sessions)
    if (positions < 0).any() or (np.diff(positions) != 1).any():
        raise ValueError('Complete consecutive signal interval required')
    output = np.log(close_full.astype(float)).diff().pow(2).rolling(window, min_periods=window).mean().pow(.5).reindex(sessions)
    if not np.isfinite(output.to_numpy()).all() or (output < 0).any():
        raise ValueError('Every T requires its complete known RMS window')
    return output.rename('sigma_knowncurrent')
