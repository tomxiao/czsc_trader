from dataclasses import replace
from datetime import date, timedelta
import math

import numpy as np
import pytest

from strategy_evaluator import (
    assess_candidates,
    compare_candidates,
    pareto_layers,
    CandidateProfile,
)
from strategy_evaluator import research_models as m


def candidate(name="C001", digest="a"):
    return m.AssessmentCandidate(f"S900-{name}", digest * 64)


def evidence(who=None, profits=(10.0, 20.0), scenario="standard", parent=None):
    who = who or candidate()
    cash = 1000.0
    rows, fills, cycles = [], [], []
    for i, profit in enumerate(profits):
        buy = (date(2026, 1, 1) + timedelta(days=i * 2)).isoformat()
        sell = (date(2026, 1, 2) + timedelta(days=i * 2)).isoformat()
        cycle = str(i)
        cash -= 100.0
        fills.append(m.AssessmentFill(cycle, buy, m.FillSide.BUY, 10, 10.0, 0.0))
        rows.append(m.AccountPoint(buy, cash, 10, 10.0, cash + 100.0))
        cash += 100.0 + profit
        fills.append(m.AssessmentFill(cycle, sell, m.FillSide.SELL, 10, 10.0 + profit / 10, 0.0))
        rows.append(m.AccountPoint(sell, cash, 0, 10.0 + profit / 10, cash))
        cycles.append(m.ClosedCycle(cycle, sell))
    return m.AssessmentEvidence(
        who,
        "20261001_S900_EX01",
        "1" * 32,
        m.digest((who, scenario, profits)),
        "b" * 64,
        "c" * 64,
        "d" * 64,
        "full",
        scenario,
        "test-v1",
        m.EvaluationScenarioContext(
            0.001 if scenario == "pressure" else 0.0005,
            "STRESS" if scenario == "pressure" else "FORMAL",
            "BuyHold",
            "BUYHOLD",
        ),
        1000.0,
        1000.0,
        0,
        2,
        tuple(rows),
        tuple(fills),
        tuple(cycles),
        tuple(1000.0 for _ in rows),
        parent,
        "e" * 64 if parent else None,
        "f" * 64,
        m.AssessmentDerivationKind.PARAMETERS if parent else None,
    )


def protocol():
    return m.SelfCheckProtocol(
        "1",
        "full",
        "standard",
        "pressure",
        2,
        1,
        m.QuantileMethod.LINEAR,
        1,
        1,
        40,
        2,
        11,
        1e-8,
        pbo_blocks=2,
    )


def request():
    center, child = candidate(), candidate("C002", "b")
    base = evidence(center)
    neighbor = evidence(child, (5.0, 10.0), parent=center)
    stress = evidence(center, (20.0, 30.0), "pressure")
    return m.CandidateAssessmentRequest(
        (center,),
        protocol(),
        (m.PerturbationLink(center, child, 1.0, "e" * 64),),
        (base, neighbor, stress),
    )


def values(panel):
    return {x.metric: x for x in panel.rows[0].diagnostics}


def test_assessment_formulas_and_reproducible_bootstrap():
    req = request()
    panel = assess_candidates(req)
    assert assess_candidates(req) == panel
    got = values(panel)
    annual = 1.03**63 - 1
    neighbor_annual = 1.015**63 - 1
    assert got[m.ResearchMetric.NET_ANNUAL_RETURN].value == pytest.approx(annual)
    assert got[m.ResearchMetric.PARAMETER_RETURN_DEGRADATION].value == pytest.approx(
        annual - neighbor_annual
    )
    assert got[m.ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION].value == 0
    assert got[m.ResearchMetric.STRESS_ANNUAL_LOSS].value == pytest.approx(annual - (1.05**63 - 1))
    assert got[m.ResearchMetric.STRESS_ANNUAL_LOSS].value < 0
    assert got[m.ResearchMetric.PROFIT_CONCENTRATION].value == pytest.approx(20 / 30)
    assert got[m.ResearchMetric.ROLLING_EXCESS_Q10].value == pytest.approx(0.01)
    assert panel.rows[0].uncertainty.status is m.DiagnosticStatus.AVAILABLE
    assert len(panel.rows) == 1  # children never become centers automatically
    assert m.AssessmentPanel.from_dict(panel.to_dict()) == panel


