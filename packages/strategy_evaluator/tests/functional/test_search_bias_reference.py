"""Small independent reference answers for PBO and effective trial count."""
from dataclasses import replace
from math import log

import numpy as np
import pytest

from strategy_evaluator import ReturnMatrixEvidence
from strategy_evaluator.search_bias import cscv_pbo, deflated_sharpe_ratio


def matrix():
    # Binary-exact fractions make the four mixed-block Sharpe ties exact.
    # Blocks 0/1 favour A; blocks 2/3 favour B. Six 2-of-4 partitions.
    return ReturnMatrixEvidence(tuple(f"2026-10-{day:02}" for day in range(1, 9)),
        ("A", "B"), ((.03125, -.015625), (-.015625, .015625)) * 2
        + ((-.015625, .03125), (.015625, -.015625)) * 2, "")


@pytest.mark.risk_cases('SE-09-C01')
def test_SE_09_C01_cscv_matches_six_hand_enumerated_partitions():
    result = cscv_pbo(matrix(), block_count=4)
    assert [(s.training_blocks, s.selected_candidate, s.validation_rank) for s in result.splits] == [
        ((0, 1), "A", 2), ((0, 2), "A", 1), ((0, 3), "A", 1),
        ((1, 2), "A", 1), ((1, 3), "A", 1), ((2, 3), "B", 2),
    ]
    assert result.pbo == pytest.approx(1 / 3)
    assert result.selection_frequency == (("A", 5), ("B", 1))
    assert result.median_validation_percentile == 1.
    assert result.median_logit == pytest.approx(log(3))


@pytest.mark.risk_cases('SE-09-C02')
def test_SE_09_C02_odd_cscv_block_count_rejected():
    with pytest.raises(ValueError, match="even"):
        cscv_pbo(matrix(), block_count=3)


@pytest.mark.risk_cases('SE-09-C03')
def test_SE_09_C03_duplicate_candidate_identity_rejected():
    with pytest.raises(ValueError, match="unique"):
        cscv_pbo(replace(matrix(), candidate_ids=("A", "A")), block_count=4)


@pytest.mark.risk_cases('SE-09-C04')
def test_SE_09_C04_dsr_requires_dispersed_trials():
    with pytest.raises(ValueError, match="positive dispersion"):
        deflated_sharpe_ratio(np.array([.01, -.01, .02]), np.array([1., 1.]), 2.)
    assert cscv_pbo(matrix(), block_count=4).pbo == pytest.approx(1/3)
