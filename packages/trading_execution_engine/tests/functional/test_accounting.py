"""Economic postings shared by daily and interval execution models."""
import pytest
from strategy_runtime.contracts import OrderSide
from trading_execution_engine import (AccountBalances, CashDisposition, post_fill,
    accrue_receivable, settle_receivable, post_split)


def test_confirmed_fill_event_and_settlement_postings_preserve_account_identity():
    initial = AccountBalances(1000., 0)
    bought = post_fill(initial, side=OrderSide.BUY, quantity=9, price=100., fee_rate=.001)
    assert bought.balances == AccountBalances(99.10000000000002, 9)
    assert initial == AccountBalances(1000., 0)
    split = post_split(bought.balances, 2.)
    assert split.quantity == 18 and split.equity(50.) == bought.balances.equity(100.)
    dividend = accrue_receivable(split, 1.8)
    sold = post_fill(dividend, side=OrderSide.SELL, quantity=18, price=50., fee_rate=.001,
        disposition=CashDisposition.RECEIVABLE)
    assert sold.balances.cash == dividend.cash and sold.balances.quantity == 0
    assert sold.balances.receivable == dividend.receivable + sold.net
    settled = settle_receivable(sold.balances, sold.balances.receivable)
    assert settled.receivable == 0. and settled.equity(50.) == sold.balances.equity(50.)
    immediate = post_fill(dividend, side=OrderSide.SELL, quantity=18, price=50., fee_rate=.001)
    assert immediate.balances.equity(50.) == sold.balances.equity(50.)


@pytest.mark.parametrize("quantity", [True, 1.5, 0, -1])
def test_posting_rejects_non_integer_or_nonpositive_quantity(quantity):
    with pytest.raises(ValueError, match="positive integer"):
        post_fill(AccountBalances(100., 0), side=OrderSide.BUY, quantity=quantity, price=1., fee_rate=0.)


def test_posting_rejects_policy_free_invalid_facts():
    balances = AccountBalances(100., 1)
    with pytest.raises(TypeError, match="OrderSide"):
        post_fill(balances, side="BUY", quantity=1, price=1., fee_rate=0.)
    with pytest.raises(ValueError, match="holdings"):
        post_fill(balances, side=OrderSide.SELL, quantity=2, price=1., fee_rate=0.)
    with pytest.raises(ValueError, match="buy fill"):
        post_fill(balances, side=OrderSide.BUY, quantity=1, price=1., fee_rate=0.,
            disposition=CashDisposition.RECEIVABLE)
    with pytest.raises(ValueError, match="fractional"):
        post_split(balances, 1.5)
    with pytest.raises(ValueError, match="finite"):
        accrue_receivable(balances, float("nan"))
