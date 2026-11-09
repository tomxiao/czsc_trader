"""Current assessment semantics and historical recomputation remain distinct."""
from dataclasses import fields, replace

import pytest

import strategy_evaluator as se
from strategy_evaluator import research_models as m
from test_parameter_perturbation import bound_request
from test_research_assessment import compare
from strategy_evaluator.research_assessment import (
    recompute_historical_assessment,
)


def current_request(*, all_na=False, partial=False):
    old = bound_request()
    axis = se.ParameterAxis("hold", 3 if all_na else 20, se.IntegerDomain(1, 30),
        se.BoundedLocalStep(se.RelativeChangeLimit(0.05)), ("hold",), "sessions")
    axes = (axis,)
    if partial:
        axes += (se.ParameterAxis("lookback", 3, se.IntegerDomain(1, 10),
            se.BoundedLocalStep(se.RelativeChangeLimit(0.05)), ("lookback",), "sessions"),)
    design = se.build_parameter_neighborhood_design(se.ParameterNeighborhoodRequest(
        old.centers[0], se.ParameterNeighborhoodProtocol(),
        se.ParameterNeighborhoodSpace(axes, "a" * 64, "b" * 64)), feasibility=lambda _: True).design
    values = {f.name: getattr(old.protocol, f.name) for f in fields(old.protocol)
              if f.name not in ("minimum_perturbations", "parameter_protocol")}
    protocol = se.NeighborhoodSelfCheckProtocol(**values, parameter_protocol=design.protocol)
    links = () if all_na else tuple(replace(link, parameter_point=design.bind_point(i))
        for i, link in enumerate(old.perturbations))
    evidence = old.evidence[:2] if all_na else (*old.evidence[:2],
        *(replace(item, parameter_point=design.bind_point(i)) for i, item in enumerate(old.evidence[2:])))
    return replace(old, protocol=protocol, parameter_designs=(design,), perturbations=links, evidence=evidence)


@pytest.mark.risk_cases('SE-17-C01')
def test_current_complete_roundtrip_and_unit_weights():
    request = current_request()
    assert m.CandidateAssessmentRequest.from_dict(request.to_dict()) == request
    panel = se.assess_candidates(request)
    assert panel.formula_version == "research-assessment-v7"
    assert panel.rows[0].parameter_context.valid_points == 2
    assert len(panel.rows[0].parameter_performances) == 2
    diagnostics = {item.metric: item for item in panel.rows[0].diagnostics}
    # Both children earn 5+10 on initial 1000 across four days; equal unit
    # weights make every LINEAR quantile the same annual return, with zero DD.
    assert diagnostics[m.ResearchMetric.PARAMETER_RETURN_Q10].value == pytest.approx((1015 / 1000) ** 63 - 1)
    assert diagnostics[m.ResearchMetric.PARAMETER_DRAWDOWN_Q90].value == 0.
    assert m.AssessmentPanel.from_dict(panel.to_dict()) == panel
    with pytest.raises(ValueError, match="unit weights"):
        replace(request, perturbations=(replace(request.perturbations[0], weight=2.0), request.perturbations[1]))


@pytest.mark.risk_cases('SE-33-C01')
def test_historical_v5_retains_prior_recomputation_semantics():
    request = bound_request()
    bad = replace(request.evidence[-1], benchmark_equity=(1001.0,) * 4)
    panel = recompute_historical_assessment(replace(request, evidence=(*request.evidence[:-1], bad)))
    assert panel.formula_version == "research-assessment-v5"
    assert panel.rows[0].parameter_context.valid_points == 2
    original = panel.to_dict()
    assert m.AssessmentPanel.from_dict(original).to_dict() == original
    assert m.AssessmentPanel.from_dict(original).sha256 == panel.sha256


PARAMETER_METRICS = (
    m.ResearchMetric.PARAMETER_RETURN_Q10,
    m.ResearchMetric.PARAMETER_DRAWDOWN_Q90,
)


def current_targets():
    return (
        m.ResearchTarget("center", m.ResearchMetric.NET_ANNUAL_RETURN,
                         lower=m.ConstantBound(0.0, True)),
        m.ParameterNeighborhoodTarget("parameter", 13, 16, (
            m.ResearchTarget("return", m.ResearchMetric.NET_ANNUAL_RETURN,
                                     lower=m.ConstantBound(0.0, True)),
        ), (m.ResearchTarget("risk", m.ResearchMetric.DRAWDOWN_MAGNITUDE,
                             upper=m.ConstantBound(0.25, True)),)),
    )


