"""Request-scoped OHLCV acceptance from persisted, post-repair session evidence."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import math
from typing import Any

import pandas as pd

from .bar_utils import intraday_close_times
from .contract import DataRequest
from .errors import DataContractError, IncompleteDataError
from .history_validation import (
    AMOUNT_RELATIVE_TOLERANCE, FLOAT_COMPARISON_EPSILON, PRICE_TOLERANCE,
    VOLUME_RELATIVE_TOLERANCE, inspect_intraday_against_daily, inspect_ohlcv_frame,
)

from .market_resolver import detect_market

QUALITY_VERSION = 1
QUALITY_KEY = "ohlcv_quality_evidence"
VALUE_COLUMNS = ("Open", "High", "Low", "Close", "Volume", "Amount")


def _values(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != set(VALUE_COLUMNS):
        raise DataContractError("OHLCV quality numeric evidence is invalid")
    if any(type(item) not in {int, float} or not math.isfinite(item) for item in value.values()):
        raise DataContractError("OHLCV quality numeric evidence is not finite")
    if (any(value[name] <= 0 for name in VALUE_COLUMNS[:4])
            or value["High"] < max(value["Open"], value["Close"], value["Low"])
            or value["Low"] > min(value["Open"], value["Close"])
            or value["Volume"] < 0 or value["Amount"] < 0):
        raise DataContractError("OHLCV quality numeric evidence relationships are invalid")
    return dict(value)


def _daily_fields(value: Mapping[str, float]) -> list[str]:
    if value["Volume"] <= 0:
        return ["NONPOSITIVE_VOLUME"]
    vwap = value["Amount"] / value["Volume"]
    return (["VWAP_BELOW_LOW"] if vwap < value["Low"] - PRICE_TOLERANCE - FLOAT_COMPARISON_EPSILON else []) + (
        ["VWAP_ABOVE_HIGH"] if vwap > value["High"] + PRICE_TOLERANCE + FLOAT_COMPARISON_EPSILON else [])


def _minute_fields(observed: Mapping[str, float], anchor: Mapping[str, float]) -> list[str]:
    fields = [name for name in VALUE_COLUMNS[:4] if abs(observed[name] - anchor[name]) > PRICE_TOLERANCE + FLOAT_COMPARISON_EPSILON]
    for name, tolerance in (("Volume", VOLUME_RELATIVE_TOLERANCE), ("Amount", AMOUNT_RELATIVE_TOLERANCE)):
        if abs(observed[name] - anchor[name]) / max(abs(anchor[name]), 1.) > tolerance + FLOAT_COMPARISON_EPSILON:
            fields.append(name)
    return fields


def _same_values(expected: Mapping[str, float], actual: Mapping[str, float], *, adjustment: bool) -> None:
    factor = actual["Close"] / expected["Close"] if adjustment else 1.
    if factor <= 0 or not math.isfinite(factor):
        raise DataContractError("OHLCV publication adjustment factor is invalid")
    for name in VALUE_COLUMNS:
        value = expected[name] * factor if name in VALUE_COLUMNS[:4] else (
            expected[name] / factor if name == "Volume" else expected[name])
        if not math.isclose(value, actual[name], rel_tol=1e-12, abs_tol=1e-12):
            raise DataContractError("OHLCV publication differs from quality numeric evidence", field=name)


def _verify_frame_values(evidence: Mapping[str, Any], frame: pd.DataFrame, *, complete_source: bool = False) -> None:
    sessions = evidence["sessions"]
    adjusted = evidence.get("publication_adjustment") == "hfq"
    frequency = evidence["frequency"]
    source = frame.copy()
    source.attrs = {}
    source["_day"] = pd.to_datetime(source.Date).dt.strftime("%Y-%m-%d")
    if frequency == "weekly":
        values = evidence.get("published_daily_values")
        if not isinstance(values, Mapping):
            raise DataContractError("weekly OHLCV requires published daily evidence")
        for day, row in sessions.items():
            if row["daily_values"] is not None:
                _same_values(_values(row["daily_values"]), _values(values.get(day)), adjustment=adjusted)
        daily = pd.DataFrame.from_dict(values, orient="index")
        daily["Date"] = pd.to_datetime(daily.index)
        expected = daily.groupby(daily.Date.dt.to_period("W-FRI")).agg(
            Date=("Date", "max"), Open=("Open", "first"), High=("High", "max"),
            Low=("Low", "min"), Close=("Close", "last"), Volume=("Volume", "sum"), Amount=("Amount", "sum"))
        expected.index = expected.Date.dt.strftime("%Y-%m-%d")
        for _, row in source.iterrows():
            _same_values(expected.loc[row._day], row, adjustment=False)
    elif frequency == "daily":
        for _, row in source.iterrows():
            _same_values(_values(sessions[row._day]["daily_values"]), row, adjustment=adjusted)
    else:
        aggregate = source.groupby("_day").agg(
            Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"),
            Close=("Close", "last"), Volume=("Volume", "sum"), Amount=("Amount", "sum"))
        for day, group in source.groupby("_day"):
            row = sessions[day]
            if len(group) != row["minute_bar_count"]:
                if complete_source:
                    raise DataContractError("quality binding requires the full source minute session")
                continue
            _same_values(_values(row["minute_values"]), aggregate.loc[day], adjustment=adjusted)


def bind_quality_frame(
    evidence: Mapping[str, Any], frame: pd.DataFrame, *, adjustment: str = "none",
    daily: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Bind quality to published observations, after any price adjustment/resampling."""
    hashes = {}
    for row in frame.loc[:, ["Date", *VALUE_COLUMNS]].itertuples(index=False, name=None):
        key = pd.Timestamp(row[0]).isoformat()
        hashes[key] = sha256(json.dumps([float(v) for v in row[1:]], allow_nan=False).encode()).hexdigest()
    bound = {**evidence, "observation_sha256": hashes}
    if "sessions" in evidence:
        bound["publication_adjustment"] = adjustment
        if evidence["frequency"] == "weekly":
            bound["published_daily_values"] = (
                {pd.Timestamp(row.Date).date().isoformat(): {name: float(row[name]) for name in VALUE_COLUMNS} for _, row in daily.iterrows()}
                if daily is not None else {day: row["daily_values"] for day, row in evidence["sessions"].items() if row["daily_values"] is not None})
        _verify_frame_values(bound, frame, complete_source=True)
    return bound


