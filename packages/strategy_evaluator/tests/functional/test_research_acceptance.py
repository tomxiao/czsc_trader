"""Acceptance business boundaries, using public SE requests and results."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import localcontext

import pytest

from strategy_evaluator.research_assessment import recompute_historical_assessment as assess_candidates
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


@pytest.mark.parametrize(
    "days,closes,expected,total,covered",
    [
        (59, (10, 30), m.TargetCheckStatus.INDETERMINATE, 0, 0),
        (60, (1, 30, 59), m.TargetCheckStatus.PASSED, 1, 1),
        (69, (10, 30, 61), m.TargetCheckStatus.FAILED, 10, 8),
    ],
)
def test_frequency_window_boundaries(days, closes, expected, total, covered):
    item = coverage_row(days, closes)
    checked = compare((item,), targets=(coverage_target(),)).rows[0].target_checks[0]
    assert checked.status is expected
    assert (checked.facts.total_windows, checked.facts.covered_windows) == (total, covered)


def test_frequency_definition_mismatch_and_median_pass_do_not_hide_coverage_failure():
    item = row(candidate())
    item = replace(
        item,
        frequency_coverage=m.FrequencyCoverageFacts(60, 3, 10, 8, ("a" * 64,)),
        diagnostics=tuple(
            replace(x, value=6.0) if x.metric is m.ResearchMetric.FREQUENCY_MEDIAN else x
            for x in item.diagnostics
        ),
    )
    median = m.ResearchTarget(
        "median", m.ResearchMetric.FREQUENCY_MEDIAN, lower=m.ConstantBound(6.0, True)
    )
    result = compare((item,), targets=(median, coverage_target())).rows[0]
    assert [x.status for x in result.target_checks] == [
        m.TargetCheckStatus.PASSED,
        m.TargetCheckStatus.FAILED,
    ]
    changed = replace(coverage_target(), minimum_closed_cycles=4)
    assert (
        compare((item,), targets=(changed,)).rows[0].acceptance_status
        is m.TargetCheckStatus.INDETERMINATE
    )


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


@pytest.mark.parametrize(
    "passes,expected", [(25, m.TargetCheckStatus.FAILED), (26, m.TargetCheckStatus.PASSED)]
)
def test_parameter_joint_count_exact_boundary(passes, expected):
    result = compare((parameter_row(passes),), targets=(parameter_target(),)).rows[0]
    check = result.target_checks[0]
    assert check.status is result.acceptance_status is expected
    assert (check.valid_points, check.joint_passes) == (32, passes)
    assert m.ParameterGroupCheck.from_dict(check.to_dict()) == check
    assert (result.pareto_layer is not None) == (expected is m.TargetCheckStatus.PASSED)


def test_parameter_same_point_intersection_and_all_point_risk():
    item = parameter_row(26)
    # Return passes first 26; drawdown passes last 26; their intersection is only 20.
    crossed = replace(
        item,
        parameter_performances=tuple(
            replace(x, drawdown=0.1) if x.point_index < 6 else x
            for x in item.parameter_performances
        ),
    )
    check = compare((crossed,), targets=(parameter_target(),)).rows[0].target_checks[0]
    assert check.joint_passes == 20 and check.status is m.TargetCheckStatus.FAILED
    tail = replace(
        item,
        parameter_performances=(
            *item.parameter_performances[:-1],
            replace(item.parameter_performances[-1], drawdown=0.250001),
        ),
    )
    check = compare((tail,), targets=(parameter_target(),)).rows[0].target_checks[0]
    assert check.joint_passes == 26 and check.reason == "PARAMETER_ALL_POINT_TARGET_NOT_MET"
    equal = replace(
        tail,
        parameter_performances=(
            *tail.parameter_performances[:-1],
            replace(tail.parameter_performances[-1], drawdown=0.25),
        ),
    )
    assert (
        compare((equal,), targets=(parameter_target(),)).rows[0].acceptance_status
        is m.TargetCheckStatus.PASSED
    )


def test_incomplete_parameter_group_does_not_shrink_denominator_or_pass_without_benchmark():
    item = parameter_row()
    for_missing = replace(item, parameter_performances=item.parameter_performances[:-1])
    checked = compare((for_missing,), targets=(parameter_target(),)).rows[0].target_checks[0]
    assert checked.valid_points == 31 and checked.status is m.TargetCheckStatus.INDETERMINATE
    missing = replace(
        item,
        parameter_performances=tuple(
            replace(x, benchmark_return=None, benchmark_drawdown=None)
            for x in item.parameter_performances
        ),
    )
    assert (
        compare((missing,), targets=(parameter_target(),)).rows[0].acceptance_status
        is m.TargetCheckStatus.INDETERMINATE
    )
    with pytest.raises(ValueError, match="duplicate"):
        replace(item, parameter_performances=(item.parameter_performances[0],) * 32)


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


@pytest.mark.parametrize(
    "annual,dd,base_return,base_dd,expected",
    [
        (0.12, 0.1, 0.1, 0.2, m.TargetCheckStatus.PASSED),
        (0.09, 0.1, 0.1, 0.2, m.TargetCheckStatus.FAILED),
        (0.1, 0.1, 0.1, 0.2, m.TargetCheckStatus.FAILED),
        (0.0, 0.1, -0.1, 0.2, m.TargetCheckStatus.FAILED),
        (0.12, 0.2, 0.1, 0.2, m.TargetCheckStatus.FAILED),
        (0.12, 0.0, 0.1, 0.0, m.TargetCheckStatus.PASSED),
        (0.12, 0.001, 0.1, 0.0, m.TargetCheckStatus.FAILED),
        (0.12, 0.25, 0.1, 0.3, m.TargetCheckStatus.PASSED),
        (0.12, 0.250001, 0.1, 0.3, m.TargetCheckStatus.FAILED),
    ],
)
def test_stress_uses_own_benchmark_and_strict_conditions(
    annual, dd, base_return, base_dd, expected
):
    item = benchmark(row(candidate()), annual=0.9, drawdown=0.8)
    scenario = replace(item.stress_scenario, one_way_cost=0.002)
    item = replace(
        item,
        stress_scenario=scenario,
        stress_performance=m.PerformanceFacts(
            item.candidate, "e" * 64, scenario, annual, dd, base_return, base_dd
        ),
    )
    result = compare((item,), targets=stress_targets()).rows[0]
    assert result.acceptance_status is expected
    assert all(x.evaluation_ids == ("e" * 64,) for x in result.target_checks)


def test_pressure_loss_alone_or_wrong_fee_cannot_certify_acceptance():
    item = row(candidate())
    assert (
        compare((item,), targets=stress_targets()).rows[0].acceptance_status
        is m.TargetCheckStatus.INDETERMINATE
    )
    facts = m.PerformanceFacts(item.candidate, "e" * 64, item.stress_scenario, 0.2, 0.0, 0.1, 0.1)
    item = replace(item, stress_performance=facts)
    assert (
        compare((item,), targets=stress_targets()).rows[0].acceptance_status
        is m.TargetCheckStatus.INDETERMINATE
    )


@pytest.mark.parametrize(
    "rb,rs,expected",
    [
        (0.1, 0.15, m.TargetCheckStatus.PASSED),
        (0.1, 0.149999, m.TargetCheckStatus.FAILED),
    ],
)
def test_center_approved_return_branches_and_decimal_multiplier_boundaries(rb, rs, expected):
    targets = (
        m.ResearchTarget(
            "positive",
            m.ResearchMetric.NET_ANNUAL_RETURN,
            lower=m.BenchmarkBound(1.5, True),
            when=m.BenchmarkCondition(
                m.ResearchMetric.NET_ANNUAL_RETURN, m.ComparisonOperator.GT, 0.0
            ),
        ),
        m.ResearchTarget(
            "nonpositive",
            m.ResearchMetric.NET_ANNUAL_RETURN,
            lower=m.ConstantBound(0.0, False),
            when=m.BenchmarkCondition(
                m.ResearchMetric.NET_ANNUAL_RETURN, m.ComparisonOperator.LE, 0.0
            ),
        ),
    )
    assert (
        compare((benchmark(row(candidate(), annual=rs), annual=rb),), targets=targets)
        .rows[0]
        .acceptance_status
        is expected
    )
    with localcontext() as context:
        context.prec = 2
        assert (
            compare((benchmark(row(candidate(), annual=rs), annual=rb),), targets=targets)
            .rows[0]
            .acceptance_status
            is expected
        )


def test_new_contracts_reject_illegal_types_scopes_and_old_formulas():
    with pytest.raises(TypeError):
        replace(coverage_target(), minimum_numerator=True)
    with pytest.raises(ValueError):
        replace(coverage_target(), minimum_denominator=0)
    with pytest.raises(ValueError):
        replace(parameter_target(), minimum_joint_passes=33)
    with pytest.raises(ValueError):
        m.ResearchTarget(
            "stress-frequency",
            m.ResearchMetric.FREQUENCY_MEDIAN,
            lower=m.ConstantBound(1.0, True),
            scope=m.TargetScope.STRESS,
        )
    with pytest.raises(ValueError, match="unsupported assessment"):
        m.AssessmentPanel("a" * 64, "b" * 64, (), (), (), formula_version="research-assessment-v4")
    with pytest.raises(ValueError, match="unsupported ranking"):
        replace(policy(), formula_version="research-ranking-v2")
    encoded = coverage_target().to_dict()
    del encoded["minimum_closed_cycles"]
    with pytest.raises(ValueError, match="fields differ"):
        m.FrequencyCoverageTarget.from_dict(encoded)


def test_empty_or_only_inactive_conditions_cannot_claim_acceptance():
    item = benchmark(row(candidate()), annual=0.1)
    assert (
        compare((item,), targets=()).rows[0].acceptance_status is m.TargetCheckStatus.INDETERMINATE
    )
    inactive = m.ResearchTarget(
        "inactive",
        m.ResearchMetric.NET_ANNUAL_RETURN,
        lower=m.ConstantBound(0.0, False),
        when=m.BenchmarkCondition(m.ResearchMetric.NET_ANNUAL_RETURN, m.ComparisonOperator.LE, 0.0),
    )
    result = compare((item,), targets=(inactive,)).rows[0]
    assert result.acceptance_status is m.TargetCheckStatus.INDETERMINATE
    assert result.status is m.ComparisonStatus.INCOMPARABLE
