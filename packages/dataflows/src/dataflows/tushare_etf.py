"""Tushare ETF market-data adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .bar_utils import (
    INTRADAY_PERIOD_MINUTES,
    adjustment_factor_sha256,
    apply_hfq_adjustment,
    drop_incomplete_intraday_bar,
    infer_asset_type,
    normalize_adjustment_factors,
    normalize_period,
    slice_intraday_request,
    standardize_vendor_ohlcv,
    with_scheduled_hfq_availability,
)
from .contract import ETF_INTRADAY_OBSERVATION_RULE
from .errors import DataContractError, EmptyDataError
from .formatting import format_dataframe_report
from .history_repair import (
    SeriesKey,
    apply_repairs_once,
    frame_content_sha256,
    inspect_registered_source_anomalies,
    patch_for,
)
from .history_validation import (
    ValidationReport,
    inspect_daily_against_weekly,
    inspect_intraday_against_daily,
    inspect_ohlcv_frame,
)
from .market_resolver import MARKET_A_SHARE, detect_market, normalize_symbol_for_vendor
from .tushare_common import get_tushare_pro


def _intraday_boundary(value: str, *, end: bool) -> str:
    if " " in value:
        return value
    return f"{value} {'23:59:59' if end else '00:00:00'}"


def _calendar_year_segments(
    start_date: str,
    end_date: str,
    *,
    years_per_segment: int = 1,
) -> list[tuple[str, str]]:
    """Split long requests to stay below Tushare's silent row caps."""
    if years_per_segment < 1:
        raise ValueError("years_per_segment must be positive")
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    segments: list[tuple[str, str]] = []
    for year in range(start.year, end.year + 1, years_per_segment):
        segment_start = max(start, pd.Timestamp(year=year, month=1, day=1))
        last_year = min(year + years_per_segment - 1, end.year)
        segment_end = min(end, pd.Timestamp(year=last_year, month=12, day=31))
        segments.append((segment_start.date().isoformat(), segment_end.date().isoformat()))
    return segments


def _intraday_calendar_segments(
    start_date: str, end_date: str, period: str
) -> list[tuple[str, str]]:
    """Keep each Tushare minute request below its silent row cap."""

    segment_days = {"1m": 30, "5m": 150, "15m": 365, "30m": 365}[period]
    current = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    segments: list[tuple[str, str]] = []
    while current <= end:
        segment_end = min(current + pd.Timedelta(days=segment_days - 1), end)
        segments.append((current.date().isoformat(), segment_end.date().isoformat()))
        current = segment_end + pd.Timedelta(days=1)
    return segments


