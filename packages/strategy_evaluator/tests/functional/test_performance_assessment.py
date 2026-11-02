"""Numeric performance inputs preserve account-path calculations and coverage."""

from dataclasses import fields, replace
from decimal import Decimal, ROUND_FLOOR

import numpy as np
import pytest
import strategy_evaluator as se
from strategy_evaluator import research_models as m

from test_calmar_ranking import common_contract, design
from test_calmar_selfcheck import ordinary, protocol
from test_equity_assessment import evidence as equity_evidence
from test_neighborhood_assessment import current_request
from test_research_assessment import candidate, policy


def account_request(**kwargs):
    request = current_request(**kwargs)
    return replace(request, protocol=se.CalmarSelfCheckProtocol(**{
        field.name: getattr(request.protocol, field.name) for field in fields(request.protocol)
    }))


def projected_request(request):
    return se.CandidatePerformanceAssessmentRequest(
        replace(request, evidence=tuple(x for x in request.evidence if x.parent is None)),
        tuple(se.project_parameter_performance(x) for x in request.evidence if x.parent is not None),
    )


def test_numeric_input_reproduces_complete_account_rows_and_roundtrip():
    request = account_request()
    numeric = projected_request(request)
    actual = se.assess_candidates(numeric)
    expected = se.assess_candidates(request)
    assert actual.rows == expected.rows
    assert actual.family_diagnostics == expected.family_diagnostics
    assert actual.formula_version == expected.formula_version == "research-assessment-v8"
    assert actual.request_sha256 == numeric.sha256 != expected.request_sha256
    assert actual.input_kind is se.AssessmentInputKind.PERFORMANCE_PROJECTION
    assert se.CandidatePerformanceAssessmentRequest.from_dict(numeric.to_dict()) == numeric
    assert se.AssessmentPanel.from_dict(actual.to_dict()) == actual
    assert "input_kind" not in expected.to_dict()


def economic_request():
    centers = (candidate(), candidate("C0011", "b"))
    designs, links, items = [], [], []
    for center_index, center in enumerate(centers):
        geometry = design(center)
        designs.append(geometry)
        base = replace(ordinary((1010., 990., 1010., 1005., 1020., 1015.),
                                (1005., 995., 1005., 1000., 1010., 1005.)), candidate=center,
                       evaluation_id=m.digest((center, "baseline")), frequency_window_days=2)
        items.extend((base, replace(base, evaluation_id=m.digest((center, "stress")),
            scenario_id="pressure", scenario_context=replace(base.scenario_context,
                one_way_cost=.001, measurement_tier="STRESS"))))
        for index in range(geometry.point_count):
            child = candidate(f"C{100 + center_index * 100 + index:04d}", "c")
            link = se.PerturbationLink(center, child, 1., m.digest((center, index)), geometry.bind_point(index))
            links.append(link)
            values = (1010., 980. + index, 1005., 995., 1010., 1010. + index)
            neighbor = ordinary(values, base.benchmark_equity)
            items.append(replace(neighbor, candidate=child, evaluation_id=m.digest((child, index)),
                frequency_window_days=2, parent=center, derivation_sha256=link.derivation_sha256,
                derivation_kind=se.AssessmentDerivationKind.PARAMETERS, parameter_point=link.parameter_point))
    return se.CandidateAssessmentRequest(centers, protocol(), tuple(links), tuple(items), parameter_designs=tuple(designs))


def comparison(request, panel, contract=None):
    replacements = {
        m.ResearchMetric.NET_ANNUAL_RETURN: m.ResearchMetric.NET_CALMAR,
        m.ResearchMetric.PARAMETER_RETURN_Q10: m.ResearchMetric.PARAMETER_CALMAR_Q10,
        m.ResearchMetric.ROLLING_EXCESS_Q10: m.ResearchMetric.ROLLING_EXCESS_CALMAR_Q10,
        m.ResearchMetric.STRESS_ANNUAL_LOSS: m.ResearchMetric.STRESS_CALMAR_LOSS,
    }
    selected = replace(policy(frequency_metric=m.ResearchMetric.FREQUENCY_MEDIAN),
        formula_version="research-ranking-v6", bins=tuple(replace(x, metric=replacements.get(x.metric, x.metric))
            for x in policy(frequency_metric=m.ResearchMetric.FREQUENCY_MEDIAN).bins))
    atom = m.ResearchTarget("calmar", m.ResearchMetric.NET_CALMAR, lower=m.ConstantBound(0., False))
    goals = m.ResearchTargets((atom, m.ParameterNeighborhoodTarget("neighbors", 3, 4, (atom,), (
        m.ResearchTarget("risk", m.ResearchMetric.DRAWDOWN_MAGNITUDE, upper=m.ConstantBound(.25, True)),))), 2)
    return se.compare_candidates(se.CalmarComparisonRequest(request.centers, goals, panel, selected,
                                                           request.parameter_designs, contract or common_contract()))