def validate_quality_metadata(metadata: Mapping[str, Any], request: DataRequest, frame: pd.DataFrame) -> dict[str, Any]:
    evidence = metadata.get(QUALITY_KEY)
    calendar = metadata.get("daily_session_coverage")
    if not isinstance(evidence, Mapping) or not isinstance(calendar, Mapping):
        raise DataContractError("OHLCV requires explicit post-repair quality and calendar evidence")
    market = detect_market(request.symbol)
    exchange = {"hk": "HKEX", "us": "US"}.get(market, "SSE" if request.symbol.endswith(".SH") else "SZSE")
    if evidence.get("market") != market or calendar.get("exchange") != exchange:
        raise DataContractError("OHLCV quality calendar market differs from request")
    expected = calendar.get("expected_dates")
    if not isinstance(expected, (tuple, list)) or any(not isinstance(day, str) for day in expected):
        raise DataContractError("OHLCV expected trading sessions are missing")
    if len(set(expected)) != len(expected) or set(expected) != set(evidence.get("sessions", {})):
        raise DataContractError("OHLCV calendar and quality sessions differ")
    for field in ("start_date", "end_date", "listing_date"):
        value = calendar.get(field)
        if not isinstance(value, str) or pd.isna(pd.to_datetime(value, errors="coerce")):
            raise DataContractError("OHLCV calendar boundary is invalid", field=field)
    if (pd.Timestamp(calendar["start_date"]).normalize() > pd.Timestamp(request.start).normalize()
            or pd.Timestamp(calendar["end_date"]).normalize() < pd.Timestamp(request.end).normalize()):
        raise IncompleteDataError("OHLCV calendar evidence does not cover request")
    if not calendar.get("source") or not calendar.get("listing_source"):
        raise DataContractError("OHLCV calendar or listing provenance is missing")
    for digest in (calendar.get("calendar_sha256"), evidence.get("reference_daily_sha256")):
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise DataContractError("OHLCV evidence hash is invalid")
    from .history_repair import frame_content_sha256

    records = calendar.get("calendar")
    if not isinstance(records, list) or not records:
        raise DataContractError("OHLCV requires full exchange calendar evidence")
    for row in records:
        if (not isinstance(row, Mapping) or set(row) != {"Date", "is_open"}
                or not isinstance(row["Date"], str) or type(row["is_open"]) is not int
                or row["is_open"] not in {0, 1}):
            raise DataContractError("OHLCV calendar records are invalid")
    canonical = pd.DataFrame(records).sort_values("Date").reset_index(drop=True)
    days = pd.to_datetime(canonical.Date, format="%Y-%m-%d", errors="coerce")
    if (days.isna().any() or not days.dt.strftime("%Y-%m-%d").equals(canonical.Date)
            or not pd.DatetimeIndex(days).equals(pd.date_range(calendar["start_date"], calendar["end_date"]))):
        raise DataContractError("OHLCV calendar omits or duplicates natural dates")
    if frame_content_sha256(canonical) != calendar["calendar_sha256"]:
        raise DataContractError("OHLCV calendar content hash differs")
    derived = canonical.loc[canonical.is_open.eq(1) & days.ge(pd.Timestamp(calendar["listing_date"])), "Date"].tolist()
    if derived != list(expected) or calendar.get("verified_sessions") != len(derived):
        raise DataContractError("OHLCV denominator differs from exchange calendar")
    for day in expected:
        parsed = pd.to_datetime(day, format="%Y-%m-%d", errors="coerce")
        if (pd.isna(parsed) or parsed.strftime("%Y-%m-%d") != day
                or parsed < pd.Timestamp(calendar["listing_date"]).normalize()
                or not pd.Timestamp(calendar["start_date"]).normalize() <= parsed <= pd.Timestamp(calendar["end_date"]).normalize()):
            raise DataContractError("OHLCV expected trading date is invalid")
    first, last = pd.Timestamp(request.start).date().isoformat(), pd.Timestamp(request.end).date().isoformat()
    selected = {day for day in expected if first <= day <= last}
    if request.frequency == "weekly":
        dates = pd.Series(pd.to_datetime(sorted(selected)))
        selected = set(dates.groupby(dates.dt.to_period("W-FRI")).max().dt.strftime("%Y-%m-%d"))
    actual = set(pd.to_datetime(frame.Date).dt.strftime("%Y-%m-%d"))
    if actual.difference(selected):
        raise DataContractError("OHLCV observations lie outside expected trading sessions")
    if selected.difference(actual):
        raise IncompleteDataError("OHLCV observations omit expected trading sessions", missing_dates=sorted(selected.difference(actual)))
    bound = bind_quality_frame({}, frame)["observation_sha256"]
    declared = evidence.get("observation_sha256")
    if not isinstance(declared, Mapping) or any(declared.get(day) != digest for day, digest in bound.items()):
        raise DataContractError("OHLCV observations differ from post-repair quality evidence")
    if evidence.get("publication_adjustment") != metadata.get("adjustment", "none"):
        raise DataContractError("OHLCV quality publication adjustment differs")
    _verify_frame_values(evidence, frame)
    return evaluate_quality(evidence, request)


