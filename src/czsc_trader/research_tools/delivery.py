"""Typed research handoffs. These values describe evidence, never control research."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar

from ..backtesting.benchmark_contracts import EvaluationBenchmark

from strategy_manager import CandidateKey
from strategy_manager import ResearchEvidenceRef, DecisionReference, FreezeReceipt
from strategy_evaluator import (
    CandidateAssessmentRequest,
    AssessmentPanel,
    CandidateComparisonRequest,
    CandidateComparison,
    ResearchTarget,
    FrequencyCoverageTarget,
    ParameterGroupTarget,
    ParameterNeighborhoodTarget,
)


from ._records import _Record, _text, _hash, _path, _unique
from ._records import _canonical as _canonical, _digest as _digest, _encode as _encode
from .context import ResearchBatchRef
from .evidence import EvidenceRef

Scalar = str | int | float | bool


class DeliveryStage(StrEnum):
    MANDATE = "MANDATE"
    COMPONENTS = "COMPONENTS"
    PROTOTYPES = "PROTOTYPES"
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


def _schema_version(stage: DeliveryStage) -> int:
    if stage in (DeliveryStage.MANDATE, DeliveryStage.ASSESSMENT):
        return 12
    if stage is DeliveryStage.PROTOTYPES:
        return 10
    return 9 if stage is DeliveryStage.INSPECTION else 8


def _readable_schema_versions(stage: DeliveryStage) -> tuple[int, ...]:
    if stage in (DeliveryStage.MANDATE, DeliveryStage.ASSESSMENT):
        return (8, 11, 12)
    return (_schema_version(stage),)


@dataclass(frozen=True, slots=True)
class DeliveryReference(_Record):
    batch: ResearchBatchRef
    stage: DeliveryStage
    revision: int
    content_sha256: str

    @property
    def strategy_id(self):
        return self.batch.strategy_id

    def _validate(self):
        if self.revision < 1:
            raise ValueError("revision must be positive")
        _hash(self.content_sha256)


@dataclass(frozen=True, slots=True)
class DeliveryDefinition(_Record):
    batch: ResearchBatchRef
    stage: DeliveryStage
    revision: int
    predecessors: tuple[DeliveryReference, ...] = ()
    schema_version: int | None = None

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or type(value.get("schema_version")) is not int:
            raise ValueError("serialized delivery requires an explicit integer schema version")
        return _Record.from_dict.__func__(cls, value)

    def __post_init__(self):
        if self.schema_version is None:
            object.__setattr__(self, "schema_version", _schema_version(self.stage))
        _Record.__post_init__(self)

    @property
    def strategy_id(self):
        return self.batch.strategy_id

    def _validate(self):
        if self.revision < 1 or self.schema_version not in _readable_schema_versions(self.stage):
            raise ValueError("invalid delivery revision/schema")
        if self.stage is DeliveryStage.INSPECTION and self.predecessors:
            raise ValueError("inspection has no research delivery predecessors")
        _unique(((x.stage,x.revision) for x in self.predecessors), "predecessor")
        for ref in self.predecessors:
            if ref.batch != self.batch:
                raise ValueError("predecessor belongs to another batch")
            if ref.stage == self.stage and ref.revision >= self.revision:
                raise ValueError("same-stage predecessor must be an earlier revision")


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
class PerformanceRequirement(_Record):
    targets: tuple[ResearchTarget | FrequencyCoverageTarget | ParameterGroupTarget | ParameterNeighborhoodTarget, ...]

    def _validate(self):
        if not self.targets:
            raise ValueError("performance requirement needs targets")
        _unique((target.target_id for target in self.targets), "performance target")


@dataclass(frozen=True, slots=True)
class BenchmarkRequirement(_Record):
    benchmark: EvaluationBenchmark


@dataclass(frozen=True, slots=True)
class MandateItem(_Record):
    item_id: str
    kind: MandateItemKind
    statement: str
    confirmation: ConfirmationRecord
    requirement: NumericRequirement | PerformanceRequirement | BenchmarkRequirement | None = None

    def _validate(self):
        _text(self.item_id, "item_id")
        _text(self.statement, "statement")
        if (self.kind is MandateItemKind.BENCHMARK) != isinstance(
            self.requirement, BenchmarkRequirement
        ):
            raise ValueError("benchmark mandate requires a typed BenchmarkRequirement")
        if isinstance(self.requirement, PerformanceRequirement) and self.kind not in (
            MandateItemKind.OBJECTIVE,
            MandateItemKind.CONSTRAINT,
        ):
            raise ValueError("performance requirement must be an objective or constraint")
        if isinstance(self.requirement, NumericRequirement) and self.kind in (
            MandateItemKind.OBJECTIVE,
            MandateItemKind.CONSTRAINT,
        ):
            raise ValueError("performance objectives/constraints require typed targets")


@dataclass(frozen=True, slots=True)
class ResearchMandate(_Record):
    items: tuple[MandateItem, ...]

    def _validate(self):
        _unique((x.item_id for x in self.items), "mandate item")
        _unique(
            (
                target.target_id
                for item in self.items
                if isinstance(item.requirement, PerformanceRequirement)
                for target in item.requirement.targets
            ),
            "mandate target",
        )


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
    evidence: EvidenceRef
    entrypoint: str

    def _validate(self):
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
    evidence: EvidenceRef
    evaluation_ids: tuple[str, ...] = ()

    def _validate(self):
        if self.evidence.schema != "account_evaluation" or self.evidence.schema_version not in (7, 8):
            raise ValueError("evaluation evidence requires published account schema 7 or 8")
        _unique(self.evaluation_ids, "evaluation ID")
        for value in self.evaluation_ids:
            _hash(value)


class PrototypeDisposition(StrEnum):
    DEVELOP = "DEVELOP"
    INVESTIGATE = "INVESTIGATE"
    STOP = "STOP"


@dataclass(frozen=True, slots=True)
class PrototypeReference(_Record):
    delivery: DeliveryReference
    prototype_id: str

    def _validate(self):
        if self.delivery.stage is not DeliveryStage.PROTOTYPES:
            raise ValueError("prototype reference requires a PROTOTYPES delivery")
        _text(self.prototype_id, "prototype_id")


@dataclass(frozen=True, slots=True)
class PrototypeComponentUse(_Record):
    component_id: str
    role: str
    rationale: str

    def _validate(self):
        for name in ("component_id", "role", "rationale"):
            _text(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class PrototypeEntry(_Record):
    prototype_id: str
    identity: CandidateIdentityRef
    definition: ExperimentDefinitionRef
    hypothesis: str
    components: tuple[PrototypeComponentUse, ...]
    evaluations: tuple[EvaluationEvidenceRef, ...]
    disposition: PrototypeDisposition
    judgment: str
    limitations: tuple[str, ...]
    next_step: str
    evidence: tuple[EvidenceRef, ...]
    missing_evaluation_reason: str | None = None
    sources: tuple[PrototypeReference, ...] = ()

    def _validate(self):
        for name in ("prototype_id", "hypothesis", "judgment", "next_step"):
            _text(getattr(self, name), name)
        for item in self.limitations:
            _text(item, "prototype limitation")
        _unique(((x.component_id, x.role) for x in self.components), "prototype component role")
        _unique((x.evidence for x in self.evaluations), "prototype evaluation evidence")
        _unique(self.evidence, "prototype evidence")
        _unique(self.sources, "prototype source")
        if not self.evaluations:
            _text(self.missing_evaluation_reason, "missing_evaluation_reason")
        elif self.missing_evaluation_reason is not None:
            raise ValueError("account-backed prototype cannot declare missing evaluations")


@dataclass(frozen=True, slots=True)
class PrototypeComparison(_Record):
    comparison_id: str
    subject_id: str
    control_id: str
    question: str
    protocol: EvidenceRef
    evidence: tuple[EvidenceRef, ...]
    conclusion: str

    def _validate(self):
        for name in ("comparison_id", "subject_id", "control_id", "question", "conclusion"):
            _text(getattr(self, name), name)
        if self.subject_id == self.control_id:
            raise ValueError("prototype comparison requires different entries")
        if not self.evidence:
            raise ValueError("prototype comparison requires result evidence")
        _unique(self.evidence, "prototype comparison evidence")


@dataclass(frozen=True, slots=True)
class PrototypePanel(_Record):
    prototypes: tuple[PrototypeEntry, ...]
    components: tuple[ComponentEntry, ...]
    comparisons: tuple[PrototypeComparison, ...]
    conclusion: str

    def _validate(self):
        _text(self.conclusion, "prototype panel conclusion")
        _unique((x.prototype_id for x in self.prototypes), "prototype_id")
        _unique((x.component_id for x in self.components), "component_id")
        _unique((x.comparison_id for x in self.comparisons), "comparison_id")
        component_ids = {x.component_id for x in self.components}
        prototype_ids = {x.prototype_id for x in self.prototypes}
        if any(use.component_id not in component_ids for item in self.prototypes for use in item.components):
            raise ValueError("prototype refers to an absent component")
        if any(x.subject_id not in prototype_ids or x.control_id not in prototype_ids for x in self.comparisons):
            raise ValueError("prototype comparison refers to an absent entry")


@dataclass(frozen=True, slots=True)
class CandidateEntry(_Record):
    identity: CandidateIdentityRef
    hypothesis: str
    judgment: str
    evaluations: tuple[EvaluationEvidenceRef, ...]

    def _validate(self):
        _text(self.hypothesis, "hypothesis")
        _text(self.judgment, "judgment")
        _unique((x.evidence for x in self.evaluations), "evaluation evidence")


@dataclass(frozen=True, slots=True)
class SearchSummary(_Record):
    search_id: str
    method: str
    scope: str
    evaluations: int
    unique_configurations: int
    selection: str
    limitations: tuple[str, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()

    def _validate(self):
        for name in ("search_id","method","scope","selection"):
            _text(getattr(self,name),name)
        if not 0 <= self.unique_configurations <= self.evaluations:
            raise ValueError("search counts must be nonnegative and internally consistent")
        for item in self.limitations:
            _text(item,"search limitation")


@dataclass(frozen=True, slots=True)
class CandidateSet(_Record):
    candidates: tuple[CandidateEntry, ...]
    handoff: tuple[CandidateKey, ...]
    searches: tuple[SearchSummary, ...]
    conclusion: str

    def _validate(self):
        _text(self.conclusion,"conclusion")
        _unique((x.identity.key for x in self.candidates),"candidate key")
        _unique(self.handoff,"handoff candidate")
        _unique((x.search_id for x in self.searches),"search ID")
        if not set(self.handoff).issubset({x.identity.key for x in self.candidates}):
            raise ValueError("handoff candidate absent from candidate set")


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
class TargetMandateBinding(_Record):
    target_id: str
    mandate_item_id: str

    def _validate(self):
        _text(self.target_id, "target_id")
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
    benchmark_mandate_item_id: str
    recommendation: str
    contrary_evidence: tuple[EvidenceRef, ...]
    pending_decisions: tuple[str, ...]

    parameter_plans: tuple[EvidenceRef, ...] = ()

    def _validate(self):
        if (
            self.source_candidates.stage is not DeliveryStage.CANDIDATES
            or self.source_mandate.stage is not DeliveryStage.MANDATE
        ):
            raise ValueError("assessment requires candidate-set and mandate deliveries")
        if self.comparison_request.panel != self.assessment:
            raise ValueError("comparison must use the supplied assessment panel")
        _unique((x.target_id for x in self.target_bindings), "target binding")
        _text(self.recommendation, "recommendation")
        for item in self.pending_decisions:
            _text(item, "pending decision")


@dataclass(frozen=True, slots=True)
class CandidateInspectionDelivery(_Record):
    inspection: ResearchEvidenceRef
    decisions: tuple[DecisionReference, ...]
    freeze: FreezeReceipt | None
    pending_decisions: tuple[str, ...]

    def _validate(self):
        if self.inspection.owner.experiment_id is None:
            raise ValueError("inspection report requires an experiment owner")
        if any(item.evidence.owner.strategy_id != self.inspection.owner.strategy_id for item in self.decisions):
            raise ValueError("inspection decisions must belong to its research batch")
        if self.freeze is not None and self.freeze.request_id.strategy_id != self.inspection.owner.strategy_id:
            raise ValueError("inspection freeze must belong to its research batch")
        _unique((x.decision_id for x in self.decisions), "decision ID")
        for item in self.pending_decisions:
            _text(item, "pending decision")


StageContent = (
    ResearchMandate
    | ComponentPanel
    | PrototypePanel
    | CandidateSet
    | CandidateAssessmentDelivery
    | CandidateInspectionDelivery
)
T = TypeVar("T", bound=StageContent)


@dataclass(frozen=True, slots=True)
class DeliveryContent(_Record, Generic[T]):
    payload: T
    status: DeliveryStatus
    facts: tuple[FactValue, ...]
    explanations: tuple[Explanation, ...]
    incomplete_items: tuple[str, ...] = ()
    report: str = field(kw_only=True)
    evidence: tuple[EvidenceRef, ...] = field(default=(), kw_only=True)

    def _validate(self):
        _text(self.report, "research report")
        _unique(self.evidence, "report evidence")
        _unique((x.fact_id for x in self.facts), "fact_id")
        if self.status is DeliveryStatus.COMPLETE and self.incomplete_items:
            raise ValueError("complete delivery cannot declare incomplete items")
        if self.status is not DeliveryStatus.COMPLETE and not self.incomplete_items:
            raise ValueError("partial/blocked delivery requires incomplete items")
        for item in self.incomplete_items:
            _text(item, "incomplete item")
        known = {x.fact_id for x in self.facts}
        refs = [x.fact_ids for x in self.explanations]
        if isinstance(self.payload, (ComponentPanel, PrototypePanel)):
            refs.extend(t.fact_ids for c in self.payload.components for t in c.tests)
        if any(ref not in known for group in refs for ref in group):
            raise ValueError("unknown fact reference")


@dataclass(frozen=True, slots=True)
class DeliveryIssue(_Record):
    code: str
    field_path: str
    message: str


class DeliveryValidationScope(StrEnum):
    INTEGRITY = "INTEGRITY"
    FULL = "FULL"


class DeliveryValidationPhase(StrEnum):
    PACKAGE_LOAD = "PACKAGE_LOAD"
    AUTHENTICATION = "AUTHENTICATION"
    RECOMPUTATION = "RECOMPUTATION"
    FINAL_RECHECK = "FINAL_RECHECK"


@dataclass(frozen=True, slots=True)
class DeliveryValidationProgress(_Record):
    phase: DeliveryValidationPhase
    completed: int
    total: int
    elapsed_seconds: float

    def _validate(self):
        if not 0 <= self.completed <= self.total or self.elapsed_seconds < 0:
            raise ValueError("invalid delivery validation progress")


@dataclass(frozen=True, slots=True)
class DeliveryValidationStats(_Record):
    unique_deliveries: int
    reference_visits: int
    recursive_expansions: int
    semantic_reuses: int
    files_hashed: int
    bytes_hashed: int
    elapsed_seconds: float
    authentication_seconds: float = 0.0
    recomputation_seconds: float = 0.0
    final_recheck_seconds: float = 0.0
    accounts_authenticated: int = 0
    account_reuses: int = 0
    file_read_task_seconds: float = 0.0
    file_hash_task_seconds: float = 0.0
    package_load_seconds: float = 0.0

    def _validate(self):
        for name in ("unique_deliveries", "reference_visits", "recursive_expansions",
                     "semantic_reuses", "files_hashed", "bytes_hashed",
                     "accounts_authenticated", "account_reuses"):
            if getattr(self, name) < 0:
                raise ValueError("validation counters must be nonnegative")
        for name in ("elapsed_seconds", "authentication_seconds", "recomputation_seconds",
                     "final_recheck_seconds", "file_read_task_seconds", "file_hash_task_seconds",
                     "package_load_seconds"):
            if getattr(self, name) < 0:
                raise ValueError("validation elapsed time must be nonnegative")


@dataclass(frozen=True, slots=True)
class DeliveryValidation(_Record):
    status: ValidationStatus
    scope: DeliveryValidationScope
    issues: tuple[DeliveryIssue, ...] = ()
    stats: DeliveryValidationStats | None = field(default=None, compare=False)

    def _validate(self):
        if (self.status is ValidationStatus.PASS) != (not self.issues):
            raise ValueError("validation status differs from issues")


@dataclass(frozen=True, slots=True)
class PublicationFile(_Record):
    path: str
    sha256: str

    def _validate(self):
        _path(self.path)
        _hash(self.sha256)


@dataclass(frozen=True, slots=True)
class DeliveryReceipt(_Record):
    reference: DeliveryReference
    files: tuple[PublicationFile, ...]
    schema_version: int | None = None

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or type(value.get("schema_version")) is not int:
            raise ValueError("serialized delivery requires an explicit integer schema version")
        return _Record.from_dict.__func__(cls, value)

    def __post_init__(self):
        if self.schema_version is None:
            object.__setattr__(self, "schema_version", _schema_version(self.reference.stage))
        _Record.__post_init__(self)

    def _validate(self):
        if self.schema_version not in _readable_schema_versions(self.reference.stage):
            raise ValueError("unsupported receipt schema")
        if not self.files:
            raise ValueError("receipt requires file manifest")
        _unique((x.path.casefold() for x in self.files), "receipt file")


@dataclass(frozen=True, slots=True)
class DeliveryAssemblyResult(_Record):
    """Runtime result; the persisted receipt/schema remains unchanged."""

    receipt: DeliveryReceipt
    validation: DeliveryValidation

    def _validate(self):
        if (self.validation.status is not ValidationStatus.PASS
            or self.validation.scope is not DeliveryValidationScope.FULL):
            raise ValueError("assembly result requires a completed FULL PASS")



class DeliveryValidationError(ValueError):
    def __init__(self, issues: tuple[DeliveryIssue, ...]):
        self.issues = issues
        super().__init__("; ".join(f"{x.field_path}: {x.message}" for x in issues))


class DeliveryConflictError(ValueError):
    """A delivery revision has already been published with different content."""


__all__ = [
    name
    for name, value in globals().copy().items()
    if isinstance(value, type) and value.__module__ == __name__ and not name.startswith("_")
] + ["ComponentDefinitionRef", "StageContent"]
