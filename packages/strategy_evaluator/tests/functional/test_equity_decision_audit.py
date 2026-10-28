"""Formal plans and all order outcomes are independently auditable."""
import copy

import pytest

from strategy_evaluator.equity import audit_equity_account
from test_equity_assessment import ledger


@pytest.mark.parametrize("field,value", [("target", -1), ("target", True), ("target", float("nan")),
    ("quantity", 999), ("quantity", 10.0), ("side", "SELL"), ("reference_price", 11.), ("limit_price", 999.)])
def test_formal_decision_rejects_target_budget_and_price_tampering(field, value):
    account = ledger(1)
    account["decisions"][0][field] = value
    with pytest.raises(ValueError):
        audit_equity_account(**account, decision_contract="FORMAL_V2")


def expired():
    account = ledger(1)
    account["bars"] = account["bars"][:2]
    for field in ("decisions", "orders", "account_points", "constraints"):
        account[field] = account[field][:1]
    for field in ("fills", "actions", "trades", "action_facts"):
        account[field] = []
    account["constraints"][0]["Tradable"] = False
    account["orders"][0].update(status="EXPIRED", reason="NOT_TRADABLE")
    account["account_points"][0].update(cash=10000., quantity=0, equity=10000., receivable=0.)
    return account


@pytest.mark.parametrize("mutation", ["orphan", "duplicate", "interval", "quantity", "reason", "missing", "false-expiry"])
def test_formal_expired_orders_require_actual_decision_and_execution_facts(mutation):
    account = expired()
    assert audit_equity_account(**account, decision_contract="FORMAL_V2").closed_cycles == 0
    if mutation == "orphan":
        account["orders"][0]["decision_id"] = "absent"
    elif mutation == "duplicate":
        account["orders"].append({**account["orders"][0], "order_id": "duplicate"})
    elif mutation == "interval":
        account["orders"][0]["valid_end"] = "2026-10-02T14:30:00+00:00"
    elif mutation == "quantity":
        account["orders"][0]["quantity"] = 999
    elif mutation == "reason":
        account["orders"][0]["reason"] = "INSUFFICIENT_CASH"
    elif mutation == "missing":
        account["orders"] = []
    else:
        account["constraints"][0]["Tradable"] = True
    with pytest.raises(ValueError):
        audit_equity_account(**account, decision_contract="FORMAL_V2")


def test_formal_split_reference_uses_post_event_snapshot_and_cycle_time_is_verified():
    account = ledger(1)
    assert audit_equity_account(**account, decision_contract="FORMAL_V2").closed_cycles == 1
    stale = copy.deepcopy(account)
    stale["decisions"][1]["reference_price"] = 8.  # Must be split-adjusted to 4.
    with pytest.raises(ValueError, match="reference price"):
        audit_equity_account(**stale, decision_contract="FORMAL_V2")
    premature = copy.deepcopy(account)
    premature["actions"][0]["account_revision"] = 0
    with pytest.raises(ValueError, match="action time"):
        audit_equity_account(**premature, decision_contract="FORMAL_V2")
    wrong_time = copy.deepcopy(account)
    wrong_time["trades"][0]["exit_at"] = wrong_time["account_points"][-1]["time"]
    with pytest.raises(ValueError, match="cycle interval"):
        audit_equity_account(**wrong_time, decision_contract="FORMAL_V2")
    account["decisions"][0]["target"] = -1
    # Historical calls retain their existing economic audit contract.
    assert audit_equity_account(**account).closed_cycles == 1
