"""Independent online arithmetic; no production import or file/data I/O."""

from math import fsum, isfinite, log, sqrt

import numpy as np
import pandas as pd

FIELDS = (
    "signal_time",
    "close",
    "state_before",
    "state_after",
    "reason",
    "target_position",
    "sigma_current",
    "sigma_available",
    "sigma_unavailable_reason",
    "sigma_locked",
    "known_peak",
    "known_trough",
)
NUMERIC = {"close", "sigma_current", "sigma_locked", "known_peak", "known_trough"}
ATOL, RTOL = 2e-12, 2e-10


def session_axis(axis):
    if (
        not isinstance(axis, pd.DatetimeIndex)
        or axis.hasnans
        or axis.has_duplicates
        or axis.tz is not None
        or not axis.is_monotonic_increasing
        or not axis.equals(axis.normalize())
    ):
        raise ValueError("complete unique ordered normalized naive sessions required")


def population_sigma(changes):
    """Explicit two-pass population variance; no np.std or production helper."""
    mean = fsum(changes) / len(changes)
    return sqrt(fsum((value - mean) ** 2 for value in changes) / len(changes))


def online(close, signal_sessions, *, lookback=20, distance=1.0):
    """Warmup only supplies variance. Actual account state is not an input."""
    if type(lookback) is not int or not 2 <= lookback <= 120:
        raise ValueError("integer L full domain[2,120] required")
    if type(distance) is not float or not isfinite(distance) or not 0.25 <= distance <= 4:
        raise ValueError("float k full domain[.25,4] required")
    if not isinstance(close, pd.Series) or not pd.api.types.is_numeric_dtype(close.dtype):
        raise ValueError("numeric positive finite Close Series required")
    session_axis(close.index)
    session_axis(signal_sessions)
    if not len(signal_sessions) or not signal_sessions.isin(close.index).all():
        raise ValueError("nonempty contained signal axis required")
    start = close.index.get_loc(signal_sessions[0])
    finish = close.index.get_loc(signal_sessions[-1])
    if not signal_sessions.equals(close.index[start : finish + 1]):
        raise ValueError("state cannot skip signal sessions")
    prices = [float(value) for value in close]
    if not all(isfinite(value) and value > 0 for value in prices):
        raise ValueError("all input prices positive finite; no repair")
    logs = [log(value) for value in prices]
    returns = [logs[p] - logs[p - 1] for p in range(1, len(logs))]
    # Phase0=flat, phase1=armed, phase2=held. This stream starts at actual T anchor.
    phase, high, low, scale = 0, prices[start], None, None
    names = ("FLAT", "ARMED", "HELD")
    rows = []
    for p in range(start, finish + 1):
        price = prices[p]
        current = population_sigma(returns[p - lookback : p]) if p >= lookback else float("nan")
        usable = isfinite(current) and current > 0
        old = phase
        # One phase step per T; arm cannot execute the buy phase on the same day.
        if old == 0:
            high = max(high, price)
            event = "FLAT_VOL_UNAVAILABLE" if not usable else "TRACK_FLAT_PEAK"
            if usable and log(high) - logs[p] >= 2 * distance * current:
                phase, low, scale, event = 1, price, current, "ARM_PRICE_EXCURSION"
        elif old == 1:
            low = min(low, price)
            event = "WAIT_PRICE_REVERSAL"
            if logs[p] - log(low) >= distance * scale:
                phase, high, low, event = 2, price, None, "BUY_PRICE_REVERSAL"
        else:
            high = max(high, price)
            event = "CONTINUE_PRICE_CYCLE"
            if log(high) - logs[p] >= distance * scale:
                phase, high, low, scale, event = 0, price, None, None, "SELL_PRICE_RETRACE"
        rows.append(
            dict(
                signal_time=signal_sessions[p - start] + pd.Timedelta(hours=17),
                close=price,
                state_before=names[old],
                state_after=names[phase],
                reason=event,
                target_position=int(phase == 2),
                sigma_current=current,
                sigma_available=usable,
                sigma_unavailable_reason=None
                if usable
                else ("INSUFFICIENT_PAST_L_RETURNS" if p < lookback else "ZERO_VOLATILITY"),
                sigma_locked=float("nan") if scale is None else scale,
                known_peak=high,
                known_trough=float("nan") if low is None else low,
            )
        )
    result = pd.DataFrame(rows, index=signal_sessions)
    for name in ("state_before", "state_after", "reason", "sigma_unavailable_reason"):
        result[name] = result[name].astype("string")
    return result


def compare(reported, expected):
    """All metadata checked; numeric tolerance never changes decision >=."""
    if not isinstance(reported, pd.DataFrame) or not reported.index.equals(expected.index):
        raise AssertionError("exact full decision axis required")
    if reported.columns.has_duplicates or not set(FIELDS).issubset(reported.columns):
        raise AssertionError("all policy metadata fields required")
    differences, count = {}, 0
    for field in FIELDS:
        if field in NUMERIC:
            actual, want = reported[field].to_numpy(float), expected[field].to_numpy(float)
            if not np.array_equal(np.isnan(actual), np.isnan(want)):
                raise AssertionError(field + ": unavailable mask")
            good = np.isfinite(want)
            if not np.isfinite(actual[good]).all() or not np.allclose(
                actual[good], want[good], atol=ATOL, rtol=RTOL
            ):
                raise AssertionError(field + ": numeric")
            differences[field] = (
                float(np.max(np.abs(actual[good] - want[good]))) if good.any() else 0.0
            )
            count += int(good.sum())
        elif not reported[field].equals(expected[field]):
            raise AssertionError(field + ": exact state/flag/time/target")
    return dict(
        status="PASS",
        full_signal_axis_n=len(expected),
        fields=list(FIELDS),
        strict_states_targets_flags_exact=True,
        scalar_atol=ATOL,
        scalar_rtol=RTOL,
        numeric_comparisons=count,
        max_absolute_differences=differences,
        actual_account_equivalence_claim=False,
    )


def verify_native_policy(close, signal_sessions, reported, *, lookback=20, distance=1.0):
    """Future authenticated HFQ caller; actual fills require separate ledger audit."""
    session_axis(signal_sessions)
    if (
        len(signal_sessions) != 1636
        or signal_sessions[0] != pd.Timestamp("2019-12-31")
        or signal_sessions[-1] != pd.Timestamp("2026-09-29")
    ):
        raise ValueError("exact original1636 native signal anchor/prefix required")
    return compare(reported, online(close, signal_sessions, lookback=lookback, distance=distance))
