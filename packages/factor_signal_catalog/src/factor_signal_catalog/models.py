from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from typing import Any


class CatalogStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    READY = "READY"
    DEPRECATED = "DEPRECATED"


class CatalogValidationError(ValueError):
    pass


def _definition_sha256(payload: dict[str, object]) -> str:
    def check(value):
        if isinstance(value, dict):
            if any(type(key) is not str for key in value):
                raise CatalogValidationError("definition object keys must be strings")
            for item in value.values():
                check(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                check(item)

    check(payload)
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise CatalogValidationError("definition must contain finite JSON values") from exc
    return sha256(encoded).hexdigest()


def _required(payload: dict[str, Any], fields: set[str], kind: str) -> None:
    missing = sorted(fields.difference(payload))
    if missing:
        raise CatalogValidationError(f"{kind} missing fields: {missing}")
    unknown = sorted(set(payload).difference(fields))
    if unknown:
        raise CatalogValidationError(f"{kind} unknown fields: {unknown}")


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise CatalogValidationError(f"{field} must be an array of non-empty strings")
    return tuple(value)


@dataclass(frozen=True)
class InformationFamily:
    family_id: str
    name: str
    description: str
    status: CatalogStatus

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "InformationFamily":
        _required(payload, {"family_id", "name", "description", "status"}, "family")
        return cls(
            str(payload["family_id"]),
            str(payload["name"]),
            str(payload["description"]),
            CatalogStatus(str(payload["status"])),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "family_id": self.family_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class FactorDefinition:
    factor_id: str
    name: str
    description: str
    information_family: str
    tags: tuple[str, ...]
    inputs: tuple[str, ...]
    provider: str
    implementation: str
    formula: str
    availability: str
    causality: str
    parameters: dict[str, object]
    status: CatalogStatus
    version: int

    @property
    def definition_sha256(self) -> str:
        return _definition_sha256(self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FactorDefinition":
        required = {
            "factor_id", "name", "description", "information_family", "tags", "inputs",
            "provider", "implementation", "formula", "availability", "causality",
            "parameters", "status", "version",
        }
        _required(payload, required, "factor")
        if not isinstance(payload["parameters"], dict):
            raise CatalogValidationError("factor parameters must be an object")
        return cls(
            str(payload["factor_id"]), str(payload["name"]), str(payload["description"]),
            str(payload["information_family"]), _strings(payload["tags"], "factor tags"),
            _strings(payload["inputs"], "factor inputs"), str(payload["provider"]),
            str(payload["implementation"]), str(payload["formula"]),
            str(payload["availability"]), str(payload["causality"]),
            dict(payload["parameters"]), CatalogStatus(str(payload["status"])),
            int(payload["version"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "factor_id": self.factor_id, "name": self.name, "description": self.description,
            "information_family": self.information_family, "tags": list(self.tags),
            "inputs": list(self.inputs), "provider": self.provider,
            "implementation": self.implementation, "formula": self.formula,
            "availability": self.availability, "causality": self.causality,
            "parameters": self.parameters, "status": self.status.value, "version": self.version,
        }


@dataclass(frozen=True)
class SignalDefinition:
    signal_id: str
    name: str
    description: str
    information_family: str
    tags: tuple[str, ...]
    factor_ids: tuple[str, ...]
    embedded_factor: bool
    provider: str
    implementation: str
    rule: str
    states: tuple[str, ...]
    parameters: dict[str, object]
    availability: str
    causality: str
    status: CatalogStatus
    version: int

    @property
    def definition_sha256(self) -> str:
        return _definition_sha256(self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SignalDefinition":
        required = {
            "signal_id", "name", "description", "information_family", "tags", "factor_ids",
            "embedded_factor", "provider", "implementation", "rule", "states", "parameters",
            "availability", "causality", "status", "version",
        }
        _required(payload, required, "signal")
        if not isinstance(payload["parameters"], dict):
            raise CatalogValidationError("signal parameters must be an object")
        return cls(
            str(payload["signal_id"]), str(payload["name"]), str(payload["description"]),
            str(payload["information_family"]), _strings(payload["tags"], "signal tags"),
            _strings(payload["factor_ids"], "signal factor_ids"), bool(payload["embedded_factor"]),
            str(payload["provider"]), str(payload["implementation"]), str(payload["rule"]),
            _strings(payload["states"], "signal states"), dict(payload["parameters"]),
            str(payload["availability"]), str(payload["causality"]),
            CatalogStatus(str(payload["status"])), int(payload["version"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "signal_id": self.signal_id, "name": self.name, "description": self.description,
            "information_family": self.information_family, "tags": list(self.tags),
            "factor_ids": list(self.factor_ids), "embedded_factor": self.embedded_factor,
            "provider": self.provider, "implementation": self.implementation, "rule": self.rule,
            "states": list(self.states), "parameters": self.parameters,
            "availability": self.availability, "causality": self.causality,
            "status": self.status.value, "version": self.version,
        }
