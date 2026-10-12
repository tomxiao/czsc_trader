"""Pure same-session next-body response; no market, label or account I/O.

Date is the complete timezone-naive bar-end timestamp column. The output axis
contains known session dates only. EX061/EX068 controls must be joined by the
caller from their frozen implementations; they are not redefined here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CLOCKS = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
PROFILE_DAYS = 20
COLUMNS = (
    "X", "S", "U", "sources_count", "sources_negative_mean",
    "negative_body_mean", "samebar_cov", "past_clock_samebar",
    "past_clock_next_response_minus_U",
)


def _dates(value: pd.DatetimeIndex, name: str, normalized: bool = False) -> None:
    if not isinstance(value, pd.DatetimeIndex) or len(value) == 0:
        raise ValueError(f"{name}: nonempty explicit DatetimeIndex required")
    if value.tz is not None or value.hasnans or value.has_duplicates:
        raise ValueError(f"{name}: finite unique timezone-naive dates required")
    if not value.is_monotonic_increasing:
        raise ValueError(f"{name}: strictly increasing dates required")
    if normalized and not value.equals(value.normalize()):
        raise ValueError(f"{name}: normalized session dates required")


def build(
    bars: pd.DataFrame, axis: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build nine declared fields and their availability without filling data.

    X=S-U has a fixed positive h4 net-return hypothesis. Sources are strictly
    negative bodies in positions 0..6, using their same-session successor body.
    No magnitude weight, future label, yearly reset or parameter fitting enters.
    A past clock is the mean of exactly T-20..T-1 full-session volume profiles;
    a zero-total-volume past session invalidates that window, without skipping it.
    """
    _dates(axis, "axis", normalized=True)
    if not isinstance(bars, pd.DataFrame) or bars.empty:
        raise ValueError("nonempty DataFrame required")
    required = ["Date", "Open", "Close", "Volume"]
    if bars.columns.has_duplicates or not set(required).issubset(bars.columns):
        raise ValueError("unique Date/Open/Close/Volume columns required")
    if not pd.api.types.is_datetime64_any_dtype(bars.Date.dtype):
        raise ValueError("Date must be an explicit datetime timestamp column")
    stamps = pd.DatetimeIndex(bars.Date)
    _dates(stamps, "bars")
    values = bars[["Open", "Close", "Volume"]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("finite O/C/V required, no fill")
    if (values[:, :2] <= 0).any() or (values[:, 2] < 0).any():
        raise ValueError("positive O/C and nonnegative V required")
    days = stamps.normalize().unique().rename("Date")
    offsets = pd.to_timedelta([clock + ":00" for clock in CLOCKS])
    expected = pd.DatetimeIndex(
        np.repeat(days.to_numpy(), 8) + np.tile(offsets.to_numpy(), len(days))
    )
    if not stamps.equals(expected):
        raise ValueError("exact eight fixed bar-end clocks required per session")
    if not axis.isin(days).all():
        raise ValueError("axis contains a session absent from bars")

    daily = values.reshape(len(days), 8, 3)
    body = np.log(daily[:, :, 1]) - np.log(daily[:, :, 0])
    negative = np.maximum(-body, 0.0)
    volume = daily[:, :, 2]
    vmax = volume.max(axis=1)
    relative = np.divide(
        volume, vmax[:, None], out=np.zeros_like(volume), where=vmax[:, None] > 0
    )
    total = relative.sum(axis=1)
    fractions = np.divide(
        relative, total[:, None], out=np.full_like(relative, np.nan),
        where=total[:, None] > 0,
    )
    clock = (
        pd.DataFrame(fractions, index=days)
        .rolling(PROFILE_DAYS, min_periods=PROFILE_DAYS).mean().shift(1)
        .to_numpy()
    )
    rows, traces = [], []
    for day in axis:
        i = days.get_loc(day)
        source = np.flatnonzero(body[i, :7] < 0)
        count = len(source)
        u = float(body[i, source + 1].mean()) if count else np.nan
        src_mean = float(negative[i, source].mean()) if count else np.nan
        current_reason = None
        if total[i] == 0:
            current_reason = "ZERO_SESSION_VOLUME"
        elif not count:
            current_reason = "NO_NEGATIVE_SOURCE_PAIR"
        elif relative[i, source].sum() == 0:
            current_reason = "ZERO_SOURCE_VOLUME"
        s = np.nan
        if current_reason is None:
            weights = relative[i, source] / relative[i, source].sum()
            s = float(weights @ body[i, source + 1])
        clock_reason = None
        if i < PROFILE_DAYS:
            clock_reason = "INSUFFICIENT_PAST20_FULL_SESSIONS"
        elif not np.isfinite(clock[i]).all():
            clock_reason = "ZERO_VOLUME_IN_PAST20_PROFILE"
        next_reason = clock_reason
        next_projection = np.nan
        if next_reason is None:
            if not count:
                next_reason = "NO_NEGATIVE_SOURCE_PAIR"
            elif clock[i, source].sum() == 0:
                next_reason = "ZERO_PAST_CLOCK_SOURCE_WEIGHT"
            else:
                q = clock[i, source] / clock[i, source].sum()
                next_projection = float(q @ body[i, source + 1] - u)
        mean_negative = float(negative[i].mean())
        same = (
            float(fractions[i] @ negative[i] - mean_negative)
            if total[i] > 0 else np.nan
        )
        past_same = (
            float(clock[i] @ negative[i] - mean_negative)
            if clock_reason is None else np.nan
        )
        row = [
            s - u, s, u, count, src_mean, mean_negative,
            same, past_same, next_projection,
        ]
        if np.isinf(np.asarray(row, dtype=float)).any():
            raise ValueError("nonfinite arithmetic result")
        rows.append(row)
        traces.append({
            "source_indices": source.tolist(),
            "successor_indices": (source + 1).tolist(),
            "last_bar_source_excluded": True,
            "X_available": current_reason is None,
            "X_reason": current_reason,
            "S_reason": current_reason,
            "U_reason": None if count else "NO_NEGATIVE_SOURCE_PAIR",
            "sources_negative_mean_reason": None if count else "NO_NEGATIVE_SOURCE_PAIR",
            "samebar_cov_reason": None if total[i] > 0 else "ZERO_SESSION_VOLUME",
            "past_clock_samebar_reason": clock_reason,
            "past_clock_next_response_reason": next_reason,
            "past_clock_available": clock_reason is None,
            "past_window_sessions": min(i, PROFILE_DAYS),
            "past_window_dates": [d.isoformat() for d in days[max(0, i-20):i]],
            "past_clock_weights": clock[i].tolist() if clock_reason is None else None,
            "joint_nine_available": bool(np.isfinite(np.asarray(row, dtype=float)).all()),
            "available_after": pd.Timestamp(day).isoformat()[:10] + "T15:00:00",
        })
    return (
        pd.DataFrame(rows, index=axis.rename("Date"), columns=COLUMNS),
        pd.DataFrame(traces, index=axis.rename("Date")),
    )
