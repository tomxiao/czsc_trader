"""Current HFQ quotation rounds once to the declared tick."""
from copy import deepcopy

import pytest

from strategy_evaluator.equity import audit_equity_account
from equity_facts_support import manual_ledger, order


def quoted_ledger():
    # 1.991 * 1.01 = 2.01091; floor to .01 = 2.01.
    # 1000 * .5 / 1.991 = 251.13 units; floor to lot 100 = 200.
    return manual_ledger([dict(price=1.991, orders=(order("BUY", 200, 2.01),),
                               target=.5, desired=200)], initial=1000., initial_price=1.991)


@pytest.mark.risk_cases('SE-28-C01')
def test_SE_28_C01_hfq_quote_and_cash_have_independent_expected_values():
    raw = quoted_ledger()
    result = audit_equity_account(**raw, account_contract=4, decision_contract="FORMAL_V4")
    assert result.fees == pytest.approx(.3982)
    assert raw["account_points"][0]["cash"] == pytest.approx(601.4018)
    assert result.total_return == pytest.approx(-.0003982)


@pytest.mark.parametrize('limit', [
    pytest.param(2.02, id='SE-28-C02'),
    pytest.param(2.00, id='SE-28-C03'),
])
@pytest.mark.risk_cases('SE-28-C02', 'SE-28-C03')
def test_one_tick_wrong_quote_rejected(limit):
    raw = deepcopy(quoted_ledger())
    raw["decisions"][0]["plan"]["orders"][0]["limit_price"] = limit
    raw["decisions"][0]["limit_price"] = limit
    raw["orders"][0]["limit_price"] = limit
    with pytest.raises(ValueError, match="independently sized target"):
        audit_equity_account(**raw, account_contract=4, decision_contract="FORMAL_V4")
