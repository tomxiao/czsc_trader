"""Numeric performance inputs preserve account-path calculations and coverage."""

from dataclasses import fields, replace
from decimal import Decimal, ROUND_FLOOR

import numpy as np
import pytest
import strategy_evaluator as se
from strategy_evaluator import research_models as m

from test_calmar_ranking import common_contract, design
from test_calmar_selfcheck import ordinary, protocol
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


@pytest.mark.risk_cases('SE-38-C01')
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


@pytest.mark.risk_cases('SE-18-C01')
def test_declared_subset_preserves_source_bindings_denominator_quantiles_and_ranking():
    missing = False
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


@pytest.mark.parametrize('indices', [
    pytest.param((1, 1), id='SE-18-C02'),
    pytest.param((True,), id='SE-18-C03'),
])
@pytest.mark.risk_cases('SE-18-C02', 'SE-18-C03')
def test_declared_point_set_rejects_invalid_or_ambiguous_source_coordinates(indices):
    with pytest.raises((ValueError, TypeError)):
        se.DeclaredParameterPointSet(economic_request().parameter_designs[0], indices, "d" * 64)




@pytest.mark.risk_cases('SE-38-C02')
def test_benchmark_scalars_must_match_the_fingerprinted_baseline():
    field = "benchmark_return"
    value = .2
    request = projected_request(account_request())
    last = request.parameter_evidence[-1]
    changed = replace(last, performance=replace(last.performance, **{field: value}))
    row = se.assess_candidates(replace(request, parameter_evidence=(request.parameter_evidence[0], changed))).rows[0]
    assert row.parameter_context.valid_points == 1


@pytest.mark.risk_cases('SE-18-C04')
def test_SE_18_C04_precomputed_panel_cannot_replace_numeric_facts():
    request = projected_request(account_request())
    with pytest.raises(TypeError):
        replace(request, parameter_evidence=(se.assess_candidates(request),))

@pytest.mark.risk_cases('SE-18-C05')
def test_SE_18_C05_callers_validated_flag_cannot_replace_numeric_facts():
    encoded = projected_request(account_request()).to_dict()
    encoded['parameter_evidence'][0]['validated'] = True
    with pytest.raises(ValueError, match='fields differ'):
        se.CandidatePerformanceAssessmentRequest.from_dict(encoded)


@pytest.mark.risk_cases('SE-18-C06')
def test_incomplete_numeric_coverage_cannot_pass_but_preserves_decisive_all_point_failures():
    decisive_failure = True
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