def verify_daily_sessions(
    pro: Any, ts_code: str, daily: pd.DataFrame, *, start: str, end: str,
    asset_type: str = "etf", market: str = "a_share",
) -> dict[str, Any]:
    """Prove the denominator with source lifecycle and full exchange calendar."""
    from .history_repair import frame_content_sha256

    if daily.empty:
        raise IncompleteDataError("daily reference is empty", symbol=ts_code)
    api = {"hk": "hk_basic", "us": "us_basic"}.get(market, "fund_basic" if asset_type == "etf" else "stock_basic")
    instrument = getattr(pro, api)(ts_code=ts_code, fields="ts_code,list_date")
    if instrument is None or len(instrument) != 1 or not {"ts_code", "list_date"}.issubset(instrument.columns):
        raise DataContractError("instrument listing evidence is missing or ambiguous", symbol=ts_code)
    if str(instrument.iloc[0].ts_code) != ts_code:
        raise DataContractError("instrument listing evidence symbol differs", symbol=ts_code)
    listed = pd.to_datetime(str(instrument.iloc[0].list_date), format="%Y%m%d", errors="coerce")
    if pd.isna(listed):
        raise DataContractError("instrument listing date is invalid", symbol=ts_code)
    first, last = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    exchange = {"hk": "HKEX", "us": "US"}.get(market, "SSE" if ts_code.endswith(".SH") else "SZSE")
    pieces = []
    for year in range(first.year, last.year + 1):
        a, b = max(first, pd.Timestamp(year, 1, 1)), min(last, pd.Timestamp(year, 12, 31))
        kwargs = {"start_date": a.strftime("%Y%m%d"), "end_date": b.strftime("%Y%m%d")}
        piece = getattr(pro, market + "_tradecal")(**kwargs) if market in {"hk", "us"} else pro.trade_cal(exchange=exchange, **kwargs)
        if piece is None or piece.empty:
            raise IncompleteDataError("trading calendar is unavailable", symbol=ts_code)
        pieces.append(piece)
    calendar = pd.concat(pieces, ignore_index=True)
    if not {"cal_date", "is_open"}.issubset(calendar.columns):
        raise DataContractError("trading calendar requires cal_date and is_open")
    dates = pd.to_datetime(calendar.cal_date.astype(str), format="%Y%m%d", errors="coerce")
    flags = pd.to_numeric(calendar.is_open, errors="coerce")
    if dates.isna().any() or dates.duplicated().any() or not flags.isin([0, 1]).all():
        raise DataContractError("trading calendar contains invalid dates or session flags")
    if not pd.DatetimeIndex(dates).sort_values().equals(pd.date_range(first, last)):
        raise IncompleteDataError("trading calendar does not cover the requested window", symbol=ts_code)
    expected = sorted(dates[flags.eq(1) & dates.ge(listed)].dt.strftime("%Y-%m-%d").tolist())
    actual = set(pd.to_datetime(daily.Date).dt.strftime("%Y-%m-%d"))
    closed = sorted(actual.difference(expected))
    if closed:
        raise DataContractError("daily bars include inapplicable exchange sessions", symbol=ts_code, dates=closed)
    canonical = pd.DataFrame({"Date": dates.dt.strftime("%Y-%m-%d"), "is_open": flags.astype(int)}).sort_values("Date").reset_index(drop=True)
    return {
        "source": market + "_tradecal" if market in {"hk", "us"} else "trade_cal", "exchange": exchange,
        "start_date": first.date().isoformat(), "end_date": last.date().isoformat(),
        "listing_date": listed.date().isoformat(), "listing_source": api,
        "verified_sessions": len(expected), "expected_dates": expected,
        "calendar": canonical.to_dict("records"),
        "calendar_sha256": frame_content_sha256(canonical),
    }