def named_row(item, suffix):
    who = m.AssessmentCandidate(f"S900-C{suffix:04d}", str(suffix % 10) * 64)
    return replace(item, candidate=who,
                   stress_performance=replace(item.stress_performance, candidate=who))


def changed_metric(item, metric, value):
    return replace(item, diagnostics=tuple(
        replace(x, value=value) if x.metric is metric else x for x in item.diagnostics
    ))


@pytest.mark.risk_cases('SE-12-C04')
def test_unavailable_parameter_item_keeps_other_checks_and_has_explicit_floor():
    request = current_request(all_na=True)
    assert request.parameter_designs[0].points == ()
    assert request.perturbations == ()
    panel = se.assess_candidates(request)
    row = panel.rows[0]
    assert row.parameter_context.prescribed_points == row.parameter_context.valid_points == 0
    assert row.parameter_performances == ()
    for value in row.diagnostics:
        if value.metric in PARAMETER_METRICS:
            assert value.status is m.DiagnosticStatus.NOT_APPLICABLE
            assert value.value is None
        elif value.metric is m.ResearchMetric.STRESS_ANNUAL_LOSS:
            assert value.status is m.DiagnosticStatus.AVAILABLE
    result = compare(panel.rows, targets=current_targets(), current=True)
    ranked = result.rows[0]
    assert ranked.target_checks[1].status is m.TargetCheckStatus.NOT_APPLICABLE
    assert ranked.acceptance_status is m.TargetCheckStatus.PASSED
    assert ranked.status is m.ComparisonStatus.RANKED
    assert ranked.bin_values[:2] == (None, None)
    assert ranked.floor_metrics == PARAMETER_METRICS
    assert type(result).from_dict(result.to_dict()) == result
    diagnostic = se.compare_parameter_robustness(
        m.ParameterRobustnessComparisonRequest((row, named_row(row, 9))))
    assert not diagnostic.comparable
    assert "UNAVAILABLE_PARAMETER_METRICS" in diagnostic.reasons
    with pytest.raises(ValueError, match="no measurement"):
        replace(row, diagnostics=tuple(replace(x, value=0.0,
            status=m.DiagnosticStatus.AVAILABLE, reason=None)
            if x.metric is m.ResearchMetric.PARAMETER_DRAWDOWN_Q90 else x
            for x in row.diagnostics))


@pytest.mark.risk_cases('SE-17-C06')
def test_SE_17_C06_missing_point_preserves_prescribed_denominator():
    request = current_request()
    row = se.assess_candidates(replace(request, evidence=request.evidence[:-1])).rows[0]
    assert row.parameter_context.prescribed_points == 2
    assert row.parameter_context.valid_points == 1
    relevant = [x for x in row.diagnostics if x.metric in PARAMETER_METRICS]
    assert relevant and all(x.value is None for x in relevant)
    assert all(x.status is not m.DiagnosticStatus.NOT_APPLICABLE for x in relevant)

@pytest.mark.risk_cases('SE-12-C01')
def test_SE_12_C01_require_complete_never_ranks_missing_applicable_metrics():
    request = current_request()
    panel = se.assess_candidates(replace(request, evidence=request.evidence[:-1]))
    ranked = compare(panel.rows, targets=current_targets(), current=True).rows[0]
    assert ranked.acceptance_status is m.TargetCheckStatus.INDETERMINATE
    assert ranked.status is m.ComparisonStatus.INCOMPARABLE
    assert ranked.floor_metrics == ()




@pytest.mark.risk_cases('SE-17-C07')
def test_SE_17_C07_failed_point_keeps_declared_denominator():
    request = current_request()
    failed = request.evidence[-1]
    attempt = m.IncompleteEvaluation(failed.candidate, failed.window_id, failed.scenario_id,
        m.IncompleteEvaluationStatus.FAILED, "numerical evaluation failed", failed.experiment_id, "2" * 32)
    request = replace(request, evidence=request.evidence[:-1], incomplete=(attempt,))
    row = se.assess_candidates(request).rows[0]
    assert row.parameter_context.prescribed_points == 2
    assert row.parameter_context.valid_points == 1
    assert request.incomplete == (attempt,)
    assert all(x.value is None for x in row.diagnostics if x.metric in PARAMETER_METRICS)
