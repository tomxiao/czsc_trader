"""Caller-owned plans and explicit DFLS references for strategy calculation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path
from types import MappingProxyType
from uuid import UUID

from dataflows import (
    DataCoverageRequirement, DataRequest, EvidenceParameters, MoneyflowParameters,
    NoParameters, PcfParameters, PreparedDataRef,
)

from .contracts import StrategyIdentity, TradableWindow
from .errors import RuntimeContractError
from .models import canonical_sha256


def _request_dict(request: DataRequest) -> dict:
    parameters = {item.name: getattr(request.parameters, item.name) for item in fields(request.parameters)}
    if isinstance(request.parameters, EvidenceParameters):
        parameters["repository_root"] = str(request.parameters.repository_root)
    if isinstance(request.parameters, MoneyflowParameters):
        parameters["trading_dates"] = list(request.parameters.trading_dates)
    return {
        "dataset": str(request.dataset), "symbol": request.symbol,
        "start": request.start, "end": request.end, "required_cutoff": request.required_cutoff,
        "frequency": request.frequency, "parameters": parameters,
        "parameter_type": type(request.parameters).__name__,
        "coverage": None if request.coverage is None else {
            item.name: getattr(request.coverage, item.name) for item in fields(request.coverage)
        },
    }


def _request_from_dict(raw: Mapping) -> DataRequest:
    value = dict(raw)
    kind = value.pop("parameter_type")
    parameters = dict(value.pop("parameters"))
    types = {item.__name__: item for item in (NoParameters, PcfParameters, MoneyflowParameters, EvidenceParameters)}
    if kind == "EvidenceParameters":
        parameters["repository_root"] = Path(parameters["repository_root"])
    elif kind == "MoneyflowParameters":
        parameters["trading_dates"] = tuple(parameters["trading_dates"])
    value["parameters"] = types[kind](**parameters)
    if value.get("coverage") is not None:
        value["coverage"] = DataCoverageRequirement(**value["coverage"])
    return DataRequest(**value)


@dataclass(frozen=True, slots=True)
class StrategyInputPlan:
    """Inputs and calculation dates derived from a specific calendar version."""

    strategy: StrategyIdentity
    tradable_window: TradableWindow
    calendar_name: str
    calendar_sha256: str
    requests: Mapping[str, DataRequest]
    calendar_dates: tuple[date, ...]
    signal_dates: Mapping[date, date]
    calculation_dates: tuple[date, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, StrategyIdentity) or not isinstance(self.tradable_window, TradableWindow):
            raise RuntimeContractError("input plan requires strategy identity and tradable window")
        if not isinstance(self.requests, Mapping) or not self.requests:
            raise RuntimeContractError("input plan requires named requests")
        if any(not isinstance(key, str) or not key or not isinstance(value, DataRequest)
               for key, value in self.requests.items()):
            raise RuntimeContractError("input plan requires named DataRequest instances")
        if self.calendar_name not in self.requests:
            raise RuntimeContractError("input plan calendar request is missing")
        if (not isinstance(self.calendar_sha256, str) or len(self.calendar_sha256) != 64
                or any(item not in "0123456789abcdef" for item in self.calendar_sha256)):
            raise RuntimeContractError("input plan calendar hash is invalid")
        for name in ("calendar_dates", "calculation_dates"):
            values = getattr(self, name)
            if (not isinstance(values, tuple) or not values or any(type(item) is not date for item in values)
                    or tuple(sorted(set(values))) != values):
                raise RuntimeContractError(f"input plan {name} must be ordered unique dates")
        if (not isinstance(self.signal_dates, Mapping) or not self.signal_dates
                or any(type(key) is not date or type(value) is not date or value >= key
                       for key, value in self.signal_dates.items())):
            raise RuntimeContractError("input plan signal dates are invalid")
        object.__setattr__(self, "requests", MappingProxyType(dict(sorted(self.requests.items()))))
        object.__setattr__(self, "signal_dates", MappingProxyType(dict(sorted(self.signal_dates.items()))))

    @property
    def available_through(self) -> date:
        return self.calculation_dates[-1]

    def to_dict(self) -> dict:
        return {
            "strategy": {item.name: getattr(self.strategy, item.name) for item in fields(self.strategy)},
            "tradable_window": {"start": self.tradable_window.start.isoformat(), "end": self.tradable_window.end.isoformat()},
            "calendar_name": self.calendar_name, "calendar_sha256": self.calendar_sha256,
            "requests": {name: _request_dict(request) for name, request in self.requests.items()},
            "calendar_dates": [item.isoformat() for item in self.calendar_dates],
            "signal_dates": {key.isoformat(): value.isoformat() for key, value in self.signal_dates.items()},
            "calculation_dates": [item.isoformat() for item in self.calculation_dates],
        }

    @classmethod
    def from_mapping(cls, value: Mapping) -> StrategyInputPlan:
        try:
            raw = dict(value)
            raw["strategy"] = StrategyIdentity(**raw["strategy"])
            raw["tradable_window"] = TradableWindow(**{key: date.fromisoformat(item) for key, item in raw["tradable_window"].items()})
            raw["requests"] = {key: _request_from_dict(item) for key, item in raw["requests"].items()}
            raw["calendar_dates"] = tuple(date.fromisoformat(item) for item in raw["calendar_dates"])
            raw["calculation_dates"] = tuple(date.fromisoformat(item) for item in raw["calculation_dates"])
            raw["signal_dates"] = {date.fromisoformat(key): date.fromisoformat(item) for key, item in raw["signal_dates"].items()}
            return cls(**raw)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise RuntimeContractError("invalid strategy input plan") from exc


@dataclass(frozen=True, slots=True)
class StrategyInputBinding:
    """A complete strategy input plan bound to one immutable preparation."""

    plan: StrategyInputPlan
    prepared: PreparedDataRef

    def __post_init__(self) -> None:
        if not isinstance(self.plan, StrategyInputPlan) or not isinstance(self.prepared, PreparedDataRef):
            raise RuntimeContractError("input binding requires StrategyInputPlan and PreparedDataRef")

    @property
    def identity(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict:
        return {"schema_version": 1, "plan": self.plan.to_dict(), "prepared": {
            "space_id": str(self.prepared.space_id),
            "preparation_id": str(self.prepared.preparation_id),
            "manifest_sha256": self.prepared.manifest_sha256,
        }}

    @classmethod
    def from_mapping(cls, value: Mapping) -> StrategyInputBinding:
        try:
            if set(value) != {"schema_version", "plan", "prepared"} or value["schema_version"] != 1:
                raise ValueError("unsupported input binding format")
            reference = dict(value["prepared"])
            reference["space_id"] = UUID(reference["space_id"])
            reference["preparation_id"] = UUID(reference["preparation_id"])
            return cls(StrategyInputPlan.from_mapping(value["plan"]), PreparedDataRef(**reference))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise RuntimeContractError("invalid strategy input binding") from exc
