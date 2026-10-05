"""Immutable candidate registration metadata; no runtime dependency."""

from dataclasses import dataclass, fields
from collections.abc import Mapping
from enum import StrEnum
from hashlib import sha256
import json
import math
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType

from .errors import RegistryError, ValidationError
from .models import canonical_sha256


class CandidateIdentityConflict(RegistryError):
    """A persistent candidate key is already bound to different content."""


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValidationError("candidate hash must be lowercase SHA-256")


def _json(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    return value


def _freeze(value):
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) or not key for key in value):
            raise ValidationError("parameter keys must be nonempty strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if (
        value is None
        or isinstance(value, (str, bool, int))
        or isinstance(value, float)
        and math.isfinite(value)
    ):
        return value
    raise ValidationError("parameters must contain finite JSON values")


class _Record:
    def to_dict(self):
        return {field.name: _json(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class CandidateKey(_Record):
    strategy_id: str
    candidate_id: str

    def __post_init__(self):
        if not isinstance(self.strategy_id, str) or not re.fullmatch(r"S[0-9]{3}", self.strategy_id):
            raise ValidationError("invalid candidate strategy_id")
        if (
            not isinstance(self.candidate_id, str)
            or not re.fullmatch(r"C[0-9]{4}", self.candidate_id)
        ):
            raise ValidationError("candidate_id must match C plus four ASCII digits")


@dataclass(frozen=True, slots=True)
class CandidateEvidence(_Record):
    """File reference relative to the operation's declared evidence root."""

    path: str
    sha256: str

    def __post_init__(self):
        if not isinstance(self.path, str):
            raise ValidationError("evidence path must be a string")
        path = PurePosixPath(self.path)
        if (
            not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or str(path) != self.path
            or "\\" in self.path
            or ":" in self.path
        ):
            raise ValidationError("evidence path must be a safe relative path")
        _hash(self.sha256)

    def resolve(self, root: Path) -> Path:
        root = Path(root).resolve()
        path = root.joinpath(*PurePosixPath(self.path).parts).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValidationError("candidate evidence is missing or escapes its root")
        if sha256(path.read_bytes()).hexdigest() != self.sha256:
            raise ValidationError(f"candidate evidence hash differs: {self.path}")
        return path


@dataclass(frozen=True, slots=True)
class CandidateRegistrationOrigin(_Record):
    experiment_id: str
    definition_sha256: str
    binding_sha256: str
    preflight: CandidateEvidence

    def __post_init__(self):
        if not isinstance(self.experiment_id, str) or not re.fullmatch(
            r"(?:[0-9]{8}_S[0-9]{3}_EX[0-9]{2,}|EX(?!000_)[0-9]{3}_[0-9]{8})", self.experiment_id
        ):
            raise ValidationError("invalid origin experiment_id")
        _hash(self.definition_sha256)
        _hash(self.binding_sha256)
        if not isinstance(self.preflight, CandidateEvidence):
            raise TypeError("preflight requires CandidateEvidence")


class CandidateDerivationKind(StrEnum):
    PARAMETERS = "PARAMETERS"
    IMPLEMENTATION = "IMPLEMENTATION"
    EXECUTION = "EXECUTION"


@dataclass(frozen=True, slots=True)
class CandidateDerivation(_Record):
    parent: CandidateKey
    parent_content_sha256: str
    child: CandidateKey
    child_content_sha256: str
    kind: CandidateDerivationKind
    changes: Mapping[str, object]
    protocol_sha256: str
    evidence: CandidateEvidence

    def __post_init__(self):
        if not isinstance(self.parent, CandidateKey) or not isinstance(self.child, CandidateKey):
            raise TypeError("derivation requires CandidateKey values")
        if self.parent == self.child or self.parent.strategy_id != self.child.strategy_id:
            raise ValidationError("derivation requires distinct candidates in one family")
        for value in (self.parent_content_sha256, self.child_content_sha256, self.protocol_sha256):
            _hash(value)
        if not isinstance(self.kind, CandidateDerivationKind) or not isinstance(
            self.evidence, CandidateEvidence
        ):
            raise TypeError("derivation kind and evidence must be typed")
        if not isinstance(self.changes, Mapping) or not self.changes:
            raise ValidationError("derivation changes must be nonempty")
        object.__setattr__(self, "changes", _freeze(self.changes))

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        for name in ("parent", "child"):
            value[name] = CandidateKey(**value[name])
        value["kind"] = CandidateDerivationKind(value["kind"])
        value["evidence"] = CandidateEvidence(**value["evidence"])
        return cls(**value)


@dataclass(frozen=True, slots=True)
class CandidateRegistration(_Record):
    key: CandidateKey
    content_sha256: str
    source_sha256: str
    dependency_sha256: str
    payload: CandidateEvidence
    source_files: tuple[CandidateEvidence, ...]
    dependencies: tuple[tuple[str, str], ...]
    origin: CandidateRegistrationOrigin
    derivation: CandidateDerivation | None = None
    schema_version: int = 2
    identity_schema_version: int = 2

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 2:
            raise ValidationError("unsupported candidate registration schema")
        if type(self.identity_schema_version) is not int or self.identity_schema_version != 2:
            raise ValidationError("unsupported candidate content identity schema")
        if (
            not isinstance(self.key, CandidateKey)
            or not isinstance(self.origin, CandidateRegistrationOrigin)
            or not isinstance(self.payload, CandidateEvidence)
        ):
            raise TypeError("registration key, origin and payload must be typed")
        origin_family = re.fullmatch(
            r"[0-9]{8}_(S[0-9]{3})_EX[0-9]{2,}", self.origin.experiment_id
        )
        if origin_family is not None and origin_family[1] != self.key.strategy_id:
            raise ValidationError("candidate and origin belong to different families")
        for value in (self.content_sha256, self.source_sha256, self.dependency_sha256):
            _hash(value)
        files = tuple(self.source_files)
        if (
            not files
            or not all(isinstance(item, CandidateEvidence) for item in files)
            or len({item.path for item in files}) != len(files)
        ):
            raise ValidationError("source_files must contain unique CandidateEvidence")
        dependencies = tuple(tuple(item) for item in self.dependencies)
        if any(
            len(item) != 2 or not all(isinstance(v, str) and v for v in item)
            for item in dependencies
        ) or len({item[0] for item in dependencies}) != len(dependencies):
            raise ValidationError("dependencies must contain unique name/version pairs")
        for name, version in dependencies:
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) or not re.fullmatch(
                r"[0-9][A-Za-z0-9.+!-]*", version
            ):
                raise ValidationError("dependencies require normalized names and exact versions")
        if (
            canonical_sha256(
                [{"name": name, "version": version} for name, version in sorted(dependencies)]
            )
            != self.dependency_sha256
        ):
            raise ValidationError("dependency hash differs")
        if self.derivation is not None:
            if (
                not isinstance(self.derivation, CandidateDerivation)
                or self.derivation.child != self.key
                or self.derivation.child_content_sha256 != self.content_sha256
            ):
                raise ValidationError("derivation child differs from registration")
        object.__setattr__(self, "source_files", files)
        object.__setattr__(self, "dependencies", tuple(sorted(dependencies)))

    @property
    def record_sha256(self):
        return canonical_sha256(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        if type(value.get("schema_version")) is not int or value["schema_version"] != 2:
            raise ValidationError("unsupported candidate registration schema")
        if type(value.get("identity_schema_version")) is not int or value["identity_schema_version"] != 2:
            raise ValidationError("unsupported candidate content identity schema")
        value = dict(value)
        value["key"] = CandidateKey(**value["key"])
        value["payload"] = CandidateEvidence(**value["payload"])
        value["source_files"] = tuple(CandidateEvidence(**item) for item in value["source_files"])
        origin = dict(value["origin"])
        origin["preflight"] = CandidateEvidence(**origin["preflight"])
        value["origin"] = CandidateRegistrationOrigin(**origin)
        if value["derivation"] is not None:
            value["derivation"] = CandidateDerivation.from_dict(value["derivation"])
        return cls(**value)


def validate_registration_files(record: CandidateRegistration, root: Path) -> None:
    for ref in (record.payload, record.origin.preflight, *record.source_files):
        ref.resolve(root)
    if record.derivation:
        record.derivation.evidence.resolve(root)
    payload = json.loads(record.payload.resolve(root).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("runtime"), dict):
        raise ValidationError("registered payload lacks runtime descriptor")
    descriptor = payload["runtime"]
    prefix = f"objects/source/{record.source_sha256}/strategy_runtime/"
    by_name = {
        item.path.removeprefix(prefix): item
        for item in record.source_files
        if item.path.startswith(prefix)
    }
    if len(by_name) != len(record.source_files) or set(by_name) != set(
        descriptor.get("source_files", ())
    ):
        raise ValidationError("registered source manifest differs from runtime descriptor")
    digest = sha256()
    for name in sorted(by_name):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(by_name[name].resolve(root).read_bytes())
        digest.update(b"\0")
    if (
        digest.hexdigest() != record.source_sha256
        or descriptor.get("source_sha256") != record.source_sha256
    ):
        raise ValidationError("registered source closure hash differs")


def _registration_evidence_root(record, experiments_root: Path) -> Path:
    if not isinstance(experiments_root, Path):
        raise TypeError("experiments_root requires Path")
    root = experiments_root / record.key.strategy_id / record.origin.experiment_id
    for path in (root, root.parent, experiments_root):
        if path.is_symlink() or path.is_junction():
            raise ValidationError("candidate experiment root contains a link")
    if not root.is_dir() or not root.resolve().is_relative_to(experiments_root.resolve()):
        raise ValidationError("candidate experiment is missing or escapes experiments root")
    return root
