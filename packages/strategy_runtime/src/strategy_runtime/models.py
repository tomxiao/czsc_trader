"""Immutable value objects and runtime records for SRT."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

import pandas as pd

from .errors import RuntimeContractError
from .alignment import InputAlignment


_FAMILY_ID = re.compile(r"S\d{3,}")
_VERSION = re.compile(r"v\d+")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_A_SHARE_SYMBOL = re.compile(r"\d{6}\.(?:SH|SZ|BJ)")


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        _thaw_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _freeze_json(value: Any, field_name: str) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                _text(key, f"{field_name} key"): _freeze_json(item, field_name)
                for key, item in value.items()
            }
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item, field_name) for item in value)
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise RuntimeContractError(f"{field_name} must contain only finite JSON values")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeContractError(f"{field_name} must be a non-empty string")
    return value.strip()


def _mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeContractError(f"{field_name} must be a mapping")
    return MappingProxyType(dict(value))


def _json_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeContractError(f"{field_name} must be a mapping")
    return _freeze_json(value, field_name)


def _unique_text(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_text(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise RuntimeContractError(f"{field_name} must contain unique values")
    return normalized


class CutoffRule(StrEnum):
    SIGNAL_SESSION = "SIGNAL_SESSION"
    PREVIOUS_SESSION = "PREVIOUS_SESSION"
    LATEST_AVAILABLE = "LATEST_AVAILABLE"


@dataclass(frozen=True, slots=True)
class ImplementationRef:
    module: str
    qualname: str
    contract_version: int
    source_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "module", _text(self.module, "implementation module"))
        object.__setattr__(self, "qualname", _text(self.qualname, "implementation qualname"))
        if self.contract_version < 1:
            raise RuntimeContractError("implementation contract_version must be positive")
        if not _SHA256.fullmatch(self.source_sha256):
            raise RuntimeContractError("implementation source_sha256 must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ParameterSet:
    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        normalized = _json_mapping(self.values, "parameter values")
        canonical_sha256(normalized)
        object.__setattr__(self, "values", normalized)

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.values)


@dataclass(frozen=True, slots=True)
class InputRequirement:
    name: str
    dataset: str
    subject: str | None
    frequency: str
    lookback_sessions: int
    cutoff_rule: CutoffRule
    maximum_staleness_days: int = 0
    alignment: InputAlignment | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "input name"))
        object.__setattr__(self, "dataset", _text(self.dataset, "input dataset"))
        object.__setattr__(self, "frequency", _text(self.frequency, "input frequency"))
        if self.subject is not None:
            object.__setattr__(self, "subject", _text(self.subject, "input subject"))
        if self.lookback_sessions < 0:
            raise RuntimeContractError("input lookback_sessions must be non-negative")
        if self.maximum_staleness_days < 0:
            raise RuntimeContractError("input maximum_staleness_days must be non-negative")
        if self.cutoff_rule is not CutoffRule.LATEST_AVAILABLE and self.maximum_staleness_days:
            raise RuntimeContractError(
                "maximum_staleness_days is only valid for LATEST_AVAILABLE inputs"
            )
        if self.alignment is not None and not isinstance(self.alignment, InputAlignment):
            raise RuntimeContractError("input alignment must be an InputAlignment")
        if (
            self.alignment is not None
            and self.alignment.maximum_staleness_days is not None
            and self.alignment.maximum_staleness_days != self.maximum_staleness_days
        ):
            raise RuntimeContractError(
                "input and alignment maximum staleness days must match"
            )


@dataclass(frozen=True, slots=True)
class InputContract:
    requirements: tuple[InputRequirement, ...]

    def __post_init__(self) -> None:
        if not self.requirements:
            raise RuntimeContractError("input contract must contain at least one requirement")
        names = [item.name for item in self.requirements]
        if len(names) != len(set(names)):
            raise RuntimeContractError("input requirement names must be unique")


@dataclass(frozen=True, slots=True)
class HistoryPolicy:
    """Declare how much prepared history participates in strategy replay."""

    mode: str = "FULL_PUBLICATION_REPLAY"
    canonical_start: str | None = None
    required_input_start: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"FULL_PUBLICATION_REPLAY", "CANONICAL_REPLAY"}:
            raise RuntimeContractError("history mode is unsupported")
        if self.mode == "CANONICAL_REPLAY":
            if not self.canonical_start:
                raise RuntimeContractError("canonical replay requires canonical_start")
            try:
                date.fromisoformat(self.canonical_start)
            except ValueError as exc:
                raise RuntimeContractError("history canonical_start must be an ISO date") from exc
        elif self.canonical_start is not None:
            raise RuntimeContractError("canonical_start is only valid for CANONICAL_REPLAY")
        if self.required_input_start is not None:
            try:
                input_start = date.fromisoformat(self.required_input_start)
            except ValueError as exc:
                raise RuntimeContractError(
                    "history required_input_start must be an ISO date"
                ) from exc
            if self.canonical_start and input_start > date.fromisoformat(self.canonical_start):
                raise RuntimeContractError("history required_input_start follows canonical_start")

    def preparation_start(self, requested_start: date) -> date:
        if self.required_input_start is not None:
            return min(requested_start, date.fromisoformat(self.required_input_start))
        if self.canonical_start is None:
            return requested_start
        return min(requested_start, date.fromisoformat(self.canonical_start))


@dataclass(frozen=True, slots=True)
class DecisionContract:
    output_kind: str
    minimum_target: float
    maximum_target: float
    effective_time_rule: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_kind", _text(self.output_kind, "decision output_kind"))
        object.__setattr__(
            self,
            "effective_time_rule",
            _text(self.effective_time_rule, "decision effective_time_rule"),
        )
        if not all(math.isfinite(item) for item in (self.minimum_target, self.maximum_target)):
            raise RuntimeContractError("decision target bounds must be finite")
        if self.minimum_target > self.maximum_target:
            raise RuntimeContractError("decision minimum_target exceeds maximum_target")


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    policy_type: str
    settings: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_type", _text(self.policy_type, "execution policy_type"))
        object.__setattr__(self, "settings", _json_mapping(self.settings, "execution settings"))
        canonical_sha256(self.settings)

    def order_type_for(self, side: str) -> str:
        """Return the effective channel-neutral order type for one side."""

        if self.policy_type != "FROZEN_RULE":
            raise RuntimeContractError(
                "order_type_for is only defined for target-position policies"
            )
        normalized = side.upper()
        if normalized == "BUY":
            return str(dict(self.settings["entry"])["order_type"])
        if normalized != "SELL":
            raise RuntimeContractError(f"unsupported target order side: {side}")
        virtual_fill = dict(self.settings.get("virtual_fill", {}))
        if str(virtual_fill.get("sell", "")).lower() == "marketable_limit_at_open":
            return "MARKET"
        return str(dict(self.settings["exit"])["order_type"])


@dataclass(frozen=True, slots=True)
class MonitoringPolicy:
    policy_type: str
    rules: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_type", _text(self.policy_type, "monitoring policy_type"))
        object.__setattr__(self, "rules", _json_mapping(self.rules, "monitoring rules"))
        canonical_sha256(self.rules)


@dataclass(frozen=True, slots=True)
class RequiredCapabilities:
    datasets: tuple[str, ...]
    order_types: tuple[str, ...]
    checkpoints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "datasets", _unique_text(self.datasets, "capability datasets"))
        object.__setattr__(
            self, "order_types", _unique_text(self.order_types, "capability order_types")
        )
        object.__setattr__(
            self, "checkpoints", _unique_text(self.checkpoints, "capability checkpoints")
        )


@dataclass(frozen=True, slots=True)
class RuntimeDefinition:
    schema_version: int
    strategy_family_id: str
    version: str | None
    release_id: str
    release_hash: str
    implementation: ImplementationRef
    parameters: ParameterSet
    inputs: InputContract
    decision: DecisionContract
    execution: ExecutionPolicy
    monitoring: MonitoringPolicy
    capabilities: RequiredCapabilities
    tradable_symbol: str
    state_mode: str = "STATELESS"
    identity_kind: str = "RELEASE"
    candidate_id: str | None = None
    history: HistoryPolicy = field(default_factory=HistoryPolicy)

    def __post_init__(self) -> None:
        if self.schema_version not in {1, 2}:
            raise RuntimeContractError("runtime definition schema_version must be 1 or 2")
        if not _FAMILY_ID.fullmatch(self.strategy_family_id):
            raise RuntimeContractError("strategy_family_id must look like S001")
        if self.identity_kind == "RELEASE":
            if not isinstance(self.version, str) or not _VERSION.fullmatch(self.version):
                raise RuntimeContractError("version must look like v1")
            if self.candidate_id is not None:
                raise RuntimeContractError("release runtime cannot carry a candidate identity")
            if self.release_id != f"{self.strategy_family_id}-{self.version}":
                raise RuntimeContractError("release_id must equal strategy_family_id-version")
        elif self.identity_kind == "CANDIDATE":
            if self.schema_version != 2 or self.version is not None:
                raise RuntimeContractError(
                    "candidate runtime requires schema 2 and no frozen version"
                )
            _candidate_id(self.candidate_id)
            if self.release_id != f"{self.strategy_family_id}-{self.candidate_id}":
                raise RuntimeContractError(
                    "candidate runtime reference differs from candidate identity"
                )
        else:
            raise RuntimeContractError("runtime identity_kind must be RELEASE or CANDIDATE")
        if not _SHA256.fullmatch(self.release_hash):
            raise RuntimeContractError("release_hash must be lowercase SHA-256")
        tradable_symbol = _text(self.tradable_symbol, "tradable_symbol").upper()
        if _A_SHARE_SYMBOL.fullmatch(tradable_symbol) is None:
            raise RuntimeContractError(
                "tradable_symbol must be a canonical A-share instrument"
            )
        object.__setattr__(self, "tradable_symbol", tradable_symbol)
        required_datasets = {item.dataset for item in self.inputs.requirements}
        if not required_datasets.issubset(self.capabilities.datasets):
            raise RuntimeContractError("input datasets must be declared as required capabilities")
        if self.state_mode not in {"STATELESS", "PERSISTED"}:
            raise RuntimeContractError("runtime state_mode must be STATELESS or PERSISTED")

    @property
    def runtime_sha256(self) -> str:
        identity = {
            "release_id": self.release_id,
            "release_hash": self.release_hash,
            "tradable_symbol": self.tradable_symbol,
            "implementation": {
                "module": self.implementation.module,
                "qualname": self.implementation.qualname,
                "contract_version": self.implementation.contract_version,
                "source_sha256": self.implementation.source_sha256,
            },
            "parameters_sha256": self.parameters.sha256,
        }
        # Keep the five existing frozen identities byte-for-byte stable.
        if self.schema_version == 2:
            identity.update(identity_kind=self.identity_kind, candidate_id=self.candidate_id)
            identity["contracts"] = {
                "inputs": [
                    {
                        "name": item.name,
                        "dataset": item.dataset,
                        "subject": item.subject,
                        "frequency": item.frequency,
                        "lookback_sessions": item.lookback_sessions,
                        "cutoff_rule": item.cutoff_rule.value,
                        "maximum_staleness_days": item.maximum_staleness_days,
                        **(
                            {"alignment": item.alignment.identity_payload()}
                            if item.alignment is not None
                            else {}
                        ),
                    }
                    for item in self.inputs.requirements
                ],
                "decision": {
                    "output_kind": self.decision.output_kind,
                    "minimum_target": self.decision.minimum_target,
                    "maximum_target": self.decision.maximum_target,
                    "effective_time_rule": self.decision.effective_time_rule,
                },
                "execution": {
                    "policy_type": self.execution.policy_type,
                    "settings": self.execution.settings,
                },
                "monitoring": {
                    "policy_type": self.monitoring.policy_type,
                    "rules": self.monitoring.rules,
                },
                "capabilities": {
                    "datasets": self.capabilities.datasets,
                    "order_types": self.capabilities.order_types,
                    "checkpoints": self.capabilities.checkpoints,
                },
                "state_mode": self.state_mode,
                "history": {
                    "mode": self.history.mode,
                    "canonical_start": self.history.canonical_start,
                    "required_input_start": self.history.required_input_start,
                },
            }
        return canonical_sha256(identity)


def _candidate_id(value: str | None) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", value):
        raise RuntimeContractError("candidate_id must be a safe non-empty identifier")
    if _VERSION.fullmatch(value):
        raise RuntimeContractError("candidate_id cannot be a frozen version")
    return value


@dataclass(frozen=True, slots=True)
class StrategyCandidate:
    """Immutable research runtime input; lifecycle authority remains with SM.

    Researchers construct a new value for each parameter set. No SM registration
    or frozen version number is needed to run a trial. ``runtime_identity_sha256``
    identifies executable content, not the wider SM submission/claims snapshot.
    """

    strategy_family_id: str
    candidate_id: str
    payload: Mapping[str, Any]
    source_root: Path | None = None

    def __post_init__(self) -> None:
        if not _FAMILY_ID.fullmatch(self.strategy_family_id):
            raise RuntimeContractError("strategy_family_id must look like S001")
        _candidate_id(self.candidate_id)
        object.__setattr__(self, "payload", _json_mapping(self.payload, "candidate payload"))
        if self.source_root is not None:
            object.__setattr__(self, "source_root", Path(self.source_root).resolve())
        if not isinstance(self.payload.get("runtime"), Mapping):
            raise RuntimeContractError("candidate payload must declare its runtime implementation")
        if not isinstance(self.payload.get("parameters"), Mapping):
            raise RuntimeContractError("candidate payload must declare its parameter values")

    @property
    def reference_id(self) -> str:
        return f"{self.strategy_family_id}-{self.candidate_id}"

    @property
    def runtime_identity_sha256(self) -> str:
        return canonical_sha256(
            {
                "strategy_family_id": self.strategy_family_id,
                "candidate_id": self.candidate_id,
                "payload": self.payload,
            }
        )


@dataclass(frozen=True, slots=True, init=False)
class StrategyRelease:
    strategy_family_id: str
    version: str
    release_id: str
    release_hash: str
    payload: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StrategyRelease":
        if not isinstance(value, Mapping):
            raise RuntimeContractError("strategy release must be a mapping")
        raw = dict(value)
        required = {"strategy_id", "version", "release_id", "release_hash", "strategy_payload"}
        missing = required - set(raw)
        if missing:
            raise RuntimeContractError(f"strategy release fields are missing: {sorted(missing)}")
        release_hash = str(raw["release_hash"])
        if not _SHA256.fullmatch(release_hash):
            raise RuntimeContractError("release_hash must be lowercase SHA-256")
        if raw.get("schema_version") in {2, 3}:
            release_payload = {
                "schema_version": raw["schema_version"],
                "strategy_id": raw["strategy_id"],
                "version": raw["version"],
                "release_id": raw["release_id"],
                "strategy_payload": raw["strategy_payload"],
            }
        else:
            release_payload = {key: item for key, item in raw.items() if key != "release_hash"}
        if canonical_sha256(release_payload) != release_hash:
            raise RuntimeContractError("release_hash does not match the complete frozen record")
        instance = object.__new__(cls)
        object.__setattr__(instance, "strategy_family_id", str(raw["strategy_id"]))
        object.__setattr__(instance, "version", str(raw["version"]))
        object.__setattr__(instance, "release_id", str(raw["release_id"]))
        object.__setattr__(instance, "release_hash", release_hash)
        object.__setattr__(
            instance,
            "payload",
            _json_mapping(raw["strategy_payload"], "strategy payload"),
        )
        instance._validate_identity()
        return instance

    def _validate_identity(self) -> None:
        if not _FAMILY_ID.fullmatch(self.strategy_family_id):
            raise RuntimeContractError("strategy_family_id must look like S001")
        if not _VERSION.fullmatch(self.version):
            raise RuntimeContractError("version must look like v1")
        if self.release_id != f"{self.strategy_family_id}-{self.version}":
            raise RuntimeContractError("release_id must equal strategy_family_id-version")


def _daily_prices(frame: pd.DataFrame, field_name: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise RuntimeContractError(f"{field_name} must be a dataframe")
    normalized = frame.rename(
        columns={
            "Date": "dt",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "vol",
            "Amount": "amount",
        }
    ).copy()
    if not {"dt", "close"} <= set(normalized.columns):
        raise RuntimeContractError(f"{field_name} must contain dt and close")
    try:
        normalized["dt"] = pd.to_datetime(normalized["dt"], errors="raise").dt.normalize()
        for column in ("open", "high", "low", "close", "vol", "amount"):
            if column in normalized.columns:
                normalized[column] = pd.to_numeric(
                    normalized[column], errors="raise"
                ).astype("float64")
    except (TypeError, ValueError) as exc:
        raise RuntimeContractError(f"{field_name} has invalid dates or prices") from exc
    if (
        normalized.empty
        or normalized["dt"].isna().any()
        or normalized["dt"].duplicated().any()
        or normalized["close"]
        .map(lambda value: math.isfinite(float(value)) and value > 0)
        .eq(False)
        .any()
    ):
        raise RuntimeContractError(
            f"{field_name} requires unique sessions and positive finite closes"
        )
    return normalized.sort_values("dt").reset_index(drop=True)


@dataclass(frozen=True, slots=True)
class ExecutionPricingData:
    """SRT-owned market facts used to price execution plans."""

    symbol: str
    adjusted_daily: pd.DataFrame
    execution_daily: pd.DataFrame

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _text(self.symbol, "pricing symbol").upper())
        adjusted = _daily_prices(self.adjusted_daily, "adjusted daily prices")
        execution = _daily_prices(self.execution_daily, "execution daily prices")
        adjusted_cutoff = pd.Timestamp(adjusted.iloc[-1]["dt"])
        execution_cutoff = pd.Timestamp(execution.iloc[-1]["dt"])
        if adjusted_cutoff != execution_cutoff:
            raise RuntimeContractError("adjusted and execution pricing cutoffs differ")
        object.__setattr__(self, "adjusted_daily", adjusted)
        object.__setattr__(self, "execution_daily", execution)

    @property
    def identity_hashes(self) -> Mapping[str, str]:
        from dataflows import canonical_frame_sha256

        return MappingProxyType(
            {
                "adjusted_daily": canonical_frame_sha256(self.adjusted_daily),
                "execution_daily": canonical_frame_sha256(self.execution_daily),
            }
        )
