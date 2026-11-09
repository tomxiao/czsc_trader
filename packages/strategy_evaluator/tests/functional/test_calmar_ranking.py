"""Versioned Calmar ranking authenticates complete designs without rewriting old panels."""

from dataclasses import replace
import pytest
from decimal import Decimal

import numpy as np

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


@pytest.mark.risk_cases('SE-11-C02')
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


@pytest.mark.risk_cases('SE-11-C01')
def test_quantile_uses_each_point_ratio_and_never_ratio_of_separate_quantiles():
    who = candidate()
    geometry = design(who, center=0.0)
    pairs = ((0.2, 0.1), (0.5, 0.5), (0.6, 0.2), (0.6, 0.1), (0.6, 0.2))
    req = request(assessed(who, geometry=geometry, point_values=pairs))
    result = se.compare_candidates(req).rows[0]
    assert result.bin_values[0] == 14000  # Q10([2, 1, 3, 6, 3]) = 1.4.
    wrong = np.quantile([r for r, _ in pairs], .1) / np.quantile([d for _, d in pairs], .9)
    assert result.bin_values[0] != int(Decimal(str(wrong)) / Decimal("0.0001"))


@pytest.mark.risk_cases('SE-19-C01')
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