def build_quality_evidence(
    daily: pd.DataFrame, *, intraday: pd.DataFrame | None = None,
    frequency: str = "daily", expected_dates: Sequence[str],
    comparison_daily: pd.DataFrame | None = None,
    market: str = "a_share",
) -> dict[str, Any]:
    """Retain daily VWAP and complete-session reconciliation without strict equality."""
    from .history_repair import frame_content_sha256

    inspect_ohlcv_frame(daily, "daily").require_pass()
    d = daily.copy()
    d.index = pd.to_datetime(d.Date).dt.strftime("%Y-%m-%d")
    if len(set(expected_dates)) != len(expected_dates):
        raise DataContractError("quality denominator has duplicate sessions")
    if set(d.index).difference(expected_dates):
        raise DataContractError("daily reference lies outside quality denominator")
    rows: dict[str, dict[str, Any]] = {}
    for day in sorted(expected_dates):
        present = day in d.index
        fields: list[str] = []
        if present:
            value = d.loc[day]
            fields = _daily_fields(value)
        rows[day] = {"daily_complete": present, "daily_accurate": present and not fields, "daily_fields": fields}
        rows[day]["daily_values"] = {column: float(value[column]) for column in VALUE_COLUMNS} if present else None
        if present and value.Volume > 0:
            rows[day]["daily_vwap"] = float(value.Amount) / float(value.Volume)
            rows[day]["daily_low"] = float(value.Low)
            rows[day]["daily_high"] = float(value.High)
    if intraday is not None:
        inspect_ohlcv_frame(intraday, frequency, market=market).require_pass()
        source = intraday.copy()
        timestamps = pd.to_datetime(source.Date)
        if not timestamps.equals(timestamps.dt.floor("s")):
            raise DataContractError("OHLCV bar timestamps contain subsecond observations")
        source["_day"] = pd.to_datetime(source.Date).dt.strftime("%Y-%m-%d")
        source["_clock"] = pd.to_datetime(source.Date).dt.strftime("%H:%M:%S")
        expected_clocks = set(intraday_close_times(frequency, market))
        observed = source.groupby("_day")["_clock"].agg(set).to_dict()
        counts = source.groupby("_day").size().to_dict()
        complete = {day for day in rows if observed.get(day, set()) == expected_clocks and counts.get(day) == len(expected_clocks)}
        reference = daily if comparison_daily is None else comparison_daily
        reference_days = pd.to_datetime(reference.Date).dt.strftime("%Y-%m-%d")
        matched = complete.intersection(set(reference_days))
        differences: dict[str, list[str]] = {}
        deltas: dict[str, dict[str, float]] = {}
        aggregate = source.groupby("_day").agg(
            Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"),
            Close=("Close", "last"), Volume=("Volume", "sum"), Amount=("Amount", "sum"),
        )
        comparison = reference.copy()
        comparison.index = reference_days
        if matched:
            report = inspect_intraday_against_daily(
                source.loc[source._day.isin(matched)].drop(columns=["_day", "_clock"]).reset_index(drop=True),
                reference.loc[reference_days.isin(matched)].reset_index(drop=True), frequency, market=market,
            )
            for finding in report.findings:
                if finding.code != "CROSS_FREQUENCY_MISMATCH":
                    raise DataContractError(finding.message, findings=[finding.to_dict()])
                differences.update(finding.context["fields_by_date"])
            for day, fields in differences.items():
                deltas[day] = {field: float(aggregate.at[day, field]) - float(comparison.at[day, field]) for field in fields}
        for day, row in rows.items():
            row.update(minute_complete=day in complete,
                       minute_accurate=day in matched and day not in differences,
                       minute_fields=differences.get(day, []), minute_differences=deltas.get(day, {}))
            row["minute_values"] = {column: float(aggregate.at[day, column]) for column in VALUE_COLUMNS} if day in aggregate.index else None
            row["comparison_daily_values"] = {column: float(comparison.at[day, column]) for column in VALUE_COLUMNS} if day in comparison.index else None
            row["minute_clocks"] = sorted(observed.get(day, set()))
            row["minute_bar_count"] = int(counts.get(day, 0))
    evidence = {
        "version": QUALITY_VERSION, "frequency": frequency,
        "reference_daily_sha256": frame_content_sha256(daily),
        "price_tolerance": PRICE_TOLERANCE,
        "volume_relative_tolerance": VOLUME_RELATIVE_TOLERANCE,
        "amount_relative_tolerance": AMOUNT_RELATIVE_TOLERANCE,
        "sessions": rows, "market": market,
    }
    bound = bind_quality_frame({**evidence, "frequency": "daily" if frequency == "weekly" else frequency}, daily if intraday is None else intraday)
    return {**bound, "frequency": frequency}


