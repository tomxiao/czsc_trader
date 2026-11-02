"""Calmar acceptance derives authenticated performance without changing saved panels."""

from dataclasses import replace
from math import nextafter

import pytest

from strategy_evaluator import (
    BenchmarkBound, BenchmarkCondition, ComparisonOperator, ConstantBound,
    ResearchMetric, ResearchTarget,
)
from strategy_evaluator import research_models as m
from test_research_assessment import candidate, compare, row
from test_research_comparison_v2 import benchmark


def calmar_target(**changes):
    return ResearchTarget(
        "calmar", ResearchMetric.NET_CALMAR, lower=BenchmarkBound(1.5, False),
        one_way_cost=0.001, **changes,
    )


def calmar_row(annual=0.15, drawdown=1.0, benchmark_return=0.1, benchmark_dd=1.0):
    item = benchmark(
        row(candidate()),
        annual=benchmark_return, drawdown=benchmark_dd,
    )
    return replace(
        item,
        baseline_scenario=replace(item.baseline_scenario, one_way_cost=0.001),
        parameter_context=m.ParameterNeighborhoodContext(
            m.ParameterNeighborhoodProtocol(), "a" * 64, "b" * 64, 2, 32, 32, "c" * 64,
        ),
        diagnostics=tuple(replace(
            x, evaluation_ids=("a" * 64,),
            value=annual if x.metric is ResearchMetric.NET_ANNUAL_RETURN else (
                drawdown if x.metric is ResearchMetric.DRAWDOWN_MAGNITUDE else x.value
            ),
        ) for x in item.diagnostics),
    )


def check(item, target=None):
    return compare((item,), targets=(target or calmar_target(),), current=True).rows[0]


@pytest.mark.parametrize(
    "annual,expected",
    [
        pytest.param(nextafter(0.15, 0.0), m.TargetCheckStatus.FAILED, id="below"),
        pytest.param(0.15, m.TargetCheckStatus.FAILED, id="exact-decimal-multiple"),
        pytest.param(nextafter(0.15, 1.0), m.TargetCheckStatus.PASSED, id="above"),
    ],
)
def test_strict_calmar_decimal_boundary_and_exact_source_identity(annual, expected):
    item = calmar_row(annual)
    saved = item.to_dict()
    result = check(item)
    got = result.target_checks[0]
    assert got.status is expected
    assert got.observed == annual
    assert got.resolved_lower == 0.15
    assert got.evaluation_ids == ("a" * 64, "b" * 64)
    assert result.acceptance_status is expected
    assert m.TargetCheck.from_dict(got.to_dict()) == got
    assert item.to_dict() == saved
    assert not any(x.metric is ResearchMetric.NET_CALMAR for x in item.diagnostics)


@pytest.mark.parametrize(
    "base,annual,expected",
    [
        pytest.param(0.0, 0.0, m.TargetCheckStatus.FAILED, id="zero-equal"),
        pytest.param(0.0, 0.01, m.TargetCheckStatus.PASSED, id="zero-positive"),
        pytest.param(-0.1, -0.15, m.TargetCheckStatus.FAILED, id="negative-equal"),
        pytest.param(-0.1, -0.14, m.TargetCheckStatus.PASSED, id="negative-literal-multiple"),
    ],
)
def test_signed_calmar_multiple_has_no_implicit_positive_return_gate(base, annual, expected):
    assert check(calmar_row(annual, benchmark_return=base)).acceptance_status is expected


def test_calmar_constant_and_benchmark_conditions_are_explicit_and_roundtrip():
    target = ResearchTarget(
        "nonpositive", ResearchMetric.NET_CALMAR, lower=ConstantBound(0.0, False),
        when=BenchmarkCondition(ResearchMetric.NET_CALMAR, ComparisonOperator.LE, 0.0),
        one_way_cost=0.001,
    )
    assert ResearchTarget.from_dict(target.to_dict()) == target
    inactive = check(calmar_row(0.1), target).target_checks[0]
    assert inactive.status is m.TargetCheckStatus.NOT_APPLICABLE
    assert inactive.condition_observed == 0.1
    active = check(calmar_row(0.1, benchmark_return=-0.2), target).target_checks[0]
    assert active.status is m.TargetCheckStatus.PASSED
    assert active.condition_observed == -0.2
    return_goal = replace(target, metric=ResearchMetric.NET_ANNUAL_RETURN)
    assert check(calmar_row(0.1, benchmark_return=-0.2), return_goal).acceptance_status is m.TargetCheckStatus.PASSED


