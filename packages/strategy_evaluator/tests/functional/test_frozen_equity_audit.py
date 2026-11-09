"""Formal plans and all order outcomes are independently auditable."""
from datetime import datetime, timedelta

import pytest

from strategy_evaluator.frozen_equity import _audit_frozen_equity_account
from frozen_equity_audit_support import ledger


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


@pytest.mark.risk_cases('SE-29-C01')
def test_gap_order_outcomes_require_actual_execution_facts():
    account = gap_account('MISSING', False)
    assert _audit_frozen_equity_account(**account, decision_contract='FORMAL_V2').total_return == 0
    account['orders'][0]['status'] = 'FILLED'
    with pytest.raises(ValueError):
        _audit_frozen_equity_account(**account, decision_contract='FORMAL_V2')


@pytest.mark.risk_cases('SE-29-C02')
def test_stale_valuation_cannot_be_forged():
    field = "valuation_price_at"
    value = "2026-10-01T14:30:00+00:00"
    account = gap_account()
    account["account_points"][0][field] = value
    with pytest.raises(ValueError):
        _audit_frozen_equity_account(**account, decision_contract="FORMAL_V2")


@pytest.mark.risk_cases('SE-29-C03')
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
    assert _audit_frozen_equity_account(**account, decision_contract="FORMAL_V2").observations == 2
    account["decisions"][0]["signal_status"] = "SUPPRESSED_UNOBSERVED_BAR"
    with pytest.raises(ValueError, match="completed available bars"):
        _audit_frozen_equity_account(**account, decision_contract="FORMAL_V2")
