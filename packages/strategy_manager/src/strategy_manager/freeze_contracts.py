"""Immutable decision, inspection and freeze contracts; no research scheduler."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from enum import StrEnum
import math
import re
from types import UnionType
from typing import get_args, get_origin, get_type_hints

from .candidates import CandidateEvidence, CandidateKey
from .models import canonical_sha256
from .validation import require_strategy_id


def _typed(value, kind):
    if get_origin(kind) is UnionType:
        return any(_typed(value, part) for part in get_args(kind))
    if get_origin(kind) is tuple:
        return type(value) is tuple and all(_typed(x, get_args(kind)[0]) for x in value)
    return type(value) is kind


def _encode(value):
    if is_dataclass(value):
        return {
            "type": type(value).__name__,
            **{f.name: _encode(getattr(value, f.name)) for f in fields(value)},
        }
    if isinstance(value, tuple):
        return [_encode(x) for x in value]
    if isinstance(value, StrEnum):
        return value.value
    return value


def _decode(value, kind):
    if get_origin(kind) is UnionType:
        for part in get_args(kind):
            try:
                return _decode(value, part)
            except (ValueError, TypeError, KeyError):
                pass
        raise ValueError("record union type differs")
    if get_origin(kind) is tuple:
        if type(value) is not list:
            raise TypeError("serialized sequence must be a list")
        return tuple(_decode(x, get_args(kind)[0]) for x in value)
    if isinstance(kind, type) and issubclass(kind, StrEnum):
        return kind(value)
    if is_dataclass(kind):
        names = {f.name for f in fields(kind)}
        if (
            type(value) is not dict
            or set(value) != names | {"type"}
            or value["type"] != kind.__name__
        ):
            raise ValueError("record fields/type differ")
        hints = get_type_hints(kind)
        return kind(**{name: _decode(value[name], hints[name]) for name in names})
    if not _typed(value, kind):
        raise TypeError(f"expected {kind}")
    return value


def _id(value):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,99}", value):
        raise ValueError("invalid record identifier")


def _hash(value):
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("expected lowercase SHA-256")


def _version(value):
    if not re.fullmatch(r"v[1-9][0-9]*", value):
        raise ValueError("invalid version")


class Record:
    def __post_init__(self):
        for name, kind in get_type_hints(type(self)).items():
            if not _typed(getattr(self, name), kind):
                raise TypeError(f"{type(self).__name__}.{name} requires {kind}")
        self._validate()

    def _validate(self):
        pass

    def to_dict(self):
        return _encode(self)

    @classmethod
    def from_dict(cls, value):
        return _decode(value, cls)

    @property
    def sha256(self):
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class ResearchEvidenceOwner(Record):
    strategy_id: str
    experiment_id: str | None = None

    def _validate(self):
        require_strategy_id(self.strategy_id)
        if self.experiment_id is not None:
            match = re.fullmatch(r"(?:[0-9]{8}_(S[0-9]{3})_EX[0-9]{2,}|EX(?!000_)[0-9]{3}_[0-9]{8})", self.experiment_id)
            if match is None or (match[1] is not None and match[1] != self.strategy_id):
                raise ValueError("invalid research evidence experiment owner")

    @property
    def repository_path(self):
        if self.experiment_id is None:
            return f"research/{self.strategy_id}"
        return f"experiments/{self.strategy_id}/{self.experiment_id}"


@dataclass(frozen=True, slots=True)
class ResearchEvidenceRef(Record):
    """Owner-relative immutable evidence, resolved only from a repository root."""

    owner: ResearchEvidenceOwner
    path: str
    sha256: str

    def _validate(self):
        CandidateEvidence(self.path, self.sha256)

    @property
    def repository_path(self):
        return f"{self.owner.repository_path}/{self.path}"

    def resolve(self, repository_root):
        from pathlib import Path
        from .errors import ValidationError

        root = Path(repository_root).resolve()
        target = root / self.repository_path
        for parent in (target, *target.parents):
            if parent == root:
                break
            if parent.is_symlink() or parent.is_junction():
                raise ValidationError("research evidence path contains a link")
        owner = (root / self.owner.repository_path).resolve()
        if not owner.is_relative_to(root):
            raise ValidationError("research evidence owner escapes repository")
        return CandidateEvidence(self.path, self.sha256).resolve(owner)


class DecisionAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    DEFER = "DEFER"


@dataclass(frozen=True, slots=True)
class StageAdvanceSubject(Record):
    delivery: CandidateEvidence
    target_stage: str

    def _validate(self):
        if self.target_stage not in {"COMPONENTS", "CANDIDATES", "ASSESSMENT", "INSPECTION"}:
            raise ValueError("invalid target stage")


@dataclass(frozen=True, slots=True)
class CandidateSelectionSubject(Record):
    delivery: CandidateEvidence
    candidate: CandidateKey
    content_sha256: str

    def _validate(self):
        _hash(self.content_sha256)


@dataclass(frozen=True, slots=True)
class FreezeSubject(Record):
    candidate: CandidateKey
    content_sha256: str
    inspection: ResearchEvidenceRef
    plan_sha256: str
    version: str

    def _validate(self):
        _hash(self.content_sha256)
        _hash(self.plan_sha256)
        _version(self.version)


@dataclass(frozen=True, slots=True)
class ResearchDecision(Record):
    decision_id: str
    strategy_id: str
    action: DecisionAction
    subject: StageAdvanceSubject | CandidateSelectionSubject | FreezeSubject
    confirmation_source: CandidateEvidence | ResearchEvidenceRef
    reason: str

    def _validate(self):
        _id(self.decision_id)
        require_strategy_id(self.strategy_id)
        if not self.reason.strip():
            raise ValueError("decision requires reason")
        if (
            hasattr(self.subject, "candidate")
            and self.subject.candidate.strategy_id != self.strategy_id
        ):
            raise ValueError("decision candidate family differs")


@dataclass(frozen=True, slots=True)
class DecisionReference(Record):
    decision_id: str
    evidence: ResearchEvidenceRef

    def _validate(self):
        _id(self.decision_id)


@dataclass(frozen=True, slots=True)
class CandidateOrigin(Record):
    candidate: CandidateKey
    content_sha256: str
    registration: ResearchEvidenceRef

    def _validate(self):
        _hash(self.content_sha256)

    @property
    def registration_sha256(self):
        return self.registration.sha256


@dataclass(frozen=True, slots=True)
class FreezeRequestId(Record):
    strategy_id: str
    value: str

    def _validate(self):
        require_strategy_id(self.strategy_id)
        _id(self.value)


@dataclass(frozen=True, slots=True)
class FreezeFile(Record):
    path: str
    source: CandidateEvidence | ResearchEvidenceRef

    def _validate(self):
        CandidateEvidence(self.path, self.source.sha256)
        if any(
            x.endswith((".", " "))
            or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(\..*)?", x)
            for x in self.path.split("/")
        ) or any(ord(c) < 32 or c in '<>"|?*' for c in self.path):
            raise ValueError("unsafe file name")


@dataclass(frozen=True, slots=True)
class FreezePlan(Record):
    origin: CandidateOrigin
    version: str
    parent_version: str | None
    change_summary: str
    source_experiment: str
    selection_data_cutoff: str
    forward_start: str
    payload: ResearchEvidenceRef
    source_files: tuple[FreezeFile, ...]
    runtime_binding: ResearchEvidenceRef
    registration_evidence: tuple[ResearchEvidenceRef, ...]

    def _validate(self):
        _version(self.version)
        if self.parent_version is not None:
            _version(self.parent_version)
            if int(self.parent_version[1:]) >= int(self.version[1:]):
                raise ValueError("parent must precede target version")
        if not self.change_summary.strip() or not self.source_experiment.strip():
            raise ValueError("freeze plan description/origin required")
        if date.fromisoformat(self.forward_start) <= date.fromisoformat(self.selection_data_cutoff):
            raise ValueError("forward_start must follow selection cutoff")
        if not self.source_files or len({x.path.casefold() for x in self.source_files}) != len(
            self.source_files
        ):
            raise ValueError("source file closure is empty or duplicated")


class InspectionStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"


class InspectionCheck(StrEnum):
    CONTENT = "CONTENT"
    RUNTIME = "RUNTIME"
    COVERAGE = "COVERAGE"
    REPRODUCTION = "REPRODUCTION"
    LEDGER_AUDIT = "LEDGER_AUDIT"
    SIGNAL_EQUIVALENCE = "SIGNAL_EQUIVALENCE"
    LEDGER_EQUIVALENCE = "LEDGER_EQUIVALENCE"
    PACKAGE = "PACKAGE"


@dataclass(frozen=True, slots=True)
class InspectionCoordinate(Record):
    window_id: str
    scenario_id: str

    def _validate(self):
        if not self.window_id.strip() or not self.scenario_id.strip():
            raise ValueError("inspection coordinate must be nonempty")


@dataclass(frozen=True, slots=True)
class InspectionProtocol(Record):
    coordinates: tuple[InspectionCoordinate, ...]
    tolerance: float = 0.0
    method_version: str = "candidate-inspection-v1"

    def _validate(self):
        if self.method_version != "candidate-inspection-v1":
            raise ValueError("unsupported inspection method")
        if not self.coordinates or len(set(self.coordinates)) != len(self.coordinates):
            raise ValueError("inspection requires unique coordinates")
        if not math.isfinite(self.tolerance) or self.tolerance < 0:
            raise ValueError("inspection tolerance must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class InspectionCheckResult(Record):
    check: InspectionCheck
    status: InspectionStatus
    evidence: tuple[ResearchEvidenceRef, ...]
    detail: str

    def _validate(self):
        if not self.detail.strip() or not self.evidence:
            raise ValueError("inspection check requires details and evidence")


@dataclass(frozen=True, slots=True)
class CandidateInspectionReport(Record):
    plan: FreezePlan
    selection: DecisionReference
    protocol: InspectionProtocol
    request_sha256: str
    checks: tuple[InspectionCheckResult, ...]
    remaining_risks: tuple[str, ...]
    owner: ResearchEvidenceOwner

    def _validate(self):
        _hash(self.request_sha256)
        if self.owner.experiment_id is None or self.owner.strategy_id != self.plan.origin.candidate.strategy_id:
            raise ValueError("inspection must belong to its candidate research experiment")
        if len({x.check for x in self.checks}) != len(self.checks):
            raise ValueError("duplicate inspection check")
        if any(not x.strip() for x in self.remaining_risks):
            raise ValueError("risk must be nonempty")

    @property
    def status(self):
        if any(x.status is InspectionStatus.FAIL for x in self.checks):
            return InspectionStatus.FAIL
        if {x.check for x in self.checks} != set(InspectionCheck) or any(
            x.status is InspectionStatus.INCOMPLETE for x in self.checks
        ):
            return InspectionStatus.INCOMPLETE
        return InspectionStatus.PASS

    @property
    def reference(self) -> ResearchEvidenceRef:
        return ResearchEvidenceRef(self.owner, f"objects/inspection/{self.sha256}", self.sha256)


class FreezeStatus(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    IN_PROGRESS = "IN_PROGRESS"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class FrozenVersionReference(Record):
    strategy_id: str
    version: str
    release_hash: str
    package_hash: str

    def _validate(self):
        require_strategy_id(self.strategy_id)
        _version(self.version)
        _hash(self.release_hash)
        _hash(self.package_hash)


@dataclass(frozen=True, slots=True)
class FreezeReceipt(Record):
    request_id: FreezeRequestId
    status: FreezeStatus
    request_sha256: str | None = None
    version: FrozenVersionReference | None = None
    reason: str | None = None

    def _validate(self):
        if self.request_sha256 is not None:
            _hash(self.request_sha256)
        if (self.status is FreezeStatus.COMMITTED) != (self.version is not None):
            raise ValueError("only committed freeze may return a version")
        if (
            self.status not in {FreezeStatus.NOT_FOUND, FreezeStatus.UNKNOWN}
            and self.request_sha256 is None
        ):
            raise ValueError("registered freeze requires request identity")
        if self.status is FreezeStatus.NOT_FOUND and (
            self.request_sha256 is not None or self.reason is not None
        ):
            raise ValueError("unknown request cannot contain a registered identity or reason")
        if self.status in {FreezeStatus.FAILED, FreezeStatus.UNKNOWN} and not self.reason:
            raise ValueError("unsuccessful freeze requires a reason")
        if self.version is not None and self.version.strategy_id != self.request_id.strategy_id:
            raise ValueError("freeze receipt family differs")


@dataclass(frozen=True, slots=True)
class FreezeCandidateRequest(Record):
    request_id: FreezeRequestId
    inspection: ResearchEvidenceRef
    approval: DecisionReference
