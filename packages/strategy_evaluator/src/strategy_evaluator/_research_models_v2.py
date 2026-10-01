# Frozen schema-v2 validation semantics from e130c88b; read-only.
"""Research comparison contracts, independent of orchestration and repositories."""

from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
import json
import math
import re
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints

from .models import ValidationError


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def unique(values, name):
    values = tuple(values)
    require(len(values) == len(set(values)), f"duplicate {name}")


def digest(value):
    return sha256(
        json.dumps(
            encode(value),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def encode(value):
    if is_dataclass(value):
        return {
            "type": type(value).__name__,
            **{f.name: encode(getattr(value, f.name)) for f in fields(value)},
        }
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [encode(v) for v in value]
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    return value


def matches(value, annotation):
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return any(matches(value, arg) for arg in get_args(annotation))
    if origin is tuple:
        return type(value) is tuple and all(matches(v, get_args(annotation)[0]) for v in value)
    return type(value) is annotation and (annotation is not float or math.isfinite(value))


def decode(value, annotation):
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        for part in get_args(annotation):
            try:
                return decode(value, part)
            except (ValueError, TypeError, KeyError):
                pass
        raise ValidationError("record does not match union")
    if origin is tuple:
        require(type(value) is list, "tuple must decode from array")
        return tuple(decode(x, get_args(annotation)[0]) for x in value)
    if isinstance(annotation, type) and is_dataclass(annotation):
        names = {f.name for f in fields(annotation)}
        require(type(value) is dict and set(value) == names | {"type"}, "record fields differ")
        require(value["type"] == annotation.__name__, "record discriminator differs")
        hints = get_type_hints(annotation)
        return annotation(**{k: decode(value[k], hints[k]) for k in names})
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        require(type(value) is str, "enum requires string")
        return annotation(value)
    require(matches(value, annotation), f"value requires {annotation}")
    return value


class ResearchRecord:
    def __post_init__(self):
        for name, annotation in get_type_hints(type(self)).items():
            value = getattr(self, name)
            if not matches(value, annotation):
                raise TypeError(f"{type(self).__name__}.{name} requires {annotation}")
            if isinstance(value, str):
                require(bool(value.strip()), f"{name} must be nonempty")
                if name.endswith("sha256") or name == "evaluation_id":
                    require(re.fullmatch(r"[0-9a-f]{64}", value) is not None, f"invalid {name}")
        self.validate()

    def validate(self):
        pass

    def to_dict(self):
        return encode(self)

    @classmethod
    def from_dict(cls, value):
        return decode(value, cls)

    @property
    def sha256(self):
        return digest(self)


@dataclass(frozen=True)
class AssessmentCandidate(ResearchRecord):
    candidate_id: str
    content_sha256: str

    def validate(self):
        require(
            re.fullmatch(r"S\d{3,}-[A-Za-z][A-Za-z0-9_.-]*", self.candidate_id) is not None,
            "candidate_id must include strategy family",
        )


class FillSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class AssessmentDerivationKind(StrEnum):
    PARAMETERS = "PARAMETERS"
    IMPLEMENTATION = "IMPLEMENTATION"
    EXECUTION = "EXECUTION"


@dataclass(frozen=True)
class AssessmentFill(ResearchRecord):
    cycle_id: str
    session: str
    side: FillSide
    quantity: int
    price: float
    fees: float

    def validate(self):
        date.fromisoformat(self.session)
        require(self.quantity > 0 and self.price > 0 and self.fees >= 0, "invalid fill amounts")


@dataclass(frozen=True)
class AccountPoint(ResearchRecord):
    session: str
    cash: float
    quantity: int
    close: float
    equity: float

    def validate(self):
        date.fromisoformat(self.session)
        require(self.quantity >= 0 and self.close > 0 and self.equity > 0, "invalid account point")


@dataclass(frozen=True)
class ClosedCycle(ResearchRecord):
    cycle_id: str
    exit_session: str

    def validate(self):
        date.fromisoformat(self.exit_session)


@dataclass(frozen=True)
class EvaluationScenarioContext(ResearchRecord):
    one_way_cost: float
    measurement_tier: str
    benchmark_id: str
    benchmark_kind: str

    def validate(self):
        require(0 <= self.one_way_cost < 1, "cost must be in [0, 1)")


@dataclass(frozen=True)
class AssessmentEvidence(ResearchRecord):
    candidate: AssessmentCandidate
    experiment_id: str
    attempt_id: str
    evaluation_id: str
    request_sha256: str
    result_sha256: str
    context_sha256: str
    window_id: str
    scenario_id: str
    metric_version: str
    scenario_context: EvaluationScenarioContext
    initial_cash: float
    opening_cash: float
    opening_quantity: int
    frequency_window_days: int
    account: tuple[AccountPoint, ...]
    fills: tuple[AssessmentFill, ...]
    closed_cycles: tuple[ClosedCycle, ...]
    benchmark_equity: tuple[float, ...] = ()
    parent: AssessmentCandidate | None = None
    derivation_sha256: str | None = None
    behavior_sha256: str | None = None
    derivation_kind: AssessmentDerivationKind | None = None

    def validate(self):
        require(re.fullmatch(r"[0-9a-f]{32}", self.attempt_id) is not None, "invalid attempt_id")
        require(
            self.initial_cash > 0 and self.opening_quantity >= 0 and self.frequency_window_days > 0,
            "invalid account opening/frequency contract",
        )
        require(bool(self.account), "empty account")
        dates = tuple(x.session for x in self.account)
        require(tuple(sorted(set(dates))) == dates, "account dates must be unique and ordered")
        require(all(x.session in dates for x in self.fills), "fill outside account calendar")
        unique((x.cycle_id for x in self.closed_cycles), "closed cycle")
        require(
            all(x.exit_session in dates for x in self.closed_cycles),
            "close outside account calendar",
        )
        require(
            not self.benchmark_equity or len(self.benchmark_equity) == len(dates),
            "benchmark calendar differs",
        )
        require(all(x > 0 for x in self.benchmark_equity), "benchmark equity must be positive")
        require(
            (self.parent is None) == (self.derivation_sha256 is None),
            "incomplete derivation identity",
        )
        require(
            (self.parent is None) == (self.derivation_kind is None), "incomplete derivation kind"
        )
        require(self.parent != self.candidate, "candidate cannot derive from itself")


class DiagnosticStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    FAILED = "FAILED"


class ResearchMetric(StrEnum):
    FULL_SAMPLE_FREQUENCY = "FULL_SAMPLE_FREQUENCY"
    NET_ANNUAL_RETURN = "NET_ANNUAL_RETURN"
    DRAWDOWN_MAGNITUDE = "DRAWDOWN_MAGNITUDE"
    FREQUENCY_MEDIAN = "FREQUENCY_MEDIAN"
    FREQUENCY_Q10 = "FREQUENCY_Q10"
    PARAMETER_RETURN_DEGRADATION = "PARAMETER_RETURN_DEGRADATION"
    PARAMETER_DRAWDOWN_DEGRADATION = "PARAMETER_DRAWDOWN_DEGRADATION"
    ROLLING_EXCESS_Q10 = "ROLLING_EXCESS_Q10"
    STRESS_ANNUAL_LOSS = "STRESS_ANNUAL_LOSS"
    PROFIT_CONCENTRATION = "PROFIT_CONCENTRATION"


FREQUENCY_METRICS = (
    ResearchMetric.FULL_SAMPLE_FREQUENCY,
    ResearchMetric.FREQUENCY_MEDIAN,
    ResearchMetric.FREQUENCY_Q10,
)
BENCHMARK_METRICS = (ResearchMetric.NET_ANNUAL_RETURN, ResearchMetric.DRAWDOWN_MAGNITUDE)


class MetricUnit(StrEnum):
    RATIO = "RATIO"
    CLOSED_CYCLES_PER_WINDOW = "CLOSED_CYCLES_PER_WINDOW"


@dataclass(frozen=True)
class DiagnosticValue(ResearchRecord):
    metric: ResearchMetric
    unit: MetricUnit
    status: DiagnosticStatus
    value: float | None
    reason: str | None
    evaluation_ids: tuple[str, ...]

    def validate(self):
        unit = (
            MetricUnit.CLOSED_CYCLES_PER_WINDOW
            if self.metric in FREQUENCY_METRICS
            else MetricUnit.RATIO
        )
        require(self.unit is unit, "metric unit differs")
        require(
            (self.status is DiagnosticStatus.AVAILABLE) == (self.value is not None),
            "status/value differ",
        )
        require(
            (self.status is DiagnosticStatus.AVAILABLE) == (self.reason is None), "missing reason"
        )
        if self.value is not None:
            if self.metric in (
                ResearchMetric.DRAWDOWN_MAGNITUDE,
                ResearchMetric.PROFIT_CONCENTRATION,
            ):
                require(0 <= self.value <= 1, "metric outside ratio range")
            if self.metric in (
                ResearchMetric.FREQUENCY_MEDIAN,
                ResearchMetric.FREQUENCY_Q10,
                ResearchMetric.FULL_SAMPLE_FREQUENCY,
                ResearchMetric.PARAMETER_RETURN_DEGRADATION,
                ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
            ):
                require(self.value >= 0, "negative count/degradation")


class QuantileMethod(StrEnum):
    LINEAR = "LINEAR"
    WEIGHTED_ECDF = "WEIGHTED_ECDF"


@dataclass(frozen=True)
class PerturbationLink(ResearchRecord):
    parent: AssessmentCandidate
    child: AssessmentCandidate
    weight: float
    derivation_sha256: str

    def validate(self):
        require(
            self.parent != self.child and self.parent.candidate_id != self.child.candidate_id,
            "perturbation needs a distinct child",
        )
        require(self.weight > 0, "perturbation weight must be positive")


@dataclass(frozen=True)
class SelfCheckProtocol(ResearchRecord):
    version: str
    baseline_window: str
    standard_scenario: str
    stress_scenario: str
    rolling_window_days: int
    rolling_step_days: int
    quantile_method: QuantileMethod
    minimum_perturbations: int
    minimum_rolling_windows: int
    bootstrap_repetitions: int
    bootstrap_block_length: int
    seed: int
    reconciliation_tolerance: float
    pbo_blocks: int = 10

    def validate(self):
        for name in (
            "rolling_window_days",
            "rolling_step_days",
            "minimum_perturbations",
            "minimum_rolling_windows",
            "bootstrap_repetitions",
            "bootstrap_block_length",
        ):
            require(getattr(self, name) > 0, f"{name} must be positive")
        require(self.reconciliation_tolerance >= 0, "negative tolerance")
        require(self.standard_scenario != self.stress_scenario, "stress must differ from standard")
        require(
            self.pbo_blocks >= 2 and self.pbo_blocks % 2 == 0, "PBO requires positive even blocks"
        )
        require(self.seed >= 0, "seed must be nonnegative")


class IncompleteEvaluationStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class IncompleteEvaluation(ResearchRecord):
    candidate: AssessmentCandidate
    window_id: str
    scenario_id: str
    status: IncompleteEvaluationStatus
    reason: str
    experiment_id: str | None = None
    attempt_id: str | None = None

    def validate(self):
        require(
            (self.experiment_id is None) == (self.attempt_id is None),
            "incomplete attempt reference",
        )
        if self.status is IncompleteEvaluationStatus.NOT_RUN:
            require(self.attempt_id is None, "unexecuted slot has no attempt")
        else:
            require(self.attempt_id is not None, "executed failure requires attempt reference")
            require(
                re.fullmatch(r"[0-9a-f]{32}", self.attempt_id) is not None, "invalid attempt_id"
            )


@dataclass(frozen=True)
class FamilyReturnEvidence(ResearchRecord):
    candidates: tuple[AssessmentCandidate, ...]
    sessions: tuple[str, ...]
    returns: tuple[tuple[float, ...], ...]
    selected: AssessmentCandidate
    raw_trial_count: int
    limitations: tuple[str, ...]

    def validate(self):
        require(self.selected in self.candidates, "selected candidate absent from research family")
        unique((x.candidate_id for x in self.candidates), "family candidate")
        require(self.raw_trial_count >= len(self.candidates), "trial count below matrix width")
        require(tuple(sorted(set(self.sessions))) == self.sessions, "invalid family calendar")
        require(len(self.returns) == len(self.sessions), "family matrix/calendar differ")
        require(
            all(len(row) == len(self.candidates) for row in self.returns),
            "family matrix width differs",
        )
        for day in self.sessions:
            date.fromisoformat(day)
        require(all(x > -1 for row in self.returns for x in row), "invalid simple return")


@dataclass(frozen=True)
class CandidateAssessmentRequest(ResearchRecord):
    centers: tuple[AssessmentCandidate, ...]
    protocol: SelfCheckProtocol
    perturbations: tuple[PerturbationLink, ...]
    evidence: tuple[AssessmentEvidence, ...]
    incomplete: tuple[IncompleteEvaluation, ...] = ()
    family_returns: FamilyReturnEvidence | None = None

    def validate(self):
        require(bool(self.centers), "explicit center set must be nonempty")
        unique((x.candidate_id for x in self.centers), "center")
        unique(
            ((x.parent.candidate_id, x.child.candidate_id) for x in self.perturbations),
            "perturbation",
        )
        require(
            all(x.parent in self.centers for x in self.perturbations),
            "perturbation parent is not a center",
        )
        unique(
            ((x.candidate.candidate_id, x.window_id, x.scenario_id) for x in self.evidence),
            "evaluation coordinate",
        )
        unique((x.evaluation_id for x in self.evidence), "evaluation ID")
        unique(
            (
                (x.candidate.candidate_id, x.window_id, x.scenario_id, x.attempt_id)
                for x in self.incomplete
            ),
            "incomplete attempt",
        )
        executed = {(x.candidate, x.window_id, x.scenario_id) for x in self.evidence}
        require(
            all(
                x.status is not IncompleteEvaluationStatus.NOT_RUN
                or (x.candidate, x.window_id, x.scenario_id) not in executed
                for x in self.incomplete
            ),
            "NOT_RUN conflicts with completed evaluation evidence",
        )
        identities = {}
        for candidate in (
            *self.centers,
            *(x.child for x in self.perturbations),
            *(x.candidate for x in self.evidence),
            *(x.candidate for x in self.incomplete),
        ):
            previous = identities.setdefault(candidate.candidate_id, candidate.content_sha256)
            require(previous == candidate.content_sha256, "candidate content identity conflict")
        if self.protocol.quantile_method is QuantileMethod.LINEAR:
            for parent in self.centers:
                require(
                    len({x.weight for x in self.perturbations if x.parent == parent}) <= 1,
                    "unequal weights require WEIGHTED_ECDF",
                )


@dataclass(frozen=True)
class UncertaintyInterval(ResearchRecord):
    status: DiagnosticStatus
    lower_95: float | None
    upper_95: float | None
    reason: str | None

    def validate(self):
        if self.status is DiagnosticStatus.AVAILABLE:
            require(
                self.lower_95 is not None
                and self.upper_95 is not None
                and self.lower_95 <= self.upper_95
                and self.reason is None,
                "invalid interval",
            )
        else:
            require(
                self.lower_95 is None and self.upper_95 is None and self.reason is not None,
                "invalid missing interval",
            )


@dataclass(frozen=True)
class FamilyDiagnostic(ResearchRecord):
    name: str
    status: DiagnosticStatus
    value: float | None
    reason: str | None

    def validate(self):
        require(
            (self.status is DiagnosticStatus.AVAILABLE) == (self.value is not None),
            "invalid family diagnostic",
        )
        require(
            (self.status is DiagnosticStatus.AVAILABLE) == (self.reason is None),
            "invalid family reason",
        )


@dataclass(frozen=True)
class BenchmarkAssessment(ResearchRecord):
    diagnostics: tuple[DiagnosticValue, ...]

    def validate(self):
        unique((x.metric for x in self.diagnostics), "benchmark metric")
        require(
            {x.metric for x in self.diagnostics} == set(BENCHMARK_METRICS),
            "benchmark requires annual return and drawdown",
        )
        require(
            all(
                x.evaluation_ids for x in self.diagnostics if x.status is DiagnosticStatus.AVAILABLE
            ),
            "benchmark source required",
        )


@dataclass(frozen=True)
class CandidateAssessment(ResearchRecord):
    candidate: AssessmentCandidate
    context_sha256: str | None
    metric_version: str | None
    frequency_window_days: int | None
    baseline_scenario: EvaluationScenarioContext | None
    stress_scenario: EvaluationScenarioContext | None
    diagnostics: tuple[DiagnosticValue, ...]
    uncertainty: UncertaintyInterval
    coverage_gaps: tuple[str, ...]
    behavior_sha256: str | None
    benchmark: BenchmarkAssessment

    def validate(self):
        require(
            (self.context_sha256 is None) == (self.baseline_scenario is None),
            "baseline context/scenario must be supplied together",
        )
        require(
            self.baseline_scenario is not None
            or all(x.status is not DiagnosticStatus.AVAILABLE for x in self.diagnostics),
            "available diagnostics require a baseline scenario",
        )
        require(
            self.stress_scenario is not None
            or all(
                x.metric is not ResearchMetric.STRESS_ANNUAL_LOSS or x.value is None
                for x in self.diagnostics
            ),
            "available stress diagnostic requires a stress scenario",
        )
        unique((x.metric for x in self.diagnostics), "diagnostic metric")
        require(
            {x.metric for x in self.diagnostics} == set(ResearchMetric),
            "incomplete diagnostic schema",
        )
        require(
            self.baseline_scenario is not None
            or all(x.status is not DiagnosticStatus.AVAILABLE for x in self.benchmark.diagnostics),
            "available benchmark requires a baseline scenario",
        )


@dataclass(frozen=True)
class AssessmentPanel(ResearchRecord):
    request_sha256: str
    protocol_sha256: str
    rows: tuple[CandidateAssessment, ...]
    family_diagnostics: tuple[FamilyDiagnostic, ...]
    family_limitations: tuple[str, ...]
    formula_version: str = "research-assessment-v2"

    def validate(self):
        require(
            self.formula_version == "research-assessment-v2",
            "unsupported assessment formula version",
        )
        unique((x.candidate.candidate_id for x in self.rows), "panel candidate")


class ComparisonOperator(StrEnum):
    LT = "LT"
    LE = "LE"
    GT = "GT"
    GE = "GE"


@dataclass(frozen=True)
class ConstantBound(ResearchRecord):
    value: float
    inclusive: bool


@dataclass(frozen=True)
class BenchmarkBound(ResearchRecord):
    multiplier: float
    inclusive: bool

    def validate(self):
        require(self.multiplier > 0, "benchmark multiplier must be positive")


@dataclass(frozen=True)
class BenchmarkCondition(ResearchRecord):
    metric: ResearchMetric
    operator: ComparisonOperator
    value: float

    def validate(self):
        require(self.metric in BENCHMARK_METRICS, "unsupported benchmark condition metric")


@dataclass(frozen=True)
class ResearchTarget(ResearchRecord):
    target_id: str
    metric: ResearchMetric
    lower: ConstantBound | BenchmarkBound | None = None
    upper: ConstantBound | BenchmarkBound | None = None
    when: BenchmarkCondition | None = None

    def validate(self):
        require(
            self.metric
            in (
                ResearchMetric.NET_ANNUAL_RETURN,
                ResearchMetric.DRAWDOWN_MAGNITUDE,
                ResearchMetric.FREQUENCY_MEDIAN,
                ResearchMetric.FREQUENCY_Q10,
                ResearchMetric.FULL_SAMPLE_FREQUENCY,
            ),
            "unsupported research target",
        )
        require(self.lower is not None or self.upper is not None, "target has no bound")
        if isinstance(self.lower, ConstantBound) and isinstance(self.upper, ConstantBound):
            require(
                self.lower.value < self.upper.value
                or (
                    self.lower.value == self.upper.value
                    and self.lower.inclusive
                    and self.upper.inclusive
                ),
                "empty or reversed target bounds",
            )
        if any(isinstance(x, BenchmarkBound) for x in (self.lower, self.upper)):
            require(self.metric in BENCHMARK_METRICS, "unsupported benchmark bound metric")


@dataclass(frozen=True)
class ResearchTargets(ResearchRecord):
    requirements: tuple[ResearchTarget, ...]
    frequency_window_days: int

    def validate(self):
        unique((x.target_id for x in self.requirements), "research target")
        require(self.frequency_window_days > 0, "invalid frequency window")


RANKING_METRICS = (
    ResearchMetric.NET_ANNUAL_RETURN,
    ResearchMetric.DRAWDOWN_MAGNITUDE,
    ResearchMetric.PARAMETER_RETURN_DEGRADATION,
    ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
    ResearchMetric.ROLLING_EXCESS_Q10,
    ResearchMetric.STRESS_ANNUAL_LOSS,
    ResearchMetric.PROFIT_CONCENTRATION,
)


class BinRounding(StrEnum):
    FLOOR = "FLOOR"
    NEAREST_HALF_EVEN = "NEAREST_HALF_EVEN"
    NEAREST_HALF_UP = "NEAREST_HALF_UP"


@dataclass(frozen=True)
class MetricBinSpec(ResearchRecord):
    metric: ResearchMetric
    resolution: float
    origin: float
    rounding: BinRounding

    def validate(self):
        require(self.metric in RANKING_METRICS and self.resolution > 0, "invalid ranking bin")


@dataclass(frozen=True)
class ComparisonVariant(ResearchRecord):
    name: str
    bins: tuple[MetricBinSpec, ...]
    adjacent_swap: int | None = None

    def validate(self):
        unique((x.metric for x in self.bins), "variant bin")
        require({x.metric for x in self.bins} == set(RANKING_METRICS), "seven bins required")
        require(
            self.adjacent_swap is None or 0 <= self.adjacent_swap < 6,
            "invalid adjacent priority swap",
        )


class ParetoBasis(StrEnum):
    RAW = "RAW"
    BINNED = "BINNED"


class MissingEvidencePolicy(StrEnum):
    REQUIRE_COMPLETE = "REQUIRE_COMPLETE"
    PREFIX_PARTIAL = "PREFIX_PARTIAL"


@dataclass(frozen=True)
class ComparisonPolicy(ResearchRecord):
    version: str
    bins: tuple[MetricBinSpec, ...]
    pareto_basis: ParetoBasis
    missing_evidence_policy: MissingEvidencePolicy
    sensitivities: tuple[ComparisonVariant, ...] = ()

    def validate(self):
        ComparisonVariant("baseline", self.bins)
        unique((x.name for x in self.sensitivities), "sensitivity name")


@dataclass(frozen=True)
class CandidateComparisonRequest(ResearchRecord):
    candidates: tuple[AssessmentCandidate, ...]
    targets: ResearchTargets
    panel: AssessmentPanel
    policy: ComparisonPolicy

    def validate(self):
        require(bool(self.candidates), "explicit comparison set required")
        unique((x.candidate_id for x in self.candidates), "comparison candidate")
        require(
            set(self.candidates) == {x.candidate for x in self.panel.rows},
            "comparison set differs from panel",
        )


class ComparisonStatus(StrEnum):
    TARGET_NOT_MET = "TARGET_NOT_MET"
    INCOMPARABLE = "INCOMPARABLE"
    RANKED = "RANKED"
    PARTIALLY_ORDERED = "PARTIALLY_ORDERED"
    TIED = "TIED"


class TargetCheckStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class TargetCheck(ResearchRecord):
    target: ResearchTarget
    observed: float | None
    status: TargetCheckStatus
    reason: str | None
    resolved_lower: float | None
    resolved_upper: float | None
    condition_observed: float | None
    evaluation_ids: tuple[str, ...]

    def validate(self):
        require(
            (self.status is TargetCheckStatus.PASSED) == (self.reason is None),
            "target status/reason differ",
        )
        require(
            self.status not in (TargetCheckStatus.PASSED, TargetCheckStatus.FAILED)
            or self.observed is not None,
            "decided target requires observation",
        )


@dataclass(frozen=True)
class CandidateRank(ResearchRecord):
    candidate: AssessmentCandidate
    status: ComparisonStatus
    target_checks: tuple[TargetCheck, ...]
    pareto_layer: int | None
    rank_in_layer: int | None
    bin_values: tuple[int | None, ...]
    reasons: tuple[str, ...]
    rank_min: int | None
    rank_max: int | None

    def validate(self):
        require((self.rank_min is None) == (self.rank_max is None), "rank interval incomplete")
        if self.rank_min is not None:
            require(
                self.pareto_layer is not None and 1 <= self.rank_min <= self.rank_max,
                "invalid rank interval",
            )
        require(
            self.rank_in_layer is None or self.rank_in_layer == self.rank_min,
            "exact/tied rank must equal the first possible rank",
        )


class PairwiseRelation(StrEnum):
    A_BEFORE_B = "A_BEFORE_B"
    B_BEFORE_A = "B_BEFORE_A"
    TIE = "TIE"
    INCOMPARABLE = "INCOMPARABLE"


@dataclass(frozen=True)
class PairwiseComparison(ResearchRecord):
    candidate_a: AssessmentCandidate
    candidate_b: AssessmentCandidate
    pareto_layer: int
    relation: PairwiseRelation
    decisive_metric: ResearchMetric | None
    reason: str | None

    def validate(self):
        require(
            self.candidate_a != self.candidate_b and self.pareto_layer > 0,
            "invalid comparison pair",
        )
        require(
            (self.relation is PairwiseRelation.TIE) == (self.decisive_metric is None),
            "pair relation/metric differ",
        )
        require(
            (self.relation is PairwiseRelation.INCOMPARABLE) == (self.reason is not None),
            "pair relation/reason differ",
        )


@dataclass(frozen=True)
class SensitivityRanking(ResearchRecord):
    name: str
    rows: tuple[CandidateRank, ...]
    pairs: tuple[PairwiseComparison, ...]


@dataclass(frozen=True)
class BehaviorGroup(ResearchRecord):
    behavior_sha256: str
    candidates: tuple[AssessmentCandidate, ...]


@dataclass(frozen=True)
class CandidateComparison(ResearchRecord):
    request_sha256: str
    rows: tuple[CandidateRank, ...]
    sensitivities: tuple[SensitivityRanking, ...]
    behavior_groups: tuple[BehaviorGroup, ...]
    pairs: tuple[PairwiseComparison, ...]


__all__ = [
    name
    for name, value in globals().copy().items()
    if isinstance(value, type) and value.__module__ == __name__ and name != "ResearchRecord"
]
