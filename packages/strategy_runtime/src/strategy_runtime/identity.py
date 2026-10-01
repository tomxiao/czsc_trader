"""Candidate content identity, independent of research IDs and machine paths."""

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import re

from .errors import RuntimeContractError
from .models import RuntimeDefinition, canonical_sha256


@dataclass(frozen=True, slots=True, order=True)
class ImplementationDependency:
    name: str
    version: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.name
        ):
            raise RuntimeContractError("dependency name is invalid")
        if not isinstance(self.version, str) or not re.fullmatch(
            r"[0-9][A-Za-z0-9.+!-]*", self.version
        ):
            raise RuntimeContractError("dependency version must be exact")
        object.__setattr__(self, "name", re.sub(r"[-_.]+", "-", self.name).lower())


@dataclass(frozen=True, slots=True)
class CandidateContentIdentity:
    content_sha256: str
    source_sha256: str
    dependency_sha256: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise RuntimeContractError("unsupported candidate identity schema")
        for name in ("content_sha256", "source_sha256", "dependency_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise RuntimeContractError(f"{name} must be lowercase SHA-256")


def _value(value):
    if is_dataclass(value):
        return {item.name: _value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {key: _value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def content_identity(
    definition: RuntimeDefinition,
    source_files: tuple[str, ...],
    dependencies: tuple[ImplementationDependency, ...],
    payload_extensions: Mapping,
) -> CandidateContentIdentity:
    if not isinstance(dependencies, tuple) or not all(
        isinstance(item, ImplementationDependency) for item in dependencies
    ):
        raise RuntimeContractError("dependencies must be a tuple of ImplementationDependency")
    if len({item.name for item in dependencies}) != len(dependencies):
        raise RuntimeContractError("dependency names must be unique")
    dependency_hash = canonical_sha256([_value(item) for item in sorted(dependencies)])
    payload = {
        name: _value(getattr(definition, name))
        for name in (
            "implementation",
            "parameters",
            "inputs",
            "decision",
            "execution",
            "monitoring",
            "capabilities",
            "tradable_symbol",
            "state_mode",
            "history",
        )
    }
    payload.update(
        schema_version=1, source_files=sorted(source_files), dependency_sha256=dependency_hash
    )
    payload["payload_extensions"] = _value(payload_extensions)
    return CandidateContentIdentity(
        canonical_sha256(payload),
        definition.implementation.source_sha256,
        dependency_hash,
    )
