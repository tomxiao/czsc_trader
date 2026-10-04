"""Tushare repair patch for 518880.SH."""

from __future__ import annotations

from typing import Mapping, Sequence

import pandas as pd

from ..history_validation import ValidationFinding
from .common import (
    configured_repair_dates,
    replace_intraday_from_1m,
)
from .model import RepairPatch, SeriesKey
from .gold_etf_volume import matches_volume_series, repair_volume, volume_reference_dates


_DAILY_SERIES = SeriesKey(
    "tushare", "fund_daily", "518880.SH", "etf.ohlcv", "daily", "none"
)
_30M_SERIES = SeriesKey(
    "tushare", "etf_mins", "518880.SH", "etf.ohlcv", "30m", "none"
)
_REBUILD_FINDINGS = {
    "INVALID_OHLCV",
    "INCOMPLETE_TRADING_SESSION",
    "TRADING_DATE_MISMATCH",
    "CROSS_FREQUENCY_MISMATCH",
}

_DAILY_CORRECTIONS = {
    "2013-11-07": {
        "Volume": (2269500.0, 2410300.0),
        "Amount": (5865485.0, 6230016.0),
    },
    "2016-03-01": {"Low": (2.611, 2.620)},
    "2019-09-10": {"Low": (3.371, 3.378)},
    "2019-11-01": {"Low": (3.300, 3.379)},
    "2020-03-09": {"Low": (3.317, 3.548)},
    "2020-08-07": {"Low": (4.315, 4.339)},
    "2021-03-03": {"High": (3.572, 3.556)},
}

_30M_REBUILD_DATES = (
    "2013-08-02",
    "2013-11-01",
    "2013-11-08",
    "2013-11-27",
    "2013-11-28",
    "2014-01-29",
    "2014-02-07",
    "2014-04-10",
    "2014-04-23",
    "2014-05-16",
    "2014-05-19",
    "2014-05-26",
    "2014-05-27",
    "2014-05-30",
    "2014-06-03",
    "2014-06-06",
    "2014-06-11",
    "2014-07-09",
    "2014-08-19",
    "2014-08-26",
    "2014-12-31",
    "2015-01-29",
    "2015-02-11",
    "2015-06-17",
    "2015-07-16",
    "2015-08-19",
    "2015-09-02",
    "2016-06-24",
    "2017-08-07",
    "2018-12-18",
    "2024-04-03",
    "2024-04-19",
    "2024-04-26",
    "2024-04-30",
    "2024-05-24",
    "2024-05-31",
    "2024-06-14",
)


def _inspect_exact_corrections(
    dataframe: pd.DataFrame,
    patch: RepairPatch,
    series: SeriesKey,
) -> tuple[ValidationFinding, ...]:
    dates = pd.to_datetime(dataframe["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    findings: list[ValidationFinding] = []
    for trade_date, fields in _DAILY_CORRECTIONS.items():
        indices = dataframe.index[dates == trade_date]
        if indices.empty:
            continue
        if len(indices) != 1:
            findings.append(
                ValidationFinding(
                    "SOURCE_SIGNATURE_UNKNOWN",
                    f"{series.symbol} {trade_date}: expected one source row",
                    {"patch_id": patch.patch_id, "row_count": len(indices)},
                )
            )
            continue
        index = indices[0]
        bad_fields: list[str] = []
        unknown_fields: list[str] = []
        for column, (expected_bad, accepted_good) in fields.items():
            actual = float(dataframe.at[index, column])
            if abs(actual - float(expected_bad)) <= 1e-9:
                bad_fields.append(column)
            elif abs(actual - float(accepted_good)) > 1e-9:
                unknown_fields.append(column)
        if unknown_fields:
            findings.append(
                ValidationFinding(
                    "SOURCE_SIGNATURE_UNKNOWN",
                    f"{series.symbol} {trade_date}: source signature changed",
                    {
                        "patch_id": patch.patch_id,
                        "date": trade_date,
                        "fields": unknown_fields,
                    },
                )
            )
        elif bad_fields:
            findings.append(
                ValidationFinding(
                    "KNOWN_SOURCE_ANOMALY",
                    f"{series.symbol} {trade_date}: known source anomaly",
                    {
                        "patch_id": patch.patch_id,
                        "date": trade_date,
                        "fields": bad_fields,
                    },
                )
            )
    return tuple(findings)


def _replace_exact_fields(
    dataframe: pd.DataFrame,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    frame = dataframe.copy()
    dates = pd.to_datetime(frame["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    affected: list[str] = []
    for trade_date, fields in _DAILY_CORRECTIONS.items():
        indices = frame.index[dates == trade_date]
        if indices.empty:
            continue
        index = indices[0]
        changed = False
        for column, (expected_bad, replacement) in fields.items():
            actual = float(frame.at[index, column])
            if abs(actual - float(expected_bad)) > 1e-9:
                continue
            frame.at[index, column] = replacement
            changed = True
        if changed:
            affected.append(trade_date)
    return frame, tuple(affected)


def _inspect(
    dataframe: pd.DataFrame, patch: RepairPatch, series: SeriesKey
) -> tuple[ValidationFinding, ...]:
    if series != _DAILY_SERIES:
        return ()
    return _inspect_exact_corrections(dataframe, patch, series)


def _reference_dates(
    daily: pd.DataFrame,
    patch: RepairPatch,
    series: SeriesKey,
    findings: Sequence[ValidationFinding],
) -> tuple[str, ...]:
    del patch
    if matches_volume_series(series):
        return volume_reference_dates(daily, series, findings)
    if series != _30M_SERIES or not {
        item.code for item in findings
    }.intersection(_REBUILD_FINDINGS):
        return ()
    return configured_repair_dates(daily, _30M_REBUILD_DATES)


def _execute(
    dataframe: pd.DataFrame,
    patch: RepairPatch,
    series: SeriesKey,
    findings: Sequence[ValidationFinding],
    references: Mapping[str, pd.DataFrame],
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    finding_codes = {item.code for item in findings}
    if matches_volume_series(series):
        return repair_volume(dataframe, patch, series, findings, references)
    if series == _DAILY_SERIES and "KNOWN_SOURCE_ANOMALY" in finding_codes:
        return _replace_exact_fields(dataframe)
    if series == _30M_SERIES and finding_codes.intersection(_REBUILD_FINDINGS):
        repair_dates = configured_repair_dates(
            references.get("daily"), _30M_REBUILD_DATES
        )
        return replace_intraday_from_1m(
            dataframe, patch, series, references, repair_dates
        )
    return dataframe.copy(), ()


PATCH = RepairPatch(
    "TUSHARE_518880_V2",
    2,
    "tushare",
    "518880.SH",
    _execute,
    _inspect,
    _reference_dates,
)
