from dataclasses import replace
import math

import pytest

from strategy_evaluator import (
    ParameterDesignRequest,
    ParameterSpace,
    ParameterCoordinate,
    ParameterCoordinateKind,
    ParameterPerturbationProtocol,
    build_parameter_perturbation_design,
    compare_parameter_robustness,
)
from strategy_evaluator import research_models as m
from strategy_evaluator.research_assessment import recompute_historical_assessment as assess_candidates
from test_research_assessment import candidate, evidence, protocol, row, compare


def design_request(dimension=8, count=32, radius=0.05):
    coordinates = tuple(
        ParameterCoordinate(str(i), 5.0, 0.0, 10.0, ParameterCoordinateKind.CONTINUOUS)
        for i in range(dimension)
    )
    return ParameterDesignRequest(
        candidate(),
        ParameterPerturbationProtocol(radius=radius, point_count=count),
        ParameterSpace(coordinates, "a" * 64, "b" * 64),
    )


def build(request=None):
    """Synthetic historical sphere records; never call the retired sampling API."""
    req = request or design_request()
    count, radius = req.protocol.point_count, req.protocol.radius
    points = tuple(m.ParameterPerturbationPoint(i, (
        5.0 + 10 * radius * math.cos(2 * math.pi * i / count),
        5.0 + 10 * radius * math.sin(2 * math.pi * i / count),
        *((5.0,) * (len(req.space.coordinates) - 2)),
    ), radius) for i in range(count))
    design = m.ParameterPerturbationDesign(req.center, req.protocol, req.space, points, count, ())
    return m.ParameterDesignResult(req.sha256, m.ParameterDesignStatus.COMPLETE, design, count, (), None)


def bound_request():
    design = build(design_request(2, 2)).design
    center, a, b = candidate(), candidate("C0002", "b"), candidate("C0003", "c")
    links = tuple(
        m.PerturbationLink(center, child, 1.0, "e" * 64, design.bind_point(i))
        for i, child in enumerate((a, b))
    )
    items = (
        evidence(center),
        evidence(center, scenario="pressure"),
        *(
            replace(
                evidence(link.child, (5.0, 10.0), parent=center),
                parameter_point=link.parameter_point,
            )
            for link in links
        ),
    )
    return m.CandidateAssessmentRequest(
        (center,),
        replace(protocol(), parameter_protocol=design.protocol),
        links,
        items,
        parameter_designs=(design,),
    )


@pytest.mark.parametrize("dimension", [8, 13])
def test_historical_sphere_record_roundtrip_radius_and_accounting(dimension):
    result = build(design_request(dimension))
    assert m.ParameterDesignResult.from_dict(result.to_dict()) == result
    for point in result.design.points:
        distance = math.sqrt(sum(((v - 5.0) / 10.0) ** 2 for v in point.coordinates))
        assert distance == pytest.approx(0.05, abs=1e-15)
    with pytest.raises(ValueError, match="radius"):
        replace(result.design, points=(replace(result.design.points[0], actual_radius=0.1), *result.design.points[1:]))
    with pytest.raises(ValueError, match="accounting"):
        replace(result, attempts=0)


def test_retired_sphere_generator_is_read_only():
    with pytest.raises(TypeError, match="read-only"):
        build_parameter_perturbation_design(design_request(), feasibility=lambda values: True)


def test_historical_contract_type_boundaries_remain_strict():
    with pytest.raises(ValueError, match="domain"):
        ParameterCoordinate("x", 0.0, -1e308, 1e308, ParameterCoordinateKind.CONTINUOUS)
    with pytest.raises(ValueError, match="tolerance"):
        ParameterPerturbationProtocol(radius=1e-12)
    with pytest.raises(TypeError):
        ParameterPerturbationProtocol(point_count=True)


