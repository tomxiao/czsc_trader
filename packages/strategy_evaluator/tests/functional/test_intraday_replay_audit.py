"""Public SE audit of a fixed core plus a completed intraday rotation."""
from copy import deepcopy
from math import sqrt

import pytest
from strategy_evaluator import AuditStatus, ReplayEvidence, audit_replay


def _evidence():
    # Independent ledger: core buy costs 4,040; the rotation costs 1,010 and
    # returns 891. Core inventory remains 400 and final cash is 5,841.
    first, last = 9960., 9441.
    returns = (first / 10000. - 1., last / first - 1.)
    mean = sum(returns) / 2
    std = sqrt(sum((value - mean) ** 2 for value in returns))
    return ReplayEvidence(
        strategy_hash="a" * 64, data_hash="b" * 64, initial_cash=10000.,
        evaluation_sessions=("2026-09-17", "2026-09-18"),
        execution_spec={
            "mode": "CORE_EVENT_INTRADAY_ROTATION", "order_semantics": "SRT_PLAN",
            "core_fraction": .5, "lot_size": 100, "fee_rate": .01,
            "entry_checkpoint": "OPEN", "exit_checkpoint": "11:30_CLOSE",
            "t_plus_one_inventory_rotation": True,
        },
        decisions=(
            {"decision_id": "core", "signal_date": "2026-09-16",
             "valid_session": "2026-09-17", "plan_mode": "CORE_SETUP", "action": "BUY"},
            {"decision_id": "rotation", "signal_date": "2026-09-17",
             "valid_session": "2026-09-18", "plan_mode": "CORE_EVENT_INTRADAY_ROTATION",
             "action": "INTRADAY_LONG_OVERLAY"},
        ),
        orders=(
            {"order_id": "core-buy", "decision_id": "core", "signal_date": "2026-09-16",
             "execution_date": "2026-09-17", "side": "BUY", "quantity": 400,
             "checkpoint": "OPEN", "role": "CORE_SETUP", "order_type": "LIMIT",
             "limit_price": 11., "status": "FILLED"},
            {"order_id": "rotation-buy", "decision_id": "rotation", "signal_date": "2026-09-17",
             "execution_date": "2026-09-18", "side": "BUY", "quantity": 100,
             "checkpoint": "OPEN", "role": "OPEN_ROTATION_BUY", "order_type": "LIMIT",
             "limit_price": 11., "status": "FILLED"},
            {"order_id": "rotation-sell", "decision_id": "rotation", "signal_date": "2026-09-17",
             "execution_date": "2026-09-18", "side": "SELL", "quantity": 100,
             "checkpoint": "11:30_CLOSE", "role": "MIDDAY_ROTATION_SELL", "order_type": "MARKET",
             "limit_price": 9., "status": "FILLED"},
        ),
        fills=(
            {"order_id": "core-buy", "decision_id": "core", "cycle_id": "core",
             "fill_time": "2026-09-17T09:35", "side": "BUY", "quantity": 400,
             "price": 10., "fees": 40.},
            {"order_id": "rotation-buy", "decision_id": "rotation", "cycle_id": "rotation",
             "fill_time": "2026-09-18T09:35", "side": "BUY", "quantity": 100,
             "price": 10., "fees": 10.},
            {"order_id": "rotation-sell", "decision_id": "rotation", "cycle_id": "rotation",
             "fill_time": "2026-09-18T11:30", "side": "SELL", "quantity": 100,
             "price": 9., "fees": 9.},
        ),
        account_daily=(
            {"date": "2026-09-17", "cash_before": 10000., "quantity_before": 0,
             "cash": 5960., "quantity": 400, "close": 10., "equity": first},
            {"date": "2026-09-18", "cash_before": 5960., "quantity_before": 400,
             "cash": 5841., "quantity": 400, "close": 9., "equity": last},
        ),
        trades=({"cycle_id": "rotation", "status": "CLOSED", "quantity": 100,
                 "net_return": 891. / 1010. - 1.},),
        metrics={
            "return": -.0559, "max_drawdown": -.0559,
            "calmar": ((last / 10000.) ** 126 - 1.) / .0559,
            "sharpe": sqrt(252.) * mean / std,
            "closed_trades": 1, "win_rate": 0.,
            "win_loss_ratio": None, "win_loss_ratio_status": "NO_WINS",
        },
        execution_daily=(
            {"date": "2026-09-16", "open": 10., "close": 10.},
            {"date": "2026-09-17", "open": 10., "close": 10.},
            {"date": "2026-09-18", "open": 10., "close": 9.},
        ),
        execution_intraday=(
            {"time": "2026-09-17T09:35", "open": 10., "close": 10.},
            {"time": "2026-09-18T09:35", "open": 10., "close": 10.},
            {"time": "2026-09-18T11:30", "open": 9., "close": 9.},
        ),
    )