def test_complete_projection_matches_full_v8_v6_quantiles_targets_and_ranking():
    request = economic_request()
    numeric = projected_request(request)
    full, projected = se.assess_candidates(request), se.assess_candidates(numeric)
    assert full.rows == projected.rows
    raw_result, numeric_result = comparison(request, full), comparison(request, projected)
    assert replace(numeric_result, request_sha256=raw_result.request_sha256) == raw_result
    assert all(x.acceptance_status is m.TargetCheckStatus.PASSED for x in numeric_result.rows)
    row = projected.rows[0]
    assert row.parameter_context.valid_points == row.parameter_context.prescribed_points == 8
    assert next(x.value for x in row.diagnostics if x.metric is m.ResearchMetric.PARAMETER_DRAWDOWN_Q90) == pytest.approx(
        np.quantile([x.drawdown for x in row.parameter_performances], .9, method="linear"))
    for result in numeric_result.rows:
        group = result.target_checks[1]
        assert group.minimum_joint_passes == 6 and group.valid_points == group.joint_passes == 8


def declared_request():
    original = economic_request()
    selected = (1, 4, 7)
    designs = tuple(se.DeclaredParameterPointSet(x, selected, "d" * 64) for x in original.parameter_designs)
    links = tuple(x for x in original.perturbations if x.parameter_point.point_index in selected)
    items = tuple(x for x in original.evidence if x.parent is None or x.parameter_point.point_index in selected)
    return replace(original, parameter_designs=designs, perturbations=links, evidence=items)


@pytest.mark.parametrize("missing", [False, True])
def test_declared_subset_preserves_source_bindings_denominator_quantiles_and_ranking(missing):
    raw = declared_request()
    numeric = projected_request(raw)
    if missing:
        numeric = replace(numeric, parameter_evidence=numeric.parameter_evidence[:-1])
    assert se.CandidatePerformanceAssessmentRequest.from_dict(numeric.to_dict()) == numeric
    panel = se.assess_candidates(numeric)
    contract = se.DeclaredPointSetComparisonContract("d" * 64, common_contract())
    result = comparison(raw, panel, contract)
    for index, row in enumerate(panel.rows):
        context = row.parameter_context
        assert context.point_indices == (1, 4, 7)
        assert context.prescribed_points == 3
        assert context.valid_points == (2 if missing and index == 1 else 3)
        assert {x.point_index for x in row.parameter_performances} <= {1, 4, 7}
        expected = se.TargetCheckStatus.INDETERMINATE if missing and index == 1 else se.TargetCheckStatus.PASSED
        ranked = next(x for x in result.rows if x.candidate == row.candidate)
        assert ranked.target_checks[1].status is expected
        assert ranked.target_checks[1].required_points == 3
        assert ranked.target_checks[1].minimum_joint_passes == 3
        if expected is se.TargetCheckStatus.PASSED:
            calmars = [x.annual_return / x.drawdown for x in row.parameter_performances]
            expected_bin = int((Decimal(str(float(np.quantile(calmars, .1)))) / Decimal('.01'))
                               .to_integral_value(rounding=ROUND_FLOOR))
            assert ranked.bin_values[0] == expected_bin
            assert next(x.value for x in row.diagnostics
                        if x.metric is m.ResearchMetric.PARAMETER_DRAWDOWN_Q90) == pytest.approx(
                            np.quantile([x.drawdown for x in row.parameter_performances], .9))
    with pytest.raises(ValueError, match="full neighborhood"):
        comparison(raw, panel)
    with pytest.raises(ValueError, match="construction differs"):
        comparison(raw, panel, replace(contract, construction_sha256="e" * 64))
    assert raw.parameter_designs[0].bind_point(7) == raw.parameter_designs[0].source_design.bind_point(7)
    if not missing:
        assert se.assess_candidates(raw).rows == panel.rows


