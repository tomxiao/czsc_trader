"""Current V4 execution-source facts audited without an execution engine."""
from copy import deepcopy

import pytest

from strategy_evaluator.equity import audit_equity_account
from equity_facts_support import manual_ledger, order


@pytest.fixture
def source():
    return manual_ledger([dict(orders=(order("BUY", 100, 10.1),)),
                          dict(orders=(order("SELL", 100),), target=0.)])


@pytest.mark.parametrize('field', [
    pytest.param("blocked", id='SE-25-C01'),
    pytest.param("volume", id='SE-25-C02'),
    pytest.param("limits", id='SE-25-C03'),
    pytest.param("dangling-order", id='SE-25-C04'),
    pytest.param("wrong-side", id='SE-25-C05'),
    pytest.param("nan-price", id='SE-37-C03'),
    pytest.param("bool-quantity", id='SE-37-C04'),
])
@pytest.mark.risk_cases('SE-25-C01', 'SE-25-C02', 'SE-25-C03', 'SE-25-C04', 'SE-25-C05', 'SE-37-C03', 'SE-37-C04')
def test_execution_and_account_facts_are_independently_authenticated(source, field):
    changed = deepcopy(source)
    if field == "blocked":
        changed["bars"][1]["ExecutionBlocked"] = True
    elif field == "volume":
        changed["bars"][1]["Volume"] = 50.
    elif field == "limits":
        changed["fills"][0]["price"] = 11.
    elif field == "dangling-order":
        changed["fills"][0]["order_id"] = "another-order"
    elif field == "wrong-side":
        changed["fills"][0]["side"] = "SELL"
    elif field == "nan-price":
        changed["fills"][0]["price"] = float("nan")
    else:
        changed["decisions"][0]["plan"]["orders"][0]["quantity"] = True
    with pytest.raises(ValueError):
        audit_equity_account(**changed, account_contract=4, decision_contract="FORMAL_V4")
