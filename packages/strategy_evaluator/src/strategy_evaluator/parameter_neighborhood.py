"""Typed, complete Cartesian parameter neighborhoods, without account semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from itertools import product
import math
from typing import Callable

from . import research_models as m


ParameterValue = float | int | str | bool
NumericValue = float | int


class ParameterKind(StrEnum):
    REAL = "REAL"
    INTEGER = "INTEGER"
    ORDINAL = "ORDINAL"
    CATEGORICAL = "CATEGORICAL"
    BOOLEAN = "BOOLEAN"


class StudyPurpose(StrEnum):
    LOCAL_SENSITIVITY = "LOCAL_SENSITIVITY"
    STRUCTURAL_CONTROL = "STRUCTURAL_CONTROL"


def _number(value):
    return Fraction(str(value))


def _unique_typed(values, name):
    m.unique(((type(x).__name__, x) for x in values), name)


@dataclass(frozen=True)
class RealDomain(m.ResearchRecord):
    lower: float
    upper: float
    lower_closed: bool = True
    upper_closed: bool = True
    quantum: float | None = None
    origin: float = 0.0

    def validate(self):
        m.require(self.lower <= self.upper, "invalid real bounds")
        m.require(
            self.lower != self.upper or (self.lower_closed and self.upper_closed),
            "empty real domain",
        )
        m.require(self.quantum is None or self.quantum > 0, "quantum must be positive")
        if self.quantum is not None:
            low = (_number(self.lower) - _number(self.origin)) / _number(self.quantum)
            high = (_number(self.upper) - _number(self.origin)) / _number(self.quantum)
            first = math.ceil(low) + int(not self.lower_closed and low.denominator == 1)
            last = math.floor(high) - int(not self.upper_closed and high.denominator == 1)
            m.require(first <= last, "real domain has no admissible quantum value")


@dataclass(frozen=True)
class IntegerDomain(m.ResearchRecord):
    lower: int
    upper: int
    step: int = 1
    origin: int = 0

    def validate(self):
        m.require(self.lower <= self.upper and self.step > 0, "invalid integer domain")
        first = self.lower + (self.origin - self.lower) % self.step
        m.require(first <= self.upper, "integer domain has no admissible value")


@dataclass(frozen=True)
class RealSetDomain(m.ResearchRecord):
    values: tuple[float, ...]

    def validate(self):
        m.require(bool(self.values), "empty real value set")
        _unique_typed(self.values, "real domain value")
        m.require(tuple(sorted(self.values)) == self.values, "numeric set must be ascending")


@dataclass(frozen=True)
class IntegerSetDomain(m.ResearchRecord):
    values: tuple[int, ...]

    def validate(self):
        m.require(bool(self.values), "empty integer value set")
        _unique_typed(self.values, "integer domain value")
        m.require(tuple(sorted(self.values)) == self.values, "numeric set must be ascending")


@dataclass(frozen=True)
class OrdinalDomain(m.ResearchRecord):
    levels: tuple[float | int | str, ...]

    def validate(self):
        m.require(bool(self.levels), "empty ordinal domain")
        m.require(
            len({type(x) for x in self.levels}) == 1, "ordinal labels must have one exact type"
        )
        m.require(
            all(not isinstance(x, str) or bool(x.strip()) for x in self.levels),
            "empty ordinal label",
        )
        _unique_typed(self.levels, "ordinal level")


@dataclass(frozen=True)
class CategoricalDomain(m.ResearchRecord):
    values: tuple[str, ...]

    def validate(self):
        m.require(bool(self.values) and all(x.strip() for x in self.values), "empty category")
        _unique_typed(self.values, "category")


@dataclass(frozen=True)
class BooleanDomain(m.ResearchRecord):
    pass


ParameterDomain = (
    RealDomain
    | IntegerDomain
    | RealSetDomain
    | IntegerSetDomain
    | OrdinalDomain
    | CategoricalDomain
    | BooleanDomain
)


@dataclass(frozen=True)
class NumericOffsets(m.ResearchRecord):
    offsets: tuple[NumericValue, ...]

    def validate(self):
        m.require(bool(self.offsets), "empty numeric offsets")


@dataclass(frozen=True)
class AdjacentLevels(m.ResearchRecord):
    steps: int = 1

    def validate(self):
        m.require(self.steps > 0, "adjacent steps must be positive")


@dataclass(frozen=True)
class ExplicitValues(m.ResearchRecord):
    values: tuple[ParameterValue, ...]

    def validate(self):
        m.require(bool(self.values), "empty explicit values")


NeighborhoodRule = NumericOffsets | AdjacentLevels | ExplicitValues


def domain_kind(domain):
    return {
        RealDomain: ParameterKind.REAL,
        RealSetDomain: ParameterKind.REAL,
        IntegerDomain: ParameterKind.INTEGER,
        IntegerSetDomain: ParameterKind.INTEGER,
        OrdinalDomain: ParameterKind.ORDINAL,
        CategoricalDomain: ParameterKind.CATEGORICAL,
        BooleanDomain: ParameterKind.BOOLEAN,
    }[type(domain)]


def _correct_type(domain, value):
    kind = domain_kind(domain)
    expected = {
        ParameterKind.REAL: float,
        ParameterKind.INTEGER: int,
        ParameterKind.CATEGORICAL: str,
        ParameterKind.BOOLEAN: bool,
    }.get(kind)
    if kind is ParameterKind.ORDINAL:
        expected = type(domain.levels[0])
    return type(value) is expected and (expected is not float or math.isfinite(value))


def _contains(domain, value):
    if not _correct_type(domain, value):
        return False
    if isinstance(domain, RealDomain):
        if not (domain.lower <= value <= domain.upper):
            return False
        if (value == domain.lower and not domain.lower_closed) or (
            value == domain.upper and not domain.upper_closed
        ):
            return False
        return (
            domain.quantum is None
            or ((_number(value) - _number(domain.origin)) / _number(domain.quantum)).denominator
            == 1
        )
    if isinstance(domain, IntegerDomain):
        return domain.lower <= value <= domain.upper and (value - domain.origin) % domain.step == 0
    if isinstance(domain, OrdinalDomain):
        return value in domain.levels
    if isinstance(domain, BooleanDomain):
        return True
    return value in domain.values


@dataclass(frozen=True)
class ParameterAxis(m.ResearchRecord):
    name: str
    center: ParameterValue
    domain: ParameterDomain
    rule: NeighborhoodRule
    payload_path: tuple[str, ...]
    unit: str

    @property
    def kind(self):
        return domain_kind(self.domain)

    def validate(self):
        m.require(
            bool(self.payload_path) and all(x.strip() for x in self.payload_path),
            "payload path must contain nonempty keys",
        )
        m.require(_contains(self.domain, self.center), "center outside exact typed domain")
        if isinstance(self.rule, NumericOffsets):
            m.require(
                self.kind in (ParameterKind.REAL, ParameterKind.INTEGER),
                "numeric offsets require numeric domain",
            )
            expected = float if self.kind is ParameterKind.REAL else int
            m.require(
                all(type(x) is expected for x in self.rule.offsets),
                "offset type differs from numeric coordinate",
            )
        elif isinstance(self.rule, AdjacentLevels):
            m.require(self.kind is ParameterKind.ORDINAL, "adjacent levels require ordinal domain")
        else:
            m.require(
                all(_correct_type(self.domain, x) for x in self.rule.values),
                "explicit value type differs from domain",
            )


@dataclass(frozen=True)
class ParameterNeighborhoodSpace(m.ResearchRecord):
    axes: tuple[ParameterAxis, ...]
    mapping_sha256: str
    feasibility_sha256: str

    def validate(self):
        m.require(bool(self.axes), "empty neighborhood space")
        m.unique((x.name for x in self.axes), "axis name")
        paths = [x.payload_path for x in self.axes]
        for i, path in enumerate(paths):
            for other in paths[i + 1 :]:
                m.require(
                    path[: len(other)] != other and other[: len(path)] != path,
                    "duplicate or overlapping payload paths",
                )


@dataclass(frozen=True)
class NamedParameterValue(m.ResearchRecord):
    name: str
    value: ParameterValue


@dataclass(frozen=True)
class ParameterNeighborhoodProtocol(m.ResearchRecord):
    purpose: StudyPurpose = StudyPurpose.LOCAL_SENSITIVITY
    max_combinations: int = 10000
    quantile_method: m.QuantileMethod = m.QuantileMethod.LINEAR
    version: str = "parameter-cartesian-neighborhood-v1"

    def validate(self):
        m.require(self.max_combinations > 0, "combination limit must be positive")
        m.require(
            self.version == "parameter-cartesian-neighborhood-v1", "unsupported neighborhood method"
        )
        m.require(
            self.quantile_method is m.QuantileMethod.LINEAR, "neighborhood quantiles require LINEAR"
        )

    @property
    def method_sha256(self):
        return m.digest(
            (self.version, self.purpose, self.quantile_method, "COMPLETE_CARTESIAN_NO_CENTER")
        )


@dataclass(frozen=True)
class ParameterNeighborhoodRequest(m.ResearchRecord):
    center: m.AssessmentCandidate
    protocol: ParameterNeighborhoodProtocol
    space: ParameterNeighborhoodSpace

    def validate(self):
        if self.protocol.purpose is StudyPurpose.LOCAL_SENSITIVITY:
            for axis in self.space.axes:
                if axis.kind in (ParameterKind.CATEGORICAL, ParameterKind.BOOLEAN):
                    m.require(
                        all(x == axis.center for x in axis.rule.values),
                        "categorical/boolean changes require STRUCTURAL_CONTROL",
                    )


class NeighborhoodRejectionReason(StrEnum):
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN"
    DUPLICATE = "DUPLICATE"
    CENTER = "CENTER"
    CONSTRAINT = "CONSTRAINT"


@dataclass(frozen=True)
class NeighborhoodRejection(m.ResearchRecord):
    reason: NeighborhoodRejectionReason
    count: int

    def validate(self):
        m.require(self.count > 0, "rejection count must be positive")


@dataclass(frozen=True)
class NeighborhoodConstraintExclusion(m.ResearchRecord):
    """Explicit constraint decision; callback business correctness is RSCH evidence."""

    values: tuple[NamedParameterValue, ...]

    def validate(self):
        m.require(bool(self.values), "empty constraint exclusion")
        m.unique((x.name for x in self.values), "constraint exclusion name")


@dataclass(frozen=True)
class ParameterNeighborhoodPoint(m.ResearchRecord):
    index: int
    values: tuple[NamedParameterValue, ...]

    def validate(self):
        m.require(self.index >= 0 and bool(self.values), "invalid named point")
        m.unique((x.name for x in self.values), "point name")


@dataclass(frozen=True)
class ParameterNeighborhoodBinding(m.ResearchRecord):
    design_sha256: str
    point_index: int
    values: tuple[NamedParameterValue, ...]

    def validate(self):
        m.require(self.point_index >= 0 and bool(self.values), "invalid named point binding")
        m.unique((x.name for x in self.values), "binding name")


_OUTSIDE = object()


def _choice_count(axis):
    if isinstance(axis.rule, NumericOffsets):
        return 1 + len(axis.rule.offsets)
    if isinstance(axis.rule, ExplicitValues):
        return 1 + len(axis.rule.values)
    return 1 + 2 * axis.rule.steps


def _choices(axis):
    if isinstance(axis.rule, NumericOffsets):
        values = []
        for offset in axis.rule.offsets:
            if axis.kind is ParameterKind.INTEGER:
                values.append(axis.center + offset)
            else:
                exact = _number(axis.center) + _number(offset)
                try:
                    values.append(float(exact))
                except OverflowError:
                    values.append(math.inf if exact > 0 else -math.inf)
        return (axis.center, *values)
    if isinstance(axis.rule, ExplicitValues):
        return (axis.center, *axis.rule.values)
    levels = axis.domain.levels
    index = levels.index(axis.center)
    return (
        axis.center,
        *(
            levels[j] if 0 <= j < len(levels) else _OUTSIDE
            for j in range(index - axis.rule.steps, index + axis.rule.steps + 1)
            if j != index
        ),
    )


def _typed_key(values):
    return tuple((type(x).__name__, x) for x in values)


def _enumerate_domain(axes):
    """Reconstruct the entire fixed domain partition, without executing user code."""
    counts = {reason: 0 for reason in NeighborhoodRejectionReason}
    seen, legal = set(), []
    center = _typed_key(x.center for x in axes)
    for values in product(*(_choices(axis) for axis in axes)):
        if any(
            v is _OUTSIDE or not _contains(a.domain, v) for a, v in zip(axes, values, strict=True)
        ):
            counts[NeighborhoodRejectionReason.OUT_OF_DOMAIN] += 1
            continue
        key = _typed_key(values)
        if key in seen:
            counts[NeighborhoodRejectionReason.DUPLICATE] += 1
            continue
        seen.add(key)
        if key == center:
            counts[NeighborhoodRejectionReason.CENTER] += 1
            continue
        legal.append(
            tuple(NamedParameterValue(a.name, v) for a, v in zip(axes, values, strict=True))
        )
    return tuple(legal), counts


def _relative(axis, value):
    if axis.kind in (ParameterKind.REAL, ParameterKind.INTEGER):
        return str(_number(value) - _number(axis.center))
    if axis.kind is ParameterKind.ORDINAL:
        return axis.domain.levels.index(value) - axis.domain.levels.index(axis.center)
    return value


@dataclass(frozen=True)
class ParameterNeighborhoodDesign(m.ResearchRecord):
    center: m.AssessmentCandidate
    protocol: ParameterNeighborhoodProtocol
    space: ParameterNeighborhoodSpace
    points: tuple[ParameterNeighborhoodPoint, ...]
    generated_combinations: int
    rejections: tuple[NeighborhoodRejection, ...]
    constraint_exclusions: tuple[NeighborhoodConstraintExclusion, ...] = ()

    def validate(self):
        ParameterNeighborhoodRequest(self.center, self.protocol, self.space)
        m.require(bool(self.points), "completed neighborhood must contain a noncenter point")
        m.require(
            tuple(x.index for x in self.points) == tuple(range(len(self.points))),
            "point indices differ",
        )
        m.unique((x.values for x in self.points), "neighborhood point")
        m.unique((x.reason for x in self.rejections), "neighborhood rejection")
        m.require(
            self.generated_combinations == math.prod(_choice_count(x) for x in self.space.axes),
            "generated combination count differs",
        )
        m.require(
            self.generated_combinations == len(self.points) + sum(x.count for x in self.rejections),
            "combination accounting differs",
        )
        m.require(
            self.generated_combinations <= self.protocol.max_combinations,
            "combination resource limit exceeded",
        )
        legal, fixed_counts = _enumerate_domain(self.space.axes)
        legal_set = set(legal)
        names = tuple(a.name for a in self.space.axes)
        retained = tuple(p.values for p in self.points)
        excluded = tuple(p.values for p in self.constraint_exclusions)
        m.unique(excluded, "constraint exclusion")
        for values in (*retained, *excluded):
            m.require(tuple(v.name for v in values) == names, "named point axes differ")
            m.require(
                all(
                    _contains(a.domain, v.value)
                    for a, v in zip(self.space.axes, values, strict=True)
                ),
                "point outside exact domain",
            )
            m.require(values in legal_set, "point outside declared neighborhood or is center")
        retained_set, excluded_set = set(retained), set(excluded)
        m.require(
            not retained_set & excluded_set, "retained and constraint excluded points overlap"
        )
        m.require(
            retained_set | excluded_set == legal_set,
            "incomplete declared neighborhood partition",
        )
        m.require(
            retained == tuple(v for v in legal if v in retained_set)
            and excluded == tuple(v for v in legal if v in excluded_set),
            "neighborhood partition order differs",
        )
        fixed_counts[NeighborhoodRejectionReason.CONSTRAINT] = len(excluded)
        m.require(
            self.rejections
            == tuple(NeighborhoodRejection(r, n) for r, n in fixed_counts.items() if n),
            "recomputed rejection accounting differs",
        )

    @property
    def point_count(self):
        return len(self.points)

    @property
    def comparison_sha256(self):
        # Center locations are represented through actual local shape, not an
        # assumed common radius. Conditional exclusions remain part of identity.
        axes = tuple(
            (a.name, a.kind, a.unit, a.domain.to_dict(), a.rule.to_dict()) for a in self.space.axes
        )
        shape = tuple(
            tuple(_relative(a, v.value) for a, v in zip(self.space.axes, p.values, strict=True))
            for p in self.points
        )
        return m.digest((self.protocol.method_sha256, axes, shape, self.space.feasibility_sha256))

    def bind_point(self, index):
        if type(index) is not int or not 0 <= index < len(self.points):
            raise ValueError("point index outside neighborhood")
        return ParameterNeighborhoodBinding(self.sha256, index, self.points[index].values)


@dataclass(frozen=True)
class ParameterNeighborhoodResult(m.ResearchRecord):
    request_sha256: str
    status: m.ParameterDesignStatus
    design: ParameterNeighborhoodDesign | None
    generated_combinations: int
    rejections: tuple[NeighborhoodRejection, ...]
    reason: str | None
    constraint_exclusions: tuple[NeighborhoodConstraintExclusion, ...] = ()

    def validate(self):
        complete = self.status is m.ParameterDesignStatus.COMPLETE
        m.require(
            complete == (self.design is not None) == (self.reason is None),
            "neighborhood result status differs",
        )
        m.require(self.generated_combinations >= 0, "negative combination count")
        m.unique((x.reason for x in self.rejections), "result rejection")
        m.unique((x.values for x in self.constraint_exclusions), "result constraint exclusion")
        m.require(
            len(self.constraint_exclusions)
            == sum(
                x.count
                for x in self.rejections
                if x.reason is NeighborhoodRejectionReason.CONSTRAINT
            ),
            "constraint exclusion count differs",
        )
        m.require(
            sum(x.count for x in self.rejections) <= self.generated_combinations,
            "rejected combinations exceed declared product",
        )
        if self.design is not None:
            m.require(
                self.generated_combinations == self.design.generated_combinations
                and self.rejections == self.design.rejections
                and self.constraint_exclusions == self.design.constraint_exclusions,
                "result and design accounting differ",
            )


@dataclass(frozen=True)
class ParameterNeighborhoodContext(m.ResearchRecord):
    protocol: ParameterNeighborhoodProtocol
    design_sha256: str
    space_sha256: str
    dimension: int
    prescribed_points: int
    valid_points: int
    comparison_sha256: str

    def validate(self):
        m.require(
            self.dimension > 0
            and self.prescribed_points > 0
            and 0 <= self.valid_points <= self.prescribed_points,
            "invalid neighborhood coverage",
        )


def build_parameter_neighborhood_design(
    request: ParameterNeighborhoodRequest,
    *,
    feasibility: Callable[[tuple[NamedParameterValue, ...]], bool],
) -> ParameterNeighborhoodResult:
    """Expand the complete declared product or fail before invoking constraints.

    Center is an implicit option on every axis. Repeated declarations are counted
    then deduplicated; invalid boundary/quantum values are rejected, never clipped
    or rounded. Feasibility sees named typed values and must return a real bool;
    the center itself must satisfy it before any neighbor is accepted. Constraint
    decisions are frozen explicitly; validation reconstructs coverage without
    executing historical callbacks. Their business correctness and purity remain
    the researcher's responsibility.
    """
    if type(request) is not ParameterNeighborhoodRequest:
        raise TypeError("request requires ParameterNeighborhoodRequest")
    if not callable(feasibility):
        raise TypeError("feasibility must be callable")
    request = ParameterNeighborhoodRequest.from_dict(request.to_dict())
    axes = request.space.axes
    total = math.prod(_choice_count(x) for x in axes)
    if total > request.protocol.max_combinations:
        return ParameterNeighborhoodResult(
            request.sha256,
            m.ParameterDesignStatus.DESIGN_FAILED,
            None,
            total,
            (),
            "COMBINATION_LIMIT_EXCEEDED",
        )
    center_values = tuple(NamedParameterValue(a.name, a.center) for a in axes)
    center_feasible = feasibility(center_values)
    if type(center_feasible) is not bool:
        raise TypeError("feasibility must return bool")
    if not center_feasible:
        return ParameterNeighborhoodResult(
            request.sha256,
            m.ParameterDesignStatus.DESIGN_FAILED,
            None,
            total,
            (),
            "CENTER_VIOLATES_CONSTRAINT",
        )
    legal, counts = _enumerate_domain(axes)
    points, excluded = [], []
    for named in legal:
        decision = feasibility(named)
        if type(decision) is not bool:
            raise TypeError("feasibility must return bool")
        if not decision:
            counts[NeighborhoodRejectionReason.CONSTRAINT] += 1
            excluded.append(NeighborhoodConstraintExclusion(named))
            continue
        points.append(ParameterNeighborhoodPoint(len(points), named))
    rejected = tuple(NeighborhoodRejection(r, n) for r, n in counts.items() if n)
    if not points:
        return ParameterNeighborhoodResult(
            request.sha256,
            m.ParameterDesignStatus.DESIGN_FAILED,
            None,
            total,
            rejected,
            "NO_FEASIBLE_NONCENTER_POINTS",
            tuple(excluded),
        )
    design = ParameterNeighborhoodDesign(
        request.center,
        request.protocol,
        request.space,
        tuple(points),
        total,
        rejected,
        tuple(excluded),
    )
    return ParameterNeighborhoodResult(
        request.sha256,
        m.ParameterDesignStatus.COMPLETE,
        design,
        total,
        rejected,
        None,
        tuple(excluded),
    )
