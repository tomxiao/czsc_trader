"""EC32: legacy accounting primitives have explicit economic boundaries."""
import pytest
from execution_channels.historical import (
    AccountBalances, accrue_receivable, settle_receivable, post_split,
)


def test_EC32_C01_split_preserves_cash_receivable_and_source():
    original = AccountBalances(99.1, 9, 1.8)
    result = post_split(original, 2.)
    assert result == AccountBalances(99.1, 18, 1.8)
    assert result.equity(50.) == original.equity(100.)
    assert original == AccountBalances(99.1, 9, 1.8)


def test_EC32_C02_fractional_entitlement_is_explicitly_unsupported():
    with pytest.raises(ValueError, match='CORPORATE_ACTION_UNSUPPORTED.*fractional'):
        post_split(AccountBalances(100., 1), 1.5)


def test_EC32_C03_receivable_is_not_cash_and_settlement_preserves_equity():
    original = AccountBalances(100., 9)
    accrued = accrue_receivable(original, 1.8)
    assert accrued == AccountBalances(100., 9, 1.8)
    settled = settle_receivable(accrued, 1.8)
    assert settled == AccountBalances(101.8, 9, 0.)
    assert settled.equity(10.) == accrued.equity(10.)
    assert original == AccountBalances(100., 9)


def test_EC32_C04_nonfinite_receivable_is_rejected():
    with pytest.raises(ValueError, match='finite'):
        accrue_receivable(AccountBalances(100., 1), float('nan'))
