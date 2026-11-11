"""Acceptance business boundaries, using public SE requests and results."""

from dataclasses import replace
from datetime import date, timedelta

import pytest

from strategy_evaluator import assess_candidates
from strategy_evaluator import research_models as m
from test_research_assessment import candidate, compare, evidence, policy, protocol, row
from test_research_comparison_v2 import benchmark


def coverage_account(days=69, closes=(10, 30, 60)):
    base = evidence()
    cash, quantity = 1000.0, 0
    rows, fills, cycles = [], [], []
    dates = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(days)]
    for i, session in enumerate(dates):
        price = 10.0
        if i + 1 in closes:
            cash -= 100.0
            quantity = 10
            fills.append(m.AssessmentFill(str(i + 1), session, m.FillSide.BUY, 10, price, 0.0))
        if i in closes:
            price = 10.1
            cash += 101.0
            quantity = 0
            fills.append(m.AssessmentFill(str(i), session, m.FillSide.SELL, 10, price, 0.0))
            cycles.append(m.ClosedCycle(str(i), session))
        rows.append(m.AccountPoint(session, cash, quantity, price, cash + quantity * price))
    return replace(
        base,
        account=tuple(rows),
        fills=tuple(fills),
        closed_cycles=tuple(cycles),
        benchmark_equity=(1000.0,) * days,
        frequency_window_days=60,
    )


def coverage_row(days=69, closes=(10, 30, 60)):
    base = coverage_account(days, closes)
    req = m.CandidateAssessmentRequest(
        (base.candidate,), replace(protocol(), frequency_min_closed_cycles=3), (), (base,)
    )
    return assess_candidates(req).rows[0]


def coverage_target():
    return m.FrequencyCoverageTarget("coverage", 60, 3, 9, 10)


@pytest.mark.risk_cases('SE-03-C04')
def test_exact_window_coverage_is_not_interpolated_quantile_and_counts_cross_boundary_exits():
    item = coverage_row()
    facts = item.frequency_coverage
    assert (facts.total_windows, facts.covered_windows) == (10, 9)
    values = {x.metric: x for x in item.diagnostics}
    assert values[m.ResearchMetric.FREQUENCY_Q10].value == pytest.approx(2.9)
    assert values[m.ResearchMetric.FREQUENCY_COVERAGE].value == 0.9
    assert values[m.ResearchMetric.FREQUENCY_COVERAGE].unit is m.MetricUnit.RATIO
    targets = (
        coverage_target(),
        m.ResearchTarget(
            "median", m.ResearchMetric.FREQUENCY_MEDIAN, lower=m.ConstantBound(6.0, True)
        ),
    )
    result = compare(
        (item,), policy(frequency_metric=m.ResearchMetric.FREQUENCY_MEDIAN), targets
    ).rows[0]
    assert result.target_checks[0].status is m.TargetCheckStatus.PASSED
    assert result.target_checks[1].status is m.TargetCheckStatus.FAILED
    assert result.acceptance_status is m.TargetCheckStatus.FAILED
    assert result.pareto_layer is None
    # Both goals are checked even when coverage, rather than median, is the ranking metric.
    second = compare(
        (item,), policy(frequency_metric=m.ResearchMetric.FREQUENCY_COVERAGE), targets
    ).rows[0]
    assert second.target_checks == result.target_checks




def parameter_target(count=32, minimum=26):
    return m.ParameterGroupTarget(
        "parameters",
        count,
        minimum,
        (
            m.ResearchTarget(
                "positive-benchmark",
                m.ResearchMetric.NET_ANNUAL_RETURN,
                lower=m.BenchmarkBound(1.25, True),
                when=m.BenchmarkCondition(
                    m.ResearchMetric.NET_ANNUAL_RETURN, m.ComparisonOperator.GT, 0.0
                ),
            ),
            m.ResearchTarget(
                "nonpositive-benchmark",
                m.ResearchMetric.NET_ANNUAL_RETURN,
                lower=m.ConstantBound(0.0, False),
                when=m.BenchmarkCondition(
                    m.ResearchMetric.NET_ANNUAL_RETURN, m.ComparisonOperator.LE, 0.0
                ),
            ),
            m.ResearchTarget(
                "relative-dd",
                m.ResearchMetric.DRAWDOWN_MAGNITUDE,
                upper=m.BenchmarkBound(0.9, True),
            ),
        ),
        (
            m.ResearchTarget(
                "risk", m.ResearchMetric.DRAWDOWN_MAGNITUDE, upper=m.ConstantBound(0.25, True)
            ),
        ),
    )


