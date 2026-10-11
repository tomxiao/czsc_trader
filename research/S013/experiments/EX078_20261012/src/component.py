"""Pure causal fixed4/20 Close-logreturn volatility concentration; no IO."""

import numpy as np
import pandas as pd


def canonical_dates(index):
    if (
        not isinstance(index, pd.DatetimeIndex)
        or index.tz is not None
        or index.hasnans
        or index.has_duplicates
        or not index.is_monotonic_increasing
        or not index.equals(index.normalize())
    ):
        raise ValueError("unique increasing timezone-naive midnight session dates required")
    unit = np.datetime_data(index.dtype)[0]
    canonical = index.as_unit("ns")
    pd.testing.assert_index_equal(canonical.as_unit(unit), index, exact=True)
    return canonical


def construct(close):
    if not isinstance(close, pd.Series) or not pd.api.types.is_numeric_dtype(close.dtype):
        raise ValueError("numeric Close Series required")
    axis = canonical_dates(close.index)
    values = close.to_numpy(float)
    if not np.isfinite(values).all() or not (values > 0).all():
        raise ValueError("strictly positive finite Close required; no fill or epsilon")
    returns = pd.Series(np.r_[np.nan, np.diff(np.log(values))], index=axis)
    # Rolling.std can suffer cancellation on constant windows. Fixed direct std
    # defines the declared population estimator and exact-zero semantics.
    sigma4 = returns.rolling(4, min_periods=4).apply(lambda x: np.std(x, ddof=0), raw=True)
    sigma20 = returns.rolling(20, min_periods=20).apply(lambda x: np.std(x, ddof=0), raw=True)
    available = sigma20.notna() & sigma20.gt(0)
    ratio = pd.Series(np.nan, index=axis, dtype=float)
    nuisance = ratio.copy()
    ratio.loc[available] = sigma4.loc[available] / sigma20.loc[available]
    nuisance.loc[available] = sigma20.loc[available]
    reason = pd.Series("INSUFFICIENT_20_COMPLETE_RETURNS", index=axis, dtype="string")
    reason.loc[sigma20.eq(0)] = "ZERO_SIGMA20"
    reason.loc[available] = pd.NA
    return pd.DataFrame(
        {
            "vol_concentration": ratio,
            "log_sigma20": nuisance,
            "sigma4": sigma4,
            "sigma20": sigma20,
            "unavailable_reason": reason,
        },
        index=axis,
    )
