"""Pure parameter geometry and explicitly scoped robustness comparisons."""

from collections import Counter
from typing import Protocol
import math

import numpy as np

from . import research_models as m


class ParameterFeasibility(Protocol):
    """A deterministic, predeclared parameter-only constraint; never a return filter."""

    def __call__(self, coordinates: tuple[float, ...]) -> bool: ...


def build_parameter_perturbation_design(
    request: m.ParameterDesignRequest, *, feasibility: ParameterFeasibility
) -> m.ParameterDesignResult:
    if type(request) is not m.ParameterDesignRequest:
        raise TypeError("request requires ParameterDesignRequest")
    if not callable(feasibility):
        raise TypeError("feasibility requires ParameterFeasibility")
    request = m.ParameterDesignRequest.from_dict(request.to_dict())
    p, coordinates = request.protocol, request.space.coordinates
    continuous = np.array([x.kind is m.ParameterCoordinateKind.CONTINUOUS for x in coordinates])
    if not np.any(continuous):
        return m.ParameterDesignResult(
            request.sha256,
            m.ParameterDesignStatus.NOT_APPLICABLE,
            None,
            0,
            (),
            "ALL_INTEGER_SPACE_REQUIRES_DISCRETE_METHOD",
        )
    centers = np.array([x.center for x in coordinates])
    widths = np.array([x.upper - x.lower for x in coordinates])
    rng = np.random.Generator(np.random.PCG64(p.seed))
    points, seen, rejected = [], set(), Counter()
    attempts = 0
    while len(points) < p.point_count and attempts < p.max_attempts:
        attempts += 1
        direction = rng.normal(size=len(coordinates))
        norm = float(np.linalg.norm(direction))
        if norm == 0:
            rejected[m.ParameterRejectionReason.DEGENERATE_DIRECTION] += 1
            continue
        delta = direction * (p.radius / norm)
        values = centers + delta * widths
        values[~continuous] = np.rint(values[~continuous])
        delta[~continuous] = (values[~continuous] - centers[~continuous]) / widths[~continuous]
        remaining = p.radius**2 - float(np.dot(delta[~continuous], delta[~continuous]))
        if remaining < 0:
            rejected[m.ParameterRejectionReason.INTEGER_RADIUS] += 1
            continue
        continuous_norm = float(np.linalg.norm(delta[continuous]))
        if continuous_norm == 0:
            rejected[m.ParameterRejectionReason.DEGENERATE_DIRECTION] += 1
            continue
        delta[continuous] *= math.sqrt(remaining) / continuous_norm
        values[continuous] = centers[continuous] + delta[continuous] * widths[continuous]
        point = tuple(float(x) for x in values)
        if any(not c.lower <= v <= c.upper for c, v in zip(coordinates, point)):
            rejected[m.ParameterRejectionReason.DOMAIN] += 1
            continue
        decision = feasibility(point)
        if type(decision) is not bool:
            raise TypeError("ParameterFeasibility must return bool")
        if not decision:
            rejected[m.ParameterRejectionReason.CONSTRAINT] += 1
            continue
        if point in seen:
            rejected[m.ParameterRejectionReason.DUPLICATE] += 1
            continue
        seen.add(point)
        actual = math.sqrt(
            sum(((v - c.center) / (c.upper - c.lower)) ** 2 for v, c in zip(point, coordinates))
        )
        if abs(actual - p.radius) > p.distance_tolerance:
            return m.ParameterDesignResult(
                request.sha256,
                m.ParameterDesignStatus.DESIGN_FAILED,
                None,
                attempts,
                rejections=tuple(
                    m.ParameterDesignRejection(reason, rejected[reason])
                    for reason in m.ParameterRejectionReason
                    if rejected[reason]
                ),
                reason="COORDINATE_PRECISION_CANNOT_REPRESENT_RADIUS",
            )
        points.append(m.ParameterPerturbationPoint(len(points), point, actual))
    rejections = tuple(
        m.ParameterDesignRejection(reason, rejected[reason])
        for reason in m.ParameterRejectionReason
        if rejected[reason]
    )
    if len(points) != p.point_count:
        return m.ParameterDesignResult(
            request.sha256,
            m.ParameterDesignStatus.DESIGN_FAILED,
            None,
            attempts,
            rejections,
            "SAMPLING_BUDGET_EXHAUSTED",
        )
    design = m.ParameterPerturbationDesign(
        request.center, p, request.space, tuple(points), attempts, rejections
    )
    return m.ParameterDesignResult(
        request.sha256, m.ParameterDesignStatus.COMPLETE, design, attempts, rejections, None
    )


def compare_parameter_robustness(
    request: m.ParameterRobustnessComparisonRequest,
) -> m.ParameterRobustnessComparison:
    if type(request) is not m.ParameterRobustnessComparisonRequest:
        raise TypeError("request requires ParameterRobustnessComparisonRequest")
    request = m.ParameterRobustnessComparisonRequest.from_dict(request.to_dict())
    rows = request.rows
    reasons = []
    contexts = [x.parameter_context for x in rows]
    if any(x is None for x in contexts):
        reasons.append("MISSING_DECLARED_PARAMETER_METHOD")
    elif len({x.protocol.method_sha256 for x in contexts}) != 1:
        reasons.append("PARAMETER_METHODS_DIFFER")
    if any(x is not None and x.valid_points != x.prescribed_points for x in contexts):
        reasons.append("INCOMPLETE_PARAMETER_COVERAGE")
    if any(x.metric_version is None or x.frequency_window_days is None for x in rows):
        reasons.append("MISSING_METRIC_CONTEXT")
    elif len({(x.metric_version, x.frequency_window_days) for x in rows}) != 1:
        reasons.append("METRIC_DEFINITIONS_DIFFER")
    metrics = (
        m.ResearchMetric.PARAMETER_RETURN_DEGRADATION,
        m.ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
    )
    output = []
    for row in rows:
        selected = {x.metric: x for x in row.diagnostics}
        values = tuple(selected[x].value for x in metrics)
        if any(selected[x].status is not m.DiagnosticStatus.AVAILABLE for x in metrics):
            reasons.append("UNAVAILABLE_PARAMETER_METRICS")
        output.append(
            m.ParameterRobustnessRow(
                row.candidate,
                row.context_sha256,
                row.parameter_context,
                row.metric_version,
                row.frequency_window_days,
                *values,
            )
        )
    comparable = not reasons
    return m.ParameterRobustnessComparison(
        request.sha256,
        comparable,
        tuple(output),
        tuple(dict.fromkeys(reasons)),
        (
            "PARAMETER_DIAGNOSTIC_ONLY",
            "NATIVE_EVALUATION_CONTEXTS_MAY_DIFFER",
            "DOMAIN_SCALING_IS_NOT_ECONOMIC_RISK_EQUIVALENCE",
        ),
    )
