"""Pure parameter geometry and explicitly scoped robustness comparisons."""

from typing import Protocol

from . import research_models as m
from .parameter_neighborhood import (
    NamedParameterValue, ParameterNeighborhoodRequest, ParameterNeighborhoodResult,
    build_parameter_neighborhood_design,
)
from .research_assessment import parameter_comparison_key


class ParameterFeasibility(Protocol):
    """Predeclared parameter-only feasibility; must not inspect outcome evidence."""

    def __call__(self, values: tuple[NamedParameterValue, ...]) -> bool: ...


def build_parameter_perturbation_design(
    request: ParameterNeighborhoodRequest, *, feasibility: ParameterFeasibility
) -> ParameterNeighborhoodResult:
    """Build current typed neighborhoods; legacy sphere records are read-only."""
    if type(request) is not ParameterNeighborhoodRequest:
        raise TypeError("requires ParameterNeighborhoodRequest; legacy sphere generation is read-only")
    return build_parameter_neighborhood_design(request, feasibility=feasibility)


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
    elif len({parameter_comparison_key(x) for x in contexts}) != 1:
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