def test_rolling_excess_uses_paired_windows_and_weights_are_explicit():
    req = request()
    base = replace(req.evidence[0], benchmark_equity=(1000.0, 1005.0, 1020.0, 1030.0))
    req = replace(req, evidence=(base, *req.evidence[1:]))
    expected = np.quantile(
        [1010 / 1000 - 1005 / 1000, 1010 / 1000 - 1020 / 1000, 1030 / 1010 - 1030 / 1005], 0.1
    )
    assert values(assess_candidates(req))[
        m.ResearchMetric.ROLLING_EXCESS_Q10
    ].value == pytest.approx(expected)
    child = candidate("C003", "c")
    extra = evidence(child, (1.0, 2.0), parent=req.centers[0])
    links = (*req.perturbations, m.PerturbationLink(req.centers[0], child, 9.0, "e" * 64))
    with pytest.raises(ValueError, match="weights"):
        replace(req, perturbations=links)
    weighted = replace(
        req,
        protocol=replace(req.protocol, quantile_method=m.QuantileMethod.WEIGHTED_ECDF),
        perturbations=links,
        evidence=(*req.evidence, extra),
    )
    metric = values(assess_candidates(weighted))[m.ResearchMetric.PARAMETER_RETURN_DEGRADATION]
    assert metric.value == pytest.approx((1.03**63 - 1) - (1.003**63 - 1))


def test_concentration_uses_cash_profit_top_ceil_and_fees():
    base = evidence(profits=tuple(float(x) for x in range(1, 12)))
    req = replace(request(), evidence=(base,))
    assert values(assess_candidates(req))[
        m.ResearchMetric.PROFIT_CONCENTRATION
    ].value == pytest.approx(21 / 66)
    fee = replace(base.fills[0], fees=1.0)
    after_fee = replace(
        base,
        fills=(fee, *base.fills[1:]),
        account=tuple(
            replace(row, cash=row.cash - 1.0, equity=row.equity - 1.0) for row in base.account
        ),
    )
    # The first cycle's profit becomes zero; only ten positive cycles remain.
    assert values(assess_candidates(replace(req, evidence=(after_fee,))))[
        m.ResearchMetric.PROFIT_CONCENTRATION
    ].value == pytest.approx(11 / 65)


def test_no_wins_missing_benchmark_failed_reconciliation_and_missing_attempts():
    req = request()
    losing = replace(evidence(profits=(-1.0, -2.0)), benchmark_equity=())
    panel = assess_candidates(replace(req, evidence=(losing,)))
    got = values(panel)
    assert got[m.ResearchMetric.PROFIT_CONCENTRATION].status is m.DiagnosticStatus.NOT_APPLICABLE
    assert got[m.ResearchMetric.ROLLING_EXCESS_Q10].value is None
    broken = replace(losing, account=(replace(losing.account[0], cash=2000.0), *losing.account[1:]))
    assert (
        values(assess_candidates(replace(req, evidence=(broken,))))[
            m.ResearchMetric.PROFIT_CONCENTRATION
        ].status
        is m.DiagnosticStatus.FAILED
    )
    missing = m.IncompleteEvaluation(
        req.centers[0],
        "full",
        "standard",
        m.IncompleteEvaluationStatus.FAILED,
        "evaluation failed",
        "20261001_S900_EX01",
        "2" * 32,
    )
    empty = assess_candidates(replace(req, evidence=(), incomplete=(missing,)))
    assert all(x.value is None for x in empty.rows[0].diagnostics)
    assert "FAILED" in empty.rows[0].coverage_gaps[0]


def test_open_cycles_are_reconciled_without_inventing_closed_profit():
    base = evidence()
    # Last cycle remains open at the terminal market price.
    open_row = replace(base.account[-1], cash=base.account[-2].cash, quantity=10)
    open_row = replace(open_row, equity=open_row.cash + open_row.quantity * open_row.close)
    current = replace(
        base,
        fills=base.fills[:-1],
        closed_cycles=base.closed_cycles[:-1],
        account=(*base.account[:-1], open_row),
    )
    result = values(assess_candidates(replace(request(), evidence=(current,))))
    assert result[m.ResearchMetric.PROFIT_CONCENTRATION].value == 1.0
    initial = replace(
        current,
        opening_quantity=10,
        opening_cash=900.0,
        account=tuple(
            replace(
                r,
                cash=r.cash - 100.0,
                quantity=r.quantity + 10,
                equity=r.equity - 100.0 + 10 * r.close,
            )
            for r in current.account
        ),
    )
    result = values(assess_candidates(replace(request(), evidence=(initial,))))
    assert result[m.ResearchMetric.PROFIT_CONCENTRATION].value == 1.0
    liquidated = replace(
        base,
        opening_cash=900.0,
        opening_quantity=10,
        account=(m.AccountPoint("2026-01-01", 1010.0, 0, 11.0, 1010.0),),
        fills=(m.AssessmentFill("initial", "2026-01-01", m.FillSide.SELL, 10, 11.0, 0.0),),
        closed_cycles=(m.ClosedCycle("initial", "2026-01-01"),),
        benchmark_equity=(),
    )
    result = values(assess_candidates(replace(request(), evidence=(liquidated,))))
    assert (
        result[m.ResearchMetric.PROFIT_CONCENTRATION].reason
        == "OPENING_POSITION_COST_ATTRIBUTION_MISSING"
    )


