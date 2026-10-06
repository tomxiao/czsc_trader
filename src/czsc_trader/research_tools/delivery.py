"""Typed research handoffs. These values describe evidence, never control research."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar

from ..backtesting.benchmark_contracts import EvaluationBenchmark

from strategy_manager import CandidateKey
from strategy_manager import CandidateInspectionReport, DecisionReference, FreezeReceipt
from strategy_evaluator import (
    CandidateAssessmentRequest,
    AssessmentPanel,
    CandidateComparisonRequest,
    CandidateComparison,
    ResearchTarget,
)


from ._records import _Record, _text, _hash, _path, _unique
from ._records import _canonical as _canonical, _digest as _digest, _encode as _encode
from .context import ResearchBatchRef
from .evidence import EvidenceRef

Scalar = str | int | float | bool


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
    schema_version: int = 6

    @property
    def strategy_id(self):
        return self.batch.strategy_id

    def _validate(self):
        if self.revision < 1 or self.schema_version != 6:
            raise ValueError("invalid delivery revision/schema")
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
    targets: tuple[ResearchTarget, ...]

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
        if (self.evidence.schema,self.evidence.schema_version) != ("account_evaluation",5):
            raise ValueError("evaluation evidence requires published account schema 5")
        _unique(self.evaluation_ids, "evaluation ID")
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
        if self.source_assessment.strategy_id != self.inspection.origin.candidate.strategy_id:
            raise ValueError("inspection delivery candidate family differs")
        _unique((x.decision_id for x in self.decisions), "decision ID")
        if self.freeze is None and not self.pending_decisions:
            raise ValueError("unfrozen inspection must identify pending user decisions")
        for item in self.pending_decisions:
            _text(item, "pending decision")


StageContent = (
    ResearchMandate
    | ComponentPanel
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
        if isinstance(self.payload, ComponentPanel):
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


@dataclass(frozen=True, slots=True)
class DeliveryValidation(_Record):
    status: ValidationStatus
    scope: DeliveryValidationScope
    issues: tuple[DeliveryIssue, ...] = ()

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
    schema_version: int = 6

    def _validate(self):
        if self.schema_version != 6:
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


__all__ = [
    name
    for name, value in globals().copy().items()
    if isinstance(value, type) and value.__module__ == __name__ and not name.startswith("_")
] + ["ComponentDefinitionRef", "StageContent"]
