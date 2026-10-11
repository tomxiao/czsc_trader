"""Exact AST/byte function from authorized frozen EX075 pure label source."""
import numpy as np
import pandas as pd

def fee_labels4(prices, signal_index):
    if (
        not isinstance(prices.index, pd.DatetimeIndex)
        or prices.index.tz is not None
        or prices.index.hasnans
        or prices.index.has_duplicates
        or not prices.index.is_monotonic_increasing
        or not prices.index.equals(prices.index.normalize())
    ):
        raise ValueError("unique ordered timezone-naive full-session price calendar required")
    if (
        not isinstance(signal_index, pd.DatetimeIndex)
        or not signal_index.isin(prices.index).all()
        or signal_index.has_duplicates
        or not signal_index.is_monotonic_increasing
    ):
        raise ValueError("ordered unique known signal session subset required")
    a = prices[["Open", "Close"]].to_numpy(float)
    if not np.isfinite(a).all() or not (a > 0).all():
        raise ValueError("positive finite independent price labels required")
    out = pd.DataFrame(index=signal_index)
    out["return4_net"], out["downside4_oc"], out["label_end4"] = np.nan, np.nan, pd.NaT
    for t in signal_index:
        i = prices.index.get_loc(t)
        if i + 5 >= len(prices):
            continue
        entry, final = a[i + 1, 0], a[i + 5, 0]
        out.loc[t, "return4_net"] = 0.999 * final / (1.001 * entry) - 1
        out.loc[t, "downside4_oc"] = max(0, 1 - min(a[i + 1 : i + 5].min(), final) / entry)
        out.loc[t, "label_end4"] = prices.index[i + 5]
    return out

