"""Current assessment semantics and historical recomputation remain distinct."""
from dataclasses import fields, replace

import pytest

import strategy_evaluator as se
from strategy_evaluator import research_models as m
from test_parameter_perturbation import bound_request
from test_research_assessment import compare


def current_request():
    old = bound_request()
    axis = se.ParameterAxis("hold", 3, se.IntegerDomain(1, 10), se.NumericOffsets((-1, 1)), ("hold",), "sessions")
    design = se.build_parameter_neighborhood_design(se.ParameterNeighborhoodRequest(
        old.centers[0], se.ParameterNeighborhoodProtocol(),
        se.ParameterNeighborhoodSpace((axis,), "a" * 64, "b" * 64)), feasibility=lambda _: True).design
    values = {f.name: getattr(old.protocol, f.name) for f in fields(old.protocol)
              if f.name not in ("minimum_perturbations", "parameter_protocol")}
    protocol = se.NeighborhoodSelfCheckProtocol(**values, parameter_protocol=design.protocol)
    links = tuple(replace(link, parameter_point=design.bind_point(i)) for i, link in enumerate(old.perturbations))
    evidence = (*old.evidence[:2], *(replace(item, parameter_point=design.bind_point(i))
                                  for i, item in enumerate(old.evidence[2:])))
    return replace(old, protocol=protocol, parameter_designs=(design,), perturbations=links, evidence=evidence)


def test_current_complete_roundtrip_and_unit_weights():
    request = current_request()
    assert m.CandidateAssessmentRequest.from_dict(request.to_dict()) == request
    panel = se.assess_candidates(request)
    assert panel.formula_version == "research-assessment-v6"
    assert panel.rows[0].parameter_context.valid_points == 2
    assert len(panel.rows[0].parameter_performances) == 2
    assert m.AssessmentPanel.from_dict(panel.to_dict()) == panel
    with pytest.raises(ValueError, match="unit weights"):
        replace(request, perturbations=(replace(request.perturbations[0], weight=2.0), request.perturbations[1]))


@pytest.mark.parametrize("empty", [False, True])
def test_wrong_or_missing_benchmark_cannot_complete_neighborhood(empty):
    request = current_request()
    bad = replace(request.evidence[-1], benchmark_equity=() if empty else (1001.0,) * 4)
    panel = se.assess_candidates(replace(request, evidence=(*request.evidence[:-1], bad)))
    row = panel.rows[0]
    assert row.parameter_context.valid_points == 1
    assert len(row.parameter_performances) == 1
    for metric in (m.ResearchMetric.PARAMETER_RETURN_Q10, m.ResearchMetric.PARAMETER_DRAWDOWN_Q90):
        assert next(x for x in row.diagnostics if x.metric is metric).value is None


def test_missing_all_benchmarks_is_not_complete():
    request = current_request()
    panel = se.assess_candidates(replace(request, evidence=tuple(replace(x, benchmark_equity=()) for x in request.evidence)))
    assert panel.rows[0].parameter_context.valid_points == 0
    assert panel.rows[0].parameter_performances == ()


def test_comparison_uses_profile_not_only_algorithm():
    row = se.assess_candidates(current_request()).rows[0]
    other_candidate = m.AssessmentCandidate("S900-C0009", "9" * 64)
    other = replace(row, candidate=other_candidate,
                    stress_performance=replace(row.stress_performance, candidate=other_candidate),
                    parameter_context=replace(row.parameter_context, comparison_sha256="d" * 64))
    result = se.compare_parameter_robustness(m.ParameterRobustnessComparisonRequest((row, other)))
    assert not result.comparable and "PARAMETER_METHODS_DIFFER" in result.reasons
    assert all(x.status is m.ComparisonStatus.INCOMPARABLE for x in compare((row, other)).rows)


def test_historical_v5_retains_prior_recomputation_semantics():
    request = bound_request()
    bad = replace(request.evidence[-1], benchmark_equity=(1001.0,) * 4)
    panel = se.assess_candidates(replace(request, evidence=(*request.evidence[:-1], bad)))
    assert panel.formula_version == "research-assessment-v5"
    assert panel.rows[0].parameter_context.valid_points == 2
