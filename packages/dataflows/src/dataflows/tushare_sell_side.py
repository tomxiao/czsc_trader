"""Tushare sell-side forecast events with conservative availability dates."""

from __future__ import annotations

from bisect import bisect_right
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .errors import DataContractError, EmptyDataError, IncompleteDataError
from .tushare_common import get_tushare_pro


_FIELDS = (
    "ts_code,name,report_date,report_title,report_type,classify,org_name,"
    "author_name,quarter,op_rt,op_pr,tp,np,eps,pe,rd,roe,ev_ebitda,rating,"
    "max_price,min_price,create_time"
)

_PAGE_LIMIT = 3000

_COLUMN_NAMES = {
    "ts_code": "Symbol",
    "name": "CompanyName",
    "report_title": "ReportTitle",
    "report_type": "ReportType",
    "classify": "Classification",
    "org_name": "Institution",
    "author_name": "Authors",
    "quarter": "ForecastPeriod",
    "op_rt": "OperatingRevenueForecast",
    "op_pr": "OperatingProfitForecast",
    "tp": "TotalProfitForecast",
    "np": "NetProfitForecast",
    "eps": "EarningsPerShareForecast",
    "pe": "PriceEarningsRatio",
    "rd": "DividendYieldPercent",
    "roe": "ReturnOnEquityPercent",
    "ev_ebitda": "EnterpriseValueToEbitda",
    "rating": "Rating",
    "max_price": "TargetPriceMax",
    "min_price": "TargetPriceMin",
    "create_time": "VendorCreatedAt",
}

_TEXT_COLUMNS = (
    "Symbol",
    "CompanyName",
    "ReportTitle",
    "ReportType",
    "Classification",
    "Institution",
    "Authors",
    "ForecastPeriod",
    "Rating",
)

_NUMERIC_COLUMNS = (
    "OperatingRevenueForecast",
    "OperatingProfitForecast",
    "TotalProfitForecast",
    "NetProfitForecast",
    "EarningsPerShareForecast",
    "PriceEarningsRatio",
    "DividendYieldPercent",
    "ReturnOnEquityPercent",
    "EnterpriseValueToEbitda",
    "TargetPriceMax",
    "TargetPriceMin",
)

_PRIMARY_KEY = (
    "Date",
    "Symbol",
    "Institution",
    "ForecastPeriod",
    "ReportTitle",
    "Authors",
    "ReportType",
    "Classification",
)


def _client(pro: object | None, env_file: str | Path | None) -> object:
    return pro if pro is not None else get_tushare_pro(env_file)


