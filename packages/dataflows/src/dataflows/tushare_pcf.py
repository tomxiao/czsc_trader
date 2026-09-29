"""Historical SZSE ETF creation/redemption basket publication."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd

from .errors import DataContractError, EmptyDataError, IncompleteDataError
from .tushare_common import get_tushare_pro


_SYMBOL = re.compile(r"1\d{5}\.SZ\Z")
_RAW_FIELDS = {
    "trade_date", "ts_code", "con_code", "qty", "sub_flag", "cpr", "rdr",
    "sub_cc", "red_cc", "exchange",
}
_NUMERIC = {
    "qty": "Quantity",
    "cpr": "CreationSubstitutionRatePercent",
    "rdr": "RedemptionSubstitutionRatePercent",
    "sub_cc": "CreationSubstitutionAmountYuan",
    "red_cc": "RedemptionSubstitutionAmountYuan",
}


def fetch_etf_creation_redemption_basket(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return complete daily SZSE PCF baskets, available from the next session."""

    if not _SYMBOL.fullmatch(symbol):
        raise DataContractError("SZSE ETF basket requires a six-digit 1xxxxx.SZ symbol")
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if start != start.normalize() or end != end.normalize():
        raise DataContractError("ETF basket requests require calendar dates")
    if start > end:
        raise DataContractError("ETF basket start must not be after end")
    client = pro if pro is not None else get_tushare_pro(env_file)

    frames: list[pd.DataFrame] = []
    for month in pd.period_range(start.to_period("M"), end.to_period("M"), freq="M"):
        query_start = max(start, month.start_time)
        query_end = min(end, month.end_time.normalize())
        frame = client.etf_sz_cons(
            ts_code=symbol,
            start_date=query_start.strftime("%Y%m%d"),
            end_date=query_end.strftime("%Y%m%d"),
        )
        if frame is None or frame.empty:
            continue
        if len(frame) >= 3000:
            raise IncompleteDataError(
                "ETF basket monthly response reached the vendor row limit",
                month=str(month), rows=len(frame), limit=3000,
            )
        missing = sorted(_RAW_FIELDS.difference(frame.columns))
        if missing:
            raise DataContractError("ETF basket source fields are missing", missing_fields=missing)
        frames.append(frame[list(sorted(_RAW_FIELDS))].copy())
    if not frames:
        raise EmptyDataError("Tushare returned no ETF basket rows in the requested range")

    raw = pd.concat(frames, ignore_index=True)
    if not raw["ts_code"].astype(str).eq(symbol).all():
        raise DataContractError("ETF basket source returned another ETF symbol")
    if raw[["con_code", "sub_flag", "exchange"]].isna().any().any():
        raise DataContractError("ETF basket source contains empty identifiers")
    try:
        dates = pd.to_datetime(raw["trade_date"].astype(str), format="%Y%m%d", errors="raise")
    except ValueError as exc:
        raise DataContractError("ETF basket source dates are invalid") from exc
    if ((dates < start) | (dates > end)).any():
        raise DataContractError("ETF basket source returned dates outside the request")

    calendar = client.trade_cal(
        exchange="SZSE", start_date=start.strftime("%Y%m%d"),
        end_date=(end + pd.Timedelta(days=40)).strftime("%Y%m%d"),
        is_open="1", fields="cal_date,is_open",
    )
    if calendar is None or calendar.empty or not {"cal_date", "is_open"} <= set(calendar):
        raise IncompleteDataError("SZSE trading calendar is unavailable for ETF basket")
    if not pd.to_numeric(calendar["is_open"], errors="coerce").eq(1).all():
        raise DataContractError("SZSE trading calendar contains non-open sessions")
    try:
        open_dates = pd.DatetimeIndex(pd.to_datetime(
            calendar["cal_date"].astype(str), format="%Y%m%d", errors="raise"
        )).sort_values()
    except ValueError as exc:
        raise DataContractError("SZSE trading calendar dates are invalid") from exc
    if open_dates.has_duplicates:
        raise DataContractError("SZSE trading calendar contains duplicate open dates")
    observed = pd.DatetimeIndex(dates.unique()).sort_values()
    expected = open_dates[(open_dates >= start) & (open_dates <= end)]
    if len(observed.difference(expected)):
        raise DataContractError("ETF basket source contains non-trading dates")
    missing_sessions = expected.difference(observed)
    if len(missing_sessions):
        raise IncompleteDataError(
            "ETF basket is missing SZSE trading sessions",
            missing_dates=[day.date().isoformat() for day in missing_sessions],
        )
    next_positions = open_dates.searchsorted(dates, side="right")
    if (next_positions >= len(open_dates)).any():
        raise IncompleteDataError("next SZSE session is unavailable for ETF basket")

    result = pd.DataFrame({
        "Date": dates.dt.strftime("%Y-%m-%d"),
        "AvailableDate": open_dates[next_positions].strftime("%Y-%m-%d 09:30:00"),
        "ConstituentSymbol": raw["con_code"].astype(str).str.strip(),
        "CashSubstitutionFlag": raw["sub_flag"].astype(str).str.strip(),
        "Exchange": raw["exchange"].astype(str).str.strip(),
    })
    for source, target in _NUMERIC.items():
        values = pd.to_numeric(raw[source], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise DataContractError("ETF basket source has invalid numeric values", field=source)
        result[target] = values.to_numpy()
    if (result["Quantity"] < 0).any() or (result["Quantity"] % 1 != 0).any():
        raise DataContractError("ETF basket quantities must be non-negative integers")
    result["Quantity"] = result["Quantity"].astype("int64")
    if result[["ConstituentSymbol", "CashSubstitutionFlag", "Exchange"]].eq("").any().any():
        raise DataContractError("ETF basket source contains empty identifiers")
    if result.duplicated(["Date", "ConstituentSymbol"]).any():
        raise DataContractError("ETF basket source contains duplicate constituents")
    result = result.sort_values(["Date", "ConstituentSymbol"]).reset_index(drop=True)
    return result, {
        "vendor": "tushare", "vendor_symbol": symbol, "frequency": "daily",
        "source_api": "etf_sz_cons", "source_calendar": "SZSE",
        "source_time_field": "Date", "availability_time_field": "AvailableDate",
        "available_at": "conservative next SZSE trading session 09:30 Asia/Shanghai",
        "availability_basis": "CONSERVATIVE_NEXT_SESSION",
        "source_disclosure_schedule": "trade-date premarket; exact timestamp unavailable",
        "primary_key": ["Date", "ConstituentSymbol"],
        "source_publication_timestamp_verified": False,
        "historical_revision_history_verified": False,
    }
