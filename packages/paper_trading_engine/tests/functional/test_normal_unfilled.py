"""Confirmed normal zero fills end the attempt without disabling the account."""

from dataclasses import asdict, replace
from datetime import date, datetime, time
from decimal import Decimal
import sqlite3

import pytest

from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.contracts import OrderSpec, PlanLegSpec
from execution_channels.futu.futu_execution import ChannelExecution
from execution_channels.futu.store import PaperStore
from strategy_runtime import CycleTarget, EntryCyclePhase, EntryCyclePlanStatus, EntryCycleState, canonical_sha256
from pte_support import FakeAdvice, FakeBroker, broker_snapshot, decision, preparation


ACCOUNT = "s001-v1"


def _at(value):
    return datetime.fromisoformat(value + "+08:00")


def _submitted(store, *, signal_cash=False):
    store.create_virtual_account(
        ACCOUNT, "零成交终结测试", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="零成交终结测试",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused(ACCOUNT, False)
    broker = FakeBroker()
    clock = [_at("2026-09-02T09:30:05")]
    execution = ChannelExecution(store, broker, now=lambda: clock[0])
    execution.refresh_orders()
    value = decision(OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY"))
    if signal_cash:
        cycle = EntryCycleState(
            canonical_sha256({"account": ACCOUNT, "opening_signal": value.signal_identity}),
            value.signal_identity, Decimal("0.5"), Decimal("50000"), 1000,
            Decimal("0"), EntryCyclePhase.ACTIVE,
        )
        value = replace(
            value, contract_version="advice.v6", capital_mode="signal_cash_fraction",
            allocation_fraction=0.5, cycle_target=CycleTarget(True, Decimal("0.5")),
            entry_cycle_before=None, entry_cycle_after=cycle, cycle_status=EntryCyclePlanStatus.OPEN,
        )
    advice = FakeAdvice(value)
    engine = AccountEngine(store, advice)
    if signal_cash:
        # This test seeds a typed local contract, as in the existing allocation
        # suite; it does not claim to authenticate synthetic SRT identity facts.
        value = replace(value, available_cash=100_000)
        store.save_account_decision(ACCOUNT, asdict(value))
        store.create_account_intent(
            account_id=ACCOUNT, decision_id=value.decision_id, order_sequence=0,
            symbol=value.symbol, side="BUY", quantity=1000, limit_price="1.68",
            valid_session=value.valid_session.isoformat(), fee_rate="0.0005",
        )
    else:
        engine.refresh_account(ACCOUNT, prepared=preparation(value))
    execution.submit_pending(reconcile=False)
    assert len(broker.placed) == 1
    intent = store.account_intents(ACCOUNT)[0]
    return store, broker, clock, execution, advice, engine, intent


def _day_end(execution, clock):
    clock[0] = _at("2026-09-02T15:00:01")
    execution.refresh_orders()


def _cancel_report(broker, *, status="CANCELLED_ALL", quantity=0, error=""):
    order = replace(
        broker.value.orders[-1], status=status,
        cumulative_filled_quantity=quantity,
        average_fill_price=1.60 if quantity else 0,
        last_error=error,
    )
    broker.value = broker_snapshot(
        orders=(*broker.value.orders[:-1], order), quantity=quantity,
    )


# Independent risk: EC20; responsibility-level assertions.
def test_day_order_normal_unfilled_survives_restart_and_retries_only_next_session(new_store, tmp_path):
    path = tmp_path / "normal-day.db"
    store, broker, clock, execution, advice, engine, intent = _submitted(new_store(path))
    decision_id = intent["decision_id"]
    clock[0] = _at("2026-09-02T14:59:59")
    execution.refresh_orders()
    assert broker.cancelled == []
    _day_end(execution, clock)
    assert broker.cancelled == [intent["channel_order_id"]]
    assert store.account_intent(intent["intent_id"])["status"] == "CANCELLING_ALL"
    assert Decimal(store.virtual_account(ACCOUNT)["frozen_cash"]) > 0

    # A successful cancel request is not a terminal report and cannot release cash.
    store.close()
    store = PaperStore(path)
    execution = ChannelExecution(store, broker, now=lambda: clock[0])
    _cancel_report(broker)
    execution.refresh_orders()
    execution.refresh_orders()
    ended = store.account_intent(intent["intent_id"])
    assert ended["status"] == "CANCELLED_ALL"
    assert ended["payload"]["termination_reason"] == "NORMAL_UNFILLED"
    assert ended["attention_required"] is False
    actual = store.account_decision(ACCOUNT, decision_id)
    assert (actual["status"], actual["state_reason"]) == ("INCOMPLETE", "NORMAL_UNFILLED")
    account = store.virtual_account(ACCOUNT)
    assert account["health"] == "OK"
    assert (Decimal(account["cash"]), Decimal(account["frozen_cash"]), account["quantity"]) == (100_000, 0, 0)
    assert account["cycle_target"] == 1000
    assert store.account_fills(ACCOUNT) == []
    assert store.account_invariant_violations() == []
    store.close()

    store = PaperStore(path)
    execution = ChannelExecution(store, broker, now=lambda: clock[0])
    engine = AccountEngine(store, advice)
    execution.refresh_orders()
    engine.refresh_account(ACCOUNT, prepared=preparation(advice.value))
    execution.submit_pending()
    assert store.virtual_account(ACCOUNT)["health"] == "OK"
    assert store.attention_account_intents(ACCOUNT) == []
    assert len(store.account_decisions(ACCOUNT)) == len(store.account_intents(ACCOUNT)) == len(broker.placed) == 1
    with sqlite3.connect(path) as connection:
        releases = connection.execute(
            "SELECT cash_delta,quantity_delta,fee FROM account_ledger WHERE account_id=? AND entry_type='INTENT_RELEASE'",
            (ACCOUNT,),
        ).fetchall()
    assert len(releases) == 1
    assert tuple(Decimal(str(value)) for value in releases[0]) == (Decimal("1680.8400"), 0, 0)

    advice.value = replace(
        advice.value, decision_id="DEC-NEXT", signal_identity="3" * 64,
        signal_date=date(2026, 9, 2), valid_session=date(2026, 9, 3),
        data_cutoff=date(2026, 9, 2),
    )
    clock[0] = _at("2026-09-03T09:30:05")
    engine.refresh_account(ACCOUNT, prepared=preparation(advice.value, "d" * 64))
    execution.submit_pending()
    assert len(broker.placed) == 2
    assert broker.placed[-1].decision_id != decision_id
    assert store.account_decision(ACCOUNT, decision_id)["state_reason"] == "NORMAL_UNFILLED"
    store.close()


# Independent risk: EC20; responsibility-level assertions.
def test_uncertain_deadline_cancel_blocks_until_terminal_evidence(memory_store, monkeypatch):
    store, broker, clock, execution, _, _, intent = _submitted(memory_store())
    frozen = store.virtual_account(ACCOUNT)["frozen_cash"]

    def lost_reply(order_id):
        requests = store.query_audit_events(event_type="CANCEL_REQUESTED")
        assert any(row["order_id"] == order_id and row["details"].get("reason") == "planned_deadline" for row in requests)
        raise ConnectionError("cancel acknowledgement lost")

    monkeypatch.setattr(broker, "cancel_order", lost_reply)
    with pytest.raises(ConnectionError, match="acknowledgement lost"):
        _day_end(execution, clock)
    account = store.virtual_account(ACCOUNT)
    assert account["health"] == "BLOCKED"
    assert account["frozen_cash"] == frozen
    assert store.account_intent(intent["intent_id"])["status"] not in {"CANCELLED_ALL", "FILLED_ALL"}
    assert len(broker.placed) == 1
    # A later confirmed report resolves uncertainty; the failed call alone did not.
    _cancel_report(broker)
    execution.refresh_orders()
    assert store.account_intent(intent["intent_id"])["payload"]["termination_reason"] == "NORMAL_UNFILLED"
    assert store.virtual_account(ACCOUNT)["health"] == "OK"
    assert Decimal(store.virtual_account(ACCOUNT)["frozen_cash"]) == 0
    store.close()


# Independent risk: EC20; responsibility-level assertions.
def _rotation_ready(store):
    store, broker, clock, execution, advice, engine, _ = _submitted(store)
    # Seed a real core holding through the ordinary submitted-order fill path.
    first = replace(broker.value.orders[0], status="FILLED_ALL", cumulative_filled_quantity=1000, average_fill_price=1.60)
    broker.value = broker_snapshot(orders=(first,), quantity=1000)
    execution.refresh_orders()
    rotation = replace(
        advice.value, contract_version="advice.v5", decision_id="DEC-ROTATE",
        signal_date=date(2026, 9, 2), valid_session=date(2026, 9, 3), data_cutoff=date(2026, 9, 2),
        actual_quantity=1000, target_quantity=1000, cycle_target_quantity=1000, delta_quantity=0,
        action="ROTATE", order=None, orders=(), signal_identity="4" * 64,
        plan_mode="CORE_EVENT_INTRADAY_ROTATION",
        plan_legs=(
            PlanLegSpec(0, "ROTATION_ENTRY", "OPEN", time(9, 30), time(9, 35), None, None,
                        OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY")),
            PlanLegSpec(1, "ROTATION_EXIT", "11:30_CLOSE", time(11, 29), time(11, 30), 0, "FILLED_ALL",
                        OrderSpec("SELL", 1000, "MARKET", 1.60, "DAY")),
        ),
    )
    advice.value = rotation
    clock[0] = _at("2026-09-03T09:30:05")
    engine.refresh_account(ACCOUNT, prepared=preparation(rotation, "d" * 64))
    return store,broker,clock,execution


def _confirm_partial_entry(store,broker,execution):
    execution.submit_pending()
    first,last = broker.value.orders
    partial = replace(last,status='FILLED_PART',cumulative_filled_quantity=400,average_fill_price=1.60)
    broker.value = broker_snapshot(orders=(first,partial),quantity=1400)
    execution.refresh_orders()
    return store.account_intents(ACCOUNT)[-1]


def test_EC06_C05_partial_entry_never_activates_full_fill_dependent_exit(memory_store):
    store,broker,clock,execution = _rotation_ready(memory_store())
    exit_leg = _confirm_partial_entry(store,broker,execution)
    clock[0] = _at('2026-09-03T11:29:05')
    execution.submit_pending()
    assert store.account_intent(exit_leg['intent_id'])['status'] == 'WAITING_DEPENDENCY'
    assert [row.side for row in broker.placed] == ['BUY','BUY']
    assert store.virtual_account(ACCOUNT)['quantity'] == 1400


def test_EC20_C04_partial_entry_dependency_survives_database_reopen(new_store,tmp_path):
    path = tmp_path / 'partial-entry.db'
    store,broker,clock,execution = _rotation_ready(new_store(path))
    exit_leg = _confirm_partial_entry(store,broker,execution)
    store.close()
    reopened = PaperStore(path)
    try:
        clock[0] = _at('2026-09-03T11:29:05')
        execution = ChannelExecution(reopened,broker,now=lambda:clock[0])
        execution.submit_pending()
        assert reopened.account_intent(exit_leg['intent_id'])['status'] == 'WAITING_DEPENDENCY'
        assert reopened.virtual_account(ACCOUNT)['quantity'] == 1400
        assert [row.side for row in broker.placed] == ['BUY','BUY']
    finally:
        reopened.close()


def test_EC20_C05_unsubmitted_expired_entry_skips_exit_and_preserves_core(memory_store):
    store,broker,clock,execution = _rotation_ready(memory_store())
    entry,exit_leg = store.account_intents(ACCOUNT)[-2:]
    clock[0] = _at('2026-09-03T11:29:05')
    execution.submit_pending()
    assert store.account_intent(exit_leg['intent_id'])['status'] == 'SKIPPED_DEPENDENCY'
    assert store.account_intent(entry['intent_id'])['payload']['termination_reason'] == 'EXECUTION_EXPIRED'
    assert [row.side for row in broker.placed] == ['BUY']
    assert store.virtual_account(ACCOUNT)['quantity'] == 1000
