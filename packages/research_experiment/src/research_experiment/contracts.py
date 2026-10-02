"""Stable domain contracts for executable research experiments."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from hashlib import sha256
import json
import math
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Generic, Protocol, TypeVar

from dataflows import DataRequest, DataResult
from strategy_runtime import (
    StrategyCandidate,
    StrategyInit,
    StrategyRelease,
    RuntimeDefinition,
    StrategyInstance,
)


_EXPERIMENT_ID = re.compile(r"(?:[0-9]{8}_(S[0-9]{3})_EX[0-9]{2,}|EX(?!000_)[0-9]{3}_[0-9]{8})")
_STRATEGY_ID = re.compile(r"S\d{3}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DEPENDENCY_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_EXACT_VERSION = re.compile(r"[0-9][A-Za-z0-9.+!-]*")


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _unique_text(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_text(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} must contain unique values")
    return normalized


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
    raise ValueError(f"{field_name} must contain only finite JSON values")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        _thaw_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _safe_relative_path(value: str | Path) -> PurePosixPath:
    text = str(value)
    if not text or "\\" in text or ":" in text:
        raise ValueError("artifact path must be a relative POSIX path")
    path = PurePosixPath(text)
    if (
        not path.parts
        or path == PurePosixPath(".")
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("artifact path must stay below the experiment workspace")
    return path


class ExperimentMode(StrEnum):
    """Whether the experiment explores mechanisms or produces formal evidence."""

    DISCOVERY = "DISCOVERY"
    FORMAL = "FORMAL"


class ExperimentDataScope(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    SEALED_VALIDATION = "SEALED_VALIDATION"


class ExperimentOutcome(StrEnum):
    """Research conclusion returned by an experiment."""

    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class ExperimentStage(StrEnum):
    """Research stage governed by one experiment definition."""

    DATA_GATE = "DATA_GATE"
    MECHANISM_DISCOVERY = "MECHANISM_DISCOVERY"
    FEATURE_DISCOVERY = "FEATURE_DISCOVERY"
    PROTOTYPE = "PROTOTYPE"
    PARAMETER_SEARCH = "PARAMETER_SEARCH"
    ROBUSTNESS = "ROBUSTNESS"
    CANDIDATE = "CANDIDATE"


class ExperimentPreflightStatus(StrEnum):
    """Outcome of one pre-execution platform check."""

    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class ExperimentPreflightCheck:
    """One machine-readable check performed before formal execution starts."""

    code: str
    status: ExperimentPreflightStatus
    message: str

    def __post_init__(self) -> None:
        code = _text(self.code, "preflight check code")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", code):
            raise ValueError("preflight check code must be upper snake case")
        if not isinstance(self.status, ExperimentPreflightStatus):
            raise ValueError("preflight check status must be ExperimentPreflightStatus")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", _text(self.message, "preflight check message"))

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "status": self.status.value, "message": self.message}


@dataclass(frozen=True, slots=True)
class ExperimentPreflightReport:
    """Source-bound result of platform preflight without formal experiment output."""

    experiment_id: str
    definition_sha256: str
    source_sha256: str
    resources_sha256: str
    checks: tuple[ExperimentPreflightCheck, ...]

    def __post_init__(self) -> None:
        if _EXPERIMENT_ID.fullmatch(self.experiment_id) is None:
            raise ValueError("preflight experiment_id is invalid")
        for field_name in ("definition_sha256", "source_sha256", "resources_sha256"):
            if _SHA256.fullmatch(getattr(self, field_name)) is None:
                raise ValueError(f"preflight {field_name} must be lowercase SHA-256")
        checks = tuple(self.checks)
        if not checks or not all(isinstance(item, ExperimentPreflightCheck) for item in checks):
            raise ValueError("preflight checks must contain typed check results")
        codes = tuple(item.code for item in checks)
        if len(codes) != len(set(codes)):
            raise ValueError("preflight check codes must be unique")
        object.__setattr__(self, "checks", checks)

    @property
    def passed(self) -> bool:
        return all(item.status is not ExperimentPreflightStatus.FAIL for item in self.checks)

    def require_pass(self) -> None:
        failed = [item for item in self.checks if item.status is ExperimentPreflightStatus.FAIL]
        if failed:
            details = "; ".join(f"{item.code}: {item.message}" for item in failed)
            raise ValueError(f"experiment preflight failed: {details}")

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "definition_sha256": self.definition_sha256,
            "source_sha256": self.source_sha256,
            "resources_sha256": self.resources_sha256,
            "passed": self.passed,
            "checks": [item.to_dict() for item in self.checks],
        }


class ExperimentCapability(StrEnum):
    """Sensitive research actions that must be declared before execution."""

    READ_REAL_RETURNS = "reads_real_returns"
    SEARCH_PARAMETERS = "searches_parameters"
    SELECT_PARAMETERS = "selects_parameters"
    CREATE_CANDIDATE = "creates_candidate"
    READ_SEALED_VALIDATION = "reads_sealed_validation"


@dataclass(frozen=True, slots=True)
class ExperimentDependency:
    """One exact third-party or platform dependency used by the experiment."""

    name: str
    version: str

    def __post_init__(self) -> None:
        name = _text(self.name, "dependency name")
        version = _text(self.version, "dependency version")
        if not _DEPENDENCY_NAME.fullmatch(name):
            raise ValueError("dependency name is invalid")
        if not _EXACT_VERSION.fullmatch(version):
            raise ValueError("dependency version must be exact")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "version", version)


@dataclass(frozen=True, slots=True)
class ExperimentCapabilities:
    """Declared sensitive behavior of an experiment."""

    reads_real_returns: bool = False
    searches_parameters: bool = False
    selects_parameters: bool = False
    creates_candidate: bool = False
    reads_sealed_validation: bool = False

    def __post_init__(self) -> None:
        for item in ExperimentCapability:
            if not isinstance(getattr(self, item.value), bool):
                raise ValueError(f"capability {item.value} must be boolean")

    def allows(self, capability: ExperimentCapability) -> bool:
        return bool(getattr(self, ExperimentCapability(capability).value))


@dataclass(frozen=True, slots=True)
class ExperimentProtocol:
    """Structured rationale, stage target and evidence plan for one experiment."""

    stage: ExperimentStage
    first_principles: tuple[str, ...]
    information_paths: tuple[str, ...]
    stage_objectives: tuple[str, ...]
    observation_metrics: tuple[str, ...]
    methodology: tuple[str, ...]
    predecessor_experiment_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.stage, ExperimentStage):
            raise ValueError("protocol stage must be an ExperimentStage")
        for field_name in (
            "first_principles",
            "information_paths",
            "stage_objectives",
            "observation_metrics",
            "methodology",
        ):
            values = _unique_text(getattr(self, field_name), field_name)
            if not values:
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, values)
        predecessors = _unique_text(self.predecessor_experiment_ids, "predecessor_experiment_ids")
        if any(_EXPERIMENT_ID.fullmatch(item) is None for item in predecessors):
            raise ValueError("predecessor_experiment_ids contain an invalid experiment id")
        object.__setattr__(self, "predecessor_experiment_ids", predecessors)

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage.value,
            "first_principles": list(self.first_principles),
            "information_paths": list(self.information_paths),
            "stage_objectives": list(self.stage_objectives),
            "observation_metrics": list(self.observation_metrics),
            "methodology": list(self.methodology),
            "predecessor_experiment_ids": list(self.predecessor_experiment_ids),
        }


@dataclass(frozen=True, slots=True)
class ExperimentDefinition:
    """Pre-execution research intent, boundary and reproducibility contract."""

    schema_version: int
    experiment_id: str
    strategy_id: str
    mode: ExperimentMode
    research_question: str
    hypothesis: str
    falsification_conditions: tuple[str, ...]
    development_cutoff: date
    random_seed: int
    allowed_datasets: tuple[str, ...]
    protocol: ExperimentProtocol
    data_scope: ExperimentDataScope
    subjects: tuple[str, ...] = ()
    validation_cutoff: date | None = None
    dependencies: tuple[ExperimentDependency, ...] = ()
    capabilities: ExperimentCapabilities = ExperimentCapabilities()

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 2:
            raise ValueError("experiment schema_version must be 2")
        if not isinstance(self.data_scope, ExperimentDataScope):
            raise ValueError("schema 2 requires an ExperimentDataScope")
        experiment_id = _text(self.experiment_id, "experiment_id")
        strategy_id = _text(self.strategy_id, "strategy_id")
        match = _EXPERIMENT_ID.fullmatch(experiment_id)
        if match is None:
            raise ValueError("experiment_id must match EXNNN_YYYYMMDD")
        if not _STRATEGY_ID.fullmatch(strategy_id) or match.group(1) not in (None, strategy_id):
            raise ValueError("strategy_id must match the experiment_id strategy")
        if not isinstance(self.mode, ExperimentMode):
            raise ValueError("mode must be an ExperimentMode")
        if type(self.development_cutoff) is not date:
            raise ValueError("development_cutoff must be a date")
        if self.validation_cutoff is not None and type(self.validation_cutoff) is not date:
            raise ValueError("validation_cutoff must be a date or None")
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int):
            raise ValueError("random_seed must be an integer")
        if self.random_seed < 0:
            raise ValueError("random_seed must be non-negative")
        falsification = _unique_text(self.falsification_conditions, "falsification_conditions")
        if not falsification:
            raise ValueError("falsification_conditions must not be empty")
        datasets = _unique_text(self.allowed_datasets, "allowed_datasets")
        if not datasets:
            raise ValueError("allowed_datasets must not be empty")
        dependencies = tuple(self.dependencies)
        if not all(isinstance(item, ExperimentDependency) for item in dependencies):
            raise ValueError("dependencies must contain ExperimentDependency values")
        dependency_names = tuple(item.name for item in dependencies)
        if len(dependency_names) != len(set(dependency_names)):
            raise ValueError("dependency names must be unique")
        if not isinstance(self.capabilities, ExperimentCapabilities):
            raise ValueError("capabilities must be ExperimentCapabilities")
        if not isinstance(self.protocol, ExperimentProtocol):
            raise ValueError("protocol must be an ExperimentProtocol")
        subjects = _unique_text(self.subjects, "subjects")
        predecessors = self.protocol.predecessor_experiment_ids
        if experiment_id in predecessors:
            raise ValueError("an experiment cannot depend on itself")
        if any(_EXPERIMENT_ID.fullmatch(item).group(1) not in (None, strategy_id) for item in predecessors):
            raise ValueError("predecessor experiments must belong to the same strategy")
        sealed = self.data_scope is ExperimentDataScope.SEALED_VALIDATION
        if sealed:
            if self.mode is not ExperimentMode.FORMAL:
                raise ValueError("sealed validation requires FORMAL execution")
            if self.validation_cutoff is None or self.validation_cutoff <= self.development_cutoff:
                raise ValueError(
                    "FORMAL experiments require validation_cutoff after development_cutoff"
                )
            if not (
                self.capabilities.reads_real_returns and self.capabilities.reads_sealed_validation
            ):
                raise ValueError(
                    "FORMAL experiments require real-return and sealed-validation capabilities"
                )
            if self.capabilities.searches_parameters or self.capabilities.selects_parameters:
                raise ValueError("FORMAL experiments cannot search or select parameters")
        elif self.validation_cutoff is not None or self.capabilities.reads_sealed_validation:
            raise ValueError("DEVELOPMENT cannot declare validation_cutoff or sealed capability")
        if self.mode is ExperimentMode.FORMAL and not self.capabilities.reads_real_returns:
            raise ValueError("FORMAL requires real-return capability")
        object.__setattr__(self, "experiment_id", experiment_id)
        object.__setattr__(self, "strategy_id", strategy_id)
        object.__setattr__(
            self, "research_question", _text(self.research_question, "research_question")
        )
        object.__setattr__(self, "hypothesis", _text(self.hypothesis, "hypothesis"))
        object.__setattr__(self, "falsification_conditions", falsification)
        object.__setattr__(self, "allowed_datasets", datasets)
        object.__setattr__(self, "subjects", subjects)
        object.__setattr__(self, "dependencies", dependencies)

    @property
    def sha256(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "strategy_id": self.strategy_id,
            "mode": self.mode.value,
            "research_question": self.research_question,
            "hypothesis": self.hypothesis,
            "falsification_conditions": self.falsification_conditions,
            "development_cutoff": self.development_cutoff.isoformat(),
            "validation_cutoff": None
            if self.validation_cutoff is None
            else self.validation_cutoff.isoformat(),
            "random_seed": self.random_seed,
            "allowed_datasets": self.allowed_datasets,
            "protocol": self.protocol.to_dict(),
            "dependencies": tuple(
                {"name": item.name, "version": item.version} for item in self.dependencies
            ),
            "capabilities": {
                item.value: self.capabilities.allows(item) for item in ExperimentCapability
            },
        }
        if self.subjects:
            payload["subjects"] = self.subjects
        payload["data_scope"] = self.data_scope.value
        return _canonical_sha256(payload)


@dataclass(frozen=True, slots=True)
class ExperimentResources:
    """Caller-declared per-operation execution configuration."""

    max_workers: int
    random_seed: int
    native_threads_per_worker: int = 1

    def __post_init__(self) -> None:
        for name in ("max_workers", "native_threads_per_worker"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int):
            raise ValueError("random_seed must be an integer")
        if self.random_seed < 0:
            raise ValueError("random_seed must be non-negative")

    @property
    def sha256(self) -> str:
        return _canonical_sha256(
            {
                "max_workers": self.max_workers,
                "random_seed": self.random_seed,
                "native_threads_per_worker": self.native_threads_per_worker,
                "schema_version": 2,
            }
        )


@dataclass(frozen=True, slots=True)
class ExperimentArtifact:
    """One immutable file produced below the governed experiment workspace."""

    path: str
    kind: str
    sha256: str

    def __post_init__(self) -> None:
        path = _safe_relative_path(self.path)
        kind = _text(self.kind, "artifact kind")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError("artifact sha256 must be lowercase SHA-256")
        object.__setattr__(self, "path", path.as_posix())
        object.__setattr__(self, "kind", kind)


class EvaluationAttemptStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    """Observed facts about one call; contains no scheduling or budget policy."""

    attempt_id: str
    experiment_id: str
    candidate_id: str
    content_sha256: str
    request_hash: str
    status: EvaluationAttemptStatus
    started_at: str
    requested_count: int
    completed_count: int | None = 0
    finished_at: str | None = None
    elapsed_seconds: float | None = None
    evaluation_ids: tuple[str, ...] = ()
    result_hash: str | None = None
    result_artifact: ExperimentArtifact | None = None
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.attempt_id, str) or not re.fullmatch(
            r"[0-9a-f]{32}", self.attempt_id
        ):
            raise ValueError("attempt_id must be a UUID hex string")
        if not isinstance(self.status, EvaluationAttemptStatus):
            raise TypeError("status must be EvaluationAttemptStatus")
        for name in ("experiment_id", "candidate_id"):
            _text(getattr(self, name), name)
        for value in (self.content_sha256, self.request_hash, *self.evaluation_ids):
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ValueError("evaluation record identities must be SHA-256")
        if len(set(self.evaluation_ids)) != len(self.evaluation_ids):
            raise ValueError("evaluation identities must be unique")
        for name in ("requested_count", "completed_count"):
            if name == "completed_count" and self.completed_count is None:
                continue
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError("evaluation counts must be nonnegative integers")
        if self.requested_count < 1 or (
            self.completed_count is not None and self.completed_count > self.requested_count
        ):
            raise ValueError("invalid evaluation counts")
        start = datetime.fromisoformat(self.started_at)
        if start.utcoffset() is None:
            raise ValueError("record timestamps must include a timezone")
        if self.status is EvaluationAttemptStatus.STARTED:
            if (
                any(
                    value is not None
                    for value in (
                        self.finished_at,
                        self.elapsed_seconds,
                        self.result_hash,
                        self.result_artifact,
                        self.error_code,
                        self.error_message,
                    )
                )
                or self.completed_count != 0
            ):
                raise ValueError("STARTED cannot contain terminal facts")
        else:
            if self.finished_at is None or self.elapsed_seconds is None:
                raise ValueError("terminal record requires completion time and duration")
            end = datetime.fromisoformat(self.finished_at)
            if end.utcoffset() is None or end < start:
                raise ValueError("invalid completion timestamp")
            if (
                isinstance(self.elapsed_seconds, bool)
                or not math.isfinite(self.elapsed_seconds)
                or self.elapsed_seconds < 0
            ):
                raise ValueError("invalid elapsed_seconds")
        if self.status is EvaluationAttemptStatus.SUCCEEDED:
            if (
                self.completed_count != self.requested_count
                or len(self.evaluation_ids) != self.completed_count
            ):
                raise ValueError("success requires all evaluation coordinates")
            if not isinstance(self.result_hash, str) or not _SHA256.fullmatch(self.result_hash):
                raise ValueError("success requires result_hash")
            if (
                not isinstance(self.result_artifact, ExperimentArtifact)
                or self.error_code
                or self.error_message
            ):
                raise ValueError("success requires result artifact and no error")
        elif self.result_hash is not None or self.result_artifact is not None:
            raise ValueError("unsuccessful record cannot reference a successful result")
        if self.status in {
            EvaluationAttemptStatus.FAILED,
            EvaluationAttemptStatus.CANCELLED,
            EvaluationAttemptStatus.UNKNOWN,
        }:
            _text(self.error_code, "error_code")
            _text(self.error_message, "error_message")
        object.__setattr__(self, "evaluation_ids", tuple(self.evaluation_ids))

    def to_dict(self) -> dict[str, object]:
        from dataclasses import fields

        value = {item.name: getattr(self, item.name) for item in fields(self)}
        value["status"] = self.status.value
        value["evaluation_ids"] = list(self.evaluation_ids)
        artifact = self.result_artifact
        value["result_artifact"] = (
            None
            if artifact is None
            else {
                "path": artifact.path,
                "kind": artifact.kind,
                "sha256": artifact.sha256,
            }
        )
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EvaluationRecord:
        payload = dict(value)
        payload["status"] = EvaluationAttemptStatus(payload["status"])
        payload["evaluation_ids"] = tuple(payload["evaluation_ids"])
        if payload["result_artifact"] is not None:
            payload["result_artifact"] = ExperimentArtifact(**payload["result_artifact"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ExperimentTrace:
    """Read-only execution trace captured at platform boundaries."""

    capabilities: tuple[ExperimentCapability, ...]
    operations: tuple[str, ...]
    data_requests: tuple[Mapping[str, Any], ...]
    data_scope: ExperimentDataScope
    evaluations: tuple[EvaluationRecord, ...] = ()

    def __post_init__(self) -> None:
        capabilities = tuple(self.capabilities)
        if not all(isinstance(item, ExperimentCapability) for item in capabilities):
            raise ValueError("trace capabilities contain an invalid value")
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("trace capabilities must be unique")
        operations = tuple(_text(item, "trace operation") for item in self.operations)
        requests = tuple(_freeze_json(item, "trace data request") for item in self.data_requests)
        evaluations = tuple(self.evaluations)
        if not all(isinstance(item, EvaluationRecord) for item in evaluations):
            raise TypeError("trace evaluations require EvaluationRecord")
        if not isinstance(self.data_scope, ExperimentDataScope):
            raise TypeError("trace data_scope must be ExperimentDataScope")
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "operations", operations)
        object.__setattr__(self, "data_requests", requests)
        object.__setattr__(self, "evaluations", evaluations)

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilities": [item.value for item in self.capabilities],
            "operations": list(self.operations),
            "data_requests": _thaw_json(self.data_requests),
            "evaluations": [item.to_dict() for item in self.evaluations],
            "data_scope": self.data_scope.value,
        }


@dataclass(frozen=True, slots=True, init=False)
class ExperimentReceipt:
    """Deterministic platform receipt for one completed experiment execution."""

    schema_version: int
    experiment_id: str
    definition_sha256: str
    source_sha256: str
    resources_sha256: str
    predecessor_receipts: Mapping[str, str]
    result_sha256: str
    artifact_sha256: Mapping[str, str]
    trace: ExperimentTrace

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("ExperimentReceipt can only be created by the platform executor")

    @classmethod
    def _from_execution(
        cls,
        *,
        schema_version: int,
        experiment_id: str,
        definition_sha256: str,
        source_sha256: str,
        resources_sha256: str,
        predecessor_receipts: Mapping[str, str],
        result_sha256: str,
        artifact_sha256: Mapping[str, str],
        trace: ExperimentTrace,
    ) -> ExperimentReceipt:
        if type(schema_version) is not int or schema_version != 2:
            raise ValueError("experiment receipt schema_version must be 2")
        if _EXPERIMENT_ID.fullmatch(experiment_id) is None:
            raise ValueError("receipt experiment_id is invalid")
        identities = {
            "definition_sha256": definition_sha256,
            "source_sha256": source_sha256,
            "resources_sha256": resources_sha256,
            "result_sha256": result_sha256,
        }
        for name, value in identities.items():
            if _SHA256.fullmatch(value) is None:
                raise ValueError(f"receipt {name} must be lowercase SHA-256")
        predecessors = {
            _text(key, "predecessor experiment id"): value
            for key, value in predecessor_receipts.items()
        }
        if any(_EXPERIMENT_ID.fullmatch(key) is None for key in predecessors):
            raise ValueError("receipt predecessor experiment id is invalid")
        if any(_SHA256.fullmatch(value) is None for value in predecessors.values()):
            raise ValueError("predecessor receipt identity must be lowercase SHA-256")
        artifacts = {
            _safe_relative_path(key).as_posix(): value for key, value in artifact_sha256.items()
        }
        if any(_SHA256.fullmatch(value) is None for value in artifacts.values()):
            raise ValueError("receipt artifact identity must be lowercase SHA-256")
        if not isinstance(trace, ExperimentTrace):
            raise ValueError("receipt trace must be an ExperimentTrace")
        instance = object.__new__(cls)
        object.__setattr__(instance, "schema_version", schema_version)
        object.__setattr__(instance, "experiment_id", experiment_id)
        for name, value in identities.items():
            object.__setattr__(instance, name, value)
        object.__setattr__(instance, "predecessor_receipts", MappingProxyType(predecessors))
        object.__setattr__(instance, "artifact_sha256", MappingProxyType(artifacts))
        object.__setattr__(instance, "trace", trace)
        return instance

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "definition_sha256": self.definition_sha256,
            "source_sha256": self.source_sha256,
            "resources_sha256": self.resources_sha256,
            "predecessor_receipts": dict(self.predecessor_receipts),
            "result_sha256": self.result_sha256,
            "artifact_sha256": dict(self.artifact_sha256),
            "trace": self.trace.to_dict(),
        }

    @property
    def sha256(self) -> str:
        return _canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    """Machine-checkable research facts returned by one experiment execution."""

    outcome: ExperimentOutcome
    facts: Mapping[str, Any]
    diagnostics: Mapping[str, Any]
    artifacts: tuple[ExperimentArtifact, ...] = ()
    candidate: StrategyCandidate | None = None
    receipt: ExperimentReceipt | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ExperimentOutcome):
            raise ValueError("outcome must be an ExperimentOutcome")
        if not isinstance(self.facts, Mapping):
            raise ValueError("facts must be a mapping")
        if not isinstance(self.diagnostics, Mapping):
            raise ValueError("diagnostics must be a mapping")
        facts = _freeze_json(self.facts, "facts")
        diagnostics = _freeze_json(self.diagnostics, "diagnostics")
        artifacts = tuple(self.artifacts)
        if not all(isinstance(item, ExperimentArtifact) for item in artifacts):
            raise ValueError("artifacts must contain ExperimentArtifact values")
        paths = tuple(item.path for item in artifacts)
        if len(paths) != len(set(paths)):
            raise ValueError("artifact paths must be unique")
        if self.candidate is not None and not isinstance(self.candidate, StrategyCandidate):
            raise ValueError("candidate must be a StrategyCandidate or None")
        if self.receipt is not None and not isinstance(self.receipt, ExperimentReceipt):
            raise ValueError("receipt must be an ExperimentReceipt or None")
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "artifacts", artifacts)

    def to_dict(self) -> dict[str, object]:
        """Return the complete JSON-safe payload bound by the execution receipt."""

        candidate = self.candidate
        return {
            "outcome": self.outcome.value,
            "facts": _thaw_json(self.facts),
            "diagnostics": _thaw_json(self.diagnostics),
            "artifacts": [
                {"path": item.path, "kind": item.kind, "sha256": item.sha256}
                for item in self.artifacts
            ],
            "candidate": None
            if candidate is None
            else {
                "reference_id": candidate.reference_id,
                "runtime_identity_sha256": candidate.runtime_identity_sha256,
            },
        }


@dataclass(frozen=True, slots=True)
class ExperimentPrecheckResult:
    """Named synthetic checks and an optional synthetic output serialization sample."""

    checks: tuple[ExperimentPreflightCheck, ...]
    result: ExperimentResult | None = None

    def __post_init__(self) -> None:
        checks = tuple(self.checks)
        if not checks or not all(isinstance(item, ExperimentPreflightCheck) for item in checks):
            raise TypeError("precheck requires non-empty typed checks")
        if len({item.code for item in checks}) != len(checks):
            raise ValueError("precheck codes must be unique")
        if any(item.code in {"PRECHECK", "COVERAGE"} for item in checks):
            raise ValueError("precheck code is reserved by the platform")
        if self.result is not None and not isinstance(self.result, ExperimentResult):
            raise TypeError("precheck result sample must be ExperimentResult")
        object.__setattr__(self, "checks", checks)


def experiment_result_sha256(result: ExperimentResult) -> str:
    """Return the stable identity of experiment output before platform receipt."""

    if not isinstance(result, ExperimentResult):
        raise TypeError("result must be an ExperimentResult")
    return _canonical_sha256(result.to_dict())


@dataclass(frozen=True, slots=True, init=False)
class ExperimentInput:
    """Verified immutable evidence exposed to a successor experiment."""

    experiment_id: str
    receipt_sha256: str
    outcome: ExperimentOutcome
    facts: Mapping[str, Any]
    artifacts: tuple[ExperimentArtifact, ...]

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("ExperimentInput can only be created from a receipted result")

    @classmethod
    def _from_receipt(
        cls,
        *,
        experiment_id: str,
        receipt_sha256: str,
        outcome: ExperimentOutcome,
        facts: Mapping[str, Any],
        artifacts: tuple[ExperimentArtifact, ...],
    ) -> ExperimentInput:
        if _EXPERIMENT_ID.fullmatch(experiment_id) is None:
            raise ValueError("input experiment_id is invalid")
        if _SHA256.fullmatch(receipt_sha256) is None:
            raise ValueError("input receipt_sha256 must be lowercase SHA-256")
        if not isinstance(outcome, ExperimentOutcome):
            raise ValueError("input outcome must be an ExperimentOutcome")
        frozen_facts = _freeze_json(facts, "input facts")
        frozen_artifacts = tuple(artifacts)
        if not all(isinstance(item, ExperimentArtifact) for item in frozen_artifacts):
            raise ValueError("input artifacts must contain ExperimentArtifact values")
        instance = object.__new__(cls)
        object.__setattr__(instance, "experiment_id", experiment_id)
        object.__setattr__(instance, "receipt_sha256", receipt_sha256)
        object.__setattr__(instance, "outcome", outcome)
        object.__setattr__(instance, "facts", frozen_facts)
        object.__setattr__(instance, "artifacts", frozen_artifacts)
        return instance

    @classmethod
    def from_result(cls, result: ExperimentResult) -> ExperimentInput:
        if not isinstance(result, ExperimentResult) or result.receipt is None:
            raise ValueError("predecessor result must contain a platform receipt")
        return cls._from_receipt(
            experiment_id=result.receipt.experiment_id,
            receipt_sha256=result.receipt.sha256,
            outcome=result.outcome,
            facts=result.facts,
            artifacts=result.artifacts,
        )


class ExperimentWorkspace:
    """Repository-local scratch space and artifact identity boundary."""

    def __init__(self, root: Path, repository_root: Path) -> None:
        root = Path(root).resolve()
        repository_root = Path(repository_root).resolve()
        governed_root = (repository_root / ".tmp").resolve()
        try:
            root.relative_to(governed_root)
        except ValueError as exc:
            raise ValueError("experiment workspace must be below repository .tmp") from exc
        root.mkdir(parents=True, exist_ok=True)
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def path(self, relative_path: str | Path) -> Path:
        relative = _safe_relative_path(relative_path)
        target = self._root.joinpath(*relative.parts).resolve()
        try:
            target.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("workspace path escapes the experiment workspace") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def register_artifact(self, relative_path: str | Path, kind: str) -> ExperimentArtifact:
        target = self.path(relative_path)
        if not target.is_file():
            raise FileNotFoundError(f"experiment artifact does not exist: {target}")
        return ExperimentArtifact(
            path=_safe_relative_path(relative_path).as_posix(),
            kind=kind,
            sha256=sha256(target.read_bytes()).hexdigest(),
        )

    def validate_artifact(self, artifact: ExperimentArtifact) -> None:
        target = self.path(artifact.path)
        if not target.is_file():
            raise FileNotFoundError(f"experiment artifact does not exist: {target}")
        if sha256(target.read_bytes()).hexdigest() != artifact.sha256:
            raise ValueError(f"experiment artifact hash differs: {artifact.path}")


class ExperimentDataPort(Protocol):
    """Platform data-publication port available to research code."""

    def fetch(self, request: DataRequest) -> DataResult: ...


class ExperimentRuntimePort(Protocol):
    """Platform strategy-runtime port available to research code."""

    def describe(
        self,
        source: StrategyRelease | StrategyCandidate,
        *,
        symbol: str | None = None,
        source_root: Path | None = None,
        runtime_binding: Mapping[str, object] | None = None,
    ) -> RuntimeDefinition: ...

    def create(self, request: StrategyInit) -> StrategyInstance: ...


RequestT = TypeVar("RequestT", contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)


@dataclass(frozen=True, slots=True)
class EvaluationOutcome(Generic[ResultT]):
    """One terminal batch item; unsuccessful computation never carries a result."""

    record: EvaluationRecord
    result: ResultT | None

    def __post_init__(self) -> None:
        if not isinstance(self.record, EvaluationRecord):
            raise TypeError("outcome requires EvaluationRecord")
        if self.record.status is EvaluationAttemptStatus.STARTED:
            raise ValueError("outcome requires a terminal record")
        if (self.record.status is EvaluationAttemptStatus.SUCCEEDED) != (self.result is not None):
            raise ValueError("only a successful outcome must contain a result")


class ExperimentEvaluationPort(Protocol[RequestT, ResultT]):
    """Platform evaluation port available to research code."""

    def evaluate(self, request: RequestT) -> ResultT: ...

    def evaluate_many(
        self, requests: tuple[RequestT, ...]
    ) -> tuple[EvaluationOutcome[ResultT], ...]: ...


ContextRequestT = TypeVar("ContextRequestT")
ContextResultT = TypeVar("ContextResultT")


class ExperimentContext(Protocol[ContextRequestT, ContextResultT]):
    """Research-facing protocol implemented by a platform context."""

    definition: ExperimentDefinition
    data: ExperimentDataPort
    runtime: ExperimentRuntimePort
    evaluation: ExperimentEvaluationPort[ContextRequestT, ContextResultT]
    workspace: ExperimentWorkspace
    resources: ExperimentResources
    predecessors: Mapping[str, ExperimentInput]

    @property
    def trace(self) -> ExperimentTrace: ...

    def require_capability(self, capability: ExperimentCapability) -> None: ...


class ResearchExperiment(ABC):
    """Researcher's executable anchor for one falsifiable experiment."""

    @property
    @abstractmethod
    def definition(self) -> ExperimentDefinition:
        """Return the immutable pre-execution definition."""

    def synthetic_precheck(self) -> ExperimentPrecheckResult | None:
        """Exercise technical boundaries without reading formal experiment outcomes."""

        return None

    @abstractmethod
    def execute(self, context: ExperimentContext) -> ExperimentResult:
        """Execute only through the supplied, capability-tracked context."""


__all__ = [
    "ExperimentPrecheckResult",
    "ExperimentArtifact",
    "ExperimentCapabilities",
    "ExperimentCapability",
    "ExperimentContext",
    "ExperimentDataPort",
    "ExperimentDefinition",
    "ExperimentDependency",
    "ExperimentEvaluationPort",
    "ExperimentInput",
    "ExperimentMode",
    "ExperimentOutcome",
    "ExperimentProtocol",
    "ExperimentPreflightCheck",
    "ExperimentPreflightReport",
    "ExperimentPreflightStatus",
    "ExperimentReceipt",
    "ExperimentResources",
    "ExperimentResult",
    "ExperimentRuntimePort",
    "ExperimentStage",
    "ExperimentTrace",
    "ExperimentWorkspace",
    "ResearchExperiment",
    "experiment_result_sha256",
]
