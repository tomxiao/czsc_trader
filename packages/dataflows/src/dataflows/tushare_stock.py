"""Tushare stock market-data adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import tushare as ts

from .bar_utils import (
    INTRADAY_PERIOD_MINUTES,
    adjustment_factor_sha256,
    apply_hfq_adjustment,
    drop_incomplete_intraday_bar,
    infer_asset_type,
    normalize_adjustment_factors,
    normalize_period,
    standardize_vendor_ohlcv,
    with_scheduled_hfq_availability,
    validate_a_share_intraday_bars,
)
from .formatting import format_dataframe_report
from .errors import EmptyDataError
from .indicator_utils import compute_indicator_report
from .history_validation import (
    inspect_daily_against_weekly,
    inspect_intraday_against_daily,
    inspect_ohlcv_frame,
)
from .market_resolver import (
    MARKET_A_SHARE,
    MARKET_HK,
    MARKET_US,
    detect_market,
    normalize_symbol_for_vendor,
)
from .tushare_common import get_tushare_pro


def _intraday_boundary(value: str, *, end: bool) -> str:
    if " " in value:
        date_part, time_part = value.split(" ", 1)
    else:
        date_part, time_part = value, "23:59:59" if end else "00:00:00"
    return f"{date_part.replace('-', '')} {time_part}"


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


def _standardize_a_share_tushare_ohlcv(dataframe: pd.DataFrame, *, intraday: bool) -> pd.DataFrame:
    """Normalize Tushare A-share bars to shares and yuan."""

    if intraday and "trade_time" in dataframe.columns and "trade_date" in dataframe.columns:
        # pro_bar adds a derived trade_date to stk_mins rows. The bar-close
        # trade_time is authoritative; both aliases would otherwise become Date.
        dataframe = dataframe.drop(columns="trade_date")
    normalized = standardize_vendor_ohlcv(dataframe, intraday=intraday)
    if not intraday:
        normalized["Volume"] = normalized["Volume"] * 100
        normalized["Amount"] = normalized["Amount"] * 1000
    return normalized


def _merge_opening_auction_into_first_bar(dataframe: pd.DataFrame, period: str) -> pd.DataFrame:
    """Fold Tushare's 09:30 auction record into the first completed bar."""

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


def _fetch_tushare_ohlcv(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    period: str = "daily",
    asset_type: str = "auto",
    env_file: str | Path | None = None,
) -> tuple[pd.DataFrame, str, str]:
    period = normalize_period(period)
    market = detect_market(symbol)
    ts_code = normalize_symbol_for_vendor(symbol, "tushare", market)
    resolved_asset_type = infer_asset_type(ts_code, asset_type)

    if market == MARKET_A_SHARE:
        if infer_asset_type(ts_code, "auto") == "fund" or resolved_asset_type == "fund":
            raise ValueError(
                "A-share ETFs are not supported by tushare_stock; "
                "use dataflows.tushare_etf.get_etf instead"
            )
        api = get_tushare_pro(env_file)
        intraday = period in INTRADAY_PERIOD_MINUTES
        fetch_frequency = {
            "daily": "D",
            "weekly": "W",
            **{item: f"{minutes}min" for item, minutes in INTRADAY_PERIOD_MINUTES.items()},
        }[period]
        dataframe = ts.pro_bar(
            api=api,
            ts_code=ts_code,
            start_date=(
                _intraday_boundary(start_date, end=False)
                if intraday
                else start_date.replace("-", "")
            ),
            end_date=(
                _intraday_boundary(end_date, end=True) if intraday else end_date.replace("-", "")
            ),
            freq=fetch_frequency,
            asset="E",
            adj=None,
        )
        if dataframe is None or dataframe.empty:
            return pd.DataFrame(), market, ts_code
        normalized = _standardize_a_share_tushare_ohlcv(dataframe, intraday=intraday)
        if intraday:
            normalized = _merge_opening_auction_into_first_bar(normalized, period)
            normalized = drop_incomplete_intraday_bar(normalized)
            validate_a_share_intraday_bars(normalized, period)
        return normalized, market, ts_code

    pro = get_tushare_pro(env_file)
    if period in {"1m", "5m", "15m"}:
        raise ValueError("Tushare HK/US minute bars are currently wired only for period=30m")
    if period == "30m" and market == MARKET_US:
        raise ValueError("Tushare US 30m bars are not wired in this implementation")
    method_name = (
        "hk_mins" if period == "30m" else {MARKET_HK: "hk_daily", MARKET_US: "us_daily"}[market]
    )
    query = getattr(pro, method_name)
    kwargs = {
        "ts_code": ts_code,
        "start_date": (
            _intraday_boundary(start_date, end=False)
            if period == "30m"
            else start_date.replace("-", "")
        ),
        "end_date": (
            _intraday_boundary(end_date, end=True) if period == "30m" else end_date.replace("-", "")
        ),
    }
    if period == "30m":
        kwargs["freq"] = "30min"
    dataframe = query(**kwargs)
    if dataframe is None or dataframe.empty:
        return pd.DataFrame(), market, ts_code
    normalized = standardize_vendor_ohlcv(dataframe, intraday=period == "30m")
    if period == "weekly":
        normalized = _resample_weekly(normalized)
    if period == "30m":
        normalized = drop_incomplete_intraday_bar(normalized)
    return normalized, market, ts_code


