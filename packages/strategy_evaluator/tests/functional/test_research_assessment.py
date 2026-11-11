from dataclasses import replace
from datetime import date, timedelta
import math

import pytest

from strategy_evaluator import research_models as m
from strategy_evaluator.research_assessment import (
    assess_candidates,
    compare_candidates,
)
from strategy_evaluator import research_assessment as assessment


def candidate(name="C0001", digest="a"):
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
            "a" * 64,
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
    return m.NeighborhoodSelfCheckProtocol(
        "1",
        "full",
        "standard",
        "pressure",
        2,
        1,
        m.QuantileMethod.LINEAR,
        1,
        40,
        2,
        11,
        1e-8,
        m.ParameterNeighborhoodProtocol(),
        pbo_blocks=2,
    )


def request():
    from strategy_evaluator import (build_parameter_neighborhood_design, ParameterNeighborhoodRequest,
        ParameterNeighborhoodSpace, ParameterAxis, IntegerDomain, BoundedLocalStep, RelativeChangeLimit)
    center, child = candidate(), candidate("C0002", "b")
    design = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(center,
        protocol().parameter_protocol, ParameterNeighborhoodSpace((ParameterAxis('hold', 20,
            IntegerDomain(20, 21), BoundedLocalStep(RelativeChangeLimit(.05)), ('hold',), 'sessions'),),
            'a' * 64, 'b' * 64)), feasibility=lambda _: True).design
    base = evidence(center)
    neighbor = replace(evidence(child, (5.0, 10.0), parent=center), parameter_point=design.bind_point(0))
    stress = evidence(center, (20.0, 30.0), "pressure")
    return m.CandidateAssessmentRequest(
        (center,),
        protocol(),
        (m.PerturbationLink(center, child, 1.0, "e" * 64, design.bind_point(0)),),
        (base, neighbor, stress),
        parameter_designs=(design,),
    )


def values(panel):
    return {x.metric: x for x in panel.rows[0].diagnostics}


@pytest.mark.risk_cases('SE-07-C01')
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


@pytest.mark.risk_cases('SE-07-C02')
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


@pytest.mark.risk_cases('SE-07-C03')
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


def policy(resolution=0.01, frequency_metric=m.ResearchMetric.FULL_SAMPLE_FREQUENCY):
    return m.ComparisonPolicy(
        "1",
        tuple(
            (
                m.MetricBinSpec(metric, resolution, 0.0, m.BinRounding.FLOOR)
                for metric in (*m.BENCHMARK_METRICS, *m.WITHIN_LAYER_METRICS, frequency_metric)
            )
        ),
        pareto_basis=m.ParetoBasis.RAW,
        missing_evidence_policy=m.MissingEvidencePolicy.REQUIRE_COMPLETE,
        formula_version="research-ranking-v4",
    )


def row(who, annual=0.1, drawdown=0.1, degradation=0.02, missing=None):
    diagnostics = []
    for metric in m.ASSESSMENT_METRICS:
        value = {
            m.ResearchMetric.NET_ANNUAL_RETURN: annual,
            m.ResearchMetric.DRAWDOWN_MAGNITUDE: drawdown,
            m.ResearchMetric.PARAMETER_RETURN_DEGRADATION: degradation,
            m.ResearchMetric.PARAMETER_RETURN_Q10: annual - degradation,
            m.ResearchMetric.PARAMETER_DRAWDOWN_Q90: drawdown + 0.01,
            m.ResearchMetric.FREQUENCY_MEDIAN: 5.0,
            m.ResearchMetric.FREQUENCY_Q10: 3.0,
            m.ResearchMetric.PROFIT_CONCENTRATION: 0.3,
        }.get(metric, 0.01)
        unit = (
            m.MetricUnit.CLOSED_CYCLES_PER_WINDOW
            if metric in m.FREQUENCY_METRICS and metric is not m.ResearchMetric.FREQUENCY_COVERAGE
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
        m.EvaluationScenarioContext(0.0005, "FORMAL", "BuyHold", "BUYHOLD", "a" * 64),
        m.EvaluationScenarioContext(0.001, "STRESS", "BuyHold", "BUYHOLD", "a" * 64),
        tuple(diagnostics),
        m.UncertaintyInterval(m.DiagnosticStatus.NOT_APPLICABLE, None, None, "test"),
        (),
        "f" * 64,
        benchmark=m.BenchmarkAssessment(
            tuple(
                (
                    m.DiagnosticValue(
                        metric,
                        m.MetricUnit.RATIO,
                        m.DiagnosticStatus.AVAILABLE,
                        0.05,
                        None,
                        ("a" * 64,),
                    )
                    for metric in m.BENCHMARK_METRICS
                )
            )
        ),
        parameter_context=m.ParameterNeighborhoodContext(
            m.ParameterNeighborhoodProtocol(), "a" * 64, "b" * 64, 2, 32, 32, "c" * 64
        ),
    )