def _resample_weekly(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe
    frame = dataframe.copy()
    frame["_timestamp"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["_timestamp"]).sort_values("_timestamp")
    frame["_week"] = frame["_timestamp"].dt.to_period("W-FRI")
    weekly = frame.groupby("_week", sort=True).agg(
        Date=("Date", "last"),
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
        Amount=("Amount", "sum"),
    )
    return weekly.reset_index(drop=True)


def _standardize_etf_ohlcv(dataframe: pd.DataFrame, *, intraday: bool) -> pd.DataFrame:
    normalized = standardize_vendor_ohlcv(dataframe, intraday=intraday)
    if not intraday:
        normalized["Volume"] = normalized["Volume"] * 100
        normalized["Amount"] = normalized["Amount"] * 1000
    return normalized


def _merge_opening_auction_into_first_bar(dataframe: pd.DataFrame, period: str) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe.copy()

    frame = dataframe.copy()
    timestamps = pd.to_datetime(frame["Date"], errors="coerce")
    minutes = INTRADAY_PERIOD_MINUTES[period]
    merged_auction_indices: list[int] = []
    for auction_index in frame.index[timestamps.dt.strftime("%H:%M:%S") == "09:30:00"]:
        auction_time = timestamps.loc[auction_index]
        target_time = (
            auction_time.normalize()
            + pd.Timedelta(hours=9, minutes=30)
            + pd.Timedelta(minutes=minutes)
        )
        target_indices = frame.index[timestamps == target_time]
        if target_indices.empty:
            continue
        target_index = target_indices[0]
        active = (
            frame.at[auction_index, "Volume"] > 0
            or frame.at[auction_index, "Amount"] > 0
        )
        if active:
            frame.at[target_index, "Open"] = frame.at[auction_index, "Open"]
            frame.at[target_index, "High"] = max(
                frame.at[auction_index, "High"], frame.at[target_index, "High"]
            )
            frame.at[target_index, "Low"] = min(
                frame.at[auction_index, "Low"], frame.at[target_index, "Low"]
            )
        frame.at[target_index, "Volume"] += frame.at[auction_index, "Volume"]
        frame.at[target_index, "Amount"] += frame.at[auction_index, "Amount"]
        merged_auction_indices.append(auction_index)

    return frame.drop(index=merged_auction_indices).sort_values("Date").reset_index(drop=True)


def _drop_zero_activity_days(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Remove synthetic intraday rows emitted for suspended ETF sessions."""
    if dataframe.empty:
        return dataframe.copy()
    frame = dataframe.copy()
    trade_dates = pd.to_datetime(frame["Date"], errors="coerce").dt.normalize()
    active = (
        frame.assign(_trade_date=trade_dates)
        .groupby("_trade_date")
        .agg(Volume=("Volume", "sum"), Amount=("Amount", "sum"))
    )
    active_dates = active.index[(active["Volume"] > 0) | (active["Amount"] > 0)]
    return frame.loc[trade_dates.isin(active_dates)].reset_index(drop=True)


def _fetch_intraday_vendor(
    pro,
    ts_code: str,
    start_date: str,
    end_date: str,
    period: str,
) -> pd.DataFrame:
    pieces = [
        pro.etf_mins(
            ts_code=ts_code,
            start_date=_intraday_boundary(segment_start, end=False),
            end_date=_intraday_boundary(segment_end, end=True),
            freq=f"{INTRADAY_PERIOD_MINUTES[period]}min",
        )
        for segment_start, segment_end in _intraday_calendar_segments(
            start_date, end_date, period
        )
    ]
    available = [piece for piece in pieces if piece is not None and not piece.empty]
    return pd.concat(available, ignore_index=True) if available else pd.DataFrame()


def _fetch_daily_vendor(
    pro,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    return pro.fund_daily(
        ts_code=ts_code,
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
    )


def _repair_daily_once(
    dataframe: pd.DataFrame,
    ts_code: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    series = SeriesKey(
        "tushare", "fund_daily", ts_code, "etf.ohlcv", "daily", "none"
    )
    structural = inspect_ohlcv_frame(dataframe, "daily")
    findings = (
        *structural.findings,
        *inspect_registered_source_anomalies(dataframe, series),
    )
    if not findings:
        return dataframe.copy(), []
    repaired, records = apply_repairs_once(dataframe, series, findings)
    post = inspect_ohlcv_frame(repaired, "daily")
    remaining = (
        *post.findings,
        *inspect_registered_source_anomalies(repaired, series),
    )
    if remaining:
        ValidationReport(tuple(remaining)).require_pass()
    return repaired, [record.to_dict() for record in records]


def _fetch_tushare_etf_ohlcv(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    period: str = "daily",
    env_file: str | Path | None = None,
) -> tuple[pd.DataFrame, str, str]:
    period = normalize_period(period)
    if period in INTRADAY_PERIOD_MINUTES:
        start_date = pd.Timestamp(start_date).date().isoformat()
        end_date = pd.Timestamp(end_date).date().isoformat()
    market = detect_market(symbol)
    if market != MARKET_A_SHARE:
        raise ValueError("tushare_etf only supports A-share ETFs")

    ts_code = normalize_symbol_for_vendor(symbol, "tushare", market)
    if infer_asset_type(ts_code, "auto") != "fund":
        raise ValueError(f"{symbol} is not recognized as an A-share ETF")

    pro = get_tushare_pro(env_file)
    if period in INTRADAY_PERIOD_MINUTES:
        dataframe = _fetch_intraday_vendor(
            pro, ts_code, start_date, end_date, period
        )
    else:
        dataframe = _fetch_daily_vendor(pro, ts_code, start_date, end_date)

    if dataframe is None or dataframe.empty:
        return pd.DataFrame(), market, ts_code

    intraday = period in INTRADAY_PERIOD_MINUTES
    normalized = _standardize_etf_ohlcv(dataframe, intraday=intraday)
    repair_records: list[dict[str, Any]] = []
    reference_daily_sha256: str | None = None
    if intraday:
        normalized = _merge_opening_auction_into_first_bar(normalized, period)
        normalized = _drop_zero_activity_days(normalized)
        normalized = drop_incomplete_intraday_bar(normalized)
        daily_vendor = _fetch_daily_vendor(pro, ts_code, start_date, end_date)
        daily = _standardize_etf_ohlcv(daily_vendor, intraday=False)
        daily, daily_records = _repair_daily_once(daily, ts_code)
        repair_records.extend(daily_records)
        reference_daily_sha256 = frame_content_sha256(daily)
        report = inspect_intraday_against_daily(normalized, daily, period)
        if not report.passed:
            series = SeriesKey(
                "tushare", "etf_mins", ts_code, "etf.ohlcv", period, "none"
            )
            repair_patch = patch_for(series)
            references: dict[str, pd.DataFrame] = {"daily": daily}
            repair_dates = (
                repair_patch.reference_dates(
                    daily, repair_patch, series, report.findings
                )
                if repair_patch is not None
                and repair_patch.reference_dates is not None
                else ()
            )
            if repair_dates:
                one_minute_pieces = [
                    _fetch_intraday_vendor(pro, ts_code, trade_date, trade_date, "1m")
                    for trade_date in repair_dates
                ]
                available = [
                    piece
                    for piece in one_minute_pieces
                    if piece is not None and not piece.empty
                ]
                references["1m"] = _standardize_etf_ohlcv(
                    pd.concat(available, ignore_index=True)
                    if available
                    else pd.DataFrame(),
                    intraday=True,
                )
            normalized, records = apply_repairs_once(
                normalized,
                series,
                report.findings,
                references=references,
            )
            repair_records.extend(record.to_dict() for record in records)
            inspect_intraday_against_daily(normalized, daily, period).require_pass()
    else:
        normalized, daily_records = _repair_daily_once(normalized, ts_code)
        repair_records.extend(daily_records)
        if period == "weekly":
            daily = normalized
            normalized = _resample_weekly(daily)
            inspect_daily_against_weekly(daily, normalized).require_pass()
        reference_daily_sha256 = frame_content_sha256(
            daily if period == "weekly" else normalized
        )
    if repair_records:
        normalized.attrs["repair_records"] = repair_records
    if reference_daily_sha256:
        normalized.attrs["reference_daily_sha256"] = reference_daily_sha256
    return normalized, market, ts_code


def _fetch_hfq_factors(
    ts_code: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
) -> pd.DataFrame:
    pro = get_tushare_pro(env_file)
    pieces = [
        pro.fund_adj(
            ts_code=ts_code,
            start_date=segment_start.replace("-", ""),
            end_date=segment_end.replace("-", ""),
        )
        for segment_start, segment_end in _calendar_year_segments(
            start_date, end_date, years_per_segment=5
        )
    ]
    dataframe = (
        pd.concat(
            [piece for piece in pieces if piece is not None and not piece.empty],
            ignore_index=True,
        )
        if any(piece is not None and not piece.empty for piece in pieces)
        else pd.DataFrame()
    )
    return normalize_adjustment_factors(dataframe)


def fetch_etf_ohlcv(
    symbol: str,
    start_date: str,
    end_date: str,
    period: str = "daily",
    *,
    env_file: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return normalized Tushare ETF bars and machine-readable metadata."""
    normalized_period = normalize_period(period)
    fetch_period = "daily" if normalized_period == "weekly" else normalized_period
    dataframe, market, ts_code = _fetch_tushare_etf_ohlcv(
        symbol,
        start_date,
        end_date,
        period=fetch_period,
        env_file=env_file,
    )
    if dataframe.empty:
        raise EmptyDataError(f"Tushare returned no data for {symbol} {normalized_period}")
    repair_records = dataframe.attrs.get("repair_records", [])
    reference_daily_sha256 = dataframe.attrs.get("reference_daily_sha256")
    factors = _fetch_hfq_factors(
        ts_code, pd.Timestamp(start_date).date().isoformat(),
        pd.Timestamp(end_date).date().isoformat(), env_file=env_file,
    )
    dataframe = apply_hfq_adjustment(dataframe, factors)
    if normalized_period == "weekly":
        dataframe = _resample_weekly(dataframe)
    validation = inspect_ohlcv_frame(
        dataframe,
        normalized_period,
        require_complete_days=normalized_period in INTRADAY_PERIOD_MINUTES,
    )
    validation.require_pass()
    dataframe = with_scheduled_hfq_availability(
        dataframe, factor_source="fund_adj", period=normalized_period
    )
    metadata = {
        "vendor": "tushare",
        "market": market,
        "vendor_symbol": ts_code,
        "period": normalized_period,
        "asset_type": "etf",
        "adjustment": "hfq",
        "adjustment_factor_source": "fund_adj",
        "adjustment_factor_sha256": adjustment_factor_sha256(factors),
        "adjustment_factor_publication_schedule": "daily 17:00 Asia/Shanghai",
        "adjustment_factor_publication_timestamp_verified": False,
        "adjustment_factor_revision_history_verified": False,
        "availability_time_field": "AvailableDate",
        "available_at": "scheduled fund_adj daily 17:00 Asia/Shanghai; historical publication unverified",
        "validation": validation.to_dict(),
    }
    if reference_daily_sha256:
        metadata["reference_daily_sha256"] = str(reference_daily_sha256)
    if repair_records:
        metadata["repair_records"] = repair_records
    if normalized_period in INTRADAY_PERIOD_MINUTES:
        dataframe = slice_intraday_request(dataframe, start_date, end_date)
    return dataframe.copy(), metadata


def fetch_etf_unadjusted_intraday(
    symbol: str,
    start_date: str,
    end_date: str,
    period: str,
    *,
    env_file: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Raw executable bars, with explicit assumed market observation timing.

    AvailableDate models completed market bars. It does not claim that the
    historical Tushare API published each bar in real time. Daily reconciliation
    remains mandatory; unresolved source defects prevent publication.
    """
    if period not in INTRADAY_PERIOD_MINUTES:
        raise DataContractError("unadjusted ETF intraday requires 1m/5m/15m/30m")
    dataframe, market, ts_code = _fetch_tushare_etf_ohlcv(
        symbol, start_date, end_date, period=period, env_file=env_file,
    )
    if dataframe.empty:
        raise EmptyDataError(f"Tushare returned no data for {symbol} {period}")
    validation = inspect_ohlcv_frame(dataframe, period, require_complete_days=True)
    validation.require_pass()
    metadata: dict[str, Any] = {
        "vendor": "tushare", "market": market, "vendor_symbol": ts_code,
        "period": period, "asset_type": "etf", "adjustment": "none",
        "source_calendar": "SSE" if ts_code.endswith(".SH") else "SZSE",
        "source_time_field": "Date", "availability_time_field": "AvailableDate",
        "available_at": ETF_INTRADAY_OBSERVATION_RULE,
        "availability_basis": "MARKET_BAR_CLOSE_ASSUMPTION",
        "source_publication_timestamp_verified": False,
        "historical_revision_history_verified": False,
        "live_feed_latency_verified": False,
        "vendor_history_update_window": "post-session 17:00-21:00 Asia/Shanghai",
        "validation": validation.to_dict(),
    }
    for name in ("reference_daily_sha256", "repair_records"):
        if name in dataframe.attrs:
            metadata[name] = dataframe.attrs[name]
    dataframe = dataframe.copy()
    dataframe["AvailableDate"] = pd.to_datetime(dataframe["Date"])
    return slice_intraday_request(dataframe, start_date, end_date), metadata


def fetch_etf_unadjusted_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return unadjusted daily ETF prices for executable order pricing."""
    dataframe, market, ts_code = _fetch_tushare_etf_ohlcv(
        symbol,
        start_date,
        end_date,
        period="daily",
        env_file=env_file,
    )
    if dataframe.empty:
        raise EmptyDataError(f"Tushare returned no data for {symbol} unadjusted daily")
    metadata: dict[str, Any] = {
        "vendor": "tushare",
        "market": market,
        "vendor_symbol": ts_code,
        "period": "daily",
        "asset_type": "etf",
        "adjustment": "none",
    }
    reference_daily_sha256 = dataframe.attrs.get("reference_daily_sha256")
    repair_records = dataframe.attrs.get("repair_records", [])
    validation = inspect_ohlcv_frame(dataframe, "daily")
    validation.require_pass()
    metadata["validation"] = validation.to_dict()
    if reference_daily_sha256:
        metadata["reference_daily_sha256"] = str(reference_daily_sha256)
    if repair_records:
        metadata["repair_records"] = repair_records
    return dataframe.copy(), metadata


def get_etf(
    symbol: str,
    start_date: str,
    end_date: str,
    period: str = "daily",
) -> str:
    try:
        dataframe, metadata = fetch_etf_ohlcv(symbol, start_date, end_date, period)
        return format_dataframe_report(
            f"Tushare ETF data for {symbol}",
            dataframe,
            {
                "Vendor": "tushare",
                "Market": metadata["market"],
                "Vendor symbol": metadata["vendor_symbol"],
                "Start date": start_date,
                "End date": end_date,
                "Period": normalize_period(period),
                "Asset type": "fund",
                "Adjustment": "hfq",
            },
            max_rows=10000,
        )
    except Exception as exc:
        return f"Error retrieving ETF data for {symbol} via tushare: {exc}"
