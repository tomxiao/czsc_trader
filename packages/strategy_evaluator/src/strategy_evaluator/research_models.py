"""Research comparison contracts, independent of orchestration and repositories."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from enum import StrEnum
from functools import lru_cache
from hashlib import sha256
import json
import math
import re
from types import MappingProxyType, UnionType
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


@lru_cache(maxsize=256)
def _record_hints(record_type: type):
    """Resolve immutable record schemas once; values are validated on every use."""
    return MappingProxyType(get_type_hints(record_type))


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
        hints = _record_hints(annotation)
        return annotation(**{k: decode(value[k], hints[k]) for k in names})
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        require(type(value) is str, "enum requires string")
        return annotation(value)
    require(matches(value, annotation), f"value requires {annotation}")
    return value


class ResearchRecord:
    def __post_init__(self):
        for name, annotation in _record_hints(type(self)).items():
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
            re.fullmatch(r"S[0-9]{3}-C[0-9]{4}", self.candidate_id) is not None,
            "candidate_id must match S plus three ASCII digits, hyphen, C plus four ASCII digits",
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
    benchmark_contract_sha256: str

    def validate(self):
        require(0 <= self.one_way_cost < 1, "cost must be in [0, 1)")
        require(
            bool(re.fullmatch(r"[0-9a-f]{64}", self.benchmark_contract_sha256)),
            "benchmark contract requires SHA-256",
        )


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
    parameter_point: ParameterPointBinding | None = None

    def validate(self):
        require(re.fullmatch(r"[0-9a-f]{32}", self.attempt_id) is not None, "invalid attempt_id")
        require(
            self.parameter_point is None
            or (
                self.parent is not None
                and self.derivation_kind is AssessmentDerivationKind.PARAMETERS
            ),
            "parameter point requires parameter derivation",
        )
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


class ParameterCoordinateKind(StrEnum):
    CONTINUOUS = "CONTINUOUS"
    INTEGER = "INTEGER"


@dataclass(frozen=True)
class ParameterCoordinate(ResearchRecord):
    name: str
    center: float
    lower: float
    upper: float
    kind: ParameterCoordinateKind

    def validate(self):
        require(
            self.lower < self.upper
            and math.isfinite(self.upper - self.lower)
            and self.lower <= self.center <= self.upper,
            "invalid parameter domain",
        )
        if self.kind is ParameterCoordinateKind.INTEGER:
            require(
                all(x.is_integer() for x in (self.center, self.lower, self.upper)),
                "integer coordinate requires integral domain",
            )


@dataclass(frozen=True)
class ParameterPerturbationProtocol(ResearchRecord):
    radius: float = 0.05
    point_count: int = 32
    seed: int = 13
    max_attempts: int = 100000
    distance_tolerance: float = 1e-10
    version: str = "parameter-total-domain-l2-v1"
    random_generator: str = "PCG64"
    integer_rounding: str = "HALF_EVEN"
    quantile_method: QuantileMethod = QuantileMethod.LINEAR

    def validate(self):
        require(0 < self.radius <= 1 and self.point_count > 0, "invalid radius/count")
        require(
            self.seed >= 0 and self.max_attempts >= self.point_count, "invalid seed/attempt budget"
        )
        require(
            0 < self.distance_tolerance <= 1e-8 and self.distance_tolerance < self.radius,
            "invalid distance tolerance",
        )
        require(self.version == "parameter-total-domain-l2-v1", "unsupported parameter method")
        require(
            self.random_generator == "PCG64" and self.integer_rounding == "HALF_EVEN",
            "unsupported sampling algorithm",
        )
        require(self.quantile_method is QuantileMethod.LINEAR, "parameter protocol requires LINEAR")

    @property
    def method_sha256(self):
        # Sampling budget and strategy-specific coordinates do not change the method identity.
        return digest(
            (
                self.version,
                self.random_generator,
                self.integer_rounding,
                self.radius,
                self.point_count,
                self.seed,
                self.distance_tolerance,
                self.quantile_method,
                "Q10_RETURN_Q90_DRAWDOWN_COMPLETE",
            )
        )


@dataclass(frozen=True)
class ParameterSpace(ResearchRecord):
    coordinates: tuple[ParameterCoordinate, ...]
    mapping_sha256: str
    feasibility_sha256: str

    def validate(self):
        require(bool(self.coordinates), "empty parameter space")
        unique((x.name for x in self.coordinates), "parameter coordinate")


@dataclass(frozen=True)
class ParameterDesignRequest(ResearchRecord):
    center: AssessmentCandidate
    protocol: ParameterPerturbationProtocol
    space: ParameterSpace


@dataclass(frozen=True)
class ParameterPerturbationPoint(ResearchRecord):
    index: int
    coordinates: tuple[float, ...]
    actual_radius: float

    def validate(self):
        require(
            self.index >= 0 and bool(self.coordinates) and self.actual_radius > 0,
            "invalid parameter point",
        )


@dataclass(frozen=True)
class ParameterPointBinding(ResearchRecord):
    design_sha256: str
    point_index: int
    coordinates: tuple[float, ...]
    actual_radius: float

    def validate(self):
        require(
            self.point_index >= 0 and bool(self.coordinates) and self.actual_radius > 0,
            "invalid point binding",
        )


class ParameterRejectionReason(StrEnum):
    INTEGER_RADIUS = "INTEGER_RADIUS"
    DOMAIN = "DOMAIN"
    CONSTRAINT = "CONSTRAINT"
    DUPLICATE = "DUPLICATE"
    DEGENERATE_DIRECTION = "DEGENERATE_DIRECTION"


@dataclass(frozen=True)
class ParameterDesignRejection(ResearchRecord):
    reason: ParameterRejectionReason
    count: int

    def validate(self):
        require(self.count > 0, "rejection count must be positive")


@dataclass(frozen=True)
class ParameterPerturbationDesign(ResearchRecord):
    center: AssessmentCandidate
    protocol: ParameterPerturbationProtocol
    space: ParameterSpace
    points: tuple[ParameterPerturbationPoint, ...]
    attempts: int
    rejections: tuple[ParameterDesignRejection, ...]

    def validate(self):
        require(len(self.points) == self.protocol.point_count, "design must cover prescribed count")
        require(
            any(x.kind is ParameterCoordinateKind.CONTINUOUS for x in self.space.coordinates),
            "all-integer space requires discrete method",
        )
        require(
            tuple(x.index for x in self.points) == tuple(range(len(self.points))),
            "point indices differ",
        )
        unique((x.coordinates for x in self.points), "parameter point")
        unique((x.reason for x in self.rejections), "rejection reason")
        require(
            self.attempts == len(self.points) + sum(x.count for x in self.rejections),
            "attempt accounting differs",
        )
        require(self.attempts <= self.protocol.max_attempts, "attempt budget exceeded")
        for point in self.points:
            require(
                len(point.coordinates) == len(self.space.coordinates), "point dimension differs"
            )
            radius = math.sqrt(
                sum(
                    ((v - c.center) / (c.upper - c.lower)) ** 2
                    for v, c in zip(point.coordinates, self.space.coordinates)
                )
            )
            require(
                abs(radius - self.protocol.radius) <= self.protocol.distance_tolerance
                and abs(radius - point.actual_radius) <= self.protocol.distance_tolerance,
                "actual radius differs",
            )
            require(
                all(
                    c.lower <= v <= c.upper
                    and (c.kind is ParameterCoordinateKind.CONTINUOUS or v.is_integer())
                    for v, c in zip(point.coordinates, self.space.coordinates)
                ),
                "point outside parameter domain",
            )

    def bind_point(self, index: int) -> ParameterPointBinding:
        require(type(index) is int and 0 <= index < len(self.points), "point index outside design")
        point = self.points[index]
        return ParameterPointBinding(self.sha256, index, point.coordinates, point.actual_radius)


class ParameterDesignStatus(StrEnum):
    COMPLETE = "COMPLETE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    DESIGN_FAILED = "DESIGN_FAILED"


@dataclass(frozen=True)
class ParameterDesignResult(ResearchRecord):
    request_sha256: str
    status: ParameterDesignStatus
    design: ParameterPerturbationDesign | None
    attempts: int
    rejections: tuple[ParameterDesignRejection, ...]
    reason: str | None

    def validate(self):
        require(
            (self.status is ParameterDesignStatus.COMPLETE) == (self.design is not None),
            "design status differs",
        )
        require(
            (self.status is ParameterDesignStatus.COMPLETE) == (self.reason is None),
            "design reason differs",
        )
        require(
            self.attempts >= 0 and sum(x.count for x in self.rejections) <= self.attempts,
            "invalid design attempt accounting",
        )
        unique((x.reason for x in self.rejections), "result rejection reason")
        if self.design is not None:
            require(
                self.attempts == self.design.attempts and self.rejections == self.design.rejections,
                "result/design accounting differs",
            )


@dataclass(frozen=True)
class ParameterDiagnosticContext(ResearchRecord):
    protocol: ParameterPerturbationProtocol
    design_sha256: str
    space_sha256: str
    dimension: int
    prescribed_points: int
    valid_points: int

    def validate(self):
        require(
            self.dimension > 0
            and self.prescribed_points == self.protocol.point_count
            and 0 <= self.valid_points <= self.prescribed_points,
            "invalid parameter coverage",
        )


@dataclass(frozen=True)
class PerturbationLink(ResearchRecord):
    parent: AssessmentCandidate
    child: AssessmentCandidate
    weight: float
    derivation_sha256: str
    parameter_point: ParameterPointBinding | None = None

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
    parameter_protocol: ParameterPerturbationProtocol | None = None

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
        require(
            self.parameter_protocol is None
            or self.quantile_method is self.parameter_protocol.quantile_method,
            "declared parameter quantile differs",
        )
        require(
            self.parameter_protocol is None
            or self.minimum_perturbations <= self.parameter_protocol.point_count,
            "minimum perturbations exceeds prescribed point count",
        )


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
    parameter_designs: tuple[ParameterPerturbationDesign, ...] = ()

    def validate(self):
        require(bool(self.centers), "explicit center set must be nonempty")
        unique((x.center for x in self.parameter_designs), "parameter design center")
        require(
            all(x.center in self.centers for x in self.parameter_designs), "design center absent"
        )
        declared = self.protocol.parameter_protocol
        require(not self.parameter_designs or declared is not None, "parameter protocol missing")
        require(
            all(x.protocol == declared for x in self.parameter_designs), "design protocol differs"
        )
        designs = {x.center: x for x in self.parameter_designs}
        for link in self.perturbations:
            if declared is not None:
                require(
                    link.parent in designs and link.parameter_point is not None,
                    "unbound parameter link",
                )
                require(
                    link.parameter_point
                    == designs[link.parent].bind_point(link.parameter_point.point_index),
                    "parameter point differs from design",
                )
            else:
                require(link.parameter_point is None, "parameter link requires declared protocol")
        for center in designs:
            unique(
                (x.parameter_point.point_index for x in self.perturbations if x.parent == center),
                "parameter point coverage",
            )
        for item in self.evidence:
            if item.parameter_point is not None:
                require(
                    declared is not None and item.parent in designs,
                    "bound evidence requires declared design",
                )
                require(
                    item.parameter_point
                    == designs[item.parent].bind_point(item.parameter_point.point_index),
                    "bound evidence differs from design",
                )
                require(
                    any(
                        x.child == item.candidate
                        and x.parent == item.parent
                        and x.parameter_point == item.parameter_point
                        for x in self.perturbations
                    ),
                    "bound evidence has no matching perturbation link",
                )
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
    parameter_context: ParameterDiagnosticContext | None = None

    def validate(self):
        if (
            self.parameter_context is not None
            and self.parameter_context.valid_points != self.parameter_context.prescribed_points
        ):
            require(
                all(
                    x.status is not DiagnosticStatus.AVAILABLE
                    for x in self.diagnostics
                    if x.metric
                    in (
                        ResearchMetric.PARAMETER_RETURN_DEGRADATION,
                        ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
                    )
                ),
                "available parameter metrics require complete coverage",
            )
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
    formula_version: str = "research-assessment-v3"

    def validate(self):
        require(
            self.formula_version == "research-assessment-v3",
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


@dataclass(frozen=True)
class ParameterRobustnessComparisonRequest(ResearchRecord):
    rows: tuple[CandidateAssessment, ...]

    def validate(self):
        require(len(self.rows) >= 2, "parameter comparison needs at least two candidates")
        unique((x.candidate for x in self.rows), "parameter comparison candidate")


@dataclass(frozen=True)
class ParameterRobustnessRow(ResearchRecord):
    candidate: AssessmentCandidate
    evaluation_context_sha256: str | None
    parameter_context: ParameterDiagnosticContext | None
    metric_version: str | None
    frequency_window_days: int | None
    return_degradation: float | None
    drawdown_degradation: float | None

    def validate(self):
        require(
            all(x is None or x >= 0 for x in (self.return_degradation, self.drawdown_degradation)),
            "negative parameter degradation",
        )


@dataclass(frozen=True)
class ParameterRobustnessComparison(ResearchRecord):
    request_sha256: str
    comparable: bool
    rows: tuple[ParameterRobustnessRow, ...]
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]

    def validate(self):
        require(self.comparable == (not self.reasons), "parameter comparison status differs")


__all__ = [
    name
    for name, value in globals().copy().items()
    if isinstance(value, type) and value.__module__ == __name__ and name != "ResearchRecord"
]
