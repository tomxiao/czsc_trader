"""Current assessment semantics and historical recomputation remain distinct."""
from dataclasses import fields, replace

import pytest

import strategy_evaluator as se
from strategy_evaluator import research_models as m
from test_parameter_perturbation import bound_request
from test_research_assessment import compare, policy
from strategy_evaluator.research_assessment import (
    recompute_historical_assessment, recompute_historical_comparison,
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


def test_current_complete_roundtrip_and_unit_weights():
    request = current_request()
    assert m.CandidateAssessmentRequest.from_dict(request.to_dict()) == request
    panel = se.assess_candidates(request)
    assert panel.formula_version == "research-assessment-v7"
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
    assert all(x.status is m.ComparisonStatus.INCOMPARABLE for x in compare((row, other), current=True).rows)


def test_historical_v5_retains_prior_recomputation_semantics():
    request = bound_request()
    bad = replace(request.evidence[-1], benchmark_equity=(1001.0,) * 4)
    panel = recompute_historical_assessment(replace(request, evidence=(*request.evidence[:-1], bad)))
    assert panel.formula_version == "research-assessment-v5"
    assert panel.rows[0].parameter_context.valid_points == 2


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


def test_partial_applicability_preserves_fixed_axes_and_full_remaining_evidence():
    request = current_request(partial=True)
    design = request.parameter_designs[0]
    assert design.point_count == 2
    assert all(dict((v.name, v.value) for v in point.values)["lookback"] == 3
               for point in design.points)
    panel = se.assess_candidates(request)
    assert panel.rows[0].parameter_context.valid_points == 2
    result = compare(panel.rows, targets=current_targets(), current=True).rows[0]
    assert result.acceptance_status is m.TargetCheckStatus.PASSED
    assert result.floor_metrics == ()


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


def test_missing_required_point_never_becomes_na_or_receives_floor():
    request = current_request()
    panel = se.assess_candidates(replace(request, evidence=request.evidence[:-1]))
    row = panel.rows[0]
    assert row.parameter_context.prescribed_points == 2
    assert row.parameter_context.valid_points == 1
    assert all(x.status is not m.DiagnosticStatus.NOT_APPLICABLE
               for x in row.diagnostics if x.metric in PARAMETER_METRICS)
    ranked = compare(panel.rows, targets=current_targets(), current=True).rows[0]
    assert ranked.acceptance_status is m.TargetCheckStatus.INDETERMINATE
    assert ranked.status is m.ComparisonStatus.INCOMPARABLE
    assert ranked.floor_metrics == ()


def test_measured_neighbor_ranks_above_floor_without_invented_raw_values():
    measured = se.assess_candidates(current_request()).rows[0]
    floor = named_row(se.assess_candidates(current_request(all_na=True)).rows[0], 9)
    floor = changed_metric(floor, m.ResearchMetric.ROLLING_EXCESS_Q10, 10.0)
    ranked = compare((floor, measured), targets=current_targets(), current=True)
    assert ranked.rows[0].candidate == measured.candidate
    assert all(x.pareto_layer == 1 for x in ranked.rows)
    assert ranked.pairs[0].decisive_metric is m.ResearchMetric.PARAMETER_RETURN_Q10
    assert ranked.rows[1].floor_metrics == PARAMETER_METRICS
    swapped_policy = replace(policy(), sensitivities=(
        m.ComparisonVariant("drawdown-first", policy().bins, adjacent_swap=0),
    ))
    swapped = compare((floor, measured), swapped_policy, targets=current_targets(), current=True)
    assert swapped.sensitivities[0].rows[0].candidate == measured.candidate
    assert swapped.sensitivities[0].rows[1].floor_metrics == PARAMETER_METRICS


def test_two_floors_use_later_metrics_and_pareto_still_has_priority():
    first = se.assess_candidates(current_request(all_na=True)).rows[0]
    second = named_row(first, 9)
    second = changed_metric(second, m.ResearchMetric.ROLLING_EXCESS_Q10, 1.0)
    result = compare((first, second), targets=current_targets(), current=True)
    assert result.rows[0].candidate == second.candidate
    assert result.pairs[0].decisive_metric is m.ResearchMetric.ROLLING_EXCESS_Q10
    measured = named_row(se.assess_candidates(current_request()).rows[0], 8)
    dominant = changed_metric(first, m.ResearchMetric.NET_ANNUAL_RETURN, 100.0)
    result = compare((measured, dominant), targets=current_targets(), current=True)
    assert [(x.candidate, x.pareto_layer) for x in result.rows] == [
        (dominant.candidate, 1), (measured.candidate, 2)]


def test_current_entry_rejects_historical_requests():
    with pytest.raises(ValueError, match="historical|read.only|current"):
        se.assess_candidates(bound_request())


def test_v6_v3_historical_roundtrip_keeps_exact_fields_and_cannot_be_reissued():
    request = current_request()
    design = request.parameter_designs[0]
    axis = replace(design.space.axes[0], rule=se.NumericOffsets((-1, 1)))
    legacy_protocol = replace(design.protocol, version="parameter-cartesian-neighborhood-v1")
    design = replace(design, protocol=legacy_protocol, space=replace(design.space, axes=(axis,)))
    request = replace(request,
        protocol=replace(request.protocol, parameter_protocol=legacy_protocol),
        parameter_designs=(design,),
        perturbations=tuple(replace(x, parameter_point=design.bind_point(i))
                            for i, x in enumerate(request.perturbations)),
        evidence=tuple(replace(x, parameter_point=design.bind_point(x.parameter_point.point_index))
                       if x.parameter_point is not None else x for x in request.evidence))
    panel = recompute_historical_assessment(request)
    assert panel.formula_version == "research-assessment-v6"
    req = m.CandidateComparisonRequest(request.centers, m.ResearchTargets((), 2), panel, policy())
    result = recompute_historical_comparison(req)
    serialized = result.to_dict()
    assert "floor_metrics" not in serialized["rows"][0]
    assert result.rows[0].floor_metrics is None
    assert type(result).from_dict(serialized).to_dict() == serialized
    with pytest.raises(ValueError, match="historical|read.only"):
        se.assess_candidates(request)
    with pytest.raises(ValueError, match="historical|read.only"):
        se.compare_candidates(req)
    with pytest.raises(ValueError, match="version|protocol|current|context"):
        replace(panel, formula_version="research-assessment-v7")
