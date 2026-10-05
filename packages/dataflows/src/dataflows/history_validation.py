"""Stable validation findings for historical market-data products."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from types import MappingProxyType
from typing import Any, Literal, Mapping

import numpy as np
import pandas as pd

from .bar_utils import INTRADAY_PERIOD_MINUTES, intraday_close_times
from .errors import DataContractError
from .market_resolver import MARKET_A_SHARE, MARKET_HK


OHLCV_COLUMNS = ("Date", "Open", "High", "Low", "Close", "Volume", "Amount")
PRICE_TOLERANCE = 0.005
VOLUME_RELATIVE_TOLERANCE = 1e-5
AMOUNT_RELATIVE_TOLERANCE = 1e-5
FLOAT_COMPARISON_EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    """One machine-readable reason why DFLS cannot publish data."""

    code: str
    message: str
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "context": dict(self.context),
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Complete validation outcome for one requested data product."""

    findings: tuple[ValidationFinding, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))

    @property
    def passed(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "PASS" if self.passed else "FAIL",
            "findings": [item.to_dict() for item in self.findings],
            **dict(self.metrics),
        }

    def require_pass(self) -> None:
        if self.passed:
            return
        raise DataContractError(
            "; ".join(
                f"{item.code}: {item.message}; context={dict(item.context)}"
                for item in self.findings
            ),
            findings=[item.to_dict() for item in self.findings],
        )


def _finding(code: str, message: str, **context: Any) -> ValidationFinding:
    return ValidationFinding(code, message, context)


def _unique_findings(
    findings: list[ValidationFinding],
) -> tuple[ValidationFinding, ...]:
    unique: list[ValidationFinding] = []
    seen: set[str] = set()
    for item in findings:
        key = json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return tuple(unique)


