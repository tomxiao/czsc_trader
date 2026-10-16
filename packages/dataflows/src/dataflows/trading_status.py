"""Authenticated daily instrument sessions and native stock suspension evidence."""
from enum import StrEnum
from pathlib import Path
import re

import pandas as pd

from .contract import DataRequest
from .errors import DataContractError, IncompleteDataError


class TradingStatus(StrEnum):
    TRADING = "TRADING"
    SUSPENDED = "SUSPENDED"


def suspension_dates(pro, symbol: str, calendar_dates, observed_dates) -> tuple[list[str], list[dict]]:
    """A missing bar is explained only by an explicit full-session suspension."""
    expected = set(calendar_dates)
    missing = expected.difference(observed_dates)
    if not expected:
        return [], []
    # suspend_d is a stock source; ETF quote gaps remain data-quality failures.
    if symbol.startswith(("5", "15", "16")):
        return [], []
    if not callable(getattr(pro, "suspend_d", None)):
        if not missing:
            return [], []
        raise IncompleteDataError("suspension source is unavailable", missing_dates=sorted(missing))
    events = pro.suspend_d(ts_code=symbol, start_date=min(expected).replace("-", ""),
                          end_date=max(expected).replace("-", ""))
    required = {"ts_code", "trade_date", "suspend_type", "suspend_timing"}
    if events is None or not required.issubset(events.columns):
        raise DataContractError("suspension source fields are missing")
    if not events.ts_code.eq(symbol).all():
        raise DataContractError("suspension source symbol differs")
    suspended, evidence = [], []
    for row in events.to_dict("records"):
        day = pd.Timestamp(str(row["trade_date"])).date().isoformat()
        if day not in expected:
            continue
        timing = row["suspend_timing"]
        if pd.notna(timing) and str(timing).strip():
            raise DataContractError("intraday suspension is not supported", date=day)
        if row["suspend_type"] == "S":
            suspended.append(day)
            evidence.append({"date": day, "status": "SUSPENDED", "source": "suspend_d"})
    if expected.difference(observed_dates).difference(suspended):
        raise IncompleteDataError("missing observations have no suspension evidence",
                                  missing_dates=sorted(missing.difference(suspended)))
    if set(suspended).intersection(observed_dates):
        raise DataContractError("suspension evidence conflicts with trading observations")
    return sorted(set(suspended)), evidence


def validate_trading_status(frame, request: DataRequest, metadata) -> None:
    if (request.symbol is None or re.fullmatch(r"\d{6}\.(SH|SZ)", request.symbol) is None
            or request.frequency != "daily" or set(frame.columns) != {"Date", "Status"}):
        raise DataContractError("daily trading status requires Date/Status and an SH/SZ symbol")
    dates = pd.to_datetime(frame.Date, errors="coerce")
    coverage = metadata.get("daily_session_coverage", {})
    calendar = pd.DataFrame(coverage.get("calendar", []))
    if not {"Date", "is_open"}.issubset(calendar.columns):
        raise DataContractError("trading status requires calendar evidence")
    days = pd.to_datetime(calendar.Date, errors="coerce")
    listed = pd.Timestamp(coverage.get("listing_date"))
    from .history_repair import frame_content_sha256

    if (pd.isna(listed) or days.isna().any() or not calendar.is_open.isin([0, 1]).all()
            or not pd.DatetimeIndex(days).equals(pd.date_range(request.start, request.end))
            or coverage.get("calendar_sha256") != frame_content_sha256(calendar)
            or coverage.get("exchange") != ("SSE" if request.symbol.endswith(".SH") else "SZSE")):
        raise DataContractError("trading status calendar evidence differs from request")
    expected = set(days[calendar.is_open.eq(1) & days.ge(listed)].dt.strftime("%Y-%m-%d"))
    if (dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing
            or set(dates.dt.strftime("%Y-%m-%d")) != expected
            or not frame.Status.isin([item.value for item in TradingStatus]).all()):
        raise DataContractError("trading status must prove every applicable exchange session")
    suspended = set(dates[frame.Status.eq(TradingStatus.SUSPENDED)].dt.strftime("%Y-%m-%d"))
    if suspended != set(coverage.get("suspended_dates", [])):
        raise DataContractError("trading status differs from suspension evidence")
    proofs = coverage.get("suspension_evidence", [])
    if suspended != {item.get("date") for item in proofs if item.get("status") == "SUSPENDED" and item.get("source")}:
        raise DataContractError("suspension source evidence is missing")


def fetch_trading_status(request: DataRequest, *, env_file: str | Path | None = None):
    from .bar_utils import infer_asset_type
    from .ohlcv_quality import verify_daily_sessions
    from .tushare_common import get_tushare_pro

    asset = "etf" if infer_asset_type(request.symbol) == "fund" else "stock"
    if asset != "stock":
        raise DataContractError("trading status source supports SH/SZ stocks only")
    pro = get_tushare_pro(env_file)
    if not callable(getattr(pro, "suspend_d", None)):
        raise DataContractError("stock suspension source is unavailable")
    raw = pro.daily(ts_code=request.symbol, start_date=request.start.replace("-", ""),
                    end_date=request.end.replace("-", ""))
    if raw is None or not {"ts_code", "trade_date", "vol"}.issubset(raw.columns):
        raise DataContractError("trading observations are unavailable")
    if not raw.ts_code.eq(request.symbol).all():
        raise DataContractError("trading observations belong to another symbol")
    observations = pd.DataFrame({"Date": pd.to_datetime(raw.loc[raw.vol.gt(0), "trade_date"], format="%Y%m%d")})
    coverage = verify_daily_sessions(pro, request.symbol, observations, start=request.start,
                                     end=request.end, asset_type=asset)
    if not coverage.get("suspended_dates"):
        # Check reported intraday halts even when a daily bar exists.
        suspension_dates(pro, request.symbol, coverage["expected_dates"],
                         coverage["expected_dates"])
    suspended = set(coverage.get("suspended_dates", []))
    days = sorted(set(coverage["expected_dates"]) | suspended)
    frame = pd.DataFrame({"Date": days, "Status": ["SUSPENDED" if day in suspended else "TRADING" for day in days]})
    metadata = {"vendor": "tushare", "source_calendar": "SSE" if request.symbol.endswith(".SH") else "SZSE",
                "daily_session_coverage": coverage, "available_at": "historical session status; publication time unverified",
                "source_publication_timestamp_verified": False, "historical_revision_history_verified": False}
    validate_trading_status(frame, request, metadata)
    return frame, metadata
