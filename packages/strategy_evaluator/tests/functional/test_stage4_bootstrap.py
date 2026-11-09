"""Public stage-four intervals preserve the complete paired-bootstrap semantics."""

from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from strategy_evaluator import bootstrap
from strategy_evaluator.research_assessment import recompute_historical_assessment as assess_candidates
from strategy_evaluator import research_models as m
from test_research_assessment import evidence, protocol


def interval_request(champion, comparator, **kwargs):
    """Small reconciled marked accounts; no execution or data preparation needed."""
    base = evidence()
    equity = base.initial_cash * np.cumprod(1 + champion)
    benchmark = base.initial_cash * np.cumprod(1 + comparator)
    sessions = tuple((date(2025, 1, 1) + timedelta(days=i)).isoformat()
                     for i in range(len(equity)))
    account = tuple(m.AccountPoint(day, 0.0, 1, float(value), float(value))
                    for day, value in zip(sessions, equity, strict=True))
    base = replace(base, account=account, benchmark_equity=tuple(float(x) for x in benchmark),
        fills=(m.AssessmentFill("open", sessions[0], m.FillSide.BUY, 1, base.initial_cash, 0.0),),
        closed_cycles=())
    settings = replace(protocol(), bootstrap_repetitions=kwargs["repetitions"],
                       bootstrap_block_length=kwargs["mean_block_length"], seed=kwargs["seed"])
    request = m.CandidateAssessmentRequest((base.candidate,), settings, (), (base,))
    # Reconstruct both public inputs from the stored account to preserve exact
    # floating-point return semantics without calling private implementation helpers.
    strategy_values = np.r_[base.initial_cash, equity]
    benchmark_values = np.r_[base.initial_cash, benchmark]
    return request, strategy_values[1:] / strategy_values[:-1] - 1, benchmark_values[1:] / benchmark_values[:-1] - 1


def assert_interval(request, expected):
    result = assess_candidates(request).rows[0].uncertainty
    assert result.status is m.DiagnosticStatus.AVAILABLE
    assert (result.lower_95, result.upper_95) == (expected.lower_95, expected.upper_95)
    return result


@pytest.mark.risk_cases('SE-08-C02')
def test_SE_08_C02_stage_four_projection_and_repeat_are_deterministic():
    champion = np.array([.02, -.015, .003, .01, -.008, .004])
    comparator = np.array([.005, -.006, .001, .003, -.002, .002])
    kwargs = dict(repetitions=257, mean_block_length=3, seed=13)
    request, champion, comparator = interval_request(champion, comparator, **kwargs)
    full = bootstrap.paired_stationary_bootstrap(
        champion, comparator, champion_id="center", comparator_id="benchmark", **kwargs)
    first = assert_interval(request, full.cagr)
    assert assert_interval(request, full.cagr) == first


@pytest.mark.risk_cases('SE-08-C01')
def test_original_bootstrap_rng_and_chunk_boundary_golden():
    champion = np.array([.02, -.015, .003, .01, -.008, .004])
    comparator = np.array([.005, -.006, .001, .003, -.002, .002])
    # Recorded from the pre-optimization implementation with its original RNG draw order.
    expected = bootstrap.BootstrapMetric(
        "cagr", "higher_is_better", 0.6375937001183745,
        -0.2944588980149083, 6.0238015605639434, 0.7976653696498055,
    )
    kwargs = dict(repetitions=257, mean_block_length=3, seed=13)
    full = bootstrap.paired_stationary_bootstrap(
        champion, comparator, champion_id="center", comparator_id="benchmark", **kwargs,
    )
    assert full.cagr == expected
    assert full.max_drawdown == bootstrap.BootstrapMetric(
        "max_drawdown", "higher_is_better", -0.009000000000000119,
        -0.020724935999999982, -0.005999999999999894, 0.005836575875486381,
    )
    assert full.calmar == bootstrap.BootstrapMetric(
        "calmar", "higher_is_better", 29.266153552802493,
        -44.49479983145599, 302.98089972126957, 0.8700787401574803,
    )


@pytest.mark.parametrize('champion,comparator,kwargs', [
    pytest.param([.01, .02], [.01], {}, id='SE-08-C03'),
    pytest.param([.01, -1.], [.01, .02], {}, id='SE-08-C04'),
    pytest.param([.01], [.01], {}, id='SE-08-C05'),
    pytest.param([.01, .02], [.01, .02], {"repetitions": 0}, id='SE-08-C06'),
])
@pytest.mark.risk_cases('SE-08-C03', 'SE-08-C04', 'SE-08-C05', 'SE-08-C06')
def test_public_bootstrap_rejects_invalid_return_series_and_protocol(champion, comparator, kwargs):
    with pytest.raises(ValueError):
        bootstrap.paired_stationary_bootstrap(
            champion, comparator, champion_id="center", comparator_id="benchmark", **kwargs,
        )