def inspect_ohlcv_frame(
    dataframe: pd.DataFrame,
    frequency: str,
    *,
    require_complete_days: bool = False,
    market: str = MARKET_A_SHARE,
    request_start: str | None = None,
    request_end: str | None = None,
) -> ValidationReport:
    """Inspect one normalized OHLCV series without repairing it."""

    findings: list[ValidationFinding] = []
    missing = sorted(set(OHLCV_COLUMNS).difference(dataframe.columns))
    if missing:
        return ValidationReport(
            (_finding("SCHEMA_MISMATCH", f"{frequency}: missing columns", missing=missing),)
        )
    if dataframe.empty:
        return ValidationReport(
            (_finding("EMPTY_DATA", f"{frequency}: no rows"),)
        )

    frame = dataframe.loc[:, OHLCV_COLUMNS].copy()
    frame.attrs = {}
    timestamps = pd.to_datetime(frame["Date"], errors="coerce")
    if timestamps.isna().any():
        findings.append(_finding("INVALID_TIMESTAMP", f"{frequency}: invalid timestamps"))
    else:
        if timestamps.duplicated().any():
            findings.append(
                _finding("DUPLICATE_TIMESTAMP", f"{frequency}: duplicate timestamps")
            )
        if not timestamps.is_monotonic_increasing:
            findings.append(
                _finding("UNORDERED_TIMESTAMP", f"{frequency}: timestamps are not increasing")
            )

    for column in OHLCV_COLUMNS[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    numeric_values = frame.loc[:, OHLCV_COLUMNS[1:]].to_numpy(dtype=float)
    if frame.loc[:, OHLCV_COLUMNS[1:]].isna().any().any() or not np.isfinite(
        numeric_values
    ).all():
        findings.append(
            _finding("NON_NUMERIC_VALUE", f"{frequency}: null or non-numeric values")
        )
    else:
        prices = frame[["Open", "High", "Low", "Close"]]
        invalid = (
            (prices <= 0).any(axis=1)
            | (frame["High"] < frame[["Open", "Close"]].max(axis=1))
            | (frame["Low"] > frame[["Open", "Close"]].min(axis=1))
            | (frame["High"] < frame["Low"])
            | (frame[["Volume", "Amount"]] < 0).any(axis=1)
        )
        if invalid.any():
            bad_dates = timestamps.loc[invalid & timestamps.notna()].astype(str).tolist()
            findings.append(
                _finding(
                    "INVALID_OHLCV",
                    f"{frequency}: invalid OHLCV relationships",
                    timestamps=bad_dates[:50],
                )
            )

    metrics: dict[str, Any] = {"row_count": int(len(frame))}
    if frequency in INTRADAY_PERIOD_MINUTES and not timestamps.isna().any():
        if market not in {MARKET_A_SHARE, MARKET_HK}:
            return ValidationReport(tuple(findings) + (_finding(
                "UNSUPPORTED_INTRADAY_MARKET", "intraday session calendar is not supported",
                market=market,
            ),), metrics)
        expected_times = set(intraday_close_times(frequency, market))
        if not timestamps.equals(timestamps.dt.floor("s")):
            findings.append(_finding("INVALID_TIMESTAMP_RESOLUTION", "intraday bars require whole-second timestamps"))
        observed_times = set(timestamps.dt.strftime("%H:%M:%S"))
        unexpected = sorted(observed_times.difference(expected_times))
        if unexpected:
            findings.append(
                _finding(
                    "UNEXPECTED_SESSION_TIME",
                    f"{frequency}: unexpected {market} close times",
                    times=unexpected,
                )
            )
        counts = timestamps.groupby(timestamps.dt.normalize()).size()
        expected_count = len(expected_times)
        start_bound = pd.Timestamp(request_start) if request_start is not None else None
        end_bound = pd.Timestamp(request_end) if request_end is not None else None
        if request_end is not None and len(request_end) == 10:
            end_bound += pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        incomplete = {}
        for day, group in timestamps.groupby(timestamps.dt.normalize()):
            expected = {day + pd.Timedelta(clock) for clock in expected_times}
            expected = {stamp for stamp in expected
                        if (start_bound is None or stamp >= start_bound)
                        and (end_bound is None or stamp <= end_bound)}
            missing = sorted(expected.difference(group))
            if missing:
                incomplete[day.date().isoformat()] = [str(stamp) for stamp in missing]
        if require_complete_days and incomplete:
            findings.append(
                _finding(
                    "INCOMPLETE_TRADING_SESSION",
                    f"{frequency}: incomplete {market} sessions within the requested range",
                    sessions=incomplete,
                    expected_bars=expected_count,
                )
            )
        metrics.update(
            {
                "complete_day_count": int((counts == expected_count).sum()),
                "expected_bars_per_day": expected_count,
                "session_times": sorted(observed_times),
            }
        )
    return ValidationReport(tuple(findings), metrics)


def inspect_intraday_against_daily(
    intraday: pd.DataFrame,
    daily: pd.DataFrame,
    frequency: str,
    *,
    market: str = MARKET_A_SHARE,
    price_tolerance: float = PRICE_TOLERANCE,
    volume_relative_tolerance: float = VOLUME_RELATIVE_TOLERANCE,
    amount_relative_tolerance: float = AMOUNT_RELATIVE_TOLERANCE,
) -> ValidationReport:
    """Inspect one intraday series against its independently fetched daily reference."""

    structural = inspect_ohlcv_frame(
        intraday, frequency, require_complete_days=True, market=market
    )
    daily_structural = inspect_ohlcv_frame(daily, "daily")
    findings = [*structural.findings, *daily_structural.findings]
    if findings:
        return ValidationReport(tuple(findings), structural.metrics)

    minute = intraday.copy()
    day = daily.copy()
    minute["_date"] = pd.to_datetime(minute["Date"]).dt.normalize()
    day["_date"] = pd.to_datetime(day["Date"]).dt.normalize()
    aggregate = minute.groupby("_date", sort=True).agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
        Amount=("Amount", "sum"),
    )
    reference = day.set_index("_date")
    missing = reference.index.difference(aggregate.index)
    unexpected = aggregate.index.difference(reference.index)
    if len(missing) or len(unexpected):
        findings.append(
            _finding(
                "TRADING_DATE_MISMATCH",
                f"{frequency}/daily trading dates differ",
                missing_intraday=[item.date().isoformat() for item in missing],
                unexpected_intraday=[item.date().isoformat() for item in unexpected],
            )
        )

    mismatches: dict[str, list[str]] = {}
    for trade_date in aggregate.index.intersection(reference.index):
        fields: list[str] = []
        for column in ("Open", "High", "Low", "Close"):
            if (
                abs(float(aggregate.at[trade_date, column]) - float(reference.at[trade_date, column]))
                > price_tolerance + FLOAT_COMPARISON_EPSILON
            ):
                fields.append(column)
        for column, tolerance in (
            ("Volume", volume_relative_tolerance),
            ("Amount", amount_relative_tolerance),
        ):
            expected = float(reference.at[trade_date, column])
            relative = abs(float(aggregate.at[trade_date, column]) - expected) / max(
                abs(expected), 1.0
            )
            if relative > tolerance + FLOAT_COMPARISON_EPSILON:
                fields.append(column)
        if fields:
            mismatches[trade_date.date().isoformat()] = fields
    if mismatches:
        findings.append(
            _finding(
                "CROSS_FREQUENCY_MISMATCH",
                f"{frequency}/daily values differ",
                fields_by_date=mismatches,
            )
        )
    metrics = {
        **dict(structural.metrics),
        "daily_matched_days": int(len(aggregate.index.intersection(reference.index))),
        "price_tolerance": price_tolerance,
        "volume_relative_tolerance": volume_relative_tolerance,
        "amount_relative_tolerance": amount_relative_tolerance,
    }
    return ValidationReport(tuple(findings), metrics)


