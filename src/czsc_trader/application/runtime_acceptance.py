"""Typed, side-effect-free runtime readiness for prospective releases."""

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from pathlib import Path

from strategy_manager import StrategyVersion, canonical_sha256
from strategy_runtime import RuntimeBinding, RuntimeDefinition, StrategyRelease, StrategyRuntime


def prospective_release(version: StrategyVersion) -> StrategyRelease:
    release_hash = version.release_hash or canonical_sha256(version.release_payload())
    return StrategyRelease.from_mapping(replace(version, release_hash=release_hash).to_dict())


def _plain(value):
    if is_dataclass(value):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class RuntimeReadiness:
    release_id: str
    release_hash: str
    identity_kind: str
    content_sha256: str

    def __post_init__(self):
        from strategy_manager.freeze_contracts import _hash

        if self.identity_kind not in {"CANDIDATE", "RELEASE"} or not self.release_id:
            raise ValueError("invalid runtime readiness identity")
        _hash(self.release_hash)
        _hash(self.content_sha256)


def runtime_readiness(definition: RuntimeDefinition) -> RuntimeReadiness:
    if type(definition) is not RuntimeDefinition:
        raise TypeError("runtime readiness requires RuntimeDefinition")
    payload = _plain(definition)
    for name in ("version", "release_id", "release_hash", "identity_kind", "candidate_id"):
        payload.pop(name)
    return RuntimeReadiness(
        definition.release_id,
        definition.release_hash,
        definition.identity_kind,
        canonical_sha256(payload),
    )


def validate_runtime_readiness(
    version: StrategyVersion, *, source_root: Path | None = None, runtime_binding: RuntimeBinding | None = None
) -> RuntimeReadiness:
    return runtime_readiness(
        StrategyRuntime().describe(prospective_release(version), source_root=source_root, runtime_binding=runtime_binding)
    )


def require_same_runtime_content(candidate: RuntimeReadiness, release: RuntimeReadiness) -> None:
    if type(candidate) is not RuntimeReadiness or type(release) is not RuntimeReadiness:
        raise TypeError("runtime comparison requires typed readiness")
    if candidate.identity_kind != "CANDIDATE" or release.identity_kind != "RELEASE":
        raise ValueError("freeze requires candidate-to-release runtime identities")
    if candidate.content_sha256 != release.content_sha256:
        raise ValueError("frozen runtime differs from reviewed candidate")


def require_runtime_readiness(version: StrategyVersion) -> RuntimeReadiness:
    return validate_runtime_readiness(version)
