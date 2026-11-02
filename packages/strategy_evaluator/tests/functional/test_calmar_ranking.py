"""Versioned Calmar ranking authenticates complete designs without rewriting old panels."""

from dataclasses import replace
from decimal import Decimal

import numpy as np
import pytest

import strategy_evaluator as se
from strategy_evaluator import research_models as m
from test_research_assessment import candidate, policy, row


def common_contract():
    return se.CommonNeighborhoodComparisonContract(
        se.RelativeChangeLimit(0.05),
        (se.ZeroCenterAbsoluteLimit("g", se.AbsoluteChangeLimit(0.05)),),
    )


def design(who, center=0.5, *, relative=0.05, unit="ratio", upper=1.0,
           path=("g",), mapping="a" * 64, feasibility_hash="b" * 64,
           feasibility=lambda values: True, empty=False):
    axes = () if empty else (
        se.ParameterAxis("alpha", 1.0, se.RealDomain(0.0, 2.0),
                         se.BoundedLocalStep(se.RelativeChangeLimit(relative)), ("alpha",), "ratio"),
        se.ParameterAxis("g", center, se.RealDomain(0.0, upper),
                         se.BoundedLocalStep(se.AbsoluteChangeLimit(0.05) if center == 0.0
                                             else se.RelativeChangeLimit(relative)), path, unit),
    )
    result = se.build_parameter_neighborhood_design(se.ParameterNeighborhoodRequest(
        who, se.ParameterNeighborhoodProtocol(), se.ParameterNeighborhoodSpace(axes, mapping, feasibility_hash),
    ), feasibility=feasibility)
    return result.design


PARAMETER_METRICS = (
    m.ResearchMetric.PARAMETER_RETURN_Q10, m.ResearchMetric.PARAMETER_DRAWDOWN_Q90,
    m.ResearchMetric.PARAMETER_RETURN_DEGRADATION, m.ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
)


def assessed(who, annual=0.2, dd=0.1, *, geometry=None, point_values=None):
    geometry = geometry or design(who)
    item = row(who, annual=annual, drawdown=dd)
    pairs = point_values or ((0.2, 0.1),) * geometry.point_count
    facts = tuple(m.PerformanceFacts(
        candidate(f"C{100 + i:04d}", "c"), f"{i:064x}", item.baseline_scenario,
        r, d, 0.1, 0.1, i,
    ) for i, (r, d) in enumerate(pairs))
    diagnostics = item.diagnostics
    if not geometry.is_applicable:
        diagnostics = tuple(replace(x, value=None, status=m.DiagnosticStatus.NOT_APPLICABLE,
                                    reason="NO_APPLICABLE_LOCAL_NEIGHBORHOOD")
                            if x.metric in PARAMETER_METRICS else x for x in diagnostics)
    elif all(r is not None and d is not None for r, d in pairs):
        rq = float(np.quantile([r for r, _ in pairs], 0.1))
        dq = float(np.quantile([d for _, d in pairs], 0.9))
        metrics = dict(zip(PARAMETER_METRICS, (rq, dq, max(0.0, annual - rq), max(0.0, dq - dd))))
        diagnostics = tuple(replace(x, value=metrics[x.metric]) if x.metric in metrics else x for x in diagnostics)
    else:
        diagnostics = tuple(replace(x, value=None, status=m.DiagnosticStatus.INSUFFICIENT_DATA, reason="missing")
                            if x.metric in PARAMETER_METRICS else x for x in diagnostics)
    return replace(item, diagnostics=diagnostics, parameter_performances=facts,
        parameter_context=se.ParameterNeighborhoodContext(
            geometry.protocol, geometry.sha256, geometry.space.sha256, len(geometry.space.axes),
            geometry.point_count, len(facts), geometry.comparison_sha256,
        )), geometry


