"""Stable public contract for DFLS data publication."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

import pandas as pd


class DataStatus(StrEnum):
    """Outcome of one data publication request."""

    READY = "READY"
    WAITING_SOURCE = "WAITING_SOURCE"
    EMPTY = "EMPTY"
    INCOMPLETE = "INCOMPLETE"
    FAILED = "FAILED"


class Dataset(StrEnum):
    """Datasets currently exposed through the stable DFLS facade."""

    ETF_OHLCV = "etf.ohlcv"
    ETF_UNADJUSTED_DAILY = "etf.unadjusted_daily"
    STOCK_OHLCV = "stock.ohlcv"
    STOCK_UNADJUSTED_DAILY = "stock.unadjusted_daily"
    SHIBOR_DAILY = "macro.shibor_daily"
    US_REAL_YIELD_DAILY = "macro.us_real_yield_daily"
    USDCNH_DAILY = "fx.usdcnh_daily"
    FXCM_DAILY = "fx.fxcm_daily"
    SGE_GOLD_DAILY = "metal.sge_gold_daily"
    FUTURES_SHFE_GOLD_DAILY = "futures.shfe_gold.daily"
    FUTURES_SHFE_GOLD_MAPPING = "futures.shfe_gold.mapping"
    FUTURES_SHFE_GOLD_HOLDING = "futures.shfe_gold.holding"
    DOMESTIC_INDEX_DAILY = "index.domestic_daily"
    CN_CPI_MONTHLY = "macro.cn_cpi_monthly"
    CN_PPI_MONTHLY = "macro.cn_ppi_monthly"
    CN_MONEY_MONTHLY = "macro.cn_money_monthly"
    INDEX_DAILY_BASIC = "index.daily_basic"
    ETF_SHARE_SIZE = "etf.share_size"
    GLOBAL_INDEX_DAILY = "index.global_daily"
    VIX_DAILY = "index.vix_daily"
    INDEX_CONSTITUENT_WEIGHT = "index.constituent_weight"
    STOCK_MONEYFLOW = "stock.moneyflow"
    TRADING_CALENDAR = "calendar.trading_sessions"
    STRATEGY_FEATURE_EVIDENCE = "strategy.feature_evidence"


@dataclass(frozen=True, slots=True)
class DataRequest:
    """A bounded, auditable request for one published dataset."""

    dataset: str | Dataset
    symbol: str | None
    start: str
    end: str
    required_cutoff: str | None
    frequency: str = "daily"
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        dataset = str(self.dataset)
        symbol = None if self.symbol is None else self.symbol.strip()
        if not dataset:
            raise ValueError("dataset must not be empty")
        if self.symbol is not None and not symbol:
            raise ValueError("symbol must be None or a non-empty string")
        start = pd.Timestamp(self.start)
        end = pd.Timestamp(self.end)
        if pd.isna(start) or pd.isna(end):
            raise ValueError("start and end must be valid timestamps")
        if start > end:
            raise ValueError("start must not be after end")
        if self.required_cutoff is not None:
            required_cutoff = pd.Timestamp(self.required_cutoff)
            if pd.isna(required_cutoff) or not start <= required_cutoff <= end:
                raise ValueError("required_cutoff must fall within start and end")
        object.__setattr__(self, "dataset", dataset)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


@dataclass(frozen=True, slots=True)
class DataError:
    """Machine-readable publication failure."""

    code: str
    message: str
    retryable: bool = False
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))


@dataclass(frozen=True, slots=True)
class DataIdentity:
    """Identity and lineage of a successfully published dataframe."""

    dataset: str
    source: str
    symbol: str | None
    data_start: str
    data_cutoff: str
    content_sha256: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        metadata = dict(self.metadata)
        for field_name in ("source_time_field", "source_calendar", "available_at"):
            value = metadata.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"data identity metadata requires non-empty {field_name}")
            metadata[field_name] = value.strip()
        object.__setattr__(self, "metadata", MappingProxyType(metadata))


@dataclass(frozen=True, slots=True)
class DataResult:
    """Result returned by DFLS; non-ready outcomes never contain usable data."""

    status: DataStatus
    dataframe: pd.DataFrame = field(default_factory=pd.DataFrame)
    identity: DataIdentity | None = None
    error: DataError | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ready = self.status is DataStatus.READY
        if ready and (self.dataframe.empty or self.identity is None or self.error is not None):
            raise ValueError("READY requires non-empty data and identity without error")
        if not ready and (not self.dataframe.empty or self.identity is not None):
            raise ValueError("non-READY result must not expose data or identity")
        if not ready and self.error is None:
            raise ValueError(f"{self.status} requires an error")

    @property
    def ready(self) -> bool:
        return self.status is DataStatus.READY
