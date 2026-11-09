"""Calmar acceptance derives authenticated performance without changing saved panels."""

from dataclasses import replace
from math import nextafter

import pytest

from strategy_evaluator import (
    BenchmarkBound, ResearchMetric, ResearchTarget,
)
from strategy_evaluator import research_models as m
from test_research_assessment import candidate, compare, row
from test_research_comparison_v2 import benchmark


def calmar_target(**changes):
    return ResearchTarget(
        "calmar", ResearchMetric.NET_CALMAR, lower=BenchmarkBound(1.25, False),
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


@pytest.mark.risk_cases('SE-05-C01')
def test_strict_calmar_decimal_boundary_and_exact_source_identity():
    annual = 0.125
    expected = m.TargetCheckStatus.FAILED
    item = calmar_row(annual)
    saved = item.to_dict()
    result = check(item)
    got = result.target_checks[0]
    assert got.status is expected
    assert got.observed == annual
    assert got.resolved_lower == 0.125
    assert got.evaluation_ids == ("a" * 64, "b" * 64)
    assert result.acceptance_status is expected
    assert m.TargetCheck.from_dict(got.to_dict()) == got
    assert item.to_dict() == saved
    assert not any(x.metric is ResearchMetric.NET_CALMAR for x in item.diagnostics)


@pytest.mark.risk_cases('SE-05-C02')
def test_signed_calmar_multiple_has_no_implicit_positive_return_gate():
    base = -0.1
    annual = -0.12
    expected = m.TargetCheckStatus.PASSED
    assert check(calmar_row(annual, benchmark_return=base)).acceptance_status is expected


@pytest.mark.parametrize('drawdown', [
    pytest.param(0.0, id='SE-05-C03'),
    pytest.param(1e-12, id='SE-05-C04'),
])
@pytest.mark.risk_cases('SE-05-C03', 'SE-05-C04')
def test_zero_or_near_zero_drawdown_never_becomes_finite_calmar(drawdown):
    side = "strategy"
    changes = {"drawdown" if side == "strategy" else "benchmark_dd": drawdown}
    result = check(calmar_row(**changes))
    got = result.target_checks[0]
    assert got.status is m.TargetCheckStatus.INDETERMINATE
    assert result.acceptance_status is m.TargetCheckStatus.INDETERMINATE
    assert got.reason == ("CALMAR_UNAVAILABLE" if side == "strategy" else "MISSING_BOUND_BENCHMARK")
    if side == "strategy":
        assert got.observed is None


@pytest.mark.risk_cases('SE-05-C05')
def test_SE_05_C05_next_drawdown_above_cutoff_is_available():
    value = nextafter(1e-12, 1.0)
    got = check(calmar_row(drawdown=value)).target_checks[0]
    assert got.status is m.TargetCheckStatus.PASSED
    assert got.observed == .15 / value

@pytest.mark.risk_cases('SE-05-C06')
def test_SE_05_C06_calmar_overflow_stays_unavailable():
    got = check(calmar_row(annual=1e308, drawdown=.01)).target_checks[0]
    assert got.status is m.TargetCheckStatus.INDETERMINATE
    assert got.observed is None
