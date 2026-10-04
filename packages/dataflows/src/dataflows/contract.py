"""Stable public contract for DFLS data publication."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path, PureWindowsPath
import re
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

import pandas as pd

FXCM_AVAILABILITY_RULE = (
    "conservative source date + 2 calendar days at 08:00 Asia/Shanghai; "
    "vendor publication timestamp unverified"
)

ETF_INTRADAY_OBSERVATION_RULE = (
    "unadjusted bar close Asia/Shanghai market-observation assumption; "
    "historical vendor publication and live-feed latency unverified"
)


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
    ETF_UNADJUSTED_INTRADAY = "etf.unadjusted_intraday"
    ETF_CREATION_REDEMPTION_BASKET = "etf.creation_redemption_basket"
    STOCK_OHLCV = "stock.ohlcv"
    STOCK_UNADJUSTED_DAILY = "stock.unadjusted_daily"
    SHIBOR_DAILY = "macro.shibor_daily"
    US_REAL_YIELD_DAILY = "macro.us_real_yield_daily"
    US_NOMINAL_YIELD_DAILY = "macro.us_nominal_yield_daily"
    US_POLICY_UNCERTAINTY_DAILY = "macro.us_policy_uncertainty_daily"
    USDCNH_DAILY = "fx.usdcnh_daily"
    FXCM_DAILY = "fx.fxcm_daily"
    SGE_GOLD_DAILY = "metal.sge_gold_daily"
    FUTURES_SHFE_GOLD_DAILY = "futures.shfe_gold.daily"
    FUTURES_SHFE_GOLD_MAPPING = "futures.shfe_gold.mapping"
    FUTURES_SHFE_GOLD_HOLDING = "futures.shfe_gold.holding"
    DOMESTIC_INDEX_DAILY = "index.domestic_daily"
    DOMESTIC_INDEX_CLOSE_DAILY = "index.domestic_close_daily"
    DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY = "index.domestic_close_turnover_daily"
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
    SELL_SIDE_FORECAST = "stock.sell_side_forecast"
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
    minimum_observations: int = 1
    minimum_sessions: int = 0

    def __post_init__(self) -> None:
        for field_name in ("maximum_start_lag_days", "minimum_observations", "minimum_sessions"):
            value = getattr(self, field_name)
            minimum = 1 if field_name == "minimum_observations" else 0
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{field_name} must be an integer >= {minimum}")


def _timestamp(value: str, name: str) -> pd.Timestamp:
    """Accept explicit ISO dates/timestamps, never locale-dependent dates."""
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})?)?",
        value,
    ):
        raise ValueError(f"{name} must be an ISO date or timestamp")
    try:
        result = pd.Timestamp(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a valid ISO date or timestamp") from exc
    if pd.isna(result):
        raise ValueError(f"{name} must be a valid timestamp")
    return result


def _relative_path(path: Path, name: str) -> None:
    if not isinstance(path, Path):
        raise TypeError(f"{name} must be a Path")
    windows = PureWindowsPath(str(path))
    if (not path.parts or path.is_absolute() or windows.drive or windows.root
            or ".." in path.parts or ".." in windows.parts):
        raise ValueError(f"{name} must be a non-empty relative path without '..'")


def _sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 hexadecimal digest")


@dataclass(frozen=True, slots=True)
class NoParameters:
    """A dataset without additional source parameters."""


@dataclass(frozen=True, slots=True)
class PcfParameters:
    verify_official_pcf_components: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.verify_official_pcf_components, bool):
            raise TypeError("verify_official_pcf_components must be bool")


@dataclass(frozen=True, slots=True)
class MoneyflowParameters:
    trading_dates: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.trading_dates, tuple) or not self.trading_dates:
            raise ValueError("trading_dates must be a non-empty tuple")
        for value in self.trading_dates:
            _timestamp(value, "trading_dates item")
            if len(value) != 10:
                raise ValueError("trading_dates items must be ISO dates")
        if tuple(sorted(set(self.trading_dates))) != self.trading_dates:
            raise ValueError("trading_dates must be unique and ascending")


@dataclass(frozen=True, slots=True)
class EvidenceParameters:
    repository_root: Path
    source_path: str
    source_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.repository_root, Path) or not self.repository_root.is_absolute():
            raise ValueError("repository_root must be an absolute Path")
        if not isinstance(self.source_path, str) or not self.source_path.strip():
            raise ValueError("source_path must be a non-empty relative path")
        _relative_path(Path(self.source_path), "source_path")
        _sha256(self.source_sha256, "source_sha256")


DataParameters = NoParameters | PcfParameters | MoneyflowParameters | EvidenceParameters


@dataclass(frozen=True, slots=True)
class DataRequest:
    """A bounded, auditable request for one published dataset."""

    dataset: str | Dataset
    symbol: str | None
    start: str
    end: str
    required_cutoff: str | None
    frequency: str = "daily"
    parameters: DataParameters = field(default_factory=NoParameters)
    coverage: DataCoverageRequirement | None = None

    def __post_init__(self) -> None:
        dataset = Dataset(self.dataset)
        if self.symbol is not None and not isinstance(self.symbol, str):
            raise TypeError("symbol must be None or a non-empty string")
        symbol = None if self.symbol is None else self.symbol.strip()
        if self.symbol is not None and not symbol:
            raise ValueError("symbol must be None or a non-empty string")
        start = _timestamp(self.start, "start")
        end = _timestamp(self.end, "end")
        if len(self.end) == 10:
            end += pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        if str(start.tzinfo) != str(end.tzinfo):
            raise ValueError("start and end must use the same timezone")
        if start > end:
            raise ValueError("start must not be after end")
        if self.required_cutoff is not None:
            required_cutoff = _timestamp(self.required_cutoff, "required_cutoff")
            if str(required_cutoff.tzinfo) != str(start.tzinfo):
                raise ValueError("required_cutoff must use the request timezone")
            if not start <= required_cutoff <= end:
                raise ValueError("required_cutoff must fall within start and end")
        if self.coverage is not None and not isinstance(self.coverage, DataCoverageRequirement):
            raise TypeError("coverage must be DataCoverageRequirement or None")
        intraday = {"1m", "5m", "15m", "30m"}
        frequencies = {"daily"}
        if dataset in {Dataset.ETF_OHLCV, Dataset.STOCK_OHLCV}:
            frequencies = {"daily", "weekly", *intraday}
        elif dataset is Dataset.ETF_UNADJUSTED_INTRADAY:
            frequencies = intraday
        if not isinstance(self.frequency, str) or self.frequency not in frequencies:
            raise ValueError(f"{dataset} frequency must be one of {sorted(frequencies)}")
        allowed = {
            Dataset.ETF_CREATION_REDEMPTION_BASKET: (NoParameters, PcfParameters),
            Dataset.STOCK_MONEYFLOW: (NoParameters, MoneyflowParameters),
            Dataset.STRATEGY_FEATURE_EVIDENCE: (EvidenceParameters,),
        }.get(dataset, (NoParameters,))
        if type(self.parameters) not in allowed:
            raise TypeError(f"parameters are not valid for {dataset}")
        if isinstance(self.parameters, MoneyflowParameters):
            if symbol is not None:
                raise ValueError("explicit trading_dates require an all-market request")
            for value in self.parameters.trading_dates:
                day = pd.Timestamp(value)
                if start.tzinfo is not None:
                    day = day.tz_localize(start.tzinfo)
                if not start.normalize() <= day <= end.normalize():
                    raise ValueError("trading_dates must fall within the request range")
        object.__setattr__(self, "dataset", dataset)
        object.__setattr__(self, "symbol", symbol)


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
    prepared: PreparedDataRef | None = None

    def __post_init__(self) -> None:
        ready = self.status is DataStatus.READY
        if ready and (self.dataframe.empty or self.identity is None or self.error is not None):
            raise ValueError("READY requires non-empty data and identity without error")
        if not ready and (not self.dataframe.empty or self.identity is not None):
            raise ValueError("non-READY result must not expose data or identity")
        if not ready and self.error is None:
            raise ValueError(f"{self.status} requires an error")
        if self.prepared is not None and (not ready or not isinstance(self.prepared, PreparedDataRef)):
            raise ValueError("prepared reference requires a READY result and PreparedDataRef")

    @property
    def ready(self) -> bool:
        return self.status is DataStatus.READY


@dataclass(frozen=True, slots=True)
class DataSpace:
    """Relative storage location owned and managed by one DFLS instance."""

    path: Path

    def __post_init__(self) -> None:
        _relative_path(self.path, "DataSpace.path")


class PreparePolicy(StrEnum):
    REUSE = "REUSE"
    REFRESH = "REFRESH"


class PrepareStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class PreparedDataRef:
    """Stable, serializable locator for one complete preparation record."""

    space_id: UUID
    preparation_id: UUID
    manifest_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.space_id, UUID) or not isinstance(self.preparation_id, UUID):
            raise TypeError("space_id and preparation_id must be UUID instances")
        _sha256(self.manifest_sha256, "manifest_sha256")


@dataclass(frozen=True, slots=True)
class ItemPrepareResult:
    request: DataRequest
    status: DataStatus
    identity: DataIdentity | None = None
    error: DataError | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, DataRequest) or not isinstance(self.status, DataStatus):
            raise TypeError("request and status must be DataRequest and DataStatus")
        if self.status is DataStatus.READY:
            if not isinstance(self.identity, DataIdentity) or self.error is not None:
                raise ValueError("READY preparation item requires identity without error")
            if self.identity.dataset != self.request.dataset or self.identity.symbol != self.request.symbol:
                raise ValueError("preparation identity must match the request")
        elif self.identity is not None or not isinstance(self.error, DataError):
            raise ValueError("non-READY preparation item requires error without identity")

    @property
    def ready(self) -> bool:
        return self.status is DataStatus.READY


@dataclass(frozen=True, slots=True)
class PrepareResult:
    status: PrepareStatus
    items: tuple[ItemPrepareResult, ...]
    reference: PreparedDataRef | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, PrepareStatus):
            raise TypeError("status must be PrepareStatus")
        if not isinstance(self.items, tuple) or not self.items:
            raise ValueError("items must be a non-empty tuple")
        if any(not isinstance(item, ItemPrepareResult) for item in self.items):
            raise TypeError("items must contain ItemPrepareResult instances")
        successful = sum(item.ready for item in self.items)
        expected = (PrepareStatus.READY if successful == len(self.items)
                    else PrepareStatus.PARTIAL if successful else PrepareStatus.FAILED)
        if self.status is not expected:
            raise ValueError("preparation status must match item outcomes")
        if self.status is PrepareStatus.READY:
            if not isinstance(self.reference, PreparedDataRef):
                raise ValueError("READY preparation requires PreparedDataRef")
        elif self.reference is not None:
            raise ValueError("incomplete preparation must not publish a reference")

    @property
    def ready(self) -> bool:
        return self.status is PrepareStatus.READY


Provider = Callable[[DataRequest], tuple[pd.DataFrame, Mapping[str, Any]]]


@dataclass(frozen=True, slots=True)
class ProviderBinding:
    """Provider implementation and revision used to identify prepared assets."""

    name: str
    revision: str
    fetch: Provider

    def __post_init__(self) -> None:
        for name in ("name", "revision"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"provider {name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        if not callable(self.fetch):
            raise TypeError("provider fetch must be callable")


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Host-owned credentials and optional explicit dataset bindings."""

    bindings: Mapping[Dataset, ProviderBinding] | None = None
    env_file: Path | None = None

    def __post_init__(self) -> None:
        if self.env_file is not None and not isinstance(self.env_file, Path):
            raise TypeError("env_file must be Path or None")
        if self.bindings is not None:
            if not isinstance(self.bindings, Mapping):
                raise TypeError("bindings must be a Mapping or None")
            for dataset, binding in self.bindings.items():
                if not isinstance(dataset, Dataset) or not isinstance(binding, ProviderBinding):
                    raise TypeError("bindings must map Dataset to ProviderBinding")
            object.__setattr__(self, "bindings", MappingProxyType(dict(self.bindings)))