def _fetch_hfq_factors(
    ts_code: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
) -> pd.DataFrame:
    dataframe = get_tushare_pro(env_file).adj_factor(
        ts_code=ts_code,
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
    )
    return normalize_adjustment_factors(dataframe)


def fetch_stock_ohlcv(
    symbol: str,
    start_date: str,
    end_date: str,
    period: str = "daily",
    *,
    env_file: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return normalized Tushare stock bars and machine-readable metadata."""
    normalized_period = normalize_period(period)
    fetch_period = (
        "daily"
        if normalized_period == "weekly" and detect_market(symbol) == MARKET_A_SHARE
        else normalized_period
    )
    dataframe, market, ts_code = _fetch_tushare_ohlcv(
        symbol,
        start_date,
        end_date,
        period=fetch_period,
        asset_type="stock",
        env_file=env_file,
    )
    if dataframe.empty:
        raise EmptyDataError(f"Tushare returned no data for {symbol} {normalized_period}")
    metadata = {
        "vendor": "tushare",
        "market": market,
        "vendor_symbol": ts_code,
        "period": normalized_period,
        "asset_type": "stock",
    }
    if market == MARKET_A_SHARE:
        factors = _fetch_hfq_factors(ts_code, start_date, end_date, env_file=env_file)
        dataframe = apply_hfq_adjustment(dataframe, factors)
        if normalized_period == "weekly":
            daily = dataframe
            dataframe = _resample_weekly(dataframe)
            inspect_daily_against_weekly(daily, dataframe).require_pass()
        elif normalized_period in INTRADAY_PERIOD_MINUTES:
            daily, _daily_market, _daily_symbol = _fetch_tushare_ohlcv(
                symbol,
                start_date,
                end_date,
                period="daily",
                asset_type="stock",
                env_file=env_file,
            )
            daily = apply_hfq_adjustment(daily, factors)
            inspect_intraday_against_daily(
                dataframe, daily, normalized_period
            ).require_pass()
        metadata.update(
            {
                "adjustment": "hfq",
                "adjustment_factor_source": "adj_factor",
                "adjustment_factor_sha256": adjustment_factor_sha256(factors),
                "adjustment_factor_publication_schedule": "trade day 09:15-09:20 Asia/Shanghai",
                "adjustment_factor_publication_timestamp_verified": False,
                "adjustment_factor_revision_history_verified": False,
                "availability_time_field": "AvailableDate",
                "available_at": (
                    "intraday bar close or daily 17:00 Asia/Shanghai conservative; "
                    "historical publication unverified"
                ),
            }
        )
    validation = inspect_ohlcv_frame(
        dataframe,
        normalized_period,
        require_complete_days=normalized_period in INTRADAY_PERIOD_MINUTES,
    )
    validation.require_pass()
    if market == MARKET_A_SHARE:
        dataframe = with_scheduled_hfq_availability(
            dataframe, factor_source="adj_factor", period=normalized_period
        )
    metadata["validation"] = validation.to_dict()
    return dataframe.copy(), metadata


def fetch_stock_unadjusted_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return unadjusted daily A-share prices for executable order pricing."""
    dataframe, market, ts_code = _fetch_tushare_ohlcv(
        symbol,
        start_date,
        end_date,
        period="daily",
        asset_type="stock",
        env_file=env_file,
    )
    if market != MARKET_A_SHARE:
        raise ValueError("unadjusted execution prices currently require an A-share symbol")
    if dataframe.empty:
        raise EmptyDataError(f"Tushare returned no data for {symbol} unadjusted daily")
    validation = inspect_ohlcv_frame(dataframe, "daily")
    validation.require_pass()
    return dataframe.copy(), {
        "vendor": "tushare",
        "market": market,
        "vendor_symbol": ts_code,
        "period": "daily",
        "asset_type": "stock",
        "adjustment": "none",
        "validation": validation.to_dict(),
    }


def get_stock(
    symbol: str,
    start_date: str,
    end_date: str,
    period: str = "daily",
    asset_type: str = "auto",
) -> str:
    try:
        if asset_type not in {"auto", "stock"}:
            raise ValueError("get_stock only supports stock assets")
        dataframe, metadata = fetch_stock_ohlcv(symbol, start_date, end_date, period)
        return format_dataframe_report(
            f"Tushare stock data for {symbol}",
            dataframe,
            {
                "Vendor": "tushare",
                "Market": metadata["market"],
                "Vendor symbol": metadata["vendor_symbol"],
                "Start date": start_date,
                "End date": end_date,
                "Period": normalize_period(period),
                "Asset type": "stock",
                "Adjustment": metadata.get("adjustment", "none"),
            },
            max_rows=10000,
        )
    except Exception as exc:
        return f"Error retrieving stock data for {symbol} via tushare: {exc}"


def get_indicator(symbol: str, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
    try:
        start_date = (
            pd.Timestamp(curr_date) - pd.Timedelta(days=max(look_back_days * 3, 365))
        ).strftime("%Y-%m-%d")
        dataframe, _metadata = fetch_stock_ohlcv(symbol, start_date, curr_date, "daily")
        return compute_indicator_report(dataframe, indicator, curr_date, look_back_days)
    except Exception as exc:
        return f"Error retrieving indicator `{indicator}` for {symbol} via tushare: {exc}"
