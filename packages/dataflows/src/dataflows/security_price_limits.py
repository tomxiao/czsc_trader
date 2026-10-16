"""Unadjusted exchange-session price boundaries for historical execution."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd

from .bar_utils import infer_asset_type
from .contract import DataRequest
from .errors import DataContractError, EmptyDataError, IncompleteDataError
from .history_repair import frame_content_sha256
from .ohlcv_quality import verify_daily_sessions
from .tushare_common import get_tushare_pro

_AVAILABILITY = "same-session pre-open source schedule; historical publication unverified"


def _identity(symbol: str | None) -> tuple[str, str, str]:
    # BSE calendars and non-stock/non-ETF instruments need their own evidence.
    if symbol is None or re.fullmatch(r"\d{6}\.(SH|SZ)", symbol) is None:
        raise DataContractError("security price limits support SH/SZ stock and ETF symbols only")
    asset = "etf" if infer_asset_type(symbol) == "fund" else "stock"
    return asset, "etf_limit" if asset == "etf" else "stk_limit", "SSE" if symbol.endswith(".SH") else "SZSE"


def validate_security_price_limits(
    frame: pd.DataFrame, request: DataRequest, metadata: Mapping[str, Any],
) -> None:
    """Validate source identity, values and every applicable exchange session."""
    asset, api, exchange = _identity(request.symbol)
    if request.frequency != "daily" or set(frame.columns) != {"Date", "UpLimit", "DownLimit"}:
        raise DataContractError("security price limits require daily Date/UpLimit/DownLimit")
    expected_metadata = {
        "vendor_symbol": request.symbol, "vendor_interface": api,
        "asset_type": asset, "adjustment": "none", "frequency": "daily",
        "source_calendar": exchange, "available_at": _AVAILABILITY,
        "source_publication_timestamp_verified": False,
        "historical_revision_history_verified": False,
    }
    if any(metadata.get(key) != value for key, value in expected_metadata.items()):
        raise DataContractError("security price-limit lineage contract differs")
    dates = pd.to_datetime(frame.Date, errors="coerce")
    values = frame[["UpLimit", "DownLimit"]].apply(pd.to_numeric, errors="coerce")
    if (dates.isna().any() or dates.duplicated().any()
            or dates.dt.normalize().ne(dates).any()
            or not np.isfinite(values.to_numpy(dtype=float)).all()
            or values.le(0).any().any() or values.UpLimit.le(values.DownLimit).any()):
        raise DataContractError("invalid, duplicate or unlimited security price boundaries")
    coverage = metadata.get("daily_session_coverage")
    if not isinstance(coverage, Mapping):
        raise DataContractError("security price limits require exchange-calendar evidence")
    try:
        calendar = pd.DataFrame(coverage["calendar"])
        calendar_dates = pd.to_datetime(calendar.Date, errors="coerce")
        flags = pd.to_numeric(calendar.is_open, errors="coerce")
        listed = pd.Timestamp(coverage["listing_date"])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise DataContractError("security price-limit calendar evidence is invalid") from exc
    if (coverage.get("exchange") != exchange
            or coverage.get("source") != "trade_cal"
            or coverage.get("listing_source") != ("fund_basic" if asset == "etf" else "stock_basic")
            or pd.isna(listed) or calendar_dates.isna().any()
            or not flags.isin([0, 1]).all()
            or not pd.DatetimeIndex(calendar_dates).equals(pd.date_range(request.start, request.end))
            or coverage.get("calendar_sha256") != frame_content_sha256(calendar)):
        raise DataContractError("security price-limit calendar does not prove the request window")
    expected = set(calendar_dates[flags.eq(1) & calendar_dates.ge(listed)].dt.strftime("%Y-%m-%d"))
    suspended = set(coverage.get("suspended_dates", []))
    if suspended != {row.get("date") for row in coverage.get("suspension_evidence", []) if row.get("status") == "SUSPENDED" and row.get("source")}:
        raise DataContractError("price limits lack suspension evidence")
    expected -= suspended
    actual = set(dates.dt.strftime("%Y-%m-%d"))
    actual -= suspended
    if actual.difference(expected):
        raise DataContractError("security price limits contain inapplicable trading dates")
    if expected.difference(actual):
        raise IncompleteDataError("security price limits omit exchange sessions",
                                  missing_dates=sorted(expected.difference(actual)))
    if coverage.get("expected_dates") != sorted(expected) or coverage.get("verified_sessions") != len(expected):
        raise DataContractError("security price-limit session evidence differs")


def fetch_security_price_limits(
    request: DataRequest, *, env_file: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    asset, api, exchange = _identity(request.symbol)
    if request.frequency != "daily":
        raise DataContractError("security price limits require daily frequency")
    pro = get_tushare_pro(env_file)
    pieces = []
    # Deterministic yearly requests stay below both documented per-call row caps.
    first, last = pd.Timestamp(request.start), pd.Timestamp(request.end)
    for year in range(first.year, last.year + 1):
        a, b = max(first, pd.Timestamp(year, 1, 1)), min(last, pd.Timestamp(year, 12, 31))
        piece = getattr(pro, api)(ts_code=request.symbol, start_date=a.strftime("%Y%m%d"),
                                 end_date=b.strftime("%Y%m%d"),
                                 fields="ts_code,trade_date,up_limit,down_limit,asset_type,exchange")
        if piece is None or piece.empty:
            continue
        required = {"ts_code", "trade_date", "up_limit", "down_limit", "asset_type", "exchange"}
        if not required.issubset(piece.columns):
            raise DataContractError("security price-limit source fields are missing")
        if (not piece.ts_code.eq(request.symbol).all()
                or not piece.asset_type.eq("ETF" if asset == "etf" else "STK").all()
                or not piece.exchange.eq(exchange).all()):
            raise DataContractError("security price-limit source instrument differs")
        pieces.append(piece)
    if not pieces:
        raise EmptyDataError("security price-limit source returned no applicable boundaries")
    source = pd.concat(pieces, ignore_index=True)
    dates = pd.to_datetime(source.trade_date.astype(str), format="%Y%m%d", errors="coerce")
    frame = pd.DataFrame({"Date": dates.dt.strftime("%Y-%m-%d"),
                          "UpLimit": pd.to_numeric(source.up_limit, errors="coerce"),
                          "DownLimit": pd.to_numeric(source.down_limit, errors="coerce")})
    frame = frame.sort_values("Date").reset_index(drop=True)
    coverage = verify_daily_sessions(pro, request.symbol, frame, start=request.start,
                                     end=request.end, asset_type=asset)
    metadata = {
        "vendor": "tushare", "vendor_symbol": request.symbol, "vendor_interface": api,
        "asset_type": asset, "adjustment": "none", "frequency": "daily",
        "source_calendar": exchange, "source_time_field": "Date",
        "availability_time_field": "Date", "available_at": _AVAILABILITY,
        "source_disclosure_schedule": "trading day approximately 08:40" if asset == "etf" else "trading day approximately 09:00",
        "availability_basis": "VENDOR_PREOPEN_SCHEDULE_ASSUMPTION",
        "source_publication_timestamp_verified": False,
        "historical_revision_history_verified": False,
        "unsupported_scenarios": ["no-price-limit sessions", "missing boundaries", "non-SH/SZ markets"],
        "daily_session_coverage": coverage,
        "source_documentation": f"https://tushare.pro/document/2?doc_id={491 if asset == 'etf' else 183}",
        "source_migration": "ETF data migrated from stk_limit to etf_limit on 2026-09-07" if asset == "etf" else "not applicable",
    }
    validate_security_price_limits(frame, request, metadata)
    return frame, metadata
