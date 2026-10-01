# Frozen schema-v1 validation semantics from 13fe9633. Read-only; never used for new publications.
"""Typed research handoffs. These values describe evidence, never control research."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from hashlib import sha256
import json
import math
from pathlib import PurePosixPath
import re
from types import UnionType
from typing import Generic, TypeVar, Union, get_args, get_origin, get_type_hints

from strategy_manager import CandidateKey
from strategy_manager import CandidateInspectionReport, DecisionReference, FreezeReceipt
from strategy_evaluator._research_models_v1 import (
    CandidateAssessmentRequest,
    AssessmentPanel,
    CandidateComparisonRequest,
    CandidateComparison,
    ResearchMetric,
)


def _text(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must be nonempty")


def _hash(value: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("expected lowercase SHA-256")


def _path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or str(path) != value
        or "\\" in value
        or ":" in value
        or any(part.endswith((".", " ")) for part in path.parts)
        or any(
            re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(\..*)?", p) for p in path.parts
        )
        or any(ord(c) < 32 or c in '<>"|?*' for c in value)
    ):
        raise ValueError("expected safe relative POSIX path")


def _unique(values, name: str) -> None:
    values = tuple(values)
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {name}")


def _matches(value, annotation) -> bool:
    if isinstance(annotation, TypeVar):
        return _matches(value, annotation.__bound__)
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return any(_matches(value, part) for part in get_args(annotation))
    if origin is tuple:
        args = get_args(annotation)
        return type(value) is tuple and all(_matches(v, args[0]) for v in value)
    if annotation is float:
        return type(value) is float and math.isfinite(value)
    return type(value) is annotation


class _Record:
    def __post_init__(self):
        for name, annotation in get_type_hints(type(self)).items():
            if not _matches(getattr(self, name), annotation):
                raise TypeError(f"{type(self).__name__}.{name} requires {annotation}")
        self._validate()

    def _validate(self):
        pass

    def to_dict(self) -> dict[str, object]:
        return _encode(self)

    @classmethod
    def from_dict(cls, value):
        result = _decode(value, cls)
        if type(result) is not cls:
            raise ValueError("delivery record type differs")
        return result


class DeliveryStage(StrEnum):
    MANDATE = "MANDATE"
    COMPONENTS = "COMPONENTS"
    CANDIDATES = "CANDIDATES"
    ASSESSMENT = "ASSESSMENT"
    INSPECTION = "INSPECTION"


class DeliveryStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class ValidationStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class EvidenceRef(_Record):
    """Path relative to the published delivery, not the current working directory."""

    path: str
    sha256: str
    media_type: str
    schema: str | None = None
    schema_version: int | None = None

    def _validate(self):
        _path(self.path)
        _hash(self.sha256)
        _text(self.media_type, "media_type")
        if (self.schema is None) != (self.schema_version is None):
            raise ValueError("schema and schema_version must be supplied together")
        if self.schema is not None:
            _text(self.schema, "schema")
            if self.schema_version < 1:
                raise ValueError("schema_version must be positive")


@dataclass(frozen=True, slots=True)
class EvidenceFile(_Record):
    """Explicit input file; source_path is provenance only after publication."""

    source_path: str
    reference: EvidenceRef

    def _validate(self):
        _path(self.source_path)
        if not self.reference.path.startswith("attachments/"):
            raise ValueError("attached evidence must use attachments/ namespace")


@dataclass(frozen=True, slots=True)
class ExperimentEvidenceRef(_Record):
    experiment_id: str
    workspace_path: str
    receipt_sha256: str

    def _validate(self):
        if not re.fullmatch(r"\d{8}_S\d{3,}_EX\d{2,}", self.experiment_id):
            raise ValueError("invalid experiment_id")
        _path(self.workspace_path)
        _hash(self.receipt_sha256)


@dataclass(frozen=True, slots=True)
class DeliveryReference(_Record):
    strategy_id: str
    stage: DeliveryStage
    revision: int
    content_sha256: str

    def _validate(self):
        CandidateKey(self.strategy_id, "Delivery")
        if self.revision < 1:
            raise ValueError("revision must be positive")
        _hash(self.content_sha256)


@dataclass(frozen=True, slots=True)
class DeliveryDefinition(_Record):
    strategy_id: str
    stage: DeliveryStage
    revision: int
    predecessors: tuple[DeliveryReference, ...] = ()
    experiments: tuple[ExperimentEvidenceRef, ...] = ()
    schema_version: int = 1

    def _validate(self):
        CandidateKey(self.strategy_id, "Delivery")
        if self.revision < 1 or self.schema_version != 1:
            raise ValueError("invalid delivery revision/schema_version")
        _unique((x.experiment_id for x in self.experiments), "experiment_id")
        _unique(((x.stage, x.revision) for x in self.predecessors), "predecessor")
        for ref in self.predecessors:
            if ref.strategy_id != self.strategy_id:
                raise ValueError("predecessor family differs")
            if ref.stage == self.stage and ref.revision >= self.revision:
                raise ValueError("same-stage predecessor must be an earlier revision")
        if any(f"_{self.strategy_id}_" not in x.experiment_id for x in self.experiments):
            raise ValueError("experiment family differs")


class ConfirmationStatus(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"


@dataclass(frozen=True, slots=True)
class ConfirmationRecord(_Record):
    status: ConfirmationStatus
    source: EvidenceRef | None = None

    def _validate(self):
        if self.status is ConfirmationStatus.CONFIRMED and self.source is None:
            raise ValueError("confirmed item requires confirmation evidence")


class MandateItemKind(StrEnum):
    TRADABLE_SYMBOL = "TRADABLE_SYMBOL"
    BENCHMARK = "BENCHMARK"
    HORIZON = "HORIZON"
    OBJECTIVE = "OBJECTIVE"
    CONSTRAINT = "CONSTRAINT"
    EXECUTION = "EXECUTION"
    DATA_PERMISSION = "DATA_PERMISSION"
    RESOURCE = "RESOURCE"


@dataclass(frozen=True, slots=True)
class NumericRequirement(_Record):
    metric: str
    unit: str
    lower: float | None = None
    upper: float | None = None

    def _validate(self):
        _text(self.metric, "metric")
        _text(self.unit, "unit")
        if self.lower is None and self.upper is None:
            raise ValueError("numeric requirement needs at least one inclusive bound")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("numeric bounds are reversed")


@dataclass(frozen=True, slots=True)
class MandateItem(_Record):
    item_id: str
    kind: MandateItemKind
    statement: str
    confirmation: ConfirmationRecord
    requirement: NumericRequirement | None = None

    def _validate(self):
        _text(self.item_id, "item_id")
        _text(self.statement, "statement")


@dataclass(frozen=True, slots=True)
class ResearchMandate(_Record):
    items: tuple[MandateItem, ...]

    def _validate(self):
        _unique((x.item_id for x in self.items), "mandate item")


class CatalogDefinitionKind(StrEnum):
    FACTOR = "FACTOR"
    SIGNAL = "SIGNAL"


@dataclass(frozen=True, slots=True)
class CatalogDefinitionRef(_Record):
    kind: CatalogDefinitionKind
    catalog_id: str
    version: int
    definition_sha256: str
    evidence: EvidenceRef

    def _validate(self):
        _text(self.catalog_id, "catalog_id")
        _hash(self.definition_sha256)
        if self.version < 1:
            raise ValueError("catalog version must be positive")


@dataclass(frozen=True, slots=True)
class ExperimentDefinitionRef(_Record):
    experiment_id: str
    definition_sha256: str
    source_sha256: str
    entrypoint: str

    def _validate(self):
        _hash(self.definition_sha256)
        _hash(self.source_sha256)
        _text(self.experiment_id, "experiment_id")
        _text(self.entrypoint, "entrypoint")


ComponentDefinitionRef = CatalogDefinitionRef | ExperimentDefinitionRef


class ComponentTestStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    INEFFECTIVE = "INEFFECTIVE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    REDUNDANT = "REDUNDANT"


@dataclass(frozen=True, slots=True)
class ComponentTestResult(_Record):
    test_id: str
    experiment_id: str
    protocol: EvidenceRef
    status: ComponentTestStatus
    explanation: str
    evidence: tuple[EvidenceRef, ...]
    fact_ids: tuple[str, ...] = ()

    def _validate(self):
        for name in ("test_id", "experiment_id", "explanation"):
            _text(getattr(self, name), name)
        if not self.evidence:
            raise ValueError("component test requires evidence, including negative results")
        _unique(self.fact_ids, "test fact")


@dataclass(frozen=True, slots=True)
class ComponentEntry(_Record):
    component_id: str
    definition: ComponentDefinitionRef
    role: str
    label: str
    horizon: str
    control: str
    availability: str
    price_basis: str
    applicability: str
    judgment: str
    tests: tuple[ComponentTestResult, ...]

    def _validate(self):
        for name in (
            "component_id",
            "role",
            "label",
            "horizon",
            "control",
            "availability",
            "price_basis",
            "applicability",
            "judgment",
        ):
            _text(getattr(self, name), name)
        _unique((x.test_id for x in self.tests), "test_id")


@dataclass(frozen=True, slots=True)
class ComponentPanel(_Record):
    components: tuple[ComponentEntry, ...]
    conclusion: str

    def _validate(self):
        _unique((x.component_id for x in self.components), "component_id")
        _text(self.conclusion, "conclusion")


@dataclass(frozen=True, slots=True)
class CandidateIdentityRef(_Record):
    key: CandidateKey
    content_sha256: str

    def _validate(self):
        _hash(self.content_sha256)


@dataclass(frozen=True, slots=True)
class EvaluationEvidenceRef(_Record):
    experiment_id: str
    attempt_id: str
    evaluation_ids: tuple[str, ...] = ()

    def _validate(self):
        _text(self.experiment_id, "experiment_id")
        _text(self.attempt_id, "attempt_id")
        _unique(self.evaluation_ids, "evaluation_id")
        for value in self.evaluation_ids:
            _hash(value)


@dataclass(frozen=True, slots=True)
class CandidateEntry(_Record):
    identity: CandidateIdentityRef
    hypothesis: str
    judgment: str
    evaluations: tuple[EvaluationEvidenceRef, ...]

    def _validate(self):
        _text(self.hypothesis, "hypothesis")
        _text(self.judgment, "judgment")
        _unique(((x.experiment_id, x.attempt_id) for x in self.evaluations), "evaluation attempt")


class ParameterScale(StrEnum):
    LINEAR = "LINEAR"
    LOG = "LOG"


@dataclass(frozen=True, slots=True)
class NumericParameterDomain(_Record):
    name: str
    lower: float
    upper: float
    scale: ParameterScale = ParameterScale.LINEAR
    step: float | None = None
    integer: bool = False

    def _validate(self):
        _text(self.name, "parameter name")
        if self.lower > self.upper or (self.scale is ParameterScale.LOG and self.lower <= 0):
            raise ValueError("invalid parameter bounds")
        if self.step is not None and self.step <= 0:
            raise ValueError("parameter step must be positive")
        if self.integer and any(
            not x.is_integer()
            for x in (self.lower, self.upper, *((self.step,) if self.step else ()))
        ):
            raise ValueError("integer domain requires integral bounds and step")


Scalar = str | int | float | bool


@dataclass(frozen=True, slots=True)
class CategoricalParameterDomain(_Record):
    name: str
    choices: tuple[Scalar, ...]

    def _validate(self):
        _text(self.name, "parameter name")
        if not self.choices:
            raise ValueError("categorical choices must be nonempty")
        _unique((_canonical(x) for x in self.choices), "categorical choice")


@dataclass(frozen=True, slots=True)
class ParameterValue(_Record):
    name: str
    value: Scalar

    def _validate(self):
        _text(self.name, "parameter name")


class SearchTrialStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PRUNED = "PRUNED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class SearchTrial(_Record):
    proposal_id: str
    parameters: tuple[ParameterValue, ...]
    status: SearchTrialStatus
    reason: str
    candidate: CandidateIdentityRef | None = None
    evaluations: tuple[EvaluationEvidenceRef, ...] = ()
    predecessor_proposal_id: str | None = None

    def _validate(self):
        _text(self.proposal_id, "proposal_id")
        _text(self.reason, "trial reason")
        _unique((x.name for x in self.parameters), "parameter")
        if self.predecessor_proposal_id == self.proposal_id:
            raise ValueError("proposal cannot succeed itself")
        if self.evaluations and self.candidate is None:
            raise ValueError("evaluation references require candidate identity")


@dataclass(frozen=True, slots=True)
class SearchRecord(_Record):
    search_id: str
    domains: tuple[NumericParameterDomain | CategoricalParameterDomain, ...]
    method: str
    method_version: str
    seed: int | None
    scheduling: str
    declared_budget: int | None
    trials: tuple[SearchTrial, ...]
    stop_reason: str

    def _validate(self):
        for name in ("search_id", "method", "method_version", "scheduling", "stop_reason"):
            _text(getattr(self, name), name)
        if self.declared_budget is not None and self.declared_budget < 1:
            raise ValueError("declared budget must be positive")
        _unique((x.name for x in self.domains), "domain")
        _unique((x.proposal_id for x in self.trials), "proposal_id")
        seen = set()
        for trial in self.trials:
            if (
                trial.predecessor_proposal_id is not None
                and trial.predecessor_proposal_id not in seen
            ):
                raise ValueError("successor must reference an earlier declared proposal")
            seen.add(trial.proposal_id)
            domains = {x.name: x for x in self.domains}
            for parameter in trial.parameters:
                if parameter.name not in domains:
                    raise ValueError("trial parameter has no declared domain")
                domain = domains[parameter.name]
                if isinstance(domain, CategoricalParameterDomain):
                    if _canonical(parameter.value) not in tuple(
                        _canonical(v) for v in domain.choices
                    ):
                        raise ValueError("trial value outside categorical domain")
                else:
                    value = parameter.value
                    if type(value) not in (float, int) or not domain.lower <= value <= domain.upper:
                        raise ValueError("trial value outside numeric domain")
                    if domain.integer and type(value) is not int:
                        raise ValueError("integer parameter requires int value")
                    if domain.step is not None:
                        n = (value - domain.lower) / domain.step
                        if not math.isclose(n, round(n), abs_tol=1e-9, rel_tol=0):
                            raise ValueError("trial value differs from declared step")


@dataclass(frozen=True, slots=True)
class CandidateSet(_Record):
    candidates: tuple[CandidateEntry, ...]
    handoff: tuple[CandidateKey, ...]
    searches: tuple[SearchRecord, ...]
    conclusion: str

    def _validate(self):
        _text(self.conclusion, "conclusion")
        _unique((x.identity.key for x in self.candidates), "candidate key")
        _unique(self.handoff, "handoff candidate")
        _unique((x.search_id for x in self.searches), "search_id")
        candidates = {x.identity.key: x.identity for x in self.candidates}
        if any(key not in candidates for key in self.handoff):
            raise ValueError("handoff candidate absent from candidate set")
        for search in self.searches:
            for trial in search.trials:
                if (
                    trial.candidate is not None
                    and candidates.get(trial.candidate.key) != trial.candidate
                ):
                    raise ValueError("trial candidate absent or content differs")


class FactStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class FactValue(_Record):
    fact_id: str
    value: Scalar | None
    unit: str
    status: FactStatus
    evidence: tuple[EvidenceRef, ...]
    reason: str | None = None

    def _validate(self):
        _text(self.fact_id, "fact_id")
        _text(self.unit, "unit")
        if not self.evidence:
            raise ValueError("fact requires source evidence")
        if self.status is FactStatus.AVAILABLE:
            if self.value is None or self.reason is not None:
                raise ValueError("available fact requires a value and no missing reason")
        elif self.value is not None or not self.reason or not self.reason.strip():
            raise ValueError("unavailable fact requires null value and reason")


class ExplanationKind(StrEnum):
    FACT = "FACT"
    HYPOTHESIS = "HYPOTHESIS"
    STATISTICAL_EVIDENCE = "STATISTICAL_EVIDENCE"
    RESEARCH_JUDGMENT = "RESEARCH_JUDGMENT"


@dataclass(frozen=True, slots=True)
class Explanation(_Record):
    kind: ExplanationKind
    text: str
    fact_ids: tuple[str, ...] = ()
    supporting: tuple[EvidenceRef, ...] = ()
    contrary: tuple[EvidenceRef, ...] = ()

    def _validate(self):
        _text(self.text, "explanation")
        _unique(self.fact_ids, "explanation fact")


@dataclass(frozen=True, slots=True)
class ReproductionSpec(_Record):
    instructions: str
    environment: tuple[EvidenceRef, ...]
    data_access: str
    determinism: str

    def _validate(self):
        for name in ("instructions", "data_access", "determinism"):
            _text(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class TargetMandateBinding(_Record):
    metric: ResearchMetric
    mandate_item_id: str

    def _validate(self):
        _text(self.mandate_item_id, "mandate_item_id")


@dataclass(frozen=True, slots=True)
class CandidateAssessmentDelivery(_Record):
    source_candidates: DeliveryReference
    source_mandate: DeliveryReference
    assessment_request: CandidateAssessmentRequest
    assessment: AssessmentPanel
    comparison_request: CandidateComparisonRequest
    comparison: CandidateComparison
    target_bindings: tuple[TargetMandateBinding, ...]
    frequency_window_item_id: str | None
    recommendation: str
    contrary_evidence: tuple[EvidenceRef, ...]
    pending_decisions: tuple[str, ...]

    def _validate(self):
        if (
            self.source_candidates.stage is not DeliveryStage.CANDIDATES
            or self.source_mandate.stage is not DeliveryStage.MANDATE
        ):
            raise ValueError("assessment requires candidate-set and mandate deliveries")
        if self.comparison_request.panel != self.assessment:
            raise ValueError("comparison must use the supplied assessment panel")
        _unique((x.metric for x in self.target_bindings), "target binding")
        _unique((x.mandate_item_id for x in self.target_bindings), "bound mandate item")
        _text(self.recommendation, "recommendation")
        if not self.pending_decisions:
            raise ValueError("assessment delivery must identify pending user decisions")
        for item in self.pending_decisions:
            _text(item, "pending decision")


@dataclass(frozen=True, slots=True)
class CandidateInspectionDelivery(_Record):
    source_assessment: DeliveryReference
    inspection: CandidateInspectionReport
    inspection_evidence: EvidenceRef
    decisions: tuple[DecisionReference, ...]
    freeze: FreezeReceipt | None
    pending_decisions: tuple[str, ...]

    def _validate(self):
        if self.source_assessment.stage is not DeliveryStage.ASSESSMENT:
            raise ValueError("inspection delivery requires assessment predecessor")
        if self.source_assessment.strategy_id != self.inspection.plan.origin.candidate.strategy_id:
            raise ValueError("inspection delivery candidate family differs")
        _unique((x.decision_id for x in self.decisions), "decision ID")
        if self.freeze is None and not self.pending_decisions:
            raise ValueError("unfrozen inspection must identify pending user decisions")
        for item in self.pending_decisions:
            _text(item, "pending decision")


StageContent = ResearchMandate | ComponentPanel | CandidateSet | CandidateAssessmentDelivery | CandidateInspectionDelivery
T = TypeVar("T", bound=StageContent)


@dataclass(frozen=True, slots=True)
class DeliveryContent(_Record, Generic[T]):
    payload: T
    status: DeliveryStatus
    facts: tuple[FactValue, ...]
    explanations: tuple[Explanation, ...]
    reproduction: ReproductionSpec
    incomplete_items: tuple[str, ...] = ()
    attachments: tuple[EvidenceFile, ...] = ()

    def _validate(self):
        _unique((x.fact_id for x in self.facts), "fact_id")
        _unique((x.reference.path.casefold() for x in self.attachments), "attachment path")
        if self.status is DeliveryStatus.COMPLETE and self.incomplete_items:
            raise ValueError("complete delivery cannot declare incomplete items")
        if self.status is not DeliveryStatus.COMPLETE and not self.incomplete_items:
            raise ValueError("partial/blocked delivery requires incomplete items")
        for item in self.incomplete_items:
            _text(item, "incomplete item")
        known = {x.fact_id for x in self.facts}
        refs = [x.fact_ids for x in self.explanations]
        if isinstance(self.payload, ComponentPanel):
            refs.extend(t.fact_ids for c in self.payload.components for t in c.tests)
        if any(ref not in known for group in refs for ref in group):
            raise ValueError("unknown fact reference")


class ResearchDeliverable(ABC, Generic[T]):
    @property
    @abstractmethod
    def definition(self) -> DeliveryDefinition: ...

    @abstractmethod
    def build(self) -> DeliveryContent[T]: ...


@dataclass(frozen=True, slots=True)
class DeliveryIssue(_Record):
    code: str
    field_path: str
    message: str


@dataclass(frozen=True, slots=True)
class DeliveryValidation(_Record):
    status: ValidationStatus
    issues: tuple[DeliveryIssue, ...] = ()

    def _validate(self):
        if (self.status is ValidationStatus.PASS) != (not self.issues):
            raise ValueError("validation status differs from issues")


@dataclass(frozen=True, slots=True)
class DeliveryReceipt(_Record):
    reference: DeliveryReference
    files: tuple[EvidenceRef, ...]
    schema_version: int = 1

    def _validate(self):
        if self.schema_version != 1:
            raise ValueError("unsupported receipt schema")
        if not self.files:
            raise ValueError("receipt requires file manifest")
        _unique((x.path.casefold() for x in self.files), "receipt file")


class DeliveryValidationError(ValueError):
    def __init__(self, issues: tuple[DeliveryIssue, ...]):
        self.issues = issues
        super().__init__("; ".join(f"{x.field_path}: {x.message}" for x in issues))


class DeliveryConflictError(ValueError):
    """A delivery revision has already been published with different content."""


def _encode(value):
    if is_dataclass(value):
        return {
            "type": type(value).__name__,
            **{field.name: _encode(getattr(value, field.name)) for field in fields(value)},
        }
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_encode(x) for x in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value


def _decode(value, annotation):
    if isinstance(annotation, TypeVar):
        annotation = annotation.__bound__
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        for part in get_args(annotation):
            try:
                return _decode(value, part)
            except (ValueError, TypeError, KeyError):
                pass
        raise ValueError(f"value does not match {annotation}")
    if origin is tuple:
        if type(value) is not list:
            raise TypeError("serialized tuple must be an array")
        return tuple(_decode(x, get_args(annotation)[0]) for x in value)
    if isinstance(annotation, type) and is_dataclass(annotation):
        names = {f.name for f in fields(annotation)}
        if type(value) is not dict or set(value) != names | {"type"}:
            raise ValueError("record fields differ from schema")
        if value["type"] != annotation.__name__:
            raise ValueError("record discriminator differs")
        hints = get_type_hints(annotation)
        return annotation(**{key: _decode(value[key], hints[key]) for key in names})
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        if type(value) is not str:
            raise TypeError("serialized enum must be a string")
        return annotation(value)
    if not _matches(value, annotation):
        raise TypeError(f"value requires {annotation}")
    return value


def _canonical(value) -> bytes:
    return json.dumps(
        _encode(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(value) -> str:
    return sha256(_canonical(value)).hexdigest()


__all__ = [
    name
    for name, value in globals().copy().items()
    if isinstance(value, type) and value.__module__ == __name__ and not name.startswith("_")
] + ["ComponentDefinitionRef", "StageContent"]