def compare(rows, selected_policy=None, targets=(), *, current=False):
    panel = m.AssessmentPanel("a" * 64, "b" * 64, rows, (), (),
        formula_version="research-assessment-v7")
    selected_policy = selected_policy or policy()
    selected_policy = replace(selected_policy, formula_version="research-ranking-v4")
    return compare_candidates(
        m.CandidateComparisonRequest(
            tuple(x.candidate for x in rows),
            m.ResearchTargets(targets, rows[0].frequency_window_days or 60),
            panel,
            selected_policy,
        )
    )


@pytest.mark.risk_cases('SE-10-C02')
def test_raw_pareto_then_binned_robustness_frequency_and_ties():
    a, b, c = candidate(), candidate("C0002", "b"), candidate("C0003", "c")
    # A strictly dominates C even though A and C fall in the same bins.
    result = compare((row(b, 0.1002, 0.1002), row(c, 0.1000, 0.1002), row(a, 0.1001, 0.1001)))
    by_id = {x.candidate.candidate_id: x for x in result.rows}
    assert by_id[c.candidate_id].pareto_layer == 2
    assert by_id[a.candidate_id].pareto_layer == by_id[b.candidate_id].pareto_layer == 1
    assert by_id[a.candidate_id].rank_in_layer == by_id[b.candidate_id].rank_in_layer == 1
    assert result.rows[0].candidate == a  # ID is only presentation order in an actual tie.
    assert len(result.behavior_groups[0].candidates) == 3


@pytest.mark.parametrize('field,change', [
    pytest.param("baseline_scenario", {"one_way_cost": 0.001}, id='SE-19-C05'),
    pytest.param("baseline_scenario", {"benchmark_contract_sha256": "f" * 64}, id='SE-19-C06'),
])
@pytest.mark.risk_cases('SE-19-C05', 'SE-19-C06')
def test_comparison_rejects_different_actual_scenario_contexts(field, change):
    left, right = row(candidate()), row(candidate("C0002", "b"))
    right = replace(right, **{field: replace(getattr(right, field), **change)})
    result = compare((left, right))
    assert all(x.status is m.ComparisonStatus.INCOMPARABLE for x in result.rows)
    assert all("EVALUATION_CONTEXTS_DIFFER" in x.reasons for x in result.rows)


@pytest.mark.parametrize('change', [
    pytest.param({"one_way_cost": 0.0005}, id='SE-06-C02'),
    pytest.param({"benchmark_contract_sha256": "b" * 64}, id='SE-06-C03'),
])
@pytest.mark.risk_cases('SE-06-C02', 'SE-06-C03')
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


def family_request():
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
    return replace(req, family_returns=family)


@pytest.mark.risk_cases('SE-09-C05')
def test_family_statistics_bind_return_matrix_and_do_not_affect_ranks():
    req = family_request()
    family = req.family_returns
    from strategy_evaluator.search_bias import effective_trial_count
    import numpy as np
    left, right = zip(*family.returns)
    mean_a, mean_b = sum(left)/len(left), sum(right)/len(right)
    a = tuple(x-mean_a for x in left)
    b = tuple(x-mean_b for x in right)
    rho = sum(x*y for x,y in zip(a,b)) / math.sqrt(sum(x*x for x in a)*sum(y*y for y in b))
    assert effective_trial_count(np.asarray(family.returns)) == pytest.approx(2/(1+rho*rho))
    panel = assess_candidates(req)
    assert {x.name for x in panel.family_diagnostics} == {"PBO", "DSR_RAW", "DSR_EFFECTIVE"}
    assert panel.family_limitations == family.limitations
    assert all(x.value is None or math.isfinite(x.value) for x in panel.family_diagnostics)
    assert panel.rows == assess_candidates(replace(req, family_returns=None)).rows






@pytest.mark.risk_cases('SE-09-C06')
def test_family_dsr_unexpected_error_is_not_converted_to_diagnostic(monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError("unexpected implementation failure")

    monkeypatch.setattr(assessment, "calculate_dsr_bundle", failed)
    with pytest.raises(RuntimeError, match="unexpected implementation failure"):
        assess_candidates(family_request())


@pytest.mark.risk_cases('SE-06-C01')
def test_SE_06_C01_stress_annual_loss_is_signed():
    panel = assess_candidates(request())
    actual = values(panel)[m.ResearchMetric.STRESS_ANNUAL_LOSS]
    assert actual.status is m.DiagnosticStatus.AVAILABLE
    # Standard ends 1030, higher-cost pressure ends 1050 over four days.
    assert actual.value == pytest.approx((1.03 ** 63 - 1) - (1.05 ** 63 - 1))
    assert actual.value < 0.
