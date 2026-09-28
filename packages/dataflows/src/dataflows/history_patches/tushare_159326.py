"""Tushare repair patch for 159326.SZ."""

from __future__ import annotations

from typing import Mapping, Sequence

import pandas as pd

from ..history_validation import ValidationFinding
from .common import configured_repair_dates, replace_intraday_from_1m
from .model import RepairPatch, SeriesKey


_30M_SERIES = SeriesKey("tushare", "etf_mins", "159326.SZ", "etf.ohlcv", "30m", "none")
_30M_REBUILD_DATES = (
    "2024-10-16",
    "2024-10-17",
    "2025-04-10",
)


def _reference_dates(
    daily: pd.DataFrame,
    patch: RepairPatch,
    series: SeriesKey,
    findings: Sequence[ValidationFinding],
) -> tuple[str, ...]:
    del patch
    if series != _30M_SERIES or not any(
        item.code == "CROSS_FREQUENCY_MISMATCH" for item in findings
    ):
        return ()
    return configured_repair_dates(daily, _30M_REBUILD_DATES)


def _execute(
    dataframe: pd.DataFrame,
    patch: RepairPatch,
    series: SeriesKey,
    findings: Sequence[ValidationFinding],
    references: Mapping[str, pd.DataFrame],
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    repair_dates = _reference_dates(
        references.get("daily", pd.DataFrame()), patch, series, findings
    )
    if not repair_dates:
        return dataframe.copy(), ()
    return replace_intraday_from_1m(dataframe, patch, series, references, repair_dates)


PATCH = RepairPatch(
    "TUSHARE_159326_V1",
    1,
    "tushare",
    "159326.SZ",
    _execute,
    reference_dates=_reference_dates,
)