@pytest.mark.parametrize("side", ["strategy", "benchmark"])
@pytest.mark.parametrize("drawdown", [0.0, 1e-12, nextafter(1e-12, 0.0)])
def test_zero_or_near_zero_drawdown_never_becomes_finite_calmar(side, drawdown):
    changes = {"drawdown" if side == "strategy" else "benchmark_dd": drawdown}
    result = check(calmar_row(**changes))
    got = result.target_checks[0]
    assert got.status is m.TargetCheckStatus.INDETERMINATE
    assert result.acceptance_status is m.TargetCheckStatus.INDETERMINATE
    assert got.reason == ("CALMAR_UNAVAILABLE" if side == "strategy" else "MISSING_BOUND_BENCHMARK")
    if side == "strategy":
        assert got.observed is None


def test_just_above_zero_drawdown_cutoff_is_available_and_quotient_overflow_is_not():
    value = nextafter(1e-12, 1.0)
    available = check(calmar_row(drawdown=value)).target_checks[0]
    assert available.status is m.TargetCheckStatus.PASSED
    assert available.observed == 0.15 / value
    overflow = check(calmar_row(annual=1e308, drawdown=0.01)).target_checks[0]
    assert overflow.status is m.TargetCheckStatus.INDETERMINATE
    assert overflow.observed is None


@pytest.mark.parametrize("side", ["strategy", "benchmark"])
@pytest.mark.parametrize("metric", [ResearchMetric.NET_ANNUAL_RETURN, ResearchMetric.DRAWDOWN_MAGNITUDE])
def test_missing_input_performance_cannot_pass_calmar(side, metric):
    item = calmar_row()
    diagnostics = item.diagnostics if side == "strategy" else item.benchmark.diagnostics
    changed = tuple(
        replace(x, value=None, status=m.DiagnosticStatus.INSUFFICIENT_DATA, reason="missing")
        if x.metric is metric else x for x in diagnostics
    )
    item = replace(item, diagnostics=changed) if side == "strategy" else replace(
        item, benchmark=replace(item.benchmark, diagnostics=changed),
    )
    assert check(item).acceptance_status is m.TargetCheckStatus.INDETERMINATE


def test_missing_benchmark_calmar_condition_and_cost_mismatch_are_explicit():
    target = calmar_target(when=BenchmarkCondition(ResearchMetric.NET_CALMAR, ComparisonOperator.GT, 0.0))
    got = check(calmar_row(benchmark_dd=0.0), target).target_checks[0]
    assert got.status is m.TargetCheckStatus.INDETERMINATE
    assert got.reason == "MISSING_CONDITION_BENCHMARK"
    item = calmar_row(0.2)
    item = replace(item, baseline_scenario=replace(item.baseline_scenario, one_way_cost=0.002))
    assert check(item).target_checks[0].reason == "TARGET_COST_DIFFERS_OR_MISSING"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_input_is_rejected_before_calmar_evaluation(value):
    with pytest.raises(TypeError):
        calmar_row(annual=value)


@pytest.mark.parametrize("where", ["stress", "group", "neighborhood"])
@pytest.mark.parametrize("condition_only", [False, True])
def test_explicit_calmar_pressure_and_parameter_targets_preserve_strong_types(where, condition_only):
    target = calmar_target()
    if condition_only:
        target = replace(
            target, metric=ResearchMetric.NET_ANNUAL_RETURN,
            when=BenchmarkCondition(ResearchMetric.NET_CALMAR, ComparisonOperator.GT, 0.0),
        )
    if where == "stress":
        result = replace(target, scope=m.TargetScope.STRESS)
    elif where == "group":
        result = m.ParameterGroupTarget("parameters", 1, 1, (target,), (replace(target, target_id="risk"),))
    else:
        result = m.ParameterNeighborhoodTarget("parameters", 13, 16, (target,), (replace(target, target_id="risk"),))
    assert type(result).from_dict(result.to_dict()) == result