def test_identity_duplicate_coordinates_and_derivation_are_rejected():
    req = request()
    with pytest.raises(ValueError, match="coordinate"):
        replace(req, evidence=(*req.evidence, req.evidence[0]))
    with pytest.raises(ValueError, match="identity conflict"):
        replace(
            req,
            evidence=(
                replace(
                    req.evidence[0], candidate=replace(req.centers[0], content_sha256="f" * 64)
                ),
            ),
        )
    with pytest.raises(ValueError, match="derivation"):
        assess_candidates(
            replace(
                req,
                evidence=(req.evidence[0], replace(req.evidence[1], derivation_sha256="f" * 64)),
            )
        )
    with pytest.raises(ValueError, match="parameter-only"):
        assess_candidates(
            replace(
                req,
                evidence=(
                    req.evidence[0],
                    replace(req.evidence[1], derivation_kind=m.AssessmentDerivationKind.EXECUTION),
                ),
            )
        )
    with pytest.raises(TypeError):
        replace(req.protocol, rolling_window_days=True)


def policy(resolution=0.01):
    return m.ComparisonPolicy(
        "1",
        tuple(
            m.MetricBinSpec(metric, resolution, 0.0, m.BinRounding.FLOOR)
            for metric in m.RANKING_METRICS
        ),
    )


def row(who, annual=0.1, drawdown=0.1, degradation=0.02, missing=None):
    diagnostics = []
    for metric in m.ResearchMetric:
        value = {
            m.ResearchMetric.NET_ANNUAL_RETURN: annual,
            m.ResearchMetric.DRAWDOWN_MAGNITUDE: drawdown,
            m.ResearchMetric.PARAMETER_RETURN_DEGRADATION: degradation,
            m.ResearchMetric.FREQUENCY_MEDIAN: 5.0,
            m.ResearchMetric.FREQUENCY_Q10: 3.0,
            m.ResearchMetric.PROFIT_CONCENTRATION: 0.3,
        }.get(metric, 0.01)
        unit = (
            m.MetricUnit.CLOSED_CYCLES_PER_WINDOW
            if metric in (m.ResearchMetric.FREQUENCY_MEDIAN, m.ResearchMetric.FREQUENCY_Q10)
            else m.MetricUnit.RATIO
        )
        diagnostics.append(
            m.DiagnosticValue(
                metric,
                unit,
                m.DiagnosticStatus.INSUFFICIENT_DATA
                if missing is metric
                else m.DiagnosticStatus.AVAILABLE,
                None if missing is metric else value,
                "missing" if missing is metric else None,
                (),
            )
        )
    return m.CandidateAssessment(
        who,
        "d" * 64,
        "v1",
        60,
        m.EvaluationScenarioContext(0.0005, "FORMAL", "BuyHold", "BUYHOLD"),
        m.EvaluationScenarioContext(0.001, "STRESS", "BuyHold", "BUYHOLD"),
        tuple(diagnostics),
        m.UncertaintyInterval(m.DiagnosticStatus.NOT_APPLICABLE, None, None, "test"),
        (),
        "f" * 64,
    )


def compare(rows, selected_policy=None, targets=()):
    panel = m.AssessmentPanel("a" * 64, "b" * 64, rows, (), ())
    return compare_candidates(
        m.CandidateComparisonRequest(
            tuple(x.candidate for x in rows),
            m.ResearchTargets(targets, 60),
            panel,
            selected_policy or policy(),
        )
    )


