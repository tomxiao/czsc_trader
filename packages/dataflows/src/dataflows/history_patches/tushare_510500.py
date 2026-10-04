"""Tushare repair patch for 510500.SH."""

from __future__ import annotations

from typing import Mapping, Sequence

import pandas as pd

from ..errors import DataRepairError
from ..history_validation import ValidationFinding, inspect_intraday_against_daily
from .common import (
    configured_repair_dates,
    rebuild_intraday_from_1m,
    replace_intraday_from_1m,
)
from .model import RepairPatch, SeriesKey


_15M_SERIES = SeriesKey(
    "tushare", "etf_mins", "510500.SH", "etf.ohlcv", "15m", "none"
)
_VOLUME_X100_DATES = (
    "2024-04-03",
    "2024-04-19",
    "2024-04-26",
    "2024-04-30",
    "2024-05-24",
    "2024-05-31",
    "2024-06-14",
)
# Exact coarse-bar extrema verified against complete 1m and daily references.
# The five dates with missing extrema in 1m remain unrepairable without timing
# evidence; daily extremes alone cannot identify their intraday occurrence.
_EXTREME_SIGNATURES = {
    "2020-09-11": ("Low", 6.837, 6.829),
    "2020-10-30": ("High", 6.925, 6.939),
}


def _extreme_dates(
    series: SeriesKey,
    findings: Sequence[ValidationFinding],
) -> tuple[str, ...]:
    if not (
        series.endpoint == "etf_mins"
        and series.dataset == "etf.ohlcv"
        and series.adjustment == "none"
        and series.frequency in {"5m", "15m", "30m"}
    ):
        return ()
    return tuple(sorted({
        str(day)
        for finding in findings
        if finding.code == "CROSS_FREQUENCY_MISMATCH"
        for day, fields in finding.context.get("fields_by_date", {}).items()
        if day in _EXTREME_SIGNATURES and fields == [_EXTREME_SIGNATURES[day][0]]
    }))


def _repair_extrema(
    dataframe: pd.DataFrame,
    patch: RepairPatch,
    series: SeriesKey,
    findings: Sequence[ValidationFinding],
    references: Mapping[str, pd.DataFrame],
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    dates = _extreme_dates(series, findings)
    if not dates:
        return dataframe.copy(), ()
    if "1m" not in references or "daily" not in references:
        raise DataRepairError(f"{patch.patch_id}: complete 1m and daily extrema evidence required")
    frame = dataframe.copy()
    frame_days = pd.to_datetime(frame.Date).dt.strftime("%Y-%m-%d")
    daily = references["daily"]
    daily_days = pd.to_datetime(daily.Date).dt.strftime("%Y-%m-%d")
    for day in dates:
        current = frame.loc[frame_days == day]
        reference = daily.loc[daily_days == day]
        if len(reference) != 1:
            raise DataRepairError(f"{patch.patch_id}: unique daily reference required on {day}")
        rebuilt = rebuild_intraday_from_1m(references["1m"], daily, series.frequency, dates=(day,))
        inspect_intraday_against_daily(rebuilt, reference, series.frequency).require_pass()
        if not pd.to_datetime(current.Date).reset_index(drop=True).equals(rebuilt.Date):
            raise DataRepairError(f"{patch.patch_id}: complete coarse bars required on {day}")
        field, bad, good = _EXTREME_SIGNATURES[day]
        observed = current[field].min() if field == "Low" else current[field].max()
        if abs(float(observed) - bad) > 1e-12 or abs(float(reference.iloc[0][field]) - good) > 1e-12:
            raise DataRepairError(f"{patch.patch_id}: unknown extrema signature on {day}")
        # Use independently reconstructed values at their actual bar closes.
        # Preserve extrema already observed by the coarse source: its Open/Close
        # can lie beyond extrema sampled by the independent minute source.
        bounds = pd.DataFrame({"source": current[field].to_numpy(), "minute": rebuilt[field].to_numpy()})
        frame.loc[current.index, field] = bounds.agg("min" if field == "Low" else "max", axis=1).to_numpy()
        inspect_intraday_against_daily(frame.loc[current.index], reference, series.frequency).require_pass()
    return frame, dates


def _scale_volume_x100(
    dataframe: pd.DataFrame,
    series: SeriesKey,
    findings: Sequence[ValidationFinding],
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    if not (
        series.endpoint == "etf_mins"
        and series.dataset == "etf.ohlcv"
        and series.adjustment == "none"
        and series.frequency in {"5m", "15m", "30m"}
    ):
        return dataframe.copy(), ()
    mismatched: set[str] = set()
    for finding in findings:
        if finding.code != "CROSS_FREQUENCY_MISMATCH":
            continue
        for trade_date, fields in finding.context.get("fields_by_date", {}).items():
            if fields == ["Volume"]:
                mismatched.add(str(trade_date))
    affected = sorted(set(_VOLUME_X100_DATES).intersection(mismatched))
    if not affected:
        return dataframe.copy(), ()
    frame = dataframe.copy()
    dates = pd.to_datetime(frame["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame.loc[dates.isin(affected), "Volume"] /= 100.0
    return frame, tuple(affected)


def _reference_dates(
    daily: pd.DataFrame,
    patch: RepairPatch,
    series: SeriesKey,
    findings: Sequence[ValidationFinding],
) -> tuple[str, ...]:
    del patch
    dates = set(_extreme_dates(series, findings))
    if series == _15M_SERIES and any(item.code == "TRADING_DATE_MISMATCH" for item in findings):
        dates.update(configured_repair_dates(daily, ("2024-10-30",)))
    return tuple(sorted(dates))


def _execute(
    dataframe: pd.DataFrame,
    patch: RepairPatch,
    series: SeriesKey,
    findings: Sequence[ValidationFinding],
    references: Mapping[str, pd.DataFrame],
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    result = dataframe.copy()
    affected: set[str] = set()
    if "daily" in references:
        repair_dates = (
            configured_repair_dates(references["daily"], ("2024-10-30",))
            if series == _15M_SERIES and any(item.code == "TRADING_DATE_MISMATCH" for item in findings)
            else ()
        )
        if repair_dates:
            result, rebuilt_dates = replace_intraday_from_1m(
                result, patch, series, references, repair_dates
            )
            affected.update(rebuilt_dates)
    result, volume_dates = _scale_volume_x100(result, series, findings)
    affected.update(volume_dates)
    result, extrema_dates = _repair_extrema(result, patch, series, findings, references)
    affected.update(extrema_dates)
    return result, tuple(sorted(affected))


PATCH = RepairPatch(
    "TUSHARE_510500_V2",
    2,
    "tushare",
    "510500.SH",
    _execute,
    reference_dates=_reference_dates,
)