def evaluate_quality(evidence: Mapping[str, Any], request: DataRequest) -> dict[str, Any]:
    """Re-evaluate the selected days, including pinned assets and smaller fetches."""
    if (not isinstance(evidence, Mapping) or type(evidence.get("version")) is not int
            or evidence["version"] != QUALITY_VERSION):
        raise DataContractError("OHLCV quality evidence is missing or unsupported")
    if evidence.get("frequency") != request.frequency:
        raise DataContractError("OHLCV quality evidence frequency differs")
    for name, expected in (("price_tolerance", PRICE_TOLERANCE), ("volume_relative_tolerance", VOLUME_RELATIVE_TOLERANCE), ("amount_relative_tolerance", AMOUNT_RELATIVE_TOLERANCE)):
        if evidence.get(name) != expected:
            raise DataContractError("OHLCV quality tolerance differs", field=name)
    sessions = evidence.get("sessions")
    if not isinstance(sessions, Mapping):
        raise DataContractError("OHLCV quality session evidence is invalid")
    first, last = pd.Timestamp(request.start).date().isoformat(), pd.Timestamp(request.end).date().isoformat()
    selected = {day: row for day, row in sessions.items() if first <= day <= last}
    if not selected:
        raise IncompleteDataError("OHLCV quality denominator contains no trading sessions")
    metrics: dict[str, Any] = {"version": QUALITY_VERSION, "total_sessions": len(selected)}
    kinds = ["daily"] + (["minute"] if request.frequency in {"1m", "5m", "15m", "30m"} else [])
    for kind in kinds:
        for row in selected.values():
            if not isinstance(row, Mapping) or any(type(row.get(kind + "_" + field)) is not bool for field in ("complete", "accurate")):
                raise DataContractError("OHLCV quality flags are invalid")
            if row[kind + "_accurate"] and not row[kind + "_complete"]:
                raise DataContractError("incomplete OHLCV session cannot be accurate")
            fields = row.get(kind + "_fields")
            if not isinstance(fields, list) or any(not isinstance(field, str) for field in fields):
                raise DataContractError("OHLCV quality error fields are invalid")
            if row[kind + "_accurate"] and fields:
                raise DataContractError("inconsistent OHLCV session cannot be marked accurate")
            if kind == "daily":
                present = row.get("daily_values") is not None
                computed = _daily_fields(_values(row["daily_values"])) if present else []
                accurate = present and not computed
            else:
                clocks = row.get("minute_clocks")
                count = row.get("minute_bar_count")
                expected_clocks = sorted(intraday_close_times(request.frequency, evidence.get("market", "a_share")))
                present = clocks == expected_clocks and type(count) is int and count == len(expected_clocks)
                matched = present and row.get("comparison_daily_values") is not None
                computed = _minute_fields(_values(row["minute_values"]), _values(row["comparison_daily_values"])) if matched else []
                accurate = matched and not computed
            if (row[kind + "_complete"] != present or row[kind + "_accurate"] != accurate or fields != computed):
                raise DataContractError("OHLCV quality flags differ from numeric evidence")
        complete = sum(row[kind + "_complete"] for row in selected.values())
        accurate = sum(row[kind + "_accurate"] for row in selected.values())
        threshold = 99 if kind == "daily" else 95
        detail = {
            "complete_sessions": complete, "accurate_sessions": accurate,
            "completeness": complete / len(selected), "accuracy": accurate / len(selected),
            "minimum_accuracy": threshold / 100,
            "incomplete_dates": [day for day, row in selected.items() if not row[kind + "_complete"]],
            "inaccurate_dates": [day for day, row in selected.items() if not row[kind + "_accurate"]],
        }
        metrics[kind] = detail
    if any(metrics[kind]["complete_sessions"] != len(selected) for kind in kinds):
        raise IncompleteDataError("OHLCV completeness must equal 100%", quality=metrics)
    if any(metrics[kind]["accurate_sessions"] * 100 < len(selected) * (99 if kind == "daily" else 95) for kind in kinds):
        raise DataContractError("OHLCV accuracy is below acceptance threshold", quality=metrics)
    return metrics