def test_raw_pareto_then_binned_seven_metrics_and_ties():
    a, b, c = candidate(), candidate("C002", "b"), candidate("C003", "c")
    # A strictly dominates C even though A and C fall in the same bins.
    result = compare((row(b, 0.1002, 0.1002), row(c, 0.1000, 0.1002), row(a, 0.1001, 0.1001)))
    by_id = {x.candidate.candidate_id: x for x in result.rows}
    assert by_id[c.candidate_id].pareto_layer == 2
    assert by_id[a.candidate_id].pareto_layer == by_id[b.candidate_id].pareto_layer == 1
    assert by_id[a.candidate_id].rank_in_layer == by_id[b.candidate_id].rank_in_layer == 1
    assert result.rows[0].candidate == a  # ID is only presentation order in an actual tie.
    assert len(result.behavior_groups[0].candidates) == 3


@pytest.mark.parametrize(
    "field,change",
    [
        ("baseline_scenario", {"one_way_cost": 0.001}),
        ("baseline_scenario", {"measurement_tier": "DIAGNOSTIC"}),
        ("baseline_scenario", {"benchmark_kind": "NONE"}),
        ("stress_scenario", {"one_way_cost": 0.002}),
    ],
)
def test_comparison_rejects_different_actual_scenario_contexts(field, change):
    left, right = row(candidate()), row(candidate("C002", "b"))
    right = replace(right, **{field: replace(getattr(right, field), **change)})
    result = compare((left, right))
    assert all(x.status is m.ComparisonStatus.INCOMPARABLE for x in result.rows)
    assert all("EVALUATION_CONTEXTS_DIFFER" in x.reasons for x in result.rows)


def test_neighbor_fee_difference_is_rejected_but_declared_stress_fee_is_allowed():
    req = request()
    neighbor = req.evidence[1]
    req = replace(
        req,
        evidence=(
            req.evidence[0],
            replace(
                neighbor, scenario_context=replace(neighbor.scenario_context, one_way_cost=0.002)
            ),
            req.evidence[2],
        ),
    )
    panel = assess_candidates(req)
    metrics = {x.metric: x for x in panel.rows[0].diagnostics}
    assert metrics[m.ResearchMetric.PARAMETER_RETURN_DEGRADATION].value is None
    assert metrics[m.ResearchMetric.STRESS_ANNUAL_LOSS].status is m.DiagnosticStatus.AVAILABLE


@pytest.mark.parametrize(
    "change",
    [
        {"measurement_tier": "FORMAL"},
        {"measurement_tier": "SCREENING"},
        {"one_way_cost": 0.0005},
        {"one_way_cost": 0.0001},
        {"benchmark_id": "Other"},
        {"benchmark_kind": "OTHER"},
    ],
)
def test_stress_pair_rejects_invalid_role_fee_or_benchmark(change):
    req = request()
    stress = req.evidence[-1]
    req = replace(
        req,
        evidence=(
            *req.evidence[:-1],
            replace(stress, scenario_context=replace(stress.scenario_context, **change)),
        ),
    )
    metric = values(assess_candidates(req))[m.ResearchMetric.STRESS_ANNUAL_LOSS]
    assert metric.status is m.DiagnosticStatus.INSUFFICIENT_DATA
    assert metric.reason == "MISSING_OR_INCOMPARABLE_STRESS"


@pytest.mark.parametrize("tier", ["STRESS", "UNKNOWN"])
def test_stress_pair_rejects_invalid_standard_role(tier):
    req = request()
    base = req.evidence[0]
    req = replace(
        req,
        evidence=(
            replace(base, scenario_context=replace(base.scenario_context, measurement_tier=tier)),
            *req.evidence[1:],
        ),
    )
    assert values(assess_candidates(req))[m.ResearchMetric.STRESS_ANNUAL_LOSS].value is None


@pytest.mark.parametrize("fee", [True, -0.1, 1.0, float("nan")])
def test_scenario_contract_rejects_invalid_fees(fee):
    with pytest.raises((TypeError, ValueError)):
        m.EvaluationScenarioContext(fee, "FORMAL", "BuyHold", "BUYHOLD")


def test_available_diagnostics_require_explicit_scenario_context():
    complete = row(candidate())
    with pytest.raises(ValueError, match="baseline scenario"):
        replace(complete, baseline_scenario=None, context_sha256=None)
    with pytest.raises(ValueError, match="stress scenario"):
        replace(complete, stress_scenario=None)