@pytest.mark.parametrize("indices", [(), (1, 1), (-1,), (8,), (True,)])
def test_declared_point_set_rejects_invalid_or_ambiguous_source_coordinates(indices):
    with pytest.raises((ValueError, TypeError)):
        se.DeclaredParameterPointSet(economic_request().parameter_designs[0], indices, "d" * 64)


@pytest.mark.parametrize("all_na,missing", [(False, 1), (False, 2), (True, 0)])
def test_missing_points_and_empty_legal_neighborhood_preserve_full_design_and_unavailable_statistics(all_na, missing):
    request = account_request(all_na=all_na)
    partial = replace(request, evidence=request.evidence[:-missing]) if missing else request
    numeric = projected_request(partial)
    row = se.assess_candidates(numeric).rows[0]
    assert row == se.assess_candidates(partial).rows[0]
    assert row.parameter_context.prescribed_points == (0 if all_na else 2)
    assert row.parameter_context.valid_points == (0 if all_na else 2 - missing)
    values = [x for x in row.diagnostics if x.metric in (
        m.ResearchMetric.PARAMETER_RETURN_Q10, m.ResearchMetric.PARAMETER_DRAWDOWN_Q90)]
    assert all(x.value is None and x.status is (
        m.DiagnosticStatus.NOT_APPLICABLE if all_na else m.DiagnosticStatus.INSUFFICIENT_DATA) for x in values)


@pytest.mark.parametrize("field,value", [
    ("context_sha256", "9" * 64), ("metric_version", "different-metric"),
    ("window_id", "different-window"), ("scenario_id", "different-scenario"),
    ("frequency_window_days", 61), ("initial_cash", 2000.),
    ("benchmark_equity_sha256", "9" * 64),
])
def test_incomparable_projection_metadata_is_excluded_and_never_creates_partial_quantiles(field, value):
    request = projected_request(account_request())
    bad = replace(request.parameter_evidence[-1], **{field: value})
    actual = se.assess_candidates(replace(request, parameter_evidence=(*request.parameter_evidence[:-1], bad))).rows[0]
    assert actual.parameter_context.valid_points == 1
    assert len(actual.parameter_performances) == 1
    assert all(x.value is None for x in actual.diagnostics if x.metric in (
        m.ResearchMetric.PARAMETER_RETURN_Q10, m.ResearchMetric.PARAMETER_DRAWDOWN_Q90))


@pytest.mark.parametrize("field,value", [("one_way_cost", .01), ("benchmark_id", "different"),
                                        ("measurement_tier", "STRESS")])
def test_incomparable_cost_and_benchmark_contract_never_count_as_valid_points(field, value):
    request = projected_request(account_request())
    last = request.parameter_evidence[-1]
    facts = replace(last.performance, scenario=replace(last.scenario_context, **{field: value}))
    changed = replace(request, parameter_evidence=(*request.parameter_evidence[:-1], replace(last, performance=facts)))
    assert se.assess_candidates(changed).rows[0].parameter_context.valid_points == 1


@pytest.mark.parametrize("field,value", [("benchmark_return", .2), ("benchmark_drawdown", .1)])
def test_benchmark_scalars_must_match_the_fingerprinted_baseline(field, value):
    request = projected_request(account_request())
    last = request.parameter_evidence[-1]
    changed = replace(last, performance=replace(last.performance, **{field: value}))
    row = se.assess_candidates(replace(request, parameter_evidence=(request.parameter_evidence[0], changed))).rows[0]
    assert row.parameter_context.valid_points == 1


@pytest.mark.parametrize("change", ["parent", "derivation", "binding", "evaluation", "point", "candidate"])
def test_invalid_identity_derivation_or_duplicate_points_are_rejected(change):
    request = projected_request(account_request())
    first, last = request.parameter_evidence
    with pytest.raises((ValueError, TypeError)):
        if change == "parent":
            last = replace(last, parent=last.candidate)
        elif change == "derivation":
            last = replace(last, derivation_sha256="7" * 64)
        elif change == "binding":
            last = replace(last, parameter_point=first.parameter_point,
                           performance=replace(last.performance, point_index=first.performance.point_index))
        elif change == "evaluation":
            last = replace(last, performance=replace(last.performance, evaluation_id=first.evaluation_id))
        elif change == "point":
            last = first
        else:
            last = replace(last, performance=replace(last.performance,
                candidate=replace(last.candidate, content_sha256="9" * 64)))
        se.assess_candidates(replace(request, parameter_evidence=(first, last)))


