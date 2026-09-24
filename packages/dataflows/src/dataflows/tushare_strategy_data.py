"""Canonical Tushare inputs required by the active frozen strategies."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from .errors import DataContractError, EmptyDataError, IncompleteDataError
from .tushare_common import get_tushare_pro


def _client(pro: object | None, env_file: str | Path | None) -> object:
    return pro if pro is not None else get_tushare_pro(env_file)


def _canonicalize(
    value: object,
    *,
    dataset: str,
    date_column: str,
    columns: dict[str, str],
    numeric_columns: tuple[str, ...],
) -> pd.DataFrame:
    frame = pd.DataFrame() if value is None else pd.DataFrame(value).copy()
    required = {date_column, *columns}
    missing = sorted(required.difference(frame.columns))
    if frame.empty:
        raise EmptyDataError(f"Tushare returned no data for {dataset}")
    if missing:
        raise DataContractError(
            f"Tushare {dataset} response is missing required fields",
            missing_fields=missing,
        )
    output = frame[[date_column, *columns]].rename(columns={date_column: "Date", **columns})
    output["Date"] = pd.to_datetime(output["Date"].astype(str), errors="raise").dt.normalize()
    for column in numeric_columns:
        output[column] = pd.to_numeric(output[column], errors="raise")
    return output.sort_values(
        ["Date", *[item for item in output.columns if item != "Date"]]
    ).reset_index(drop=True)


def _fetch_yearly(
    fetch: Callable[[str, str], object],
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Fetch annual slices so vendor row limits cannot truncate long histories."""

    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    frames: list[pd.DataFrame] = []
    for year in range(start.year, end.year + 1):
        chunk_start = max(start, pd.Timestamp(year=year, month=1, day=1))
        chunk_end = min(end, pd.Timestamp(year=year, month=12, day=31))
        value = fetch(chunk_start.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d"))
        frame = pd.DataFrame() if value is None else pd.DataFrame(value)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _canonicalize_monthly(
    value: object,
    *,
    dataset: str,
    columns: dict[str, str],
    numeric_columns: tuple[str, ...],
) -> pd.DataFrame:
    frame = pd.DataFrame() if value is None else pd.DataFrame(value).copy()
    required = {"month", *columns}
    missing = sorted(required.difference(frame.columns))
    if frame.empty:
        raise EmptyDataError(f"Tushare returned no data for {dataset}")
    if missing:
        raise DataContractError(
            f"Tushare {dataset} response is missing required fields",
            missing_fields=missing,
        )
    output = frame[["month", *columns]].rename(columns=columns)
    output["Date"] = pd.PeriodIndex(
        output.pop("month").astype(str), freq="M"
    ).to_timestamp(how="end").normalize()
    for column in numeric_columns:
        output[column] = pd.to_numeric(output[column], errors="raise")
    return output[["Date", *columns.values()]].sort_values("Date").reset_index(drop=True)


def fetch_shibor_daily(
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    client = _client(pro, env_file)
    dataframe = _canonicalize(
        _fetch_yearly(
            lambda start, end: client.shibor(
                start_date=start,
                end_date=end,
            ),
            start_date,
            end_date,
        ),
        dataset="SHIBOR daily",
        date_column="date",
        columns={"on": "OvernightRate"},
        numeric_columns=("OvernightRate",),
    )
    return dataframe, {
        "vendor": "tushare",
        "frequency": "daily",
        "primary_key": ["Date"],
        "maximum_start_lag_days": 10,
    }


def fetch_us_real_yield_daily(
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    client = _client(pro, env_file)
    dataframe = _canonicalize(
        _fetch_yearly(
            lambda start, end: client.us_trycr(
                start_date=start,
                end_date=end,
                fields="date,y5,y7,y10,y20,y30",
            ),
            start_date,
            end_date,
        ),
        dataset="US real Treasury yield daily",
        date_column="date",
        columns={
            "y5": "RealYield5YPercent",
            "y7": "RealYield7YPercent",
            "y10": "RealYield10YPercent",
            "y20": "RealYield20YPercent",
            "y30": "RealYield30YPercent",
        },
        numeric_columns=(
            "RealYield5YPercent",
            "RealYield7YPercent",
            "RealYield10YPercent",
            "RealYield20YPercent",
            "RealYield30YPercent",
        ),
    )
    return dataframe, {
        "vendor": "tushare",
        "frequency": "daily",
        "primary_key": ["Date"],
        "unit": "percent",
        "availability_rule": "source date no later than prior China trading day",
    }


def fetch_us_nominal_yield_daily(
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dataframe = _canonicalize(
        _fetch_yearly(
            lambda start, end: _client(pro, env_file).us_tycr(
                start_date=start, end_date=end, fields="date,y10"
            ),
            start_date,
            end_date,
        ),
        dataset="US nominal Treasury yield daily",
        date_column="date",
        columns={"y10": "NominalYield10YPercent"},
        numeric_columns=("NominalYield10YPercent",),
    )
    return dataframe, {
        "vendor": "tushare",
        "vendor_interface": "us_tycr",
        "frequency": "daily",
        "primary_key": ["Date"],
        "unit": "percent",
        "availability_rule": "source date strictly earlier than China decision session",
        "maximum_start_lag_days": 10,
    }


def fetch_fxcm_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    client = _client(pro, env_file)
    dataframe = _canonicalize(
        _fetch_yearly(
            lambda start, end: client.fx_daily(
                ts_code=symbol,
                start_date=start,
                end_date=end,
                fields=(
                    "ts_code,trade_date,bid_open,bid_close,bid_high,bid_low,"
                    "ask_open,ask_close,ask_high,ask_low,tick_qty"
                ),
            ),
            start_date,
            end_date,
        ),
        dataset=f"FXCM daily {symbol}",
        date_column="trade_date",
        columns={
            "bid_open": "BidOpen",
            "bid_high": "BidHigh",
            "bid_low": "BidLow",
            "bid_close": "BidClose",
            "ask_open": "AskOpen",
            "ask_high": "AskHigh",
            "ask_low": "AskLow",
            "ask_close": "AskClose",
            "tick_qty": "TickQuantity",
        },
        numeric_columns=(
            "BidOpen",
            "BidHigh",
            "BidLow",
            "BidClose",
            "AskOpen",
            "AskHigh",
            "AskLow",
            "AskClose",
            "TickQuantity",
        ),
    )
    return dataframe, {
        "vendor": "tushare",
        "vendor_symbol": symbol,
        "frequency": "daily",
        "primary_key": ["Date"],
        "vendor_timezone": "GMT",
        "availability_rule": "GMT source date must be strictly earlier than China decision session",
        "maximum_start_lag_days": 10,
    }


def fetch_usdcnh_daily(
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Retain the stable USDCNH dataset over the generic FXCM adapter."""

    dataframe, metadata = fetch_fxcm_daily(
        "USDCNH.FXCM",
        start_date,
        end_date,
        env_file=env_file,
        pro=pro,
    )
    metadata = dict(metadata)
    metadata["availability_rule"] = "use at least one completed China trading day lag"
    metadata.pop("maximum_start_lag_days", None)
    return dataframe, metadata


def fetch_sge_gold_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    client = _client(pro, env_file)
    dataframe = _canonicalize(
        _fetch_yearly(
            lambda start, end: client.sge_daily(
                ts_code=symbol,
                start_date=start,
                end_date=end,
                fields=(
                    "ts_code,trade_date,close,open,high,low,price_avg,change,"
                    "pct_change,vol,amount"
                ),
            ),
            start_date,
            end_date,
        ),
        dataset=f"SGE gold daily {symbol}",
        date_column="trade_date",
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "price_avg": "AveragePrice",
            "change": "Change",
            "pct_change": "PercentChange",
            "vol": "Volume",
            "amount": "Amount",
        },
        numeric_columns=(
            "Open",
            "High",
            "Low",
            "Close",
            "AveragePrice",
            "Change",
            "PercentChange",
            "Volume",
            "Amount",
        ),
    )
    dataframe["PercentChange"] /= 100.0
    return dataframe, {
        "vendor": "tushare",
        "vendor_symbol": symbol,
        "frequency": "daily",
        "primary_key": ["Date"],
        "percent_change_unit": "decimal_return",
        "session_rule": "prior night session plus current day session through 15:30",
        "availability_rule": "use prior trading day until publication time is governed",
        "price_validation_tolerance": "0.011 CNY per gram for one-tick vendor rounding",
    }


def fetch_domestic_index_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dataframe = _canonicalize(
        _client(pro, env_file).index_daily(
            ts_code=symbol,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            fields=(
                "ts_code,trade_date,close,open,high,low,pre_close,change,"
                "pct_chg,vol,amount"
            ),
        ),
        dataset=f"domestic index daily {symbol}",
        date_column="trade_date",
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "pre_close": "PreviousClose",
            "change": "Change",
            "pct_chg": "PercentChange",
            "vol": "Volume",
            "amount": "Amount",
        },
        numeric_columns=(
            "Open",
            "High",
            "Low",
            "Close",
            "PreviousClose",
            "Change",
            "PercentChange",
            "Volume",
            "Amount",
        ),
    )
    dataframe["PercentChange"] /= 100.0
    return dataframe, {
        "vendor": "tushare",
        "vendor_symbol": symbol,
        "frequency": "daily",
        "primary_key": ["Date"],
        "percent_change_unit": "decimal_return",
        "availability_rule": "current session after market close",
    }


def fetch_cn_cpi_monthly(
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    start_month = pd.Timestamp(start_date).strftime("%Y%m")
    end_month = pd.Timestamp(end_date).strftime("%Y%m")
    dataframe = _canonicalize_monthly(
        _client(pro, env_file).cn_cpi(start_m=start_month, end_m=end_month),
        dataset="China CPI monthly",
        columns={
            "nt_val": "NationalIndex",
            "nt_yoy": "NationalYoYPercent",
            "nt_mom": "NationalMoMPercent",
            "nt_accu": "NationalAccumulatedPercent",
        },
        numeric_columns=(
            "NationalIndex",
            "NationalYoYPercent",
            "NationalMoMPercent",
            "NationalAccumulatedPercent",
        ),
    )
    return dataframe, _monthly_metadata("cn_cpi")


def fetch_us_cpi_release(
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Publish US unadjusted CPI YoY events after their first SSE session.

    Tushare's CPI calendar clock is interpreted as Asia/Shanghai only when it
    converts to the BLS 08:30 America/New_York release clock. Unexpected source
    clocks fail closed instead of silently shifting an event across sessions.
    """

    client = _client(pro, env_file)
    raw = _fetch_yearly(
        lambda start, end: client.eco_cal(
            start_date=start,
            end_date=end,
            country="美国",
            event="*未季调CPI年率*",
            fields="date,time,country,event,value",
        ),
        start_date,
        end_date,
    )
    required = {"date", "time", "event", "value"}
    if raw.empty:
        raise EmptyDataError("Tushare returned no US CPI release events")
    missing = sorted(required.difference(raw.columns))
    if missing:
        raise DataContractError("US CPI release fields are missing", missing_fields=missing)
    events = raw.loc[
        raw["event"].astype(str).str.startswith("美国未季调CPI年率")
    ].copy()
    if events.empty:
        raise EmptyDataError("Tushare returned no matching US CPI release events")
    times = events["time"].astype(str).str.strip()
    if not times.str.fullmatch(r"\d{2}:\d{2}").all():
        raise DataContractError("US CPI release clock is invalid")
    try:
        release_at = pd.to_datetime(
            events["date"].astype(str) + " " + times,
            format="%Y%m%d %H:%M",
            errors="raise",
        ).dt.tz_localize("Asia/Shanghai")
        yoy = pd.to_numeric(
            events["value"].astype(str).str.strip().str.removesuffix("%"),
            errors="raise",
        )
    except (TypeError, ValueError) as exc:
        raise DataContractError("US CPI release date or actual value is invalid") from exc
    eastern = release_at.dt.tz_convert("America/New_York")
    if not (
        eastern.dt.strftime("%H:%M").eq("08:30")
        & eastern.dt.date.eq(release_at.dt.date)
    ).all():
        raise DataContractError("US CPI calendar clock conflicts with BLS Eastern release")

    frame = pd.DataFrame(
        {
            "Date": release_at.dt.tz_localize(None).dt.normalize(),
            "ReleaseAt": release_at,
            "YoYPercent": yoy,
        }
    ).sort_values("Date").reset_index(drop=True)
    if frame["Date"].duplicated().any():
        raise DataContractError("US CPI has duplicate release dates")
    if frame["Date"].diff().dt.days.gt(45).any():
        raise IncompleteDataError("US CPI release history has a gap over 45 days")

    calendar_start = frame["Date"].min()
    calendar_end = frame["Date"].max() + pd.Timedelta(days=14)
    calendar_raw = pd.DataFrame(
        client.trade_cal(
            exchange="SSE",
            start_date=calendar_start.strftime("%Y%m%d"),
            end_date=calendar_end.strftime("%Y%m%d"),
            fields="cal_date,is_open",
        )
    )
    if calendar_raw.empty or not {"cal_date", "is_open"}.issubset(calendar_raw.columns):
        raise IncompleteDataError("SSE calendar is unavailable for US CPI availability")
    try:
        calendar_dates = pd.to_datetime(
            calendar_raw["cal_date"].astype(str), format="%Y%m%d", errors="raise"
        ).dt.normalize()
        open_flags = pd.to_numeric(calendar_raw["is_open"], errors="raise")
    except (TypeError, ValueError) as exc:
        raise DataContractError("SSE calendar contains invalid dates or open flags") from exc
    calendar = pd.DataFrame({"Date": calendar_dates, "IsOpen": open_flags})
    if calendar["Date"].duplicated().any() or not calendar["IsOpen"].isin([0, 1]).all():
        raise DataContractError("SSE calendar contains duplicate or invalid sessions")
    expected_days = pd.date_range(calendar_start, calendar_end, freq="D")
    if not pd.DatetimeIndex(calendar["Date"].sort_values()).equals(expected_days):
        raise IncompleteDataError("SSE calendar does not cover US CPI release dates")
    open_days = sorted(calendar.loc[calendar["IsOpen"] == 1, "Date"])
    available = []
    for release_day in frame["Date"]:
        next_index = bisect_right(open_days, release_day)
        if next_index == len(open_days):
            raise IncompleteDataError("no later SSE session for US CPI release")
        available.append(open_days[next_index])
    frame.insert(2, "AvailableDate", pd.to_datetime(available))
    return frame, {
        "vendor": "tushare",
        "vendor_interface": "eco_cal",
        "frequency": "monthly_event",
        "primary_key": ["Date"],
        "source_time_field": "ReleaseAt",
        "source_calendar": "US_BLS_EASTERN",
        "source_timezone": "Asia/Shanghai",
        "official_release_timezone": "America/New_York",
        "available_at": "first SSE open day strictly after Shanghai release date",
        "maximum_start_lag_days": 45,
    }


def _fetch_us_calendar_release(
    start_date: str,
    end_date: str,
    *,
    query: str,
    event_prefix: str,
    value_column: str,
    unit_suffix: str,
    maximum_gap_days: int,
    env_file: str | Path | None,
    pro: object | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Publish monthly US events at a conservative next-SSE-session boundary.

    Tushare does not document a verified timezone for every eco_cal event, and
    one historical budget clock is unknown. The source date is therefore the
    precision of this contract; no event can become usable on that date.
    """

    client = _client(pro, env_file)
    raw = _fetch_yearly(
        lambda start, end: client.eco_cal(
            start_date=start,
            end_date=end,
            country="美国",
            event=query,
            fields="date,time,country,event,value",
        ),
        start_date,
        end_date,
    )
    required = {"date", "time", "event", "value"}
    if raw.empty:
        raise EmptyDataError(f"Tushare returned no {value_column} release events")
    missing = sorted(required.difference(raw.columns))
    if missing:
        raise DataContractError("US calendar release fields are missing", missing_fields=missing)
    events = raw.loc[raw["event"].astype(str).str.startswith(event_prefix)].copy()
    if events.empty:
        raise EmptyDataError(f"Tushare returned no matching {value_column} events")
    values = events["value"].astype(str).str.strip().str.replace(",", "", regex=False)
    pattern = r"[+-]?\d+(?:\.\d+)?" + unit_suffix
    if not values.str.fullmatch(pattern).all():
        raise DataContractError(f"{value_column} actual value or unit is invalid")
    clocks = events["time"].astype(str).str.strip()
    valid_clocks = clocks.str.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d")
    if value_column == "PmiIndex" and not valid_clocks.all():
        raise DataContractError("US ISM PMI source clock is invalid")
    if value_column == "PmiIndex" and clocks.lt("15:00").any():
        raise DataContractError("US ISM PMI source clock precedes China close")
    try:
        dates = pd.to_datetime(events["date"].astype(str), format="%Y%m%d", errors="raise")
        numeric = pd.to_numeric(values.str.removesuffix(unit_suffix), errors="raise")
    except (TypeError, ValueError) as exc:
        raise DataContractError(f"{value_column} release date or value is invalid") from exc
    frame = pd.DataFrame({
        "Date": dates.dt.normalize(),
        value_column: numeric,
        "SourceClock": clocks,
        "SourceEvent": events["event"].astype(str),
    }).sort_values("Date").reset_index(drop=True)
    if frame["Date"].duplicated().any():
        raise DataContractError(f"{value_column} has duplicate release dates")
    if frame["Date"].diff().dt.days.gt(maximum_gap_days).any():
        raise IncompleteDataError(f"{value_column} release history has a gap")

    calendar_start = frame["Date"].min()
    calendar_end = frame["Date"].max() + pd.Timedelta(days=14)
    calendar_raw = pd.DataFrame(client.trade_cal(
        exchange="SSE",
        start_date=calendar_start.strftime("%Y%m%d"),
        end_date=calendar_end.strftime("%Y%m%d"),
        fields="cal_date,is_open",
    ))
    if calendar_raw.empty or not {"cal_date", "is_open"}.issubset(calendar_raw.columns):
        raise IncompleteDataError("SSE calendar is unavailable for US release availability")
    try:
        calendar_dates = pd.to_datetime(
            calendar_raw["cal_date"].astype(str), format="%Y%m%d", errors="raise"
        ).dt.normalize()
        open_flags = pd.to_numeric(calendar_raw["is_open"], errors="raise")
    except (TypeError, ValueError) as exc:
        raise DataContractError("SSE calendar contains invalid dates or open flags") from exc
    calendar = pd.DataFrame({"Date": calendar_dates, "IsOpen": open_flags})
    if calendar["Date"].duplicated().any() or not calendar["IsOpen"].isin([0, 1]).all():
        raise DataContractError("SSE calendar contains duplicate or invalid sessions")
    expected_days = pd.date_range(calendar_start, calendar_end, freq="D")
    if not pd.DatetimeIndex(calendar["Date"].sort_values()).equals(expected_days):
        raise IncompleteDataError("SSE calendar does not cover US release dates")
    open_days = sorted(calendar.loc[calendar["IsOpen"] == 1, "Date"])
    available = []
    for release_day in frame["Date"]:
        next_index = bisect_right(open_days, release_day)
        if next_index == len(open_days):
            raise IncompleteDataError("no later SSE session for US release")
        available.append(open_days[next_index])
    frame.insert(1, "AvailableDate", pd.to_datetime(available))
    return frame, {
        "vendor": "tushare",
        "vendor_interface": "eco_cal",
        "frequency": "monthly_event",
        "primary_key": ["Date"],
        "source_time_field": "Date",
        "source_calendar": "TUSHARE_ECO_CAL_DATE",
        "source_timezone_assumption": "Asia/Shanghai",
        "source_time_precision": "date_only",
        "unverified_source_clock_rows": int((~valid_clocks).sum()),
        "available_at": "first SSE open day strictly after source calendar date",
        "maximum_start_lag_days": maximum_gap_days,
    }


def fetch_us_ism_pmi_release(
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    return _fetch_us_calendar_release(
        start_date, end_date,
        query="*ISM制造业PMI*", event_prefix="美国ISM制造业PMI",
        value_column="PmiIndex", unit_suffix="", maximum_gap_days=40,
        env_file=env_file, pro=pro,
    )


def fetch_us_federal_budget_release(
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    return _fetch_us_calendar_release(
        start_date, end_date,
        query="*政府预算*", event_prefix="美国政府预算(美元)",
        value_column="BudgetBalanceBillionUSD", unit_suffix="B", maximum_gap_days=70,
        env_file=env_file, pro=pro,
    )


def fetch_cn_ppi_monthly(
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    start_month = pd.Timestamp(start_date).strftime("%Y%m")
    end_month = pd.Timestamp(end_date).strftime("%Y%m")
    dataframe = _canonicalize_monthly(
        _client(pro, env_file).cn_ppi(start_m=start_month, end_m=end_month),
        dataset="China PPI monthly",
        columns={
            "ppi_yoy": "ProducerYoYPercent",
            "ppi_mom": "ProducerMoMPercent",
            "ppi_accu": "ProducerAccumulatedPercent",
        },
        numeric_columns=(
            "ProducerYoYPercent",
            "ProducerMoMPercent",
            "ProducerAccumulatedPercent",
        ),
    )
    return dataframe, _monthly_metadata("cn_ppi")


def fetch_cn_money_monthly(
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    start_month = pd.Timestamp(start_date).strftime("%Y%m")
    end_month = pd.Timestamp(end_date).strftime("%Y%m")
    dataframe = _canonicalize_monthly(
        _client(pro, env_file).cn_m(start_m=start_month, end_m=end_month),
        dataset="China money supply monthly",
        columns={
            "m0": "M0",
            "m0_yoy": "M0YoYPercent",
            "m0_mom": "M0MoMPercent",
            "m1": "M1",
            "m1_yoy": "M1YoYPercent",
            "m1_mom": "M1MoMPercent",
            "m2": "M2",
            "m2_yoy": "M2YoYPercent",
            "m2_mom": "M2MoMPercent",
        },
        numeric_columns=(
            "M0",
            "M0YoYPercent",
            "M0MoMPercent",
            "M1",
            "M1YoYPercent",
            "M1MoMPercent",
            "M2",
            "M2YoYPercent",
            "M2MoMPercent",
        ),
    )
    return dataframe, _monthly_metadata("cn_m")


def _monthly_metadata(vendor_interface: str) -> dict[str, Any]:
    return {
        "vendor": "tushare",
        "vendor_interface": vendor_interface,
        "frequency": "monthly",
        "primary_key": ["Date"],
        "reference_date_rule": "calendar month end",
        "availability_rule": "reference month M usable from first China session of M+2",
    }


def fetch_index_daily_basic(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dataframe = _canonicalize(
        _client(pro, env_file).index_dailybasic(
            ts_code=symbol,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            fields="ts_code,trade_date,turnover_rate_f",
        ),
        dataset=f"index daily basic {symbol}",
        date_column="trade_date",
        columns={"turnover_rate_f": "TurnoverRateFreeFloat"},
        numeric_columns=("TurnoverRateFreeFloat",),
    )
    return dataframe, {
        "vendor": "tushare",
        "vendor_symbol": symbol,
        "frequency": "daily",
        "primary_key": ["Date"],
    }


def fetch_etf_share_size(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dataframe = _canonicalize(
        _client(pro, env_file).etf_share_size(
            ts_code=symbol,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            fields="trade_date,ts_code,total_share",
        ),
        dataset=f"ETF share size {symbol}",
        date_column="trade_date",
        columns={"total_share": "TotalShare"},
        numeric_columns=("TotalShare",),
    )
    return dataframe, {
        "vendor": "tushare",
        "vendor_symbol": symbol,
        "frequency": "daily",
        "primary_key": ["Date"],
        "availability_rule": "T+1 08:30 Asia/Shanghai",
    }


def fetch_global_index_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dataframe = _canonicalize(
        _fetch_yearly(
            lambda start, end: _client(pro, env_file).index_global(
                ts_code=symbol,
                start_date=start,
                end_date=end,
            ),
            start_date,
            end_date,
        ),
        dataset=f"global index daily {symbol}",
        date_column="trade_date",
        columns={"pct_chg": "PercentChange"},
        numeric_columns=("PercentChange",),
    )
    dataframe["PercentChange"] /= 100.0
    return dataframe, {
        "vendor": "tushare",
        "vendor_symbol": symbol,
        "frequency": "daily",
        "primary_key": ["Date"],
        "unit": "decimal_return",
        "availability_rule": "US close date must be strictly earlier than China decision session",
        "maximum_start_lag_days": 10,
    }


def fetch_vix_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if symbol.upper() != "VIX":
        raise DataContractError("VIX daily dataset only supports symbol VIX", symbol=symbol)
    client = _client(pro, env_file)
    dataframe = _canonicalize(
        _fetch_yearly(
            lambda start, end: client.vix_index(
                start_date=start,
                end_date=end,
                fields="trade_date,open,high,low,close,pct_change",
            ),
            start_date,
            end_date,
        ),
        dataset="VIX daily",
        date_column="trade_date",
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "pct_change": "PercentChange",
        },
        numeric_columns=(
            "Open",
            "High",
            "Low",
            "Close",
            "PercentChange",
        ),
    )
    dataframe["PercentChange"] /= 100.0
    return dataframe, {
        "vendor": "tushare",
        "vendor_symbol": "VIX",
        "frequency": "daily",
        "primary_key": ["Date"],
        "percent_change_unit": "decimal_return",
        "availability_rule": "US close date must be strictly earlier than China decision session",
        "maximum_start_lag_days": 10,
    }


def fetch_index_constituent_weight(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dataframe = _canonicalize(
        _client(pro, env_file).index_weight(
            index_code=symbol,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            fields="index_code,con_code,trade_date,weight",
        ),
        dataset=f"index constituent weight {symbol}",
        date_column="trade_date",
        columns={"con_code": "ConstituentSymbol", "weight": "Weight"},
        numeric_columns=("Weight",),
    )
    return dataframe, {
        "vendor": "tushare",
        "vendor_symbol": symbol,
        "frequency": "snapshot",
        "primary_key": ["Date", "ConstituentSymbol"],
    }


def fetch_stock_moneyflow(
    start_date: str,
    end_date: str,
    *,
    symbol: str | None = None,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if symbol is None and pd.Timestamp(start_date) != pd.Timestamp(end_date):
        raise DataContractError("all-market stock moneyflow requests must cover exactly one day")
    parameters = {
        "fields": "ts_code,trade_date,net_mf_amount",
        "start_date": start_date.replace("-", ""),
        "end_date": end_date.replace("-", ""),
    }
    if symbol is not None:
        parameters["ts_code"] = symbol
    dataframe = _canonicalize(
        _client(pro, env_file).moneyflow(**parameters),
        dataset=f"stock moneyflow {symbol or 'all-market'}",
        date_column="trade_date",
        columns={"ts_code": "Symbol", "net_mf_amount": "NetMoneyflowAmount"},
        numeric_columns=("NetMoneyflowAmount",),
    )
    return dataframe, {
        "vendor": "tushare",
        "vendor_symbol": symbol,
        "frequency": "daily",
        "primary_key": ["Date", "Symbol"],
    }


def fetch_stock_moneyflow_sessions(
    trading_dates: tuple[str, ...],
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch all-market moneyflow for explicit trading sessions.

    Tushare exposes the all-market snapshot one session at a time.  Keeping the
    session list explicit prevents weekend/holiday requests and makes the
    publication boundary auditable.
    """

    if not trading_dates:
        raise DataContractError("stock moneyflow trading_dates must not be empty")
    client = _client(pro, env_file)
    frames: list[pd.DataFrame] = []
    for value in trading_dates:
        session = pd.Timestamp(value).strftime("%Y%m%d")
        frame = _canonicalize(
            client.moneyflow(
                trade_date=session,
                fields="ts_code,trade_date,net_mf_amount",
            ),
            dataset=f"all-market stock moneyflow {session}",
            date_column="trade_date",
            columns={"ts_code": "Symbol", "net_mf_amount": "NetMoneyflowAmount"},
            numeric_columns=("NetMoneyflowAmount",),
        )
        frames.append(frame)
    dataframe = (
        pd.concat(frames, ignore_index=True).sort_values(["Date", "Symbol"]).reset_index(drop=True)
    )
    return dataframe, {
        "vendor": "tushare",
        "frequency": "daily",
        "primary_key": ["Date", "Symbol"],
        "requested_trading_dates": list(trading_dates),
    }


def fetch_trading_calendar(
    exchange: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dataframe = _canonicalize(
        _client(pro, env_file).trade_cal(
            exchange=exchange,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            fields="exchange,cal_date,is_open,pretrade_date",
        ),
        dataset=f"trading calendar {exchange}",
        date_column="cal_date",
        columns={"is_open": "IsOpen", "pretrade_date": "PreviousTradingDate"},
        numeric_columns=("IsOpen",),
    )
    dataframe["PreviousTradingDate"] = pd.to_datetime(
        dataframe["PreviousTradingDate"].astype(str), errors="coerce"
    ).dt.normalize()
    return dataframe, {
        "vendor": "tushare",
        "exchange": exchange,
        "frequency": "daily",
        "primary_key": ["Date"],
    }
