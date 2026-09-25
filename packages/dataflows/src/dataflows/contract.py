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
    US_NOMINAL_YIELD_DAILY = "macro.us_nominal_yield_daily"
    USDCNH_DAILY = "fx.usdcnh_daily"
    FXCM_DAILY = "fx.fxcm_daily"
    SGE_GOLD_DAILY = "metal.sge_gold_daily"
    FUTURES_SHFE_GOLD_DAILY = "futures.shfe_gold.daily"
    FUTURES_SHFE_GOLD_MAPPING = "futures.shfe_gold.mapping"
    FUTURES_SHFE_GOLD_HOLDING = "futures.shfe_gold.holding"
    DOMESTIC_INDEX_DAILY = "index.domestic_daily"
    CN_CPI_MONTHLY = "macro.cn_cpi_monthly"
    US_CPI_RELEASE = "macro.us_cpi_release"
    US_ISM_PMI_RELEASE = "macro.us_ism_pmi_release"
    US_FEDERAL_BUDGET_RELEASE = "macro.us_federal_budget_release"
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


class TemporalAlignment(StrEnum):
    """How source availability is aligned to a decision timestamp."""

    EXACT_SESSION = "EXACT_SESSION"
    STRICT_PRIOR = "STRICT_PRIOR"
    LATEST_AVAILABLE = "LATEST_AVAILABLE"


class RequestRangePolicy(StrEnum):
    """Provider interpretation of the requested start/end range."""

    EXACT = "EXACT"
    CALENDAR_MONTH = "CALENDAR_MONTH"


@dataclass(frozen=True, slots=True)
class DataTemporalContract:
    """Typed time semantics published with a READY dataset."""

    source_time_field: str
    availability_time_field: str
    source_calendar: str
    available_at: str
    request_range_policy: RequestRangePolicy

    def __post_init__(self) -> None:
        for field_name in (
            "source_time_field",
            "availability_time_field",
            "source_calendar",
            "available_at",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())
        if not isinstance(self.request_range_policy, RequestRangePolicy):
            object.__setattr__(
                self,
                "request_range_policy",
                RequestRangePolicy(self.request_range_policy),
            )


@dataclass(frozen=True, slots=True)
class DataTemporalRequirement:
    """Causal alignment requested by research code."""

    alignment: TemporalAlignment
    decision_time: str
    max_staleness_days: int | None = None
    warmup_sessions: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.alignment, TemporalAlignment):
            object.__setattr__(self, "alignment", TemporalAlignment(self.alignment))
        if not isinstance(self.decision_time, str) or not self.decision_time.strip():
            raise ValueError("decision_time must be a non-empty string")
        object.__setattr__(self, "decision_time", self.decision_time.strip())
        for field_name in ("max_staleness_days", "warmup_sessions"):
            value = getattr(self, field_name)
            if value is None and field_name == "max_staleness_days":
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class DataCoverageRequirement:
    """Minimum history coverage required before DFLS may return READY."""

    maximum_start_lag_days: int = 0
    minimum_rows: int = 1

    def __post_init__(self) -> None:
        for field_name in ("maximum_start_lag_days", "minimum_rows"):
            value = getattr(self, field_name)
            minimum = 0 if field_name == "maximum_start_lag_days" else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{field_name} must be an integer >= {minimum}")


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
    coverage: DataCoverageRequirement | None = None

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
        if self.coverage is not None and not isinstance(self.coverage, DataCoverageRequirement):
            raise TypeError("coverage must be DataCoverageRequirement or None")
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
        for field_name in (
            "source_time_field",
            "availability_time_field",
            "source_calendar",
            "available_at",
            "request_range_policy",
        ):
            value = metadata.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"data identity metadata requires non-empty {field_name}")
            metadata[field_name] = value.strip()
        object.__setattr__(self, "metadata", MappingProxyType(metadata))

    @property
    def temporal_contract(self) -> DataTemporalContract:
        return DataTemporalContract(
            source_time_field=self.metadata["source_time_field"],
            availability_time_field=self.metadata["availability_time_field"],
            source_calendar=self.metadata["source_calendar"],
            available_at=self.metadata["available_at"],
            request_range_policy=RequestRangePolicy(self.metadata["request_range_policy"]),
        )


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