def inspect_daily_against_weekly(
    daily: pd.DataFrame,
    weekly: pd.DataFrame,
) -> ValidationReport:
    """Inspect weekly bars against deterministic aggregation of daily bars."""

    daily_report = inspect_ohlcv_frame(daily, "daily")
    weekly_report = inspect_ohlcv_frame(weekly, "weekly")
    findings = [*daily_report.findings, *weekly_report.findings]
    if findings:
        return ValidationReport(tuple(findings))
    source = daily.copy()
    source["_date"] = pd.to_datetime(source["Date"]).dt.normalize()
    source["_week"] = source["_date"].dt.to_period("W-SUN")
    aggregate = source.groupby("_week", sort=True).agg(
        Date=("_date", "max"),
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
        Amount=("Amount", "sum"),
    ).set_index("Date")
    reference = weekly.assign(
        Date=pd.to_datetime(weekly["Date"]).dt.normalize()
    ).set_index("Date")
    if not aggregate.index.equals(reference.index):
        findings.append(
            _finding(
                "WEEKLY_DATE_MISMATCH",
                "daily/weekly week-ending trade dates differ",
            )
        )
    mismatched_fields: list[str] = []
    if aggregate.index.equals(reference.index):
        for column in ("Open", "High", "Low", "Close"):
            if not np.allclose(
                aggregate[column],
                reference[column],
                rtol=0.0,
                atol=PRICE_TOLERANCE + FLOAT_COMPARISON_EPSILON,
            ):
                mismatched_fields.append(column)
        for column, tolerance in (
            ("Volume", VOLUME_RELATIVE_TOLERANCE),
            ("Amount", AMOUNT_RELATIVE_TOLERANCE),
        ):
            denominator = np.maximum(np.abs(reference[column].to_numpy(dtype=float)), 1.0)
            relative = np.abs(
                aggregate[column].to_numpy(dtype=float)
                - reference[column].to_numpy(dtype=float)
            ) / denominator
            if bool(np.any(relative > tolerance + FLOAT_COMPARISON_EPSILON)):
                mismatched_fields.append(column)
    if mismatched_fields:
        findings.append(
            _finding(
                "WEEKLY_VALUE_MISMATCH",
                "daily/weekly values differ",
                fields=mismatched_fields,
            )
        )
    return ValidationReport(
        tuple(findings), {"weekly_matched_periods": int(len(aggregate))}
    )


