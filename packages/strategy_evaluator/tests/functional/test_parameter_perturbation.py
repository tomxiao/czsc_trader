from dataclasses import replace
import math

import numpy as np
import pytest

from strategy_evaluator import (
    ParameterDesignRequest,
    ParameterSpace,
    ParameterCoordinate,
    ParameterCoordinateKind,
    ParameterPerturbationProtocol,
    build_parameter_perturbation_design,
    compare_parameter_robustness,
    assess_candidates,
)
from strategy_evaluator import research_models as m
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


def build(request=None, feasibility=lambda point: True):
    return build_parameter_perturbation_design(request or design_request(), feasibility=feasibility)


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
def test_total_radius_not_coordinate_rms_and_roundtrip(dimension):
    result = build(design_request(dimension))
    assert result.status is m.ParameterDesignStatus.COMPLETE
    assert result.attempts == 32
    assert m.ParameterDesignResult.from_dict(result.to_dict()) == result
    for point in result.design.points:
        distance = math.sqrt(sum(((v - 5.0) / 10.0) ** 2 for v in point.coordinates))
        assert distance == pytest.approx(0.05, abs=1e-15)
    assert result == build(design_request(dimension))
    assert (
        result.design.protocol.method_sha256
        == build(design_request(8)).design.protocol.method_sha256
    )


def test_affine_units_preserve_points_and_nonlinear_domain_does_not_claim_equivalence():
    original = design_request()
    converted = replace(
        original,
        space=replace(
            original.space,
            coordinates=tuple(
                replace(
                    c, center=7 + c.center * 100, lower=7 + c.lower * 100, upper=7 + c.upper * 100
                )
                for c in original.space.coordinates
            ),
        ),
    )
    first, second = build(original).design, build(converted).design
    for a, b in zip(first.points, second.points):
        assert np.array(b.coordinates) == pytest.approx(7 + np.array(a.coordinates) * 100)
    assert first.sha256 != second.sha256
    assert first.protocol.method_sha256 == second.protocol.method_sha256
    with pytest.raises(ValueError, match="radius"):
        replace(first, points=(replace(first.points[0], actual_radius=0.1), *first.points[1:]))


def test_mixed_integer_preserves_lattice_and_exact_total_radius():
    req = design_request(3)
    space = replace(
        req.space,
        coordinates=(
            replace(req.space.coordinates[0], kind=ParameterCoordinateKind.INTEGER),
            *req.space.coordinates[1:],
        ),
    )
    result = build(replace(req, space=space))
    assert result.status is m.ParameterDesignStatus.COMPLETE
    assert all(p.coordinates[0].is_integer() for p in result.design.points)
    assert all(abs(p.actual_radius - 0.05) < 1e-14 for p in result.design.points)
    assert result.design.attempts == 32 + sum(r.count for r in result.design.rejections)


def test_integer_only_is_not_applicable_and_exhaustion_returns_no_partial_design():
    req = design_request(2, 2)
    integers = replace(
        req.space,
        coordinates=tuple(
            replace(c, kind=ParameterCoordinateKind.INTEGER) for c in req.space.coordinates
        ),
    )
    assert build(replace(req, space=integers)).status is m.ParameterDesignStatus.NOT_APPLICABLE
    req = replace(req, protocol=replace(req.protocol, max_attempts=3))
    result = build(req, lambda point: False)
    assert result.status is m.ParameterDesignStatus.DESIGN_FAILED
    assert result.design is None and result.attempts == 3
    assert result.rejections == (
        m.ParameterDesignRejection(m.ParameterRejectionReason.CONSTRAINT, 3),
    )
    assert (
        build(
            replace(
                design_request(1, 3),
                protocol=ParameterPerturbationProtocol(point_count=3, max_attempts=8),
            )
        ).status
        is m.ParameterDesignStatus.DESIGN_FAILED
    )


def test_contract_boundaries_and_callback_type_are_strict():
    with pytest.raises(ValueError, match="domain"):
        ParameterCoordinate("x", 0.0, -1e308, 1e308, ParameterCoordinateKind.CONTINUOUS)
    with pytest.raises(ValueError, match="tolerance"):
        ParameterPerturbationProtocol(radius=1e-12)
    with pytest.raises(TypeError):
        ParameterPerturbationProtocol(point_count=True)
    with pytest.raises(TypeError, match="Feasibility"):
        build(feasibility=None)
    with pytest.raises(TypeError, match="bool"):
        build(feasibility=lambda point: 1)
    with pytest.raises(ValueError, match="accounting"):
        replace(build(), attempts=0)


def test_complete_declared_coverage_computes_linear_quantiles():
    req = bound_request()
    panel = assess_candidates(req)
    context = panel.rows[0].parameter_context
    assert context.valid_points == context.prescribed_points == 2
    assert context.design_sha256 == req.parameter_designs[0].sha256
    values = {x.metric: x.value for x in panel.rows[0].diagnostics}
    assert values[m.ResearchMetric.PARAMETER_RETURN_DEGRADATION] > 0
    assert panel.formula_version == "research-assessment-v3"
    assert m.CandidateAssessmentRequest.from_dict(req.to_dict()) == req


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


def test_partial_policy_keeps_early_economic_relation_but_rejects_unbound_parameter_pair():
    from test_research_comparison_v2 import partial_policy

    a = replace(row(candidate(), annual=0.11, drawdown=0.12), parameter_context=None)
    b = replace(row(candidate("C0002", "b"), annual=0.10, drawdown=0.11), parameter_context=None)
    assert compare((a, b), partial_policy()).pairs[0].relation is m.PairwiseRelation.A_BEFORE_B
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