def test_missing_and_unmet_candidates_remain_in_output_frequency_is_not_ranked():
    a, b, c = candidate(), candidate("C002", "b"), candidate("C003", "c")
    result = compare(
        (row(a, 0.1), row(b, 0.01), row(c, 0.2, missing=m.ResearchMetric.PROFIT_CONCENTRATION)),
        targets=(m.ResearchTarget(m.ResearchMetric.NET_ANNUAL_RETURN, lower=0.05),),
    )
    statuses = {x.candidate: x.status for x in result.rows}
    assert statuses == {
        a: m.ComparisonStatus.RANKED,
        b: m.ComparisonStatus.TARGET_NOT_MET,
        c: m.ComparisonStatus.INCOMPARABLE,
    }
    first, second = row(a), row(b)
    second = replace(
        second,
        diagnostics=tuple(
            replace(x, value=9.0) if x.metric is m.ResearchMetric.FREQUENCY_MEDIAN else x
            for x in second.diagnostics
        ),
    )
    frequency = (m.ResearchTarget(m.ResearchMetric.FREQUENCY_MEDIAN, lower=4.0, upper=10.0),)
    result = compare((first, second), targets=frequency)
    assert [x.rank_in_layer for x in result.rows] == [1, 1]
    rejected_context = compare(
        (row(a, 0.1), replace(row(b, 0.01), context_sha256="e" * 64)),
        targets=(m.ResearchTarget(m.ResearchMetric.NET_ANNUAL_RETURN, lower=0.05),),
    )
    assert rejected_context.rows[0].status is m.ComparisonStatus.RANKED


def test_sensitivity_does_not_rewrite_baseline_and_context_mismatch_is_explicit():
    a, b = candidate(), candidate("C002", "b")
    rows = (row(a, 0.11, 0.2), row(b, 0.10, 0.1))
    variant = m.ComparisonVariant("swap_return_drawdown", policy().bins, 0)
    result = compare(rows, replace(policy(), sensitivities=(variant,)))
    assert result.rows[0].candidate == a
    assert result.sensitivities[0].rows[0].candidate == b
    mismatch = compare((rows[0], replace(rows[1], context_sha256="e" * 64)))
    assert all(x.status is m.ComparisonStatus.INCOMPARABLE for x in mismatch.rows)
    fine = tuple(replace(x, resolution=0.001) for x in policy().bins)
    result = compare(
        (row(a, 0.1001, 0.1001, 0.0299), row(b, 0.1002, 0.1002, 0.0201)),
        replace(policy(), sensitivities=(m.ComparisonVariant("finer", fine),)),
    )
    assert result.rows[0].rank_in_layer == result.rows[1].rank_in_layer
    assert result.sensitivities[0].rows[0].candidate == b


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True])
def test_pareto_rejects_nonfinite_and_boolean_metrics(bad):
    with pytest.raises(ValueError):
        pareto_layers((CandidateProfile("a", True, True, (("x", bad),)),))


def test_pareto_rejects_intersection_comparison_and_duplicates():
    profile = CandidateProfile("a", True, True, (("x", 1.0), ("y", 2.0)))
    with pytest.raises(ValueError, match="match exactly"):
        pareto_layers((profile, replace(profile, candidate_id="b", worst_scores=(("x", 1.0),))))
    with pytest.raises(ValueError, match="duplicate"):
        pareto_layers((profile, profile))
    with pytest.raises(ValueError, match="unique"):
        pareto_layers((replace(profile, worst_scores=(("x", 1.0), ("x", 2.0))),))
    assert pareto_layers(()) == ()


def test_family_statistics_bind_return_matrix_and_do_not_affect_ranks():
    req = request()
    matrix = tuple(
        tuple(
            float(e.account[i].equity / (e.initial_cash if i == 0 else e.account[i - 1].equity) - 1)
            for e in req.evidence[:2]
        )
        for i in range(4)
    )
    family = m.FamilyReturnEvidence(
        tuple(e.candidate for e in req.evidence[:2]),
        tuple(x.session for x in req.evidence[0].account),
        matrix,
        req.centers[0],
        12,
        ("shared development samples",),
    )
    panel = assess_candidates(replace(req, family_returns=family))
    assert {x.name for x in panel.family_diagnostics} == {"PBO", "DSR_RAW", "DSR_EFFECTIVE"}
    assert panel.family_limitations == family.limitations
    assert all(x.value is None or math.isfinite(x.value) for x in panel.family_diagnostics)
    tampered = replace(family, returns=((0.1, 0.2), *family.returns[1:]))
    with pytest.raises(ValueError, match="returns differ"):
        assess_candidates(replace(req, family_returns=tampered))