def request(*items, contract=None):
    rows, designs = zip(*items)
    old = policy(frequency_metric=m.ResearchMetric.FREQUENCY_MEDIAN)
    replacements = {
        m.ResearchMetric.NET_ANNUAL_RETURN: m.ResearchMetric.NET_CALMAR,
        m.ResearchMetric.PARAMETER_RETURN_Q10: m.ResearchMetric.PARAMETER_CALMAR_Q10,
    }
    selected = replace(old, formula_version="research-ranking-v5", bins=tuple(
        replace(x, metric=replacements.get(x.metric, x.metric), resolution=0.0001) for x in old.bins
    ))
    return se.CalmarComparisonRequest(
        tuple(x.candidate for x in rows),
        m.ResearchTargets((m.ResearchTarget("center", m.ResearchMetric.NET_CALMAR,
                                           lower=m.ConstantBound(0.0, False)),), 60),
        m.AssessmentPanel("a" * 64, "b" * 64, tuple(rows), (), (), formula_version="research-assessment-v7"),
        selected, tuple(designs), contract or common_contract(),
    )


def ranks(req):
    return {x.candidate.candidate_id: x for x in se.compare_candidates(req).rows}


def test_v5_calmar_pareto_reverses_return_drawdown_tradeoff_and_preserves_v4_encoding():
    a, b = candidate(), candidate("C0002", "b")
    req = request(assessed(a, 0.3, 0.2), assessed(b, 0.2, 0.1))
    saved = req.panel.to_dict()
    result = ranks(req)
    assert result[b.candidate_id].pareto_layer == 1
    assert result[a.candidate_id].pareto_layer == 2
    assert se.CalmarComparisonRequest.from_dict(req.to_dict()) == req
    assert req.panel.to_dict() == saved
    assert all(x.metric not in m.DERIVED_RANKING_METRICS for row in req.panel.rows for x in row.diagnostics)
    old = m.CandidateComparisonRequest(req.candidates, req.targets, req.panel,
                                      replace(policy(), formula_version="research-ranking-v4"))
    old_result = se.compare_candidates(old)
    assert all(x.pareto_layer == 1 for x in old_result.rows)
    assert set(old.to_dict()) == {"type", "candidates", "targets", "panel", "policy"}
    assert m.CandidateComparisonRequest.from_dict(old.to_dict()).sha256 == old.sha256
    assert {x.value for x in m.ASSESSMENT_METRICS} == {
        "FREQUENCY_COVERAGE", "FULL_SAMPLE_FREQUENCY", "BENCHMARK_POSITIVE_YEAR_FREQUENCY",
        "NET_ANNUAL_RETURN", "DRAWDOWN_MAGNITUDE", "FREQUENCY_MEDIAN", "FREQUENCY_Q10",
        "PARAMETER_RETURN_DEGRADATION", "PARAMETER_DRAWDOWN_DEGRADATION", "PARAMETER_RETURN_Q10",
        "PARAMETER_DRAWDOWN_Q90", "ROLLING_EXCESS_Q10", "STRESS_ANNUAL_LOSS", "PROFIT_CONCENTRATION",
    }


def test_first_within_layer_metric_is_calmar_quantile_not_return_quantile():
    a, b = candidate(), candidate("C0002", "b")
    req = request(assessed(a, point_values=((0.4, 0.2),) * 8),
                  assessed(b, point_values=((0.3, 0.1),) * 8))
    result = se.compare_candidates(req)
    assert result.rows[0].candidate == b
    assert result.pairs[0].decisive_metric is m.ResearchMetric.PARAMETER_CALMAR_Q10
    assert result.pairs[0].relation is m.PairwiseRelation.B_BEFORE_A
    old = m.CandidateComparisonRequest(req.candidates, req.targets, req.panel,
                                      replace(policy(), formula_version="research-ranking-v4"))
    assert se.compare_candidates(old).rows[0].candidate == a


