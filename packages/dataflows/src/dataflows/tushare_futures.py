"""Causal Tushare publications for SHFE gold-futures research."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .errors import DataContractError, EmptyDataError
from .tushare_common import get_tushare_pro


_CANONICAL_SYMBOL = "AU.SHFE"
_VENDOR_CONTINUOUS_SYMBOL = "AU.SHF"
_EXCHANGE = "SHFE"
_AVAILABILITY_RULE = (
    "source trade date T is usable from the next China trading session; "
    "an earlier timestamp requires a separately governed publication time"
)


def _client(pro: object | None, env_file: str | Path | None) -> object:
    return pro if pro is not None else get_tushare_pro(env_file)


def _require_symbol(symbol: str) -> None:
    if str(symbol).strip().upper() != _CANONICAL_SYMBOL:
        raise DataContractError(
            "SHFE gold futures datasets only support AU.SHFE",
            symbol=symbol,
        )


def _vendor_date(value: str | pd.Timestamp) -> str:
    return pd.Timestamp(value).strftime("%Y%m%d")


def _frame(value: object) -> pd.DataFrame:
    return pd.DataFrame() if value is None else pd.DataFrame(value).copy()


def _require_columns(
    frame: pd.DataFrame,
    required: set[str],
    dataset: str,
) -> None:
    if frame.empty:
        raise EmptyDataError(f"Tushare returned no data for {dataset}")
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise DataContractError(
            f"Tushare {dataset} response is missing required fields",
            missing_fields=missing,
        )


def _contract_directory(client: object, start_date: str, end_date: str) -> pd.DataFrame:
    raw = _frame(
        client.fut_basic(
            exchange=_EXCHANGE,
            fut_type="1",
            fut_code="AU",
            fields="ts_code,symbol,exchange,fut_code,list_date,delist_date,d_month",
        )
    )
    _require_columns(
        raw,
        {"ts_code", "exchange", "fut_code", "list_date", "delist_date"},
        "SHFE gold contract directory",
    )
    listed = pd.to_datetime(raw["list_date"].astype(str), errors="raise").dt.normalize()
    delisted = pd.to_datetime(raw["delist_date"].astype(str), errors="raise").dt.normalize()
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    selected = raw.loc[
        raw["exchange"].astype(str).str.upper().eq(_EXCHANGE)
        & raw["fut_code"].astype(str).str.upper().eq("AU")
        & listed.le(end)
        & delisted.ge(start)
    ].copy()
    if selected.empty:
        raise EmptyDataError("Tushare returned no active SHFE gold contracts")
    selected["ListDate"] = listed.loc[selected.index]
    selected["MaturityDate"] = delisted.loc[selected.index]
    selected["Contract"] = selected["ts_code"].astype(str).str.upper()
    return selected.sort_values(["ListDate", "Contract"]).reset_index(drop=True)


def _year_slices(start_date: str, end_date: str) -> tuple[tuple[str, str], ...]:
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    return tuple(
        (
            max(start, pd.Timestamp(year=year, month=1, day=1)).strftime("%Y%m%d"),
            min(end, pd.Timestamp(year=year, month=12, day=31)).strftime("%Y%m%d"),
        )
        for year in range(start.year, end.year + 1)
    )


def _month_slices(start_date: str, end_date: str) -> tuple[tuple[str, str], ...]:
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    periods = pd.period_range(start, end, freq="M")
    return tuple(
        (
            max(start, period.start_time.normalize()).strftime("%Y%m%d"),
            min(end, period.end_time.normalize()).strftime("%Y%m%d"),
        )
        for period in periods
    )


def _metadata(primary_key: list[str]) -> dict[str, Any]:
    return {
        "vendor": "tushare",
        "vendor_symbol": _CANONICAL_SYMBOL,
        "exchange": _EXCHANGE,
        "frequency": "daily",
        "primary_key": primary_key,
        "source_time_field": "Date",
        "source_calendar": _EXCHANGE,
        "available_at": _AVAILABILITY_RULE,
        "maximum_start_lag_days": 10,
    }


def fetch_shfe_gold_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Publish all active AU contract bars required to derive a daily term structure."""

    _require_symbol(symbol)
    client = _client(pro, env_file)
    contracts = _contract_directory(client, start_date, end_date)
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    frames: list[pd.DataFrame] = []
    maturity_by_contract = contracts.set_index("Contract")["MaturityDate"].to_dict()
    for contract in contracts.itertuples(index=False):
        chunk_start = max(start, contract.ListDate)
        chunk_end = min(end, contract.MaturityDate)
        raw = _frame(
            client.fut_daily(
                ts_code=contract.Contract,
                start_date=_vendor_date(chunk_start),
                end_date=_vendor_date(chunk_end),
                fields="ts_code,trade_date,close,settle,vol,amount,oi",
            )
        )
        if not raw.empty:
            frames.append(raw)
    if not frames:
        raise EmptyDataError("Tushare returned no SHFE gold futures daily bars")
    raw = pd.concat(frames, ignore_index=True)
    required = {
        "ts_code",
        "trade_date",
        "close",
        "settle",
        "vol",
        "amount",
        "oi",
    }
    _require_columns(raw, required, "SHFE gold futures daily")
    output = raw[
        [
            "trade_date",
            "ts_code",
            "close",
            "settle",
            "vol",
            "amount",
            "oi",
        ]
    ].rename(
        columns={
            "trade_date": "Date",
            "ts_code": "Contract",
            "close": "Close",
            "settle": "Settle",
            "vol": "Volume",
            "amount": "Amount",
            "oi": "OpenInterest",
        }
    )
    output["Date"] = pd.to_datetime(output["Date"].astype(str), errors="raise").dt.normalize()
    output["Contract"] = output["Contract"].astype(str).str.upper()
    output["MaturityDate"] = output["Contract"].map(maturity_by_contract)
    if output["MaturityDate"].isna().any():
        raise DataContractError("daily bars contain a contract outside the AU directory")
    for column in (
        "Close",
        "Settle",
        "Volume",
        "Amount",
        "OpenInterest",
    ):
        output[column] = pd.to_numeric(output[column], errors="raise")
    output = (
        output[
            [
                "Date",
                "Contract",
                "MaturityDate",
                "Close",
                "Settle",
                "Volume",
                "Amount",
                "OpenInterest",
            ]
        ]
        .sort_values(["Date", "Contract"])
        .reset_index(drop=True)
    )
    return output, _metadata(["Date", "Contract"])


