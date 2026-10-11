"""Pure standby draft: downside-body/volume covariance and past-only nuisance."""

import numpy as np
import pandas as pd

CLOCKS = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
PROFILE_DAYS = 20


def arrays(bars):
    if (
        not isinstance(bars, pd.DataFrame)
        or not isinstance(bars.index, pd.DatetimeIndex)
        or bars.empty
    ):
        raise ValueError("nonempty explicit datetime bars required")
    if (
        bars.index.tz is not None
        or bars.index.hasnans
        or bars.index.has_duplicates
        or not bars.index.is_monotonic_increasing
    ):
        raise ValueError("unique ordered timezone-naive times required")
    if bars.columns.has_duplicates or not {"Open", "Close", "Volume"}.issubset(bars.columns):
        raise ValueError("unique Open/Close/Volume columns required")
    values = bars[["Open", "Close", "Volume"]].to_numpy(float)
    if not np.isfinite(values).all() or not (values > 0).all():
        raise ValueError("strictly positive finite O/C/V required, no fill")
    days = bars.index.normalize().unique().rename("Date")
    offsets = pd.to_timedelta([s + ":00" for s in CLOCKS])
    expected = pd.DatetimeIndex(
        np.repeat(days.to_numpy(), 8) + np.tile(offsets.to_numpy(), len(days))
    )
    if not bars.index.equals(expected):
        raise ValueError("exact eight full clock-mapped bars required")
    return days, values.reshape(len(days), 8, 3)


def features(bars):
    days, a = arrays(bars)
    downside = np.maximum(np.log(a[:, :, 0]) - np.log(a[:, :, 1]), 0)
    relative = a[:, :, 2] / a[:, :, 2].max(axis=1, keepdims=True)
    fractions = relative / relative.sum(axis=1, keepdims=True)
    average = downside.mean(axis=1)
    # Population cov(V,d)/meanV == volume-fraction weighted d minus mean(d).
    component = (fractions * downside).sum(axis=1) - average
    p = pd.DataFrame(fractions, index=days, columns=["p" + str(j) for j in range(1, 9)])
    # Shift AFTER rolling: at T only sessions T-20..T-1 enter q; clocks fixed.
    q = p.rolling(PROFILE_DAYS, min_periods=PROFILE_DAYS).mean().shift(1)
    available = q.notna().all(axis=1)
    shape = pd.Series(np.nan, index=days)
    shape.loc[available] = (q.to_numpy()[available] * downside[available]).sum(axis=1) - average[
        available
    ]
    result = pd.DataFrame(
        {
            "down_volume_cov": component,
            "mean_negative_body": average,
            "past_volume_shape_projection": shape,
            "profile_available": available,
            "profile_unavailable_reason": np.where(
                available, None, "INSUFFICIENT_PAST20_FULL_SESSIONS"
            ),
        },
        index=days,
    )
    return result, q


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