def test_complete_declared_coverage_computes_linear_quantiles():
    req = bound_request()
    panel = assess_candidates(req)
    context = panel.rows[0].parameter_context
    assert context.valid_points == context.prescribed_points == 2
    assert context.design_sha256 == req.parameter_designs[0].sha256
    values = {x.metric: x.value for x in panel.rows[0].diagnostics}
    assert values[m.ResearchMetric.PARAMETER_RETURN_DEGRADATION] > 0
    assert panel.formula_version == "research-assessment-v5"
    assert m.CandidateAssessmentRequest.from_dict(req.to_dict()) == req
    item = panel.rows[0]
    assert len(item.parameter_performances) == 2
    assert {x.point_index for x in item.parameter_performances} == {0, 1}
    assert item.stress_performance.scenario.one_way_cost == 0.001
    assert m.AssessmentPanel.from_dict(panel.to_dict()) == panel
    group = m.ParameterGroupTarget("points", 2, 2,
        (m.ResearchTarget("profit", m.ResearchMetric.NET_ANNUAL_RETURN,
                         lower=m.ConstantBound(0.0, False)),),
        (m.ResearchTarget("risk", m.ResearchMetric.DRAWDOWN_MAGNITUDE,
                         upper=m.ConstantBound(0.25, True)),))
    checked = compare((item,), targets=(group,)).rows[0].target_checks[0]
    assert (checked.valid_points, checked.joint_passes) == (2, 2)
    assert checked.status is m.TargetCheckStatus.PASSED


def test_declared_count_cannot_be_less_than_minimum_required_coverage():
    req = bound_request()
    # A fully successful prescribed design must not be made insufficient by its protocol.
    with pytest.raises(ValueError, match="minimum perturbations exceeds"):
        replace(req.protocol, minimum_perturbations=3)
    assert replace(req.protocol, minimum_perturbations=2).minimum_perturbations == 2


def test_parameter_quantiles_match_independent_linear_account_calculation():
    req = bound_request()
    first, second = req.perturbations
    neighbors = tuple(
        replace(
            evidence(link.child, profits, parent=req.centers[0]),
            parameter_point=link.parameter_point,
        )
        for link, profits in ((first, (-15.0, 30.0)), (second, (-20.0, 20.0)))
    )
    panel = assess_candidates(replace(req, evidence=(*req.evidence[:2], *neighbors)))
    metrics = {x.metric: x.value for x in panel.rows[0].diagnostics}
    expected_return = (1.03**63 - 1) - 0.1 * (1.015**63 - 1)
    assert metrics[m.ResearchMetric.PARAMETER_RETURN_DEGRADATION] == pytest.approx(expected_return)
    assert metrics[m.ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION] == pytest.approx(0.0195)
    assert metrics[m.ResearchMetric.PARAMETER_RETURN_Q10] == pytest.approx(0.1 * (1.015**63 - 1))
    assert metrics[m.ResearchMetric.PARAMETER_DRAWDOWN_Q90] == pytest.approx(0.0195)


def test_missing_point_never_computes_from_available_subset():
    req = bound_request()
    for incomplete in (
        replace(req, evidence=req.evidence[:-1]),
        replace(req, perturbations=req.perturbations[:-1], evidence=req.evidence[:-1]),
    ):
        panel = assess_candidates(incomplete)
        assert panel.rows[0].parameter_context.valid_points == 1
        for diagnostic in panel.rows[0].diagnostics:
            if diagnostic.metric in (
                m.ResearchMetric.PARAMETER_RETURN_Q10,
                m.ResearchMetric.PARAMETER_DRAWDOWN_Q90,
                m.ResearchMetric.PARAMETER_RETURN_DEGRADATION,
                m.ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
            ):
                assert diagnostic.value is None