def test_quantile_uses_each_point_ratio_and_never_ratio_of_separate_quantiles():
    who = candidate()
    geometry = design(who, center=0.0)
    pairs = ((0.2, 0.1), (0.5, 0.5), (0.6, 0.2), (0.6, 0.1), (0.6, 0.2))
    req = request(assessed(who, geometry=geometry, point_values=pairs))
    result = se.compare_candidates(req).rows[0]
    assert result.bin_values[0] == 14000  # Q10([2, 1, 3, 6, 3]) = 1.4.
    wrong = np.quantile([r for r, _ in pairs], .1) / np.quantile([d for _, d in pairs], .9)
    assert result.bin_values[0] != int(Decimal(str(wrong)) / Decimal("0.0001"))


def test_common_contract_accepts_actual_boundary_shapes_and_retains_every_signature():
    a, b = candidate(), candidate("C0002", "b")
    req = request(assessed(a, geometry=design(a, 0.0)), assessed(b, geometry=design(b, 0.5)))
    assert [x.point_count for x in req.parameter_designs] == [5, 8]
    signatures = tuple(x.comparison_sha256 for x in req.parameter_designs)
    assert len(set(signatures)) == 2
    result = se.compare_candidates(req)
    assert all(x.status is m.ComparisonStatus.TIED for x in result.rows)
    assert tuple(x.comparison_sha256 for x in req.parameter_designs) == signatures
    old = m.CandidateComparisonRequest(req.candidates, req.targets, req.panel,
                                      replace(policy(), formula_version="research-ranking-v4"))
    assert all("PARAMETER_METHODS_DIFFER" in x.reasons for x in se.compare_candidates(old).rows)


@pytest.mark.parametrize("field,value", [
    ("relative", .04), ("unit", "percent"), ("upper", 2.0), ("path", ("other",)),
    ("mapping", "c" * 64), ("feasibility_hash", "d" * 64),
])
def test_common_contract_rejects_rule_or_parameter_semantics_mismatch(field, value):
    a, b = candidate(), candidate("C0002", "b")
    with pytest.raises(ValueError, match="relative scale|semantics|domains|units|mapping"):
        request(assessed(a), assessed(b, geometry=design(b, **{field: value})))


@pytest.mark.parametrize("field", ["design_sha256", "space_sha256", "comparison_sha256", "dimension", "prescribed_points"])
def test_common_contract_authenticates_each_actual_design_against_panel(field):
    item, geometry = assessed(candidate())
    value = 99 if field in ("dimension", "prescribed_points") else "e" * 64
    changes = {field: value}
    if field == "prescribed_points":
        changes["valid_points"] = value
    item = replace(item, parameter_context=replace(item.parameter_context, **changes))
    with pytest.raises(ValueError, match="design differs"):
        request((item, geometry))


def test_missing_design_and_forged_constraint_pruning_cannot_claim_common_comparability():
    item, geometry = assessed(candidate())
    req = request((item, geometry))
    with pytest.raises(ValueError, match="complete parameter designs"):
        replace(req, parameter_designs=())
    pruned = design(candidate(), feasibility=lambda values: values[0].value <= 1.0)
    assert pruned.constraint_exclusions
    with pytest.raises(ValueError, match="without constraint exclusions"):
        request(assessed(candidate(), geometry=pruned))
    encoded = geometry.to_dict()
    encoded["points"].pop()
    with pytest.raises(ValueError):
        se.ParameterNeighborhoodDesign.from_dict(encoded)


@pytest.mark.parametrize("amount", [None, 0.04])
def test_zero_center_requires_its_explicit_matching_absolute_scale(amount):
    who = candidate()
    scales = () if amount is None else (se.ZeroCenterAbsoluteLimit("g", se.AbsoluteChangeLimit(amount)),)
    contract = se.CommonNeighborhoodComparisonContract(se.RelativeChangeLimit(.05), scales)
    with pytest.raises(ValueError, match="zero-center axis"):
        request(assessed(who, geometry=design(who, 0.0)), contract=contract)