def _fetch_yearly(client: object, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    frames: list[pd.DataFrame] = []
    for year in range(start.year, end.year + 1):
        chunk_start = max(start, pd.Timestamp(year=year, month=1, day=1))
        chunk_end = min(end, pd.Timestamp(year=year, month=12, day=31))
        offset = 0
        seen_pages: set[bytes] = set()
        while True:
            value = client.report_rc(
                ts_code=symbol,
                start_date=chunk_start.strftime("%Y%m%d"),
                end_date=chunk_end.strftime("%Y%m%d"),
                fields=_FIELDS,
                limit=_PAGE_LIMIT,
                offset=offset,
            )
            frame = pd.DataFrame() if value is None else pd.DataFrame(value)
            if frame.empty:
                break
            signature = pd.util.hash_pandas_object(
                frame.astype("string"), index=False
            ).values.tobytes()
            if signature in seen_pages:
                raise IncompleteDataError(
                    "Tushare sell-side forecast pagination did not advance",
                    symbol=symbol,
                    offset=offset,
                )
            seen_pages.add(signature)
            frames.append(frame)
            if len(frame) < _PAGE_LIMIT:
                break
            offset += _PAGE_LIMIT
    if not frames:
        raise EmptyDataError(f"Tushare returned no sell-side forecasts for {symbol}")
    return pd.concat(frames, ignore_index=True)


def _canonicalize(raw: pd.DataFrame, symbol: str) -> tuple[pd.DataFrame, int]:
    required = {"report_date", *_COLUMN_NAMES}
    missing = sorted(required.difference(raw.columns))
    if missing:
        raise DataContractError(
            "Tushare sell-side forecast response is missing required fields",
            missing_fields=missing,
        )
    try:
        dates = pd.to_datetime(
            raw["report_date"].astype(str), format="%Y%m%d", errors="raise"
        ).dt.normalize()
    except (TypeError, ValueError) as exc:
        raise DataContractError("sell-side forecast report dates are invalid") from exc

    frame = raw[["report_date", *_COLUMN_NAMES]].rename(columns=_COLUMN_NAMES).copy()
    frame.insert(0, "Date", dates)
    frame = frame.drop(columns="report_date")
    for column in _TEXT_COLUMNS:
        frame[column] = frame[column].astype("string").str.strip()
    if frame["Symbol"].isna().any() or not frame["Symbol"].eq(symbol).all():
        observed = sorted(frame["Symbol"].dropna().astype(str).unique())
        raise DataContractError(
            "sell-side forecast response contains another symbol",
            requested_symbol=symbol,
            observed_symbols=observed,
        )
    for column in _NUMERIC_COLUMNS:
        raw_values = frame[column]
        numeric = pd.to_numeric(raw_values, errors="coerce")
        present = raw_values.notna() & raw_values.astype("string").str.strip().ne("")
        invalid = present & numeric.isna()
        if invalid.any():
            raise DataContractError(
                "sell-side forecast response contains invalid numeric values",
                field=column,
                invalid_rows=int(invalid.sum()),
            )
        frame[column] = numeric.astype(float)
    try:
        frame["VendorCreatedAt"] = pd.to_datetime(
            frame["VendorCreatedAt"], errors="raise"
        )
    except (TypeError, ValueError) as exc:
        raise DataContractError("sell-side forecast vendor create times are invalid") from exc
    if frame["VendorCreatedAt"].isna().any():
        raise DataContractError("sell-side forecast vendor create times are missing")

    exact_duplicates = int(frame.duplicated(keep="first").sum())
    frame = frame.drop_duplicates(keep="first")
    frame = frame.sort_values(list(_PRIMARY_KEY), kind="mergesort", na_position="last")
    return frame.reset_index(drop=True), exact_duplicates


def _attach_availability(frame: pd.DataFrame, client: object) -> pd.DataFrame:
    availability_anchor = pd.concat(
        [frame["Date"], frame["VendorCreatedAt"].dt.normalize()], axis=1
    ).max(axis=1)
    calendar_start = availability_anchor.min() + pd.Timedelta(days=1)
    calendar_end = availability_anchor.max() + pd.Timedelta(days=40)
    raw = pd.DataFrame(
        client.trade_cal(
            exchange="SSE",
            start_date=calendar_start.strftime("%Y%m%d"),
            end_date=calendar_end.strftime("%Y%m%d"),
            fields="cal_date,is_open",
        )
    )
    if raw.empty or not {"cal_date", "is_open"}.issubset(raw.columns):
        raise IncompleteDataError("SSE calendar is unavailable for sell-side forecasts")
    try:
        dates = pd.to_datetime(
            raw["cal_date"].astype(str), format="%Y%m%d", errors="raise"
        ).dt.normalize()
        open_flags = pd.to_numeric(raw["is_open"], errors="raise")
    except (TypeError, ValueError) as exc:
        raise DataContractError("SSE calendar contains invalid dates or open flags") from exc
    calendar = pd.DataFrame({"Date": dates, "IsOpen": open_flags}).sort_values("Date")
    if calendar["Date"].duplicated().any() or not calendar["IsOpen"].isin([0, 1]).all():
        raise DataContractError("SSE calendar contains duplicate or invalid sessions")
    expected = pd.date_range(calendar_start, calendar_end, freq="D")
    if not pd.DatetimeIndex(calendar["Date"]).equals(expected):
        raise IncompleteDataError("SSE calendar does not cover sell-side forecast dates")
    open_days = calendar.loc[calendar["IsOpen"].eq(1), "Date"].tolist()
    available = []
    for anchor in availability_anchor:
        index = bisect_right(open_days, anchor)
        if index == len(open_days):
            raise IncompleteDataError("no later SSE session for sell-side forecast")
        available.append(open_days[index])
    result = frame.copy()
    result.insert(1, "AvailableDate", pd.to_datetime(available))
    return result


def fetch_sell_side_forecast(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Publish current Tushare report_rc rows at the next SSE session boundary."""

    client = _client(pro, env_file)
    frame, exact_duplicates = _canonicalize(
        _fetch_yearly(client, symbol, start_date, end_date), symbol
    )
    frame = _attach_availability(frame, client)
    numeric_values = frame[list(_NUMERIC_COLUMNS)].to_numpy(dtype=float, na_value=np.nan)
    if np.isinf(numeric_values).any():
        raise DataContractError("sell-side forecast response contains infinite numeric values")
    return frame, {
        "vendor": "tushare",
        "vendor_interface": "report_rc",
        "vendor_symbol": symbol,
        "frequency": "report_event",
        "primary_key": list(_PRIMARY_KEY),
        "source_time_field": "Date",
        "availability_time_field": "AvailableDate",
        "source_calendar": "SSE",
        "available_at": "first SSE open day strictly after report date and vendor create date",
        "source_time_precision": "date_only",
        "vendor_create_time_timezone_assumption": "Asia/Shanghai",
        "point_in_time_mode": "CURRENT_VENDOR_SNAPSHOT",
        "historical_revision_identity": "unavailable_from_vendor",
        "query_partition": "calendar_year_with_3000_row_pagination",
        "exact_duplicates_removed": exact_duplicates,
        "field_units": {
            "OperatingRevenueForecast": "CNY_10000",
            "OperatingProfitForecast": "CNY_10000",
            "TotalProfitForecast": "CNY_10000",
            "NetProfitForecast": "CNY_10000",
            "EarningsPerShareForecast": "CNY_PER_SHARE",
            "PriceEarningsRatio": "RATIO",
            "DividendYieldPercent": "PERCENT",
            "ReturnOnEquityPercent": "PERCENT",
            "EnterpriseValueToEbitda": "RATIO",
            "TargetPriceMax": "CNY_PER_SHARE",
            "TargetPriceMin": "CNY_PER_SHARE",
        },
    }
