"""Bar normalization and reconciliation helpers."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

import pandas as pd


INTRADAY_PERIOD_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30}
SUPPORTED_PERIODS = {"daily", "weekly", *INTRADAY_PERIOD_MINUTES}

_COLUMN_ALIASES = {
    "日期": "Date",
    "时间": "Date",
    "trade_date": "Date",
    "trade_time": "Date",
    "date": "Date",
    "datetime": "Date",
    "开盘": "Open",
    "open": "Open",
    "最高": "High",
    "high": "High",
    "最低": "Low",
    "low": "Low",
    "收盘": "Close",
    "close": "Close",
    "成交量": "Volume",
    "vol": "Volume",
    "volume": "Volume",
    "成交额": "Amount",
    "amount": "Amount",
}


def normalize_period(period: str) -> str:
    value = str(period).strip().lower()
    aliases = {
        "day": "daily",
        "week": "weekly",
        "1min": "1m",
        "5min": "5m",
        "15min": "15m",
        "30min": "30m",
    }
    value = aliases.get(value, value)
    if value not in SUPPORTED_PERIODS:
        raise ValueError(f"Unsupported period `{period}`. Choose from: {sorted(SUPPORTED_PERIODS)}")
    return value


def a_share_intraday_close_times(period: str) -> tuple[str, ...]:
    """Return causal bar-close timestamps for one complete A-share session."""

    normalized = normalize_period(period)
    if normalized not in INTRADAY_PERIOD_MINUTES:
        raise ValueError(f"{period} is not an intraday period")
    minutes = INTRADAY_PERIOD_MINUTES[normalized]
    morning = pd.date_range(
        pd.Timestamp("2000-01-01 09:30") + pd.Timedelta(minutes=minutes),
        pd.Timestamp("2000-01-01 11:30"),
        freq=f"{minutes}min",
    )
    afternoon = pd.date_range(
        pd.Timestamp("2000-01-01 13:00") + pd.Timedelta(minutes=minutes),
        pd.Timestamp("2000-01-01 15:00"),
        freq=f"{minutes}min",
    )
    return tuple(item.strftime("%H:%M:%S") for item in (*morning, *afternoon))


A_SHARE_30M_CLOSE_TIMES = set(a_share_intraday_close_times("30m"))


def infer_asset_type(symbol: str, requested: str = "auto") -> str:
    value = requested.strip().lower()
    if value not in {"auto", "stock", "fund"}:
        raise ValueError("asset_type must be one of: auto, stock, fund")
    if value != "auto":
        return value
    code = symbol.split(".", 1)[0]
    return "fund" if code.startswith(("1", "5")) else "stock"


def standardize_vendor_ohlcv(dataframe: pd.DataFrame, *, intraday: bool = False) -> pd.DataFrame:
    if dataframe is None or dataframe.empty:
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume", "Amount"])

    mapping = {
        column: _COLUMN_ALIASES.get(str(column), str(column)) for column in dataframe.columns
    }
    renamed = dataframe.rename(columns=mapping).copy()
    required = ["Date", "Open", "High", "Low", "Close"]
    missing = [column for column in required if column not in renamed.columns]
    if missing:
        raise ValueError(f"Missing required OHLC columns: {missing}")
    if "Volume" not in renamed.columns:
        renamed["Volume"] = 0
    if "Amount" not in renamed.columns:
        renamed["Amount"] = 0

    timestamps = pd.to_datetime(renamed["Date"], errors="coerce")
    renamed = renamed.loc[timestamps.notna()].copy()
    timestamps = timestamps.loc[timestamps.notna()]
    renamed["Date"] = timestamps.dt.strftime("%Y-%m-%d %H:%M:%S" if intraday else "%Y-%m-%d")
    for column in ["Open", "High", "Low", "Close", "Volume", "Amount"]:
        renamed[column] = pd.to_numeric(renamed[column], errors="coerce")
    return (
        renamed[["Date", "Open", "High", "Low", "Close", "Volume", "Amount"]]
        .sort_values("Date")
        .reset_index(drop=True)
    )


def normalize_adjustment_factors(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Normalize Tushare adjustment factors to one positive factor per trade date."""
    if dataframe is None or dataframe.empty:
        raise ValueError("Tushare returned no adjustment factors")
    aliases = {
        "trade_date": "Date",
        "date": "Date",
        "adj_factor": "AdjFactor",
        "factor": "AdjFactor",
    }
    factors = dataframe.rename(
        columns={column: aliases.get(str(column), str(column)) for column in dataframe.columns}
    ).copy()
    missing = sorted({"Date", "AdjFactor"}.difference(factors.columns))
    if missing:
        raise ValueError(f"Adjustment factors missing columns: {missing}")
    factors = factors[["Date", "AdjFactor"]]
    factors["Date"] = pd.to_datetime(factors["Date"], errors="coerce").dt.normalize()
    factors["AdjFactor"] = pd.to_numeric(factors["AdjFactor"], errors="coerce")
    if factors.isna().any().any() or (factors["AdjFactor"] <= 0).any():
        raise ValueError("Adjustment factors contain invalid dates or non-positive values")
    if factors["Date"].duplicated().any():
        raise ValueError("Adjustment factors contain duplicate trade dates")
    return factors.sort_values("Date").reset_index(drop=True)


