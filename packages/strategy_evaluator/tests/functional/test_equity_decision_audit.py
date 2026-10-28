"""Formal plans and all order outcomes are independently auditable."""
import copy
from datetime import datetime, timedelta

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


def gap_account(status="MISSING", blocked=False):
    account = expired()
    account["constraints"][0]["Tradable"] = True
    for bar in account["bars"]:
        bar.update(Amount=10000., BarStatus="OBSERVED", ExecutionBlocked=False)
    bar = account["bars"][-1]
    bar.update(BarStatus=status, ExecutionBlocked=blocked)
    if status == "MISSING":
        for field in ("Open", "High", "Low", "Close", "Volume", "Amount"):
            bar[field] = None
    elif status == "ZERO_VOLUME":
        bar["Volume"], bar["Amount"] = 0., 0.
    reason = "MISSING_BAR" if status == "MISSING" else "ZERO_VOLUME" if status == "ZERO_VOLUME" else "KNOWN_INTERRUPTION"
    account["orders"][0]["reason"] = reason
    account["decisions"][0]["signal_status"] = "EVALUATED"
    stale = status != "OBSERVED"
    point = account["account_points"][0]
    point.update(close=10. if stale else 8., bar_status=status, valuation_stale=stale,
                 valuation_price_at=account["bars"][0 if stale else 1]["Date"], execution_blocked=blocked)
    return account


@pytest.mark.parametrize("status,blocked", [("MISSING", False), ("ZERO_VOLUME", False), ("OBSERVED", True)])
def test_gap_order_outcomes_require_actual_execution_facts(status, blocked):
    account = gap_account(status, blocked)
    assert audit_equity_account(**account, decision_contract="FORMAL_V2").total_return == 0
    account["orders"][0]["reason"] = "NOT_TRADABLE"
    with pytest.raises(ValueError, match="order outcome"):
        audit_equity_account(**account, decision_contract="FORMAL_V2")


@pytest.mark.parametrize("field,value", [("valuation_stale", False), ("close", 8.),
    ("valuation_price_at", "2026-10-01T14:30:00+00:00"), ("bar_status", "OBSERVED")])
def test_stale_valuation_cannot_be_forged(field, value):
    account = gap_account()
    account["account_points"][0][field] = value
    with pytest.raises(ValueError):
        audit_equity_account(**account, decision_contract="FORMAL_V2")


def test_gap_signal_suppression_occurs_only_after_missing_bar_is_observable():
    account = gap_account()
    previous = account["bars"][-1]
    start = previous["Date"]
    end = (datetime.fromisoformat(start) + timedelta(minutes=30)).isoformat()
    bar = {**account["bars"][0], "Date": end, "BarStart": start, "AvailableDate": end}
    account["bars"].append(bar)
    decision = {**account["decisions"][0], "decision_id": "next", "execution_start": start,
                "execution_end": end, "decision_at": start, "portfolio_revision": 1,
                "signal_status": "SUPPRESSED_UNOBSERVED_BAR", "side": "WAIT", "quantity": 0,
                "limit_price": None, "target": 0.}
    account["decisions"].append(decision)
    account["constraints"].append({**account["constraints"][0], "Date": start, "AvailableDate": start})
    account["account_points"].append({**account["account_points"][0], "time": end, "decision_id": "next",
        "account_revision": 1, "bar_status": "OBSERVED", "valuation_stale": False, "valuation_price_at": end})
    assert audit_equity_account(**account, decision_contract="FORMAL_V2").observations == 2
    account["decisions"][0]["signal_status"] = "SUPPRESSED_UNOBSERVED_BAR"
    with pytest.raises(ValueError, match="completed available bars"):
        audit_equity_account(**account, decision_contract="FORMAL_V2")


def test_gap_stale_mark_adjusts_for_split_without_changing_price_observation_time():
    account = ledger(1)
    account["bars"] = account["bars"][:3]
    for field in ("decisions", "account_points", "constraints", "actions", "action_facts"):
        account[field] = account[field][:2]
    account["orders"], account["fills"], account["trades"] = account["orders"][:1], account["fills"][:1], []
    for bar in account["bars"]:
        bar.update(Amount=10000., BarStatus="OBSERVED", ExecutionBlocked=False)
    for decision in account["decisions"]:
        decision["signal_status"] = "EVALUATED"
    for point in account["account_points"]:
        point.update(bar_status="OBSERVED", valuation_stale=False, valuation_price_at=point["time"], execution_blocked=False)
    for field in ("Open", "High", "Low", "Close", "Volume", "Amount"):
        account["bars"][-1][field] = None
    account["bars"][-1]["BarStatus"] = "MISSING"
    point = account["account_points"][-1]
    point.update(close=4., equity=9982., bar_status="MISSING", valuation_stale=True,
                 valuation_price_at=account["bars"][-2]["Date"])
    assert audit_equity_account(**account, decision_contract="FORMAL_V2").total_return == pytest.approx(-.0018)