def test_mixed_radius_wrong_evidence_and_duplicate_point_are_rejected():
    req = bound_request()
    with pytest.raises(ValueError, match="protocol differs"):
        replace(
            req,
            parameter_designs=(
                replace(
                    req.parameter_designs[0],
                    protocol=replace(req.parameter_designs[0].protocol, seed=14),
                ),
            ),
        )
    with pytest.raises(ValueError, match="design"):
        replace(
            req,
            perturbations=(
                replace(
                    req.perturbations[0],
                    parameter_point=replace(
                        req.perturbations[0].parameter_point, actual_radius=0.1
                    ),
                ),
                req.perturbations[1],
            ),
        )
    with pytest.raises(ValueError, match="coverage"):
        replace(
            req,
            perturbations=(
                req.perturbations[0],
                replace(req.perturbations[1], parameter_point=req.perturbations[0].parameter_point),
            ),
        )
    with pytest.raises(ValueError, match="point differs"):
        assess_candidates(
            replace(
                req, evidence=(*req.evidence[:-1], replace(req.evidence[-1], parameter_point=None))
            )
        )
    with pytest.raises(ValueError, match="quantile"):
        replace(req.protocol, quantile_method=m.QuantileMethod.WEIGHTED_ECDF)


def test_narrow_native_context_comparison_and_ordinary_ranking_stays_strict():
    design = build().design
    context = m.ParameterDiagnosticContext(
        design.protocol, design.sha256, design.space.sha256, 8, 32, 32
    )
    a = replace(row(candidate()), parameter_context=context)
    b = replace(
        row(candidate("C0002", "b")),
        parameter_context=replace(context, dimension=13),
        context_sha256="c" * 64,
    )
    result = compare_parameter_robustness(m.ParameterRobustnessComparisonRequest((a, b)))
    assert result.comparable
    assert result.rows[0].evaluation_context_sha256 != result.rows[1].evaluation_context_sha256
    assert all(x.status is m.ComparisonStatus.INCOMPARABLE for x in compare((a, b)).rows)
    different = replace(
        b,
        context_sha256=a.context_sha256,
        parameter_context=replace(context, protocol=replace(context.protocol, radius=0.1)),
    )
    assert (
        "PARAMETER_METHODS_DIFFER"
        in compare_parameter_robustness(
            m.ParameterRobustnessComparisonRequest((a, different))
        ).reasons
    )
    assert all(x.status is m.ComparisonStatus.INCOMPARABLE for x in compare((a, different)).rows)
    legacy = replace(b, parameter_context=None)
    assert (
        "MISSING_DECLARED_PARAMETER_METHOD"
        in compare_parameter_robustness(m.ParameterRobustnessComparisonRequest((a, legacy))).reasons
    )
    definition = replace(b, metric_version="different")
    assert (
        "METRIC_DEFINITIONS_DIFFER"
        in compare_parameter_robustness(
            m.ParameterRobustnessComparisonRequest((a, definition))
        ).reasons
    )


def test_legacy_serialized_contract_is_not_silently_upgraded():
    value = evidence().to_dict()
    del value["parameter_point"]
    with pytest.raises(ValueError, match="fields differ"):
        m.AssessmentEvidence.from_dict(value)


def test_partial_policy_requires_parameter_method_before_same_layer_comparison():
    from test_research_comparison_v2 import partial_policy

    a = replace(row(candidate(), annual=0.11, drawdown=0.12), parameter_context=None)
    b = replace(row(candidate("C0002", "b"), annual=0.10, drawdown=0.11), parameter_context=None)
    assert compare((a, b), partial_policy()).pairs[0].relation is m.PairwiseRelation.INCOMPARABLE
    tied = replace(b, diagnostics=a.diagnostics)
    result = compare((a, tied), partial_policy())
    assert result.pairs[0].relation is m.PairwiseRelation.INCOMPARABLE
    assert result.pairs[0].reason == "MISSING_DECLARED_PARAMETER_METHOD"
    assert all(x.status is m.ComparisonStatus.INCOMPARABLE for x in compare((a, b)).rows)


def test_partial_policy_checks_method_when_reaching_parameter_item():
    from test_research_comparison_v2 import partial_policy

    a, b = row(candidate()), row(candidate("C0002", "b"))
    b = replace(
        b,
        parameter_context=replace(
            b.parameter_context, protocol=replace(b.parameter_context.protocol, radius=0.1)
        ),
    )
    result = compare((a, b), partial_policy())
    assert result.pairs[0].reason == "PARAMETER_METHODS_DIFFER"