def test_projection_accepts_numeric_facts_not_precomputed_panels_or_caller_passes():
    request = projected_request(account_request())
    with pytest.raises(TypeError):
        replace(request, parameter_evidence=(se.assess_candidates(request),))
    encoded = request.to_dict()
    encoded["parameter_evidence"][0]["PASS"] = True
    with pytest.raises(ValueError, match="fields differ"):
        se.CandidatePerformanceAssessmentRequest.from_dict(encoded)
    with pytest.raises(ValueError, match="center account"):
        replace(request, baseline_request=account_request())
    with pytest.raises(ValueError, match="CalmarSelfCheck"):
        replace(request, baseline_request=replace(request.baseline_request, protocol=current_request().protocol))


@pytest.mark.parametrize("dd", [0., 1e-12])
def test_zero_or_nearzero_drawdown_cannot_turn_full_coverage_into_available_calmar(dd):
    request = economic_request()
    numeric = projected_request(request)
    projections = tuple(replace(x, performance=replace(x.performance, drawdown=dd)) for x in numeric.parameter_evidence)
    panel = se.assess_candidates(replace(numeric, parameter_evidence=projections))
    result = comparison(request, panel)
    assert all(x.parameter_context.valid_points == x.parameter_context.prescribed_points for x in panel.rows)
    assert all(x.target_checks[1].status is m.TargetCheckStatus.INDETERMINATE for x in result.rows)
    assert all(x.bin_values[0] is None for x in result.rows)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_numeric_performance_is_rejected_before_aggregation(bad):
    request = projected_request(account_request())
    with pytest.raises(TypeError):
        replace(request.parameter_evidence[0].performance, annual_return=bad)


def test_equity_bar_close_projection_matches_actual_synthetic_journal_calculation():
    request = account_request()
    raw = equity_evidence("BAR_CLOSE", days=3)
    items = tuple(replace(raw, candidate=x.candidate, evaluation_id=x.evaluation_id,
        window_id=x.window_id, scenario_id=x.scenario_id,
        scenario_context=replace(x.scenario_context, one_way_cost=0.),
        parent=x.parent, derivation_kind=x.derivation_kind, derivation_sha256=x.derivation_sha256,
        parameter_point=x.parameter_point) for x in request.evidence)
    request = replace(request, evidence=items)
    full, projected = se.assess_candidates(request), se.assess_candidates(projected_request(request))
    assert full.rows == projected.rows
    assert projected.rows[0].parameter_context.valid_points == 2
    assert all(x.drawdown > 0 for x in projected.rows[0].parameter_performances)
    assert se.assessment_benchmark_fingerprint(items[0]) == se.assessment_benchmark_fingerprint(items[-1])
    daily = replace(raw, metric_version="equity-assessment-v4:SESSION_CLOSE:MAX_SINGLE",
                    equity=replace(raw.equity, drawdown_basis="SESSION_CLOSE"))
    assert se.assessment_benchmark_fingerprint(raw) != se.assessment_benchmark_fingerprint(daily)


@pytest.mark.parametrize("decisive_failure", [False, True])
def test_incomplete_numeric_coverage_cannot_pass_but_preserves_decisive_all_point_failures(decisive_failure):
    request = economic_request()
    numeric = projected_request(request)
    projections = numeric.parameter_evidence[:-1]
    if decisive_failure:
        projections = (*projections[:-1], replace(projections[-1],
            performance=replace(projections[-1].performance, drawdown=.5)))
    panel = se.assess_candidates(replace(numeric, parameter_evidence=projections))
    checked = next(x for x in comparison(request, panel).rows if x.candidate == request.centers[-1])
    group = checked.target_checks[1]
    assert group.required_points == 8 and group.valid_points == 7
    assert group.status is (m.TargetCheckStatus.FAILED if decisive_failure else m.TargetCheckStatus.INDETERMINATE)
    assert group.reason == ("PARAMETER_ALL_POINT_TARGET_NOT_MET" if decisive_failure else "INCOMPLETE_PARAMETER_COVERAGE")
    assert checked.bin_values[0] is None