def inspect_market_collection(
    frames: Mapping[str, pd.DataFrame],
    *,
    execution_daily: pd.DataFrame | None = None,
    trading_calendar: pd.DataFrame | None = None,
    expected_start: str | pd.Timestamp | None = None,
    execution_date_policy: Literal["equal", "subset"] = "equal",
    calendar_requires_full_coverage: bool = True,
) -> ValidationReport:
    """Inspect all relationships available in one market-data request group."""

    if execution_date_policy not in {"equal", "subset"}:
        raise ValueError("execution_date_policy must be equal or subset")
    findings: list[ValidationFinding] = []
    metrics: dict[str, Any] = {}
    structural_reports: dict[str, ValidationReport] = {}
    for frequency, frame in frames.items():
        report = inspect_ohlcv_frame(
            frame,
            frequency,
            require_complete_days=frequency in INTRADAY_PERIOD_MINUTES,
        )
        structural_reports[frequency] = report
        findings.extend(report.findings)
        metrics[frequency] = dict(report.metrics)

    daily = frames.get("daily")
    if daily is not None and structural_reports["daily"].passed:
        for frequency, frame in frames.items():
            if frequency in INTRADAY_PERIOD_MINUTES:
                report = inspect_intraday_against_daily(frame, daily, frequency)
                findings.extend(report.findings)
                metrics[frequency] = dict(report.metrics)
        weekly = frames.get("weekly")
        if weekly is not None:
            report = inspect_daily_against_weekly(daily, weekly)
            findings.extend(report.findings)
            metrics["weekly_reconciliation"] = dict(report.metrics)
        if execution_daily is not None:
            execution_report = inspect_ohlcv_frame(execution_daily, "execution_daily")
            findings.extend(execution_report.findings)
            if execution_report.passed:
                adjusted_dates = pd.DatetimeIndex(
                    pd.to_datetime(daily["Date"]).dt.normalize()
                )
                execution_dates = pd.DatetimeIndex(
                    pd.to_datetime(execution_daily["Date"]).dt.normalize()
                )
                dates_match = (
                    adjusted_dates.equals(execution_dates)
                    if execution_date_policy == "equal"
                    else execution_dates.difference(adjusted_dates).empty
                )
                if not dates_match:
                    findings.append(
                        _finding(
                            "EXECUTION_DATE_MISMATCH",
                            "execution daily dates do not satisfy the adjusted daily contract",
                            policy=execution_date_policy,
                        )
                    )
        if trading_calendar is not None:
            required = {"Date", "IsOpen"}
            missing = sorted(required.difference(trading_calendar.columns))
            if missing:
                findings.append(
                    _finding(
                        "CALENDAR_SCHEMA_MISMATCH",
                        "trading calendar columns are incomplete",
                        missing=missing,
                    )
                )
            else:
                calendar = trading_calendar.loc[:, ["Date", "IsOpen"]].copy()
                calendar["Date"] = pd.to_datetime(
                    calendar["Date"], errors="coerce"
                ).dt.normalize()
                calendar["IsOpen"] = pd.to_numeric(
                    calendar["IsOpen"], errors="coerce"
                )
                observed = pd.DatetimeIndex(pd.to_datetime(daily["Date"]).dt.normalize())
                if (
                    calendar.empty
                    or calendar.isna().any().any()
                    or calendar["Date"].duplicated().any()
                    or not calendar["Date"].is_monotonic_increasing
                    or not calendar["IsOpen"].isin([0, 1]).all()
                ):
                    findings.append(
                        _finding(
                            "INVALID_CALENDAR",
                            "trading calendar contains invalid or duplicate rows",
                        )
                    )
                else:
                    coverage_start = (
                        pd.Timestamp(expected_start).normalize()
                        if expected_start is not None
                        else observed[0]
                    )
                    coverage_end = observed[-1]
                    if not calendar_requires_full_coverage:
                        coverage_start = max(coverage_start, calendar["Date"].iloc[0])
                        coverage_end = min(coverage_end, calendar["Date"].iloc[-1])
                        if coverage_start > coverage_end:
                            findings.append(
                                _finding(
                                    "CALENDAR_NO_OVERLAP",
                                    "trading calendar does not overlap daily data",
                                )
                            )
                            return ValidationReport(
                                _unique_findings(findings), metrics
                            )
                    expected = pd.DatetimeIndex(
                        calendar.loc[
                            calendar["IsOpen"].astype(int).eq(1)
                            & calendar["Date"].between(coverage_start, coverage_end),
                            "Date",
                        ]
                    )
                    observed_in_coverage = observed[
                        (observed >= coverage_start) & (observed <= coverage_end)
                    ]
                    if not observed_in_coverage.equals(expected):
                        findings.append(
                            _finding(
                                "CALENDAR_COVERAGE_MISMATCH",
                                "daily data and trading calendar sessions differ",
                                missing=[
                                    item.date().isoformat()
                                    for item in expected.difference(observed_in_coverage)
                                ],
                                unexpected=[
                                    item.date().isoformat()
                                    for item in observed_in_coverage.difference(expected)
                                ],
                            )
                        )
                    metrics["calendar_matched_sessions"] = int(len(expected))
    return ValidationReport(_unique_findings(findings), metrics)
