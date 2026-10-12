"""Independent scalar co-down audit; does not import the primary builder."""

from __future__ import annotations

import math

import pandas as pd

COLUMNS = (
    "co_down_dependence20", "mean_a20", "mean_b20", "rms_a20", "rms_b20",
    "freq_a20", "freq_b20",
)
TRACE_KEYS = {
    "signal_date", "calendar_position", "window_complete", "available", "reason",
    "window_positions", "window_dates", "predecessor_position", "predecessor_date",
    "numerator", "denominator", "max_observation_date",
}


def _date_axis(index, name):
    if (
        not isinstance(index, pd.DatetimeIndex) or len(index) == 0
        or index.tz is not None or index.hasnans or index.has_duplicates
        or not index.is_monotonic_increasing or not index.equals(index.normalize())
    ):
        raise ValueError("invalid " + name)


def verify(prices, axis, calendar, reported, trace):
    """Reconstruct seven values and every window/availability field using scalars.

    The first20 calendar positions have insufficient history for20 gaps plus
    their real predecessor. Mature zero-energy windows retain all six marginals
    but normalized dependence is NA. No unavailable cell is silently omitted.
    """
    for index, name in ((calendar, "calendar"), (axis, "axis")):
        _date_axis(index, name)
    if not isinstance(prices, pd.DataFrame):
        raise ValueError("prices must be DataFrame")
    _date_axis(prices.index, "prices")
    if not prices.index.equals(calendar):
        raise ValueError("prices must cover every declared calendar date exactly")
    if prices.columns.has_duplicates or not {"open", "close"}.issubset(prices.columns):
        raise ValueError("unique open/close fields required")
    mapping = {day: i for i, day in enumerate(calendar)}
    if any(day not in mapping for day in axis):
        raise ValueError("signal date absent from calendar")
    positions = [mapping[day] for day in axis]
    if any(right != left + 1 for left, right in zip(positions, positions[1:])):
        raise ValueError("signal interval must traverse every calendar session")
    opening, closing = [], []
    for o, c in prices[["open", "close"]].itertuples(index=False, name=None):
        o, c = float(o), float(c)
        if not math.isfinite(o) or not math.isfinite(c) or o <= 0 or c <= 0:
            raise ValueError("finite positive open/close required")
        opening.append(o)
        closing.append(c)
    if (
        not isinstance(reported, pd.DataFrame) or not reported.index.equals(axis)
        or tuple(reported.columns) != COLUMNS or len(reported) != len(axis)
    ):
        raise ValueError("reported seven-column axis/schema mismatch")
    if not isinstance(trace, list) or len(trace) != len(axis):
        raise ValueError("one trace record per signal required")
    compared = 0
    maximum = 0.0
    counts = {"AVAILABLE": 0, "INSUFFICIENT_HISTORY": 0,
              "ZERO_NEGATIVE_ENERGY_DENOMINATOR": 0}
    for row, (date, location) in enumerate(zip(axis, positions)):
        complete = location >= 20
        window = list(range(location - 19, location + 1)) if complete else []
        pred = window[0] - 1 if complete else None
        expected = [math.nan] * 7
        numerator = denominator = None
        reason = "INSUFFICIENT_HISTORY"
        if complete:
            aa, bb = [], []
            for j in window:
                gap = math.log(opening[j]) - math.log(closing[j-1])
                body = math.log(closing[j]) - math.log(opening[j])
                aa.append(max(-gap, 0.0))
                bb.append(max(-body, 0.0))
            mean_a, mean_b = math.fsum(aa) / 20, math.fsum(bb) / 20
            energy_a = math.fsum(v * v for v in aa) / 20
            energy_b = math.fsum(v * v for v in bb) / 20
            numerator = math.fsum(a*b for a, b in zip(aa, bb)) / 20 - mean_a*mean_b
            denominator = math.sqrt(energy_a * energy_b)
            expected[1:] = [
                mean_a, mean_b, math.sqrt(energy_a), math.sqrt(energy_b),
                sum(v > 0 for v in aa)/20, sum(v > 0 for v in bb)/20,
            ]
            if energy_a == 0 or energy_b == 0:
                reason = "ZERO_NEGATIVE_ENERGY_DENOMINATOR"
            else:
                if denominator == 0:
                    raise ValueError("nonzero energies but numerical denominator underflow")
                expected[0] = numerator / denominator
                reason = "AVAILABLE"
        actual = reported.iloc[row].to_numpy(dtype=float)
        for name, value, observed in zip(COLUMNS, expected, actual):
            compared += 1
            if math.isnan(value):
                if not math.isnan(observed):
                    raise ValueError(f"unavailable cell not NA: {date}/{name}")
            elif not math.isfinite(observed) or not math.isclose(
                value, observed, rel_tol=0, abs_tol=1e-12
            ):
                raise ValueError(f"scalar feature mismatch: {date}/{name}")
            else:
                maximum = max(maximum, abs(value - observed))
        expected_trace = {
            "signal_date": date.isoformat(), "calendar_position": location,
            "window_complete": complete, "available": reason == "AVAILABLE",
            "reason": reason, "window_positions": window,
            "window_dates": [calendar[j].isoformat() for j in window],
            "predecessor_position": pred,
            "predecessor_date": calendar[pred].isoformat() if complete else None,
            "numerator": numerator, "denominator": denominator,
            "max_observation_date": date.isoformat() if complete else None,
        }
        record = trace[row]
        if not isinstance(record, dict) or set(record) != TRACE_KEYS:
            raise ValueError("trace schema mismatch")
        for key, expected_value in expected_trace.items():
            observed = record[key]
            if key in ("numerator", "denominator") and expected_value is not None:
                if (
                    observed is None or not math.isfinite(float(observed))
                    or not math.isclose(float(observed), expected_value, rel_tol=0, abs_tol=1e-14)
                ):
                    raise ValueError("trace numeric mismatch: " + key)
            elif observed != expected_value:
                raise ValueError("trace exact mismatch: " + key)
        counts[reason] += 1
    return {
        "status": "PASS", "signal_rows": len(axis), "feature_cells": compared,
        "trace_windows": len(axis), "all_trace_fields_checked": True,
        "maximum_absolute_feature_difference": maximum,
        "availability_counts": counts, "implementation": "independent_scalar_math_fsum",
    }
