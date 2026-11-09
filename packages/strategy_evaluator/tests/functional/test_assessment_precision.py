"""Public SE statistics own mathematical boundaries and native-thread stability."""

import numpy as np
import pytest
from strategy_evaluator import performance_metrics


@pytest.mark.risk_cases('SE-01-C01')
def test_SE_01_C01_drawdown_includes_initial_capital():
    # Mark 100 -> 90 -> 95. No recorded observation exceeds initial capital.
    returns = np.array([-.1, 95. / 90. - 1.])
    assert performance_metrics(returns).max_drawdown == pytest.approx(-.1)
