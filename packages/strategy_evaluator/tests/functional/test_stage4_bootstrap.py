"""Stage-four CAGR computation preserves the complete paired-bootstrap semantics."""

import numpy as np
import pytest

from strategy_evaluator import bootstrap


@pytest.mark.parametrize("observations", [2, 7, 257])
@pytest.mark.parametrize("repetitions", [1, 256, 257])
@pytest.mark.parametrize("seed", [0, 13])
def test_cagr_only_matches_full_bootstrap_exactly(observations, repetitions, seed):
    rng = np.random.default_rng(19)
    champion = rng.normal(0.0004, 0.01, observations)
    comparator = rng.normal(0.0002, 0.008, observations)
    kwargs = dict(repetitions=repetitions, mean_block_length=3, seed=seed)
    full = bootstrap.paired_stationary_bootstrap(
        champion, comparator, champion_id="center", comparator_id="benchmark", **kwargs,
    )
    assert bootstrap._paired_stationary_bootstrap_cagr(champion, comparator, **kwargs) == full.cagr


def test_original_bootstrap_rng_and_chunk_boundary_golden():
    champion = np.array([.02, -.015, .003, .01, -.008, .004])
    comparator = np.array([.005, -.006, .001, .003, -.002, .002])
    # Recorded from the pre-optimization implementation with its original RNG draw order.
    expected = bootstrap.BootstrapMetric(
        "cagr", "higher_is_better", 0.6375937001183745,
        -0.2944588980149083, 6.0238015605639434, 0.7976653696498055,
    )
    kwargs = dict(repetitions=257, mean_block_length=3, seed=13)
    assert bootstrap._paired_stationary_bootstrap_cagr(champion, comparator, **kwargs) == expected
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


@pytest.mark.parametrize("champion", [np.zeros(7), np.full(7, .01)])
def test_cagr_only_does_not_calculate_sample_drawdown_or_calmar(monkeypatch, champion):
    comparator = np.zeros(7)
    kwargs = dict(repetitions=257, mean_block_length=1, seed=13)
    expected = bootstrap.paired_stationary_bootstrap(
        champion, comparator, champion_id="center", comparator_id="benchmark", **kwargs,
    ).cagr

    def unused(*args):
        raise AssertionError("sampled drawdown and Calmar must not be computed")

    monkeypatch.setattr(bootstrap, "_row_metrics", unused)
    assert bootstrap._paired_stationary_bootstrap_cagr(champion, comparator, **kwargs) == expected


@pytest.mark.parametrize("champion,comparator,kwargs", [
    ([.01, .02], [.01], {}),
    ([[.01, .02]], [[.01, .02]], {}),
    ([], [], {}),
    ([.01], [.01], {}),
    ([.01, float("nan")], [.01, .02], {}),
    ([.01, .02], [.01, float("inf")], {}),
    ([.01, -1.], [.01, .02], {}),
    ([.01, .02], [.01, -1.01], {}),
    ([.01, .02], [.01, .02], {"repetitions": 0}),
    ([.01, .02], [.01, .02], {"mean_block_length": 0}),
    ([.01, .02], [.01, .02], {"seed": -1}),
])
def test_cagr_only_rejects_same_boundaries(champion, comparator, kwargs):
    with pytest.raises(ValueError) as original:
        bootstrap.paired_stationary_bootstrap(
            champion, comparator, champion_id="center", comparator_id="benchmark", **kwargs,
        )
    with pytest.raises(ValueError) as optimized:
        bootstrap._paired_stationary_bootstrap_cagr(champion, comparator, **kwargs)
    assert str(optimized.value) == str(original.value)