def test_public_intraday_audit_authenticates_core_rotation_and_preserves_evidence():
    evidence = _evidence()
    before = deepcopy(evidence.to_dict())
    result = audit_replay(evidence)
    assert result.status is AuditStatus.PASS, result.reason_codes
    assert result.reason_codes == ()
    assert {"INTRADAY_ORDER_CONTRACT", "INTRADAY_CHECKPOINT_PRICES",
            "T_PLUS_ONE_CORE_ROTATION_LEDGER", "INTRADAY_TRADE_PAIRING",
            "INTRADAY_METRICS"}.issubset(result.checks)
    assert audit_replay(ReplayEvidence.from_dict(before)).evidence_hash == result.evidence_hash
    assert evidence.to_dict() == before


@pytest.mark.parametrize("section,index,field,value,reason", [
    pytest.param("execution_spec", None, "t_plus_one_inventory_rotation", False,
                 "INVALID_INTRADAY_OVERLAY_SPEC", id="rotation-spec"),
    pytest.param("decisions", 1, "signal_date", "2026-09-18",
                 "ORDER_DECISION_MISMATCH", id="future-signal"),
    pytest.param("orders", 2, "quantity", 200,
                 "INVALID_INTRADAY_ORDER_PAIR", id="unpaired-quantity"),
    pytest.param("fills", 1, "fees", 11., "INTRADAY_FILL_MISMATCH", id="fill-fee"),
    pytest.param("fills", 2, "price", 9.1, "INTRADAY_FILL_MISMATCH", id="checkpoint-price"),
    pytest.param("account_daily", 1, "cash", 5842.,
                 "INTRADAY_ACCOUNT_LEDGER_MISMATCH", id="cash"),
    pytest.param("account_daily", 1, "quantity", 500,
                 "INTRADAY_ACCOUNT_LEDGER_MISMATCH", id="core-inventory"),
    pytest.param("trades", 0, "net_return", 0., "TRADE_VALUE_MISMATCH", id="trade-return"),
    pytest.param("metrics", None, "calmar", float("inf"), "METRIC_MISMATCH", id="finite-metric"),
])
def test_public_intraday_audit_rejects_changed_business_fact(section, index, field, value, reason):
    evidence = _evidence()
    baseline = audit_replay(evidence)
    assert baseline.status is AuditStatus.PASS, baseline.reason_codes
    payload = evidence.to_dict()
    target = payload[section] if index is None else payload[section][index]
    target[field] = value
    result = audit_replay(ReplayEvidence.from_dict(payload))
    assert result.status is AuditStatus.FAIL
    assert reason in result.reason_codes
    assert result.evidence_hash != baseline.evidence_hash


@pytest.mark.parametrize("missing", ["rotation-buy-fill", "midday-checkpoint", "metric"],
                         ids=["dependent-sell-without-buy", "missing-price", "missing-metric"])
def test_public_intraday_audit_rejects_incomplete_evidence(missing):
    evidence = _evidence()
    assert audit_replay(evidence).status is AuditStatus.PASS
    payload = evidence.to_dict()
    if missing == "rotation-buy-fill":
        payload["fills"].pop(1)
        reason = "INTRADAY_ORDER_NOT_FILLED"
    elif missing == "midday-checkpoint":
        payload["execution_intraday"].pop(2)
        reason = "MISSING_INTRADAY_CHECKPOINT"
    else:
        del payload["metrics"]["calmar"]
        reason = "METRIC_MISMATCH"
    result = audit_replay(ReplayEvidence.from_dict(payload))
    assert result.status is AuditStatus.FAIL
    assert reason in result.reason_codes