@pytest.mark.parametrize("missing", [(None, .1), (.2, None)])
def test_missing_point_performance_is_rejected_by_public_facts(missing):
    with pytest.raises(TypeError):
        assessed(candidate(), point_values=(missing,) + ((.2, .1),) * 7)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_point_inputs_are_rejected_by_public_facts(invalid):
    with pytest.raises(TypeError):
        assessed(candidate(), point_values=((invalid, .1),) + ((.2, .1),) * 7)


@pytest.mark.parametrize("which", ["center", "point"])
@pytest.mark.parametrize("dd", [0.0, 1e-12])
def test_unavailable_calmar_cannot_become_a_ranked_value(which, dd):
    item = assessed(candidate(), dd=dd) if which == "center" else assessed(
        candidate(), point_values=((0.2, dd),) + ((0.2, .1),) * 7,
    )
    result = se.compare_candidates(request(item)).rows[0]
    assert result.status is m.ComparisonStatus.INCOMPARABLE
    assert result.pareto_layer is None
    if which == "point":
        assert result.bin_values[0] is None
        assert "PARAMETER_CALMAR_Q10:INCOMPLETE_OR_UNAVAILABLE_PARAMETER_CALMAR" in result.reasons


def test_missing_point_keeps_original_design_denominator_and_unavailable_quantile():
    item, geometry = assessed(candidate())
    item = replace(item, parameter_performances=item.parameter_performances[:-1],
        parameter_context=replace(item.parameter_context, valid_points=7),
        diagnostics=tuple(replace(x, value=None, status=m.DiagnosticStatus.INSUFFICIENT_DATA, reason="missing")
                          if x.metric in PARAMETER_METRICS else x for x in item.diagnostics))
    req = request((item, geometry))
    result = se.compare_candidates(req).rows[0]
    assert result.status is m.ComparisonStatus.INCOMPARABLE and result.bin_values[0] is None
    assert req.parameter_designs[0].point_count == req.panel.rows[0].parameter_context.prescribed_points == 8


def test_overflowing_point_calmar_is_unavailable_without_nonfinite_output():
    item = assessed(candidate(), point_values=((1e308, .01),) + ((.2, .1),) * 7)
    result = se.compare_candidates(request(item)).rows[0]
    assert result.bin_values[0] is None and result.status is m.ComparisonStatus.INCOMPARABLE
    assert m.CandidateComparison.from_dict(se.compare_candidates(request(item)).to_dict())


def test_formally_inapplicable_parameters_keep_new_floor_metrics_without_fabricated_values():
    a, b = candidate(), candidate("C0002", "b")
    req = request(assessed(a, geometry=design(a, empty=True)),
                  assessed(b, point_values=((-0.2, .1),) * 8))
    result = ranks(req)
    floor = result[a.candidate_id]
    assert floor.floor_metrics == (m.ResearchMetric.PARAMETER_CALMAR_Q10, m.ResearchMetric.PARAMETER_DRAWDOWN_Q90)
    assert floor.bin_values[:2] == (None, None)
    assert result[b.candidate_id].rank_min < floor.rank_min
    assert m.CandidateComparison.from_dict(se.compare_candidates(req).to_dict())


def test_v5_requires_its_explicit_request_and_matching_bins_while_targets_stay_unchanged():
    req = request(assessed(candidate()))
    with pytest.raises(ValueError, match="CalmarComparisonRequest"):
        m.CandidateComparisonRequest(req.candidates, req.targets, req.panel, req.policy)
    with pytest.raises(ValueError, match="ranking bins differ"):
        replace(req.policy, bins=policy().bins)
    assert req.policy.pareto_metrics == (m.ResearchMetric.NET_CALMAR, m.ResearchMetric.DRAWDOWN_MAGNITUDE)
    assert req.policy.ranking_metrics[1:] == (*m.WITHIN_LAYER_METRICS[1:], m.ResearchMetric.FREQUENCY_MEDIAN)
    assert se.compare_candidates(req).rows[0].target_checks[0].target == req.targets.requirements[0]