def fetch_shfe_gold_mapping(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Publish the daily AU main-contract mapping without synthesizing prices."""

    _require_symbol(symbol)
    client = _client(pro, env_file)
    frames = [
        _frame(
            client.fut_mapping(
                ts_code=_VENDOR_CONTINUOUS_SYMBOL,
                start_date=chunk_start,
                end_date=chunk_end,
            )
        )
        for chunk_start, chunk_end in _year_slices(start_date, end_date)
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise EmptyDataError("Tushare returned no SHFE gold main-contract mapping")
    raw = pd.concat(frames, ignore_index=True)
    _require_columns(
        raw,
        {"ts_code", "trade_date", "mapping_ts_code"},
        "SHFE gold main-contract mapping",
    )
    output = raw[["trade_date", "ts_code", "mapping_ts_code"]].rename(
        columns={
            "trade_date": "Date",
            "ts_code": "ContinuousSymbol",
            "mapping_ts_code": "Contract",
        }
    )
    output["Date"] = pd.to_datetime(output["Date"].astype(str), errors="raise").dt.normalize()
    output["ContinuousSymbol"] = _CANONICAL_SYMBOL
    output["Contract"] = output["Contract"].astype(str).str.upper()
    output = output.sort_values(["Date", "ContinuousSymbol"]).reset_index(drop=True)
    return output, _metadata(["Date", "ContinuousSymbol"])


def fetch_shfe_gold_holding(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    env_file: str | Path | None = None,
    pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Publish member rankings for the mapped AU main contract on every source date."""

    _require_symbol(symbol)
    client = _client(pro, env_file)
    mapping, _ = fetch_shfe_gold_mapping(
        symbol,
        start_date,
        end_date,
        pro=client,
    )
    frames: list[pd.DataFrame] = []
    for chunk_start, chunk_end in _month_slices(start_date, end_date):
        month_start = pd.Timestamp(chunk_start)
        month_end = pd.Timestamp(chunk_end)
        month_mapping = mapping.loc[mapping["Date"].between(month_start, month_end)].copy()
        for contract in sorted(month_mapping["Contract"].unique()):
            raw = _frame(
                client.fut_holding(
                    symbol=str(contract).split(".")[0],
                    start_date=chunk_start,
                    end_date=chunk_end,
                    exchange=_EXCHANGE,
                    fields=(
                        "trade_date,symbol,broker,vol,vol_chg,long_hld,long_chg,short_hld,short_chg"
                    ),
                )
            )
            if raw.empty:
                continue
            raw["Date"] = pd.to_datetime(
                raw["trade_date"].astype(str), errors="raise"
            ).dt.normalize()
            allowed_dates = set(
                month_mapping.loc[month_mapping["Contract"].eq(contract), "Date"].tolist()
            )
            raw = raw.loc[raw["Date"].isin(allowed_dates)].copy()
            if not raw.empty:
                raw["Contract"] = str(contract).upper()
                frames.append(raw)
    if not frames:
        raise EmptyDataError("Tushare returned no mapped SHFE gold holding rankings")
    raw = pd.concat(frames, ignore_index=True)
    required = {
        "Date",
        "Contract",
        "broker",
        "vol",
        "vol_chg",
        "long_hld",
        "long_chg",
        "short_hld",
        "short_chg",
    }
    _require_columns(raw, required, "SHFE gold main-contract holding rankings")
    output = raw[
        [
            "Date",
            "Contract",
            "broker",
            "vol",
            "vol_chg",
            "long_hld",
            "long_chg",
            "short_hld",
            "short_chg",
        ]
    ].rename(
        columns={
            "broker": "Broker",
            "vol": "Volume",
            "vol_chg": "VolumeChange",
            "long_hld": "LongHolding",
            "long_chg": "LongChange",
            "short_hld": "ShortHolding",
            "short_chg": "ShortChange",
        }
    )
    output["Broker"] = output["Broker"].astype(str).str.strip()
    if output["Broker"].eq("").any():
        raise DataContractError("holding rankings contain an empty broker")
    for column in (
        "Volume",
        "VolumeChange",
        "LongHolding",
        "LongChange",
        "ShortHolding",
        "ShortChange",
    ):
        output[column] = pd.to_numeric(output[column], errors="raise")
    output = output.sort_values(["Date", "Contract", "Broker"]).reset_index(drop=True)
    metadata = _metadata(["Date", "Contract", "Broker"])
    metadata.update(
        mapping_symbol=_VENDOR_CONTINUOUS_SYMBOL,
        missing_rank_semantics="null means the member was absent from that ranking, not zero",
    )
    return output, metadata


__all__ = [
    "fetch_shfe_gold_daily",
    "fetch_shfe_gold_holding",
    "fetch_shfe_gold_mapping",
]