def parameter_row(passes=26):
    item = row(candidate())
    return replace(
        item,
        parameter_performances=tuple(
            m.PerformanceFacts(
                candidate(f"C{i + 2:04}", "b"),
                f"{i:064x}",
                item.baseline_scenario,
                0.125 if i < passes else 0.01,
                0.09,
                0.1,
                0.1,
                i,
            )
            for i in range(32)
        ),
    )


def stress_targets():
    args = {"scope": m.TargetScope.STRESS, "one_way_cost": 0.002}
    return (
        m.ResearchTarget(
            "profit", m.ResearchMetric.NET_ANNUAL_RETURN, lower=m.ConstantBound(0.0, False), **args
        ),
        m.ResearchTarget(
            "excess", m.ResearchMetric.NET_ANNUAL_RETURN, lower=m.BenchmarkBound(1.0, False), **args
        ),
        m.ResearchTarget(
            "dd-positive",
            m.ResearchMetric.DRAWDOWN_MAGNITUDE,
            upper=m.BenchmarkBound(1.0, False),
            when=m.BenchmarkCondition(
                m.ResearchMetric.DRAWDOWN_MAGNITUDE, m.ComparisonOperator.GT, 0.0
            ),
            **args,
        ),
        m.ResearchTarget(
            "dd-zero",
            m.ResearchMetric.DRAWDOWN_MAGNITUDE,
            upper=m.ConstantBound(0.0, True),
            when=m.BenchmarkCondition(
                m.ResearchMetric.DRAWDOWN_MAGNITUDE, m.ComparisonOperator.LE, 0.0
            ),
            **args,
        ),
        m.ResearchTarget(
            "dd-cap", m.ResearchMetric.DRAWDOWN_MAGNITUDE, upper=m.ConstantBound(0.25, True), **args
        ),
    )


@pytest.mark.risk_cases('SE-06-C04')
def test_SE_06_C04_stress_acceptance_uses_same_fee_benchmark():
    # Standard benchmark .9 would fail this candidate; its paired pressure
    # benchmark .1 passes. Constant/boundary arithmetic is tested separately.
    item = benchmark(row(candidate()), annual=.9, drawdown=.8)
    scenario = replace(item.stress_scenario, one_way_cost=.002)
    item = replace(item, stress_scenario=scenario,
        stress_performance=m.PerformanceFacts(item.candidate, "e" * 64, scenario, .12, .1, .1, .2))
    result = compare((item,), targets=stress_targets()).rows[0]
    assert result.acceptance_status is m.TargetCheckStatus.PASSED
    assert all(x.evaluation_ids == ("e" * 64,) for x in result.target_checks)




@pytest.mark.risk_cases('SE-04-C05')
def test_SE_04_C05_empty_targets_do_not_claim_acceptance():
    item = benchmark(row(candidate()), annual=.1)
    assert compare((item,), targets=()).rows[0].acceptance_status is m.TargetCheckStatus.INDETERMINATE

@pytest.mark.risk_cases('SE-04-C06')
def test_SE_04_C06_all_inactive_targets_do_not_claim_acceptance():
    item = benchmark(row(candidate()), annual=.1)
    inactive = m.ResearchTarget('inactive', m.ResearchMetric.NET_ANNUAL_RETURN,
        lower=m.ConstantBound(0., False),
        when=m.BenchmarkCondition(m.ResearchMetric.NET_ANNUAL_RETURN, m.ComparisonOperator.LE, 0.))
    result = compare((item,), targets=(inactive,)).rows[0]
    assert result.acceptance_status is m.TargetCheckStatus.INDETERMINATE
    assert result.status is m.ComparisonStatus.INCOMPARABLE