def adjustment_factor_sha256(dataframe: pd.DataFrame) -> str:
    """Return a stable digest for the normalized factor series."""
    factors = normalize_adjustment_factors(dataframe).copy()
    factors["Date"] = factors["Date"].dt.strftime("%Y-%m-%d")
    payload = factors.to_csv(index=False, lineterminator="\n", float_format="%.10g")
    return sha256(payload.encode("utf-8")).hexdigest()


def apply_hfq_adjustment(dataframe: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    """Apply backward adjustment to OHLC and inverse adjustment to volume."""
    if dataframe is None or dataframe.empty:
        return dataframe.copy()
    normalized_factors = normalize_adjustment_factors(factors)
    frame = dataframe.copy()
    timestamps = pd.to_datetime(frame["Date"], errors="coerce")
    if timestamps.isna().any():
        raise ValueError("Cannot adjust bars with invalid timestamps")
    frame["_trade_date"] = timestamps.dt.normalize()
    frame = frame.merge(
        normalized_factors.rename(columns={"Date": "_trade_date"}),
        on="_trade_date",
        how="left",
        validate="many_to_one",
    )
    missing_dates = frame.loc[frame["AdjFactor"].isna(), "_trade_date"].drop_duplicates()
    if not missing_dates.empty:
        details = ", ".join(item.strftime("%Y-%m-%d") for item in missing_dates)
        raise ValueError(f"Adjustment factors do not cover bar dates: {details}")
    for column in ("Open", "High", "Low", "Close"):
        frame[column] = frame[column] * frame["AdjFactor"]
    frame["Volume"] = frame["Volume"] / frame["AdjFactor"]
    return frame.drop(columns=["_trade_date", "AdjFactor"])[dataframe.columns]


def with_scheduled_hfq_availability(
    dataframe: pd.DataFrame, *, factor_source: str, period: str
) -> pd.DataFrame:
    """Attach a scheduled earliest-use time, not verified historical publication."""
    if factor_source not in {"fund_adj", "adj_factor"}:
        raise ValueError("unsupported HFQ factor source")
    timestamps = pd.to_datetime(dataframe["Date"], errors="raise")
    if factor_source == "fund_adj" or period not in INTRADAY_PERIOD_MINUTES:
        available = timestamps.dt.normalize() + pd.Timedelta(hours=17)
    else:
        available = timestamps
    return dataframe.assign(AvailableDate=available)


def drop_incomplete_intraday_bar(
    dataframe: pd.DataFrame, *, now: pd.Timestamp | str | None = None
) -> pd.DataFrame:
    if dataframe is None or dataframe.empty:
        return dataframe.copy()
    cutoff = pd.Timestamp.now() if now is None else pd.Timestamp(now)
    timestamps = pd.to_datetime(dataframe["Date"], errors="coerce")
    return dataframe.loc[timestamps.notna() & (timestamps <= cutoff)].reset_index(drop=True)


def validate_a_share_intraday_bars(
    dataframe: pd.DataFrame,
    period: str,
    *,
    require_complete_days: bool = False,
) -> dict[str, Any]:
    normalized_period = normalize_period(period)
    expected_times = set(a_share_intraday_close_times(normalized_period))
    required = {"Date", "Open", "High", "Low", "Close", "Volume"}
    missing = sorted(required.difference(dataframe.columns))
    if missing:
        raise ValueError(f"Missing required {normalized_period} columns: {missing}")

    timestamps = pd.to_datetime(dataframe["Date"], errors="coerce")
    if timestamps.isna().any():
        raise ValueError(f"{normalized_period} data contains invalid timestamps")
    if timestamps.duplicated().any():
        raise ValueError(f"{normalized_period} data contains duplicate timestamps")

    times = set(timestamps.dt.strftime("%H:%M:%S"))
    unexpected = sorted(times.difference(expected_times))
    if unexpected:
        raise ValueError(
            f"{normalized_period} data contains unexpected A-share close times: {unexpected}"
        )

    invalid_ohlc = (
        (dataframe["High"] < dataframe[["Open", "Close"]].max(axis=1))
        | (dataframe["Low"] > dataframe[["Open", "Close"]].min(axis=1))
        | (dataframe["High"] < dataframe["Low"])
        | (dataframe["Volume"] < 0)
    )
    if invalid_ohlc.any():
        raise ValueError(f"{normalized_period} data contains invalid OHLCV relationships")

    counts = timestamps.groupby(timestamps.dt.strftime("%Y-%m-%d")).size()
    expected_count = len(expected_times)
    partial_days = [
        f"{date} has {int(count)} bars" for date, count in counts.items() if count != expected_count
    ]
    if require_complete_days and partial_days:
        raise ValueError(
            f"Incomplete A-share {normalized_period} trading day: " + ", ".join(partial_days)
        )
    return {
        "bar_count": len(dataframe),
        "complete_day_count": int((counts == expected_count).sum()),
        "expected_bars_per_day": expected_count,
        "partial_days": partial_days,
        "session_times": sorted(times),
    }


def validate_intraday_against_daily(
    intraday: pd.DataFrame,
    daily: pd.DataFrame,
    period: str,
    *,
    price_tolerance: float = 0.005,
    volume_relative_tolerance: float = 1e-5,
    amount_relative_tolerance: float = 1e-5,
) -> dict[str, Any]:
    """Reject overlapping or incomplete intraday data via daily reconciliation."""

    normalized_period = normalize_period(period)
    validate_a_share_intraday_bars(
        intraday,
        normalized_period,
        require_complete_days=True,
    )

    intraday_frame = intraday.copy()
    daily_frame = daily.copy()
    intraday_frame["_timestamp"] = pd.to_datetime(intraday_frame["Date"], errors="coerce")
    daily_frame["_timestamp"] = pd.to_datetime(daily_frame["Date"], errors="coerce")
    if intraday_frame["_timestamp"].isna().any() or daily_frame["_timestamp"].isna().any():
        raise ValueError("Cannot reconcile bars with invalid timestamps")

    intraday_frame["_date"] = intraday_frame["_timestamp"].dt.strftime("%Y-%m-%d")
    daily_frame["_date"] = daily_frame["_timestamp"].dt.strftime("%Y-%m-%d")
    aggregate = intraday_frame.groupby("_date", sort=True).agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
        Amount=("Amount", "sum"),
    )
    reference = daily_frame.drop_duplicates("_date", keep="last").set_index("_date")
    common_days = sorted(set(aggregate.index).intersection(reference.index))
    if not common_days:
        raise ValueError(f"No common trading days between {normalized_period} and daily data")

    failures: list[str] = []
    for day in common_days:
        mismatched_fields: list[str] = []
        for field in ["Open", "High", "Low", "Close"]:
            if (
                abs(float(aggregate.at[day, field]) - float(reference.at[day, field]))
                > price_tolerance
            ):
                mismatched_fields.append(field)
        for field, tolerance in [
            ("Volume", volume_relative_tolerance),
            ("Amount", amount_relative_tolerance),
        ]:
            expected = float(reference.at[day, field])
            relative_error = abs(float(aggregate.at[day, field]) - expected) / max(
                abs(expected), 1.0
            )
            if relative_error > tolerance:
                mismatched_fields.append(field)
        if mismatched_fields:
            failures.append(f"{day}: {', '.join(mismatched_fields)}")
    if failures:
        raise ValueError(f"{normalized_period}/daily reconciliation failed: " + "; ".join(failures))
    return {"matched_day_count": len(common_days), "matched_days": common_days}
