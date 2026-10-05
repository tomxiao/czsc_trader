"""Public SE statistics own mathematical boundaries and native-thread stability."""

import numpy as np
import pytest
from threadpoolctl import threadpool_limits
from strategy_evaluator import annualized_sharpe, calculate_dsr_bundle, effective_trial_count, performance_metrics


@pytest.mark.parametrize("equity, expected", [([80, 90], -.2), ([80], -.2), ([100], 0.), ([110, 120], 0.), ([80, 120, 90], -.25)])
def test_public_performance_drawdown_includes_initial_capital(equity, expected):
    values = np.array([100., *equity, equity[-1]], dtype=float)
    returns = values[1:] / values[:-1] - 1.
    assert performance_metrics(returns).max_drawdown == pytest.approx(expected)
    with pytest.raises(ValueError, match="greater than -1"):
        performance_metrics(np.array([-1., 0.]))


def test_public_dsr_statistics_are_stable_across_native_thread_counts():
    rng = np.random.default_rng(37)
    common = rng.normal(.001, .01, (128, 1))
    matrix = common + rng.normal(0, .002, (128, 64))
    probabilities = []
    for threads in (1, 2, 8, 16):
        with threadpool_limits(limits=threads):
            sharpes = np.array([annualized_sharpe(column) for column in matrix.T])
            bundle = calculate_dsr_bundle(matrix[:, 0], sharpes, raw_count=64, effective_count=effective_trial_count(matrix))
            probabilities.append(bundle.effective.probability)
    assert all(value is not None and np.isfinite(value) and 0. <= value <= 1. for value in probabilities)
    assert probabilities == pytest.approx([probabilities[0]] * len(probabilities), rel=1e-12, abs=0.)
