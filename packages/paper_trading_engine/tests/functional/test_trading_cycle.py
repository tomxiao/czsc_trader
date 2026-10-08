from dataclasses import asdict, replace
from datetime import date, datetime, time, timezone
import re
from time import monotonic, sleep
from types import SimpleNamespace
import pytest

from paper_trading_engine.account_engine import (
    AccountDecisionBlockedError,
    AccountEngine,
    ActiveOrderPendingError,
)
from paper_trading_engine.account_strategy_cycle import AccountStrategyCycle
from paper_trading_engine.audit import AuditRecorder
from paper_trading_engine.broker import TERMINAL_INTENT_STATUSES
from paper_trading_engine.coordinator import PteCoordinator
from paper_trading_engine.contracts import AdviceDecision, OrderSpec, PlanLegSpec
from paper_trading_engine.futu_execution import FutuExecution
from paper_trading_engine.scheduler import RuntimeScheduler
from paper_trading_engine.store import PaperStore
from paper_trading_engine.lifecycle import IntentControlState
from pte_support import FakeAdvice, FakeBroker, broker_snapshot, decision, preparation, adopt_test_decision, claim_test_intent


def _wait_until(predicate, timeout=2.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    assert predicate()


def _operator_coordinator(accounts, store):
    class Preparer:
        @staticmethod
        def latest_completed_signal_date(at):
            del at
            return date(2026, 9, 1)

        @staticmethod
        def prepare(account, *, signal_date):
            del account
            return SimpleNamespace(
                available_through=signal_date,
                data_identity="c" * 64,
                data_reference={"space_id": "11111111-1111-1111-1111-111111111111",
                                "preparation_id": "22222222-2222-2222-2222-222222222222",
                                "manifest_sha256": "a" * 64},
                tradable_window=SimpleNamespace(
                    start=date(2026, 9, 2), end=date(2026, 9, 2)
                ),
            )

    cycle = AccountStrategyCycle(accounts, Preparer(), store)
    return PteCoordinator(accounts, object(), strategy_cycle=cycle)


def test_blocked_or_draining_account_cannot_complete_a_decision_generation(new_store, tmp_path):
    store = new_store(tmp_path / "decision-gate.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    store.set_setting("last_data_prepare_date", "2026-09-01")
    store.set_virtual_health("s001-v1", "BLOCKED", "等待人工处理")
    advice = FakeAdvice(decision(OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY")))
    accounts = AccountEngine(store, advice)

    class Preparer:
        def prepare(self, account, *, signal_date):
            return SimpleNamespace(
                available_through=signal_date,
                data_identity="c" * 64,
                data_reference={"space_id": "11111111-1111-1111-1111-111111111111",
                                "preparation_id": "22222222-2222-2222-2222-222222222222",
                                "manifest_sha256": "a" * 64},
                tradable_window=SimpleNamespace(
                    start=date(2026, 9, 2), end=date(2026, 9, 2)
                ),
            )

    scheduler = RuntimeScheduler(
        accounts,
        AccountStrategyCycle(accounts, Preparer(), store),
        store,
        preparation_time="00:00",
    )
    scheduler.tick_daily(datetime(2026, 9, 2, 20, 30, 0))
    _wait_until(lambda: bool(store.operation_failures()))
    assert store.get_setting("last_account_decision_date") is None
    assert store.account_decisions("s001-v1") == []
    assert store.account_intents("s001-v1") == []
    assert advice.calls == []
    assert {row["operation"] for row in store.operation_failures()} == {
        "account_strategy_cycle:s001-v1"
    }

    store.set_virtual_health("s001-v1", "OK")
    accounts.begin_shutdown()
    with pytest.raises(AccountDecisionBlockedError, match="PTE正在停止"):
        accounts.refresh_account("s001-v1", prepared=preparation(advice.value))
    assert store.account_decisions("s001-v1") == []
    assert store.account_intents("s001-v1") == []
    store.close()


def test_immediate_split_order_intents_are_persisted_atomically(new_store, tmp_path, monkeypatch):
    store = new_store(tmp_path / "split-order-atomic.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    audit = AuditRecorder(store)
    events = [
        audit.build(
            "ORDER_INTENT_CREATED", source="test", account_id="s001-v1",
            decision_id="DEC-SPLIT", correlation_id="DEC-SPLIT",
            details={"order_sequence": sequence},
        )
        for sequence in range(2)
    ]
    orders = [
        {
            "sequence": sequence, "side": "BUY", "quantity": 1000,
            "order_type": "LIMIT", "limit_price": 1.68,
        }
        for sequence in range(2)
    ]
    original_insert = store._insert_audit_event
    inserted = 0

    def fail_second_event(event):
        nonlocal inserted
        inserted += 1
        if inserted == 2:
            raise RuntimeError("simulated audit persistence failure")
        original_insert(event)

    monkeypatch.setattr(store, "_insert_audit_event", fail_second_event)
    with pytest.raises(RuntimeError, match="audit persistence"):
        adopt_test_decision(store, account_id="s001-v1", decision_id="DEC-SPLIT", valid_session="2026-09-02", orders=orders)
        store.create_account_immediate_intents(
            account_id="s001-v1", decision_id="DEC-SPLIT", symbol="588080.SH",
            valid_session="2026-09-02", fee_rate="0.0005",
            orders=orders, audit_events=events,
        )
    account = store.virtual_account("s001-v1")
    assert store.account_intents("s001-v1") == []
    assert float(account["cash"]) == 100_000
    assert float(account["frozen_cash"]) == 0
    assert store.query_audit_events(event_type="ORDER_INTENT_CREATED") == []

    monkeypatch.setattr(store, "_insert_audit_event", original_insert)
    adopt_test_decision(store, account_id="s001-v1", decision_id="DEC-SPLIT", valid_session="2026-09-02", orders=orders)
    created = store.create_account_immediate_intents(
        account_id="s001-v1", decision_id="DEC-SPLIT", symbol="588080.SH",
        valid_session="2026-09-02", fee_rate="0.0005",
        orders=orders, audit_events=events,
    )
    assert len(created) == 2
    assert float(store.virtual_account("s001-v1")["frozen_cash"]) == 3361.68
    store.close()


def test_initial_commit_rolls_back_and_pause_does_not_change_decision_content(new_store, tmp_path, monkeypatch):
    store = new_store(tmp_path / "lifecycle-commit.db")
    account = store.create_virtual_account(
        "s001-v1", "test", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="test", strategy_version="v1",
        release_hash="b" * 64, qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    assert account["run_state"] == "PAUSED"
    advice = FakeAdvice(decision(OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY")))
    accounts = AccountEngine(store, advice)
    store.set_virtual_paused("s001-v1", False)
    original = store.create_account_immediate_intents

    def fail_persistence(**kwargs):
        raise RuntimeError("intent persistence failed")

    monkeypatch.setattr(store, "create_account_immediate_intents", fail_persistence)
    with pytest.raises(RuntimeError, match="persistence"):
        accounts.refresh_account("s001-v1", prepared=preparation(advice.value))
    assert store.account_decisions("s001-v1") == []
    assert store.account_snapshots("s001-v1") == []
    assert store.query_audit_events(event_type="DECISION_GENERATED") == []
    assert store.virtual_account("s001-v1")["last_decision_id"] is None
    assert store.account_invariant_violations() == []

    monkeypatch.setattr(store, "create_account_immediate_intents", original)
    store.set_virtual_paused("s001-v1", True)
    accounts.refresh_account("s001-v1", prepared=preparation(advice.value))
    observed = store.account_decisions("s001-v1")[0]
    assert "execution_disposition" not in observed["payload"]
    assert observed["status"] == "PENDING" and store.account_intents("s001-v1") == []
    store.set_virtual_paused("s001-v1", False)
    accounts.drive_account_decision("s001-v1", prepared=preparation(advice.value))
    adopted = store.account_decision("s001-v1", observed["decision_id"])
    assert adopted["payload"] == observed["payload"]
    assert adopted["generated_at"] == observed["generated_at"]
    assert len(store.account_intents("s001-v1")) == 1
    store.close()


@pytest.mark.parametrize("entry", ["single", "immediate", "plan"])
def test_order_entry_rejects_terminal_or_changed_immutable_plan(new_store, tmp_path, entry):
    store = new_store(tmp_path / "entry-gate.db")
    store.create_virtual_account(
        "s001-v1", "test", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="test", strategy_version="v1",
        release_hash="b" * 64, qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    planned = {"sequence": 0, "side": "BUY", "quantity": 100, "order_type": "LIMIT", "limit_price": 1.68}
    leg = {**planned, "plan_mode": "CORE_SETUP", "role": "CORE_SETUP", "checkpoint": "OPEN",
           "submit_after": "09:30:00", "submit_before": "09:35:00", "dependency_sequence": None}
    adopt_test_decision(store, account_id="s001-v1", decision_id="GATED", valid_session="2026-09-02",
                        orders=[planned] if entry != "plan" else None, legs=[leg] if entry == "plan" else None)

    def create(quantity):
        common = {"account_id": "s001-v1", "decision_id": "GATED", "symbol": "588080.SH", "valid_session": "2026-09-02", "fee_rate": .0005}
        if entry == "single":
            return store.create_account_intent(**common, order_sequence=0, side="BUY", quantity=quantity, limit_price=1.68, order_type="LIMIT")
        if entry == "immediate":
            return store.create_account_immediate_intents(**common, orders=[{**planned, "quantity": quantity}])
        return store.create_account_plan_intents(**common, legs=[{**leg, "quantity": quantity}])

    before = store.virtual_account("s001-v1")
    with pytest.raises(ValueError, match="immutable plan"):
        create(200)
    assert store.virtual_account("s001-v1") == before
    assert store.account_intents("s001-v1") == []
    store.expire_unsubmitted_decisions(datetime(2026, 9, 3, tzinfo=timezone.utc))
    assert store.account_decision("s001-v1", "GATED")["status"] == "INCOMPLETE"
    with pytest.raises(ValueError, match="terminal"):
        create(100)
    assert store.account_intents("s001-v1") == []
    store.close()


def intraday_setup_decision(strategy: dict[str, str]) -> AdviceDecision:
    return AdviceDecision(
        contract_version="advice.v5", decision_id="DEC-CORE-SETUP",
        symbol="510500.SH", signal_date=date(2026, 9, 1),
        valid_session=date(2026, 9, 2), actual_quantity=0,
        target_quantity=1000, cycle_target_quantity=1000, delta_quantity=1000,
        action="BUY", strategy=strategy, signal_reference_price=1.70,
        execution_reference_price=1.70, data_cutoff=date(2026, 9, 1),
        order=None, signal_identity="1" * 64, plan_identity="2" * 64,
        portfolio_revision=0, state_revision=0, orders=(),
        available_cash=100_000, fee_rate=0.0005,
        plan_mode="CORE_SETUP",
        plan_legs=(PlanLegSpec(
            0, "CORE_SETUP", "OPEN", time(9, 30), time(9, 35),
            None, None, OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY"),
        ),),
    )


def test_expired_plan_is_terminal_and_requires_new_decision(new_store, tmp_path):
    store = new_store(tmp_path / "generation.db")
    store.create_virtual_account(
        "s003-v1", "S003-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S003", strategy_name_snapshot="成分资金流宽度早盘延续",
        strategy_version="v1", release_hash="c" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-08",
        symbol="510500.SH",
    )
    adopt_test_decision(store, account_id="s003-v1", decision_id="DEC-GENERATION", valid_session="2026-09-14", legs=[{
            "sequence": 0, "side": "BUY", "quantity": 1000,
            "order_type": "LIMIT", "limit_price": "7.5000",
            "plan_mode": "CORE_SETUP", "role": "CORE_SETUP", "checkpoint": "OPEN",
            "submit_after": "09:30:00", "submit_before": "09:35:00",
            "dependency_sequence": None, "dependency_required_status": None,
        }])
    store.set_virtual_paused("s003-v1", False)
    [intent] = store.create_account_plan_intents(
        account_id="s003-v1", decision_id="DEC-GENERATION", symbol="510500.SH",
        valid_session="2026-09-14", fee_rate="0.0005",
        legs=[{
            "sequence": 0, "side": "BUY", "quantity": 1000,
            "order_type": "LIMIT", "limit_price": "7.5000",
            "plan_mode": "CORE_SETUP", "role": "CORE_SETUP", "checkpoint": "OPEN",
            "submit_after": "09:30:00", "submit_before": "09:35:00",
            "dependency_sequence": None, "dependency_required_status": None,
        }],
    )
    store.release_account_intent(
        intent["intent_id"], "EXPIRED", attention_reason="计划订单错过提交截止时间",
    )
    with pytest.raises(ValueError, match="terminal"):
        store.update_account_intent_status(intent["intent_id"], IntentControlState.SUBMISSION_UNCERTAIN)
    recovered = store.account_intent(intent["intent_id"])
    assert recovered["reservation_generation"] == 1
    assert store.account_decision("s003-v1", "DEC-GENERATION")["status"] == "INCOMPLETE"
    store.release_account_intent(intent["intent_id"], "REJECTED")
    assert store.account_invariant_violations() == []
    with store._lock:
        releases = store._connection.execute(
            "SELECT 1 FROM account_ledger WHERE account_id=? AND entry_type='INTENT_RELEASE'",
            ("s003-v1",),
        ).fetchall()
    assert len(releases) == 1
    store.release_account_intent(intent["intent_id"], "REJECTED")
    assert store.account_invariant_violations() == []
    store.close()


def test_missing_recovered_release_can_be_repaired_once_with_audit(new_store, tmp_path):
    store = new_store(tmp_path / "repair.db")
    store.create_virtual_account(
        "s003-v1", "S003-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S003", strategy_name_snapshot="成分资金流宽度早盘延续",
        strategy_version="v1", release_hash="c" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-08",
        symbol="510500.SH",
    )
    adopt_test_decision(store, account_id="s003-v1", decision_id="DEC-REPAIR", valid_session="2026-09-14", orders=[{'side': "BUY", 'quantity': 1000, 'order_type': 'LIMIT' if "BUY" == 'BUY' else 'MARKET', 'limit_price': "7.5000"}])
    store.set_virtual_paused("s003-v1", False)
    intent = store.create_account_intent(
        account_id="s003-v1", decision_id="DEC-REPAIR", order_sequence=0,
        symbol="510500.SH", side="BUY", quantity=1000,
        limit_price="7.5000", valid_session="2026-09-14",
    )
    reserve = "7503.7500"
    with store._lock, store._connection:
        store._connection.execute(
            "UPDATE virtual_accounts SET cash='100000.0000',frozen_cash='0.0000' "
            "WHERE account_id='s003-v1'"
        )
        store._connection.execute(
            "UPDATE intents SET status='REJECTED',attention_required=1,"
            "attention_reason='broker rejected' WHERE intent_id=?", (intent["intent_id"],)
        )
    assert store.account_invariant_violations()
    event = AuditRecorder(store).build(
        "ACCOUNT_LEDGER_REPAIRED", source="test", actor_type="OPERATOR",
        account_id="s003-v1", correlation_id=intent["intent_id"],
    )
    result = store.repair_released_intent_ledger("s003-v1", intent["intent_id"], event)
    assert result["status"] == "REPAIRED"
    assert result["cash_delta"] == reserve
    assert store.account_invariant_violations() == []
    repeated = store.repair_released_intent_ledger("s003-v1", intent["intent_id"], event)
    assert repeated["status"] == "ALREADY_REPAIRED"
    assert len(store.query_audit_events(event_type="ACCOUNT_LEDGER_REPAIRED")) == 1
    store.close()


def test_ft_pte02_account_decision_futu_order_fill_restart_and_idempotence(new_store, tmp_path, monkeypatch):
    store = new_store(tmp_path / "runtime.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    advice = FakeAdvice(decision(OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY")))
    accounts = AccountEngine(
        store, advice, now=lambda: datetime(2026, 9, 8, 6, 35, tzinfo=timezone.utc),
    )
    broker = FakeBroker()
    FutuExecution(store, broker).refresh_orders()
    execution = FutuExecution(store, broker, symbol="588080.SH", today=lambda: date(2026, 9, 2))

    FutuExecution(store, FakeBroker()).refresh_orders()
    accounts.refresh_account("s001-v1", prepared=preparation(advice.value))
    accounts.refresh_account("s001-v1", prepared=preparation(advice.value))
    assert len(store.account_decisions("s001-v1")) == 1
    assert len(store.pending_account_intents()) == 1
    store.set_setting("last_data_prepare_date", "2026-09-01")
    driven = accounts.drive_account_decision(
        "s001-v1", prepared=preparation(advice.value)
    )
    assert driven.outcome == "DECISION_REUSED"
    assert len(advice.calls) == 2
    saved_decision = store.account_decisions("s001-v1")[0]
    assert re.fullmatch(r"DEC-20260908-1435-[0-9A-F]{12}", saved_decision["decision_id"])
    assert saved_decision["payload"]["source_decision_id"] == "DEC-ONE"
    assert saved_decision["payload"]["prepared_data_identity"] == "c" * 64
    snapshot = store.account_snapshots("s001-v1")[0]
    assert snapshot["session"] == "2026-09-01"
    assert float(snapshot["total_assets"]) == 100_000
    decision_event = store.query_audit_events(
        event_type="DECISION_GENERATED", account_id="s001-v1"
    )[0]
    assert decision_event["channel"] is None

    execution.refresh_account()
    execution.submit_pending()
    execution.submit_pending()
    assert len(broker.placed) == 1
    submitted = broker.value.orders[0]
    broker.value = broker_snapshot(
        orders=(replace(
            submitted, status="FILLED_PART", cumulative_filled_quantity=400,
            average_fill_price=1.67,
        ),), quantity=400,
    )
    execution.refresh_orders()
    execution.refresh_orders()
    assert store.virtual_account("s001-v1")["quantity"] == 400
    assert len(store.account_fills("s001-v1")) == 1

    next_advice = FakeAdvice(replace(
        decision(), decision_id="DEC-TWO", source_decision_id="DEC-TWO",
        signal_date=date(2026, 9, 2), valid_session=date(2026, 9, 3),
        data_cutoff=date(2026, 9, 2), target_quantity=1000,
        cycle_target_quantity=1000,
    ))
    next_accounts = AccountEngine(store, next_advice)
    store.set_setting("last_data_prepare_date", "2026-09-02")
    with pytest.raises(ActiveOrderPendingError, match="存在未完成订单"):
        next_accounts.refresh_account(
            "s001-v1", prepared=preparation(next_advice.value)
        )
    assert next_advice.calls == []
    assert store.virtual_account("s001-v1")["health"] == "READY"
    assert len(store.account_intents("s001-v1")) == 1
    blocked_events = store.query_audit_events(event_type="ORDER_SUBMISSION_BLOCKED")
    assert [row["details"]["reason"] for row in blocked_events] == [
        "previous_order_active",
    ]
    execution.refresh_orders()
    assert store.virtual_account("s001-v1")["health"] == "READY"

    broker.value = broker_snapshot(
        orders=(replace(
            submitted, status="FILLED_ALL", cumulative_filled_quantity=1000,
            average_fill_price=1.676,
        ),), quantity=1000,
    )
    original_insert = store._insert_audit_event

    def fail_fill_audit(event):
        if event.event_type == "ORDER_FILLED":
            raise RuntimeError("fill audit unavailable")
        return original_insert(event)

    monkeypatch.setattr(store, "_insert_audit_event", fail_fill_audit)
    account_before = store.virtual_account("s001-v1")
    with pytest.raises(RuntimeError, match="fill audit unavailable"):
        execution.refresh_orders()
    assert store.virtual_account("s001-v1") == account_before
    assert len(store.account_fills("s001-v1")) == 1
    assert store.account_order(submitted.channel_order_id)["cumulative_filled_quantity"] == 400
    assert store.query_audit_events(event_type="ORDER_FILLED") == []
    store.close()
    store = PaperStore(tmp_path / "runtime.db")
    execution = FutuExecution(store, broker, today=lambda: date(2026, 9, 2))
    next_accounts = AccountEngine(store, next_advice)
    execution.refresh_orders()
    execution.refresh_orders()
    assert len(broker.placed) == 1
    assert store.account_invariant_violations() == []
    assert store.virtual_account("s001-v1")["quantity"] == 1000
    assert store.virtual_account("s001-v1")["health"] == "READY"
    next_accounts.refresh_account(
        "s001-v1", prepared=preparation(next_advice.value)
    )
    assert len(next_advice.calls) == 1
    assert len(store.account_decisions("s001-v1")) == 2
    assert len(store.account_intents("s001-v1")) == 1
    assert sum(row["quantity"] for row in store.account_fills("s001-v1")) == 1000
    assert len(store.query_audit_events(event_type="ORDER_FILLED", account_id="s001-v1")) == 1
    store.close()


    reopened = PaperStore(tmp_path / "runtime.db")
    assert reopened.virtual_account("s001-v1")["quantity"] == 1000
    assert len(reopened.account_orders("s001-v1")) == 1
    assert len(reopened.account_fills("s001-v1")) == 2
    reopened.close()

def test_account_snapshot_values_position_with_execution_price(new_store, tmp_path):
    store = new_store(tmp_path / "valuation.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    with store._lock, store._connection:
        store._connection.execute(
            "UPDATE virtual_accounts SET cash='90000.0000',quantity=1000 "
            "WHERE account_id='s001-v1'"
        )
    advice = replace(
        decision(), actual_quantity=1000, target_quantity=1000,
        cycle_target_quantity=1000, delta_quantity=0,
        signal_reference_price=2.50, execution_reference_price=7.61,
    )
    AccountEngine(store, FakeAdvice(advice)).refresh_account(
        "s001-v1", prepared=preparation(advice)
    )
    snapshot = store.account_snapshots("s001-v1")[0]
    assert float(snapshot["close"]) == pytest.approx(7.61)
    assert float(snapshot["market_value"]) == pytest.approx(7_610)
    assert float(snapshot["total_assets"]) == pytest.approx(97_610)
    store.close()


def test_ft_pte10_intraday_plan_waits_for_fill_and_recovers_after_restart(new_store, tmp_path):
    store = new_store(tmp_path / "runtime.db")
    store.create_virtual_account(
        "s003-v1", "S003-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S003", strategy_name_snapshot="成分资金流宽度早盘延续",
        strategy_version="v1", release_hash="c" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-08",
        symbol="510500.SH",
    )
    store.set_virtual_paused("s003-v1", False)
    broker = FakeBroker()
    FutuExecution(store, broker).refresh_orders()
    strategy = {
        "strategy_id": "S003", "name": "成分资金流宽度早盘延续",
        "version": "v1", "release_id": "S003-v1",
        "release_hash": "c" * 64, "qualification": "PAPER_READY",
    }
    setup = intraday_setup_decision(strategy)
    AccountEngine(store, FakeAdvice(setup)).refresh_account(
        "s003-v1", prepared=preparation(setup)
    )
    assert store.virtual_account("s003-v1")["cycle_target"] is None
    setup_execution = FutuExecution(
        store, broker, now=lambda: datetime(2026, 9, 2, 1, 30, 5, tzinfo=timezone.utc),
    )
    setup_execution.refresh_account()
    setup_execution.submit_pending(reconcile=False)
    setup_order = broker.value.orders[-1]
    broker.value = broker_snapshot(
        orders=(replace(
            setup_order, status="FILLED_ALL", cumulative_filled_quantity=1000,
            average_fill_price=1.67,
        ),),
        quantity=1000,
        symbol="510500.SH",
    )
    setup_execution.refresh_orders()
    assert store.virtual_account("s003-v1")["cycle_target"] == 1000

    plan = AdviceDecision(
        contract_version="advice.v5",
        decision_id="DEC-PLAN",
        symbol="510500.SH",
        signal_date=date(2026, 9, 2),
        valid_session=date(2026, 9, 3),
        actual_quantity=1000,
        target_quantity=1000,
        cycle_target_quantity=1000,
        delta_quantity=0,
        action="ROTATE",
        strategy=strategy,
        signal_reference_price=1.70,
        execution_reference_price=1.70,
        data_cutoff=date(2026, 9, 2),
        order=None,
        signal_identity="3" * 64,
        plan_identity="4" * 64,
        portfolio_revision=0,
        state_revision=0,
        orders=(),
        available_cash=90_000,
        fee_rate=0.0005,
        plan_mode="CORE_EVENT_INTRADAY_ROTATION",
        plan_legs=(
            PlanLegSpec(
                0, "ROTATION_ENTRY", "OPEN", time(9, 30), time(9, 35),
                None, None, OrderSpec("BUY", 1000, "LIMIT", 1.80, "DAY"),
            ),
            PlanLegSpec(
                1, "ROTATION_EXIT", "11:30_CLOSE", time(11, 29), time(11, 30),
                0, "FILLED_ALL", OrderSpec("SELL", 1000, "MARKET", 1.70, "DAY"),
            ),
        ),
    )
    AccountEngine(store, FakeAdvice(plan)).refresh_account(
        "s003-v1", prepared=preparation(plan)
    )
    intents = store.account_intents("s003-v1")[-2:]
    assert [row["status"] for row in intents] == ["PENDING_SUBMIT", "WAITING_DEPENDENCY"]

    open_execution = FutuExecution(
        store, broker, now=lambda: datetime(2026, 9, 3, 1, 30, 5, tzinfo=timezone.utc),
    )
    open_execution.refresh_account()
    open_execution.submit_pending(reconcile=False)
    assert [row.side for row in broker.placed] == ["BUY", "BUY"]
    assert store.account_intent(intents[1]["intent_id"])["status"] == "WAITING_DEPENDENCY"

    rotation_buy = broker.value.orders[-1]
    broker.value = broker_snapshot(
        quantity=2000, symbol="510500.SH",
        orders=(
            broker.value.orders[0],
            replace(
                rotation_buy, status="FILLED_ALL", cumulative_filled_quantity=1000,
                average_fill_price=1.71,
            ),
        ),
    )
    store.close()
    store = PaperStore(tmp_path / "runtime.db")
    restarted = FutuExecution(
        store, broker, now=lambda: datetime(2026, 9, 3, 3, 29, 5, tzinfo=timezone.utc),
    )
    restarted.refresh()
    assert [row.side for row in broker.placed] == ["BUY", "BUY", "SELL"]
    assert store.account_intent(intents[1]["intent_id"])["status"] == "SUBMITTED"

    rotation_sell = broker.value.orders[-1]
    broker.value = broker_snapshot(
        quantity=1000, symbol="510500.SH",
        orders=(
            broker.value.orders[0], broker.value.orders[1],
            replace(
                rotation_sell, status="FILLED_ALL", cumulative_filled_quantity=1000,
                average_fill_price=1.72,
            ),
        ),
    )
    restarted.refresh_orders()
    assert store.virtual_account("s003-v1")["quantity"] == 1000
    assert all(
        row["status"] == "FILLED_ALL" for row in store.account_intents("s003-v1")
    )
    assert len(store.query_audit_events(event_type="EXECUTION_PLAN_LEG_READY")) == 1
    store.close()


def test_ft_pte11_intraday_plan_blocks_exit_when_entry_is_not_filled(new_store, tmp_path):
    store = new_store(tmp_path / "runtime.db")
    store.create_virtual_account(
        "s003-v1", "S003-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S003", strategy_name_snapshot="成分资金流宽度早盘延续",
        strategy_version="v1", release_hash="c" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-08",
        symbol="510500.SH",
    )
    store.set_virtual_paused("s003-v1", False)
    broker = FakeBroker()
    FutuExecution(store, broker).refresh_orders()
    strategy = {
        "strategy_id": "S003", "name": "成分资金流宽度早盘延续",
        "version": "v1", "release_id": "S003-v1",
        "release_hash": "c" * 64, "qualification": "PAPER_READY",
    }
    setup = intraday_setup_decision(strategy)
    AccountEngine(store, FakeAdvice(setup)).refresh_account(
        "s003-v1", prepared=preparation(setup)
    )
    assert store.virtual_account("s003-v1")["cycle_target"] is None
    setup_execution = FutuExecution(
        store, broker, now=lambda: datetime(2026, 9, 2, 1, 30, 5, tzinfo=timezone.utc),
    )
    setup_execution.refresh_account()
    setup_execution.submit_pending(reconcile=False)
    setup_order = broker.value.orders[-1]
    broker.value = broker_snapshot(
        orders=(replace(
            setup_order, status="FILLED_ALL", cumulative_filled_quantity=1000,
            average_fill_price=1.67,
        ),),
        quantity=1000,
        symbol="510500.SH",
    )
    setup_execution.refresh_orders()
    assert store.virtual_account("s003-v1")["cycle_target"] == 1000

    plan = AdviceDecision(
        contract_version="advice.v5", decision_id="DEC-PLAN-BLOCKED",
        symbol="510500.SH", signal_date=date(2026, 9, 2),
        valid_session=date(2026, 9, 3), actual_quantity=1000,
        target_quantity=1000, cycle_target_quantity=1000, delta_quantity=0,
        action="ROTATE", strategy=strategy, signal_reference_price=1.70,
        execution_reference_price=1.70, data_cutoff=date(2026, 9, 2),
        order=None, signal_identity="5" * 64, plan_identity="6" * 64,
        portfolio_revision=0, state_revision=0, orders=(),
        available_cash=90_000, fee_rate=0.0005,
        plan_mode="CORE_EVENT_INTRADAY_ROTATION",
        plan_legs=(
            PlanLegSpec(
                0, "ROTATION_ENTRY", "OPEN", time(9, 30), time(9, 35),
                None, None, OrderSpec("BUY", 1000, "LIMIT", 1.80, "DAY"),
            ),
            PlanLegSpec(
                1, "ROTATION_EXIT", "11:30_CLOSE", time(11, 29), time(11, 30),
                0, "FILLED_ALL", OrderSpec("SELL", 1000, "MARKET", 1.70, "DAY"),
            ),
        ),
    )
    AccountEngine(store, FakeAdvice(plan)).refresh_account(
        "s003-v1", prepared=preparation(plan)
    )
    assert store.virtual_account("s003-v1")["cycle_target"] == 1000
    plan_intents = store.account_intents("s003-v1")[-2:]
    entry, exit_leg = plan_intents

    previous_evening = FutuExecution(
        store, broker, now=lambda: datetime(2026, 9, 2, 12, 51, tzinfo=timezone.utc),
    )
    previous_evening.refresh_account()
    previous_evening.submit_pending(reconcile=False)
    assert store.account_intent(entry["intent_id"])["status"] == "PENDING_SUBMIT"
    assert store.virtual_account("s003-v1")["health"] != "BLOCKED"

    open_execution = FutuExecution(
        store, broker, now=lambda: datetime(2026, 9, 3, 1, 30, 5, tzinfo=timezone.utc),
    )
    open_execution.refresh_account()
    open_execution.submit_pending(reconcile=False)
    assert [row.side for row in broker.placed] == ["BUY", "BUY"]

    after_deadline = FutuExecution(
        store, broker, now=lambda: datetime(2026, 9, 3, 1, 36, tzinfo=timezone.utc),
    )
    after_deadline.refresh_orders()
    assert broker.cancelled == [store.account_intent(entry["intent_id"])["channel_order_id"]]
    assert store.account_intent(entry["intent_id"])["status"] == "CANCELLING_ALL"
    assert store.account_intent(exit_leg["intent_id"])["status"] == "WAITING_DEPENDENCY"

    rotation_buy = broker.value.orders[-1]
    broker.value = replace(
        broker.value,
        orders=(
            broker.value.orders[0],
            replace(rotation_buy, status="CANCELLED_ALL"),
        ),
    )
    after_deadline.refresh_orders()
    noon_execution = FutuExecution(
        store, broker, now=lambda: datetime(2026, 9, 3, 3, 29, tzinfo=timezone.utc),
    )
    noon_execution.submit_pending(reconcile=False)
    assert [row.side for row in broker.placed] == ["BUY", "BUY"]
    assert store.account_intent(entry["intent_id"])["status"] == "CANCELLED_ALL"
    assert store.account_intent(exit_leg["intent_id"])["status"] == "EXPIRED"
    assert store.virtual_account("s003-v1")["health"] == "BLOCKED"
    assert len(store.query_audit_events(event_type="EXECUTION_PLAN_BLOCKED")) == 1
    store.close()


def test_existing_decision_id_is_preserved_when_same_decision_is_recomputed(new_store, tmp_path):
    store = new_store(tmp_path / "runtime.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    old_decision = decision()
    old_payload = asdict(old_decision)
    old_payload["prepared_data_identity"] = preparation(old_decision).data_identity
    old_payload["prepared_data_reference"] = preparation(old_decision).data_reference
    old_payload.pop("source_decision_id")
    old_payload.pop("plan_identity")
    store.save_account_decision("s001-v1", old_payload)

    accounts = AccountEngine(
        store, FakeAdvice(old_decision),
        now=lambda: datetime(2026, 9, 8, 6, 35, tzinfo=timezone.utc),
    )
    accounts.refresh_account("s001-v1", prepared=preparation(old_decision))

    saved = store.account_decisions("s001-v1")
    assert len(saved) == 1
    assert saved[0]["decision_id"] == "DEC-ONE"
    assert store.virtual_account("s001-v1")["last_decision_id"] == "DEC-ONE"
    conflicting = dict(old_payload)
    conflicting["target_quantity"] = 100
    with pytest.raises(ValueError, match="idempotent"):
        store.save_account_decision("s001-v1", conflicting)
    store.close()


def test_operator_can_drive_one_account_decision_with_explicit_result_and_audit(new_store, tmp_path):
    store = new_store(tmp_path / "manual-decision.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    advice = FakeAdvice(decision())
    accounts = AccountEngine(store, advice)
    coordinator = _operator_coordinator(accounts, store)

    first = coordinator.drive_virtual_account_decision("s001-v1")
    store.set_setting("last_data_prepare_date", "2026-09-01")
    repeated = coordinator.drive_virtual_account_decision("s001-v1")

    assert first == {
        "status": "DECISION_COMPLETED", "account_id": "s001-v1",
        "decision_id": first["decision_id"], "signal_date": "2026-09-01",
        "valid_session": "2026-09-02", "action": "WAIT",
        "target_quantity": 0, "execution_reference_price": 1.68,
        "reused_decision": False,
    }
    assert repeated["decision_id"] == first["decision_id"]
    assert repeated["status"] == "DECISION_REUSED"
    assert repeated["reused_decision"] is True
    assert len(advice.calls) == 2
    advice.value = replace(
        decision(), decision_id="DEC-TWO", source_decision_id="DEC-TWO",
        signal_identity="7" * 64,
    )
    superseded = coordinator.drive_virtual_account_decision("s001-v1")
    assert superseded["status"] == "DECISION_COMPLETED"
    assert superseded["reused_decision"] is False
    decisions = store.account_decisions("s001-v1")
    assert {row["decision_id"]: row["status"] for row in decisions} == {
        first["decision_id"]: "COMPLETED",
        superseded["decision_id"]: "COMPLETED",
    }
    events = store.query_audit_events(
        event_type="ACCOUNT_DECISION_DRIVEN", account_id="s001-v1",
    )
    assert len(events) == 3
    assert all(row["actor_type"] == "OPERATOR" for row in events)
    store.set_virtual_health("s001-v1", "BLOCKED", "等待人工处理")
    with pytest.raises(AccountDecisionBlockedError, match="已阻塞"):
        coordinator.drive_virtual_account_decision("s001-v1")
    failed = store.query_audit_events(
        event_type="ACCOUNT_DECISION_DRIVE_FAILED", account_id="s001-v1",
    )
    assert len(failed) == 1
    assert failed[0]["outcome"] == "FAILURE"
    assert failed[0]["details"]["error_type"] == "AccountDecisionBlockedError"
    store.close()


def test_operator_supersedes_unsubmitted_intents_and_releases_reservations(new_store, tmp_path):
    store = new_store(tmp_path / "supersede-intents.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    advice = FakeAdvice(decision(OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY")))
    coordinator = _operator_coordinator(AccountEngine(store, advice), store)
    first = coordinator.drive_virtual_account_decision("s001-v1")
    old_intent = store.account_intents("s001-v1")[0]
    assert store.virtual_account("s001-v1")["frozen_cash"] != "0.0000"

    advice.value = replace(
        decision(OrderSpec("BUY", 2000, "LIMIT", 1.67, "DAY")),
        decision_id="DEC-TWO", source_decision_id="DEC-TWO",
    )
    result = coordinator.drive_virtual_account_decision("s001-v1")

    assert result["status"] == "DECISION_AND_INTENTS_SUPERSEDED"
    assert advice.calls[-1][1] == pytest.approx(100_000)
    assert result["superseded_decision_id"] == first["decision_id"]
    assert result["superseded_intent_ids"] == [old_intent["intent_id"]]
    assert store.account_intent(old_intent["intent_id"])["status"] == "SUPERSEDED"
    current_intents = [
        row for row in store.account_intents("s001-v1")
        if row["status"] not in TERMINAL_INTENT_STATUSES
    ]
    assert len(current_intents) == 1
    assert current_intents[0]["decision_id"] == result["decision_id"]
    assert current_intents[0]["quantity"] == 2000
    account = store.virtual_account("s001-v1")
    assert float(account["cash"]) + float(account["frozen_cash"]) == pytest.approx(100_000)
    assert float(account["frozen_cash"]) == pytest.approx(3341.67)
    assert len(store.query_audit_events(event_type="DECISION_SUPERSEDED")) == 1
    assert len(store.query_audit_events(event_type="ORDER_INTENT_SUPERSEDED")) == 1
    store.close()


def test_operator_supersession_projects_s003_style_reserved_cash(new_store, tmp_path):
    store = new_store(tmp_path / "supersession-s003-cash.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 55_076.373,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    first_decision = replace(
        decision(OrderSpec("BUY", 5900, "LIMIT", 8.613, "DAY")),
        fee_rate=0.00012,
    )
    advice = FakeAdvice(first_decision)
    accounts = AccountEngine(store, advice)
    accounts.drive_account_decision(
        "s001-v1", prepared=preparation(first_decision)
    )

    reserved = store.virtual_account("s001-v1")
    assert float(reserved["cash"]) == pytest.approx(4253.575)
    assert float(reserved["frozen_cash"]) == pytest.approx(50_822.798)

    advice.value = replace(
        first_decision, decision_id="DEC-TWO", source_decision_id="DEC-TWO",
        signal_identity="8" * 64,
    )
    result = accounts.drive_account_decision(
        "s001-v1", prepared=preparation(advice.value)
    )

    assert result.outcome == "DECISION_AND_INTENTS_SUPERSEDED"
    assert advice.calls[-1][1] == pytest.approx(55_076.373)
    current = [
        row for row in store.account_intents("s001-v1")
        if row["status"] not in TERMINAL_INTENT_STATUSES
    ]
    assert len(current) == 1
    assert current[0]["quantity"] == 5900
    store.close()


def test_operator_supersession_calculation_failure_preserves_old_reservation(new_store, tmp_path):
    store = new_store(tmp_path / "supersession-calculation-failure.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    advice = FakeAdvice(decision(OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY")))
    accounts = AccountEngine(store, advice)
    accounts.drive_account_decision(
        "s001-v1", prepared=preparation(advice.value)
    )
    old_intent = store.account_intents("s001-v1")[0]
    before = store.virtual_account("s001-v1")

    class FailingAdvice:
        def get_decision(self, *_args, **_kwargs):
            raise RuntimeError("simulated calculation failure")

    accounts.advice = FailingAdvice()
    with pytest.raises(RuntimeError, match="simulated calculation failure"):
        accounts.drive_account_decision(
            "s001-v1", prepared=preparation(advice.value)
        )

    after = store.virtual_account("s001-v1")
    assert after["cash"] == before["cash"]
    assert after["frozen_cash"] == before["frozen_cash"]
    assert store.account_intent(old_intent["intent_id"])["status"] == "PENDING_SUBMIT"
    assert len(store.account_decisions("s001-v1")) == 1
    store.close()


def test_operator_supersession_rejects_intent_claimed_during_calculation(new_store, tmp_path):
    store = new_store(tmp_path / "supersession-concurrent-claim.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    advice = FakeAdvice(decision(OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY")))
    accounts = AccountEngine(store, advice)
    accounts.drive_account_decision(
        "s001-v1", prepared=preparation(advice.value)
    )
    old_intent = store.account_intents("s001-v1")[0]

    class ClaimingAdvice(FakeAdvice):
        def get_decision(self, *args, **kwargs):
            value = super().get_decision(*args, **kwargs)
            assert claim_test_intent(store, old_intent["intent_id"])
            return value

    accounts.advice = ClaimingAdvice(replace(
        decision(OrderSpec("BUY", 2000, "LIMIT", 1.67, "DAY")),
        decision_id="DEC-TWO", source_decision_id="DEC-TWO",
    ))
    with pytest.raises(ActiveOrderPendingError, match="状态已变化"):
        accounts.drive_account_decision(
            "s001-v1", prepared=preparation(accounts.advice.value)
        )

    assert store.account_intent(old_intent["intent_id"])["status"] == "SUBMITTING"
    assert len(store.account_decisions("s001-v1")) == 1
    store.close()


def test_operator_cannot_supersede_claimed_intent(new_store, tmp_path):
    store = new_store(tmp_path / "claimed-intent.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    advice = FakeAdvice(decision(OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY")))
    accounts = AccountEngine(store, advice)
    accounts.drive_account_decision(
        "s001-v1", prepared=preparation(advice.value)
    )
    intent = store.account_intents("s001-v1")[0]
    assert claim_test_intent(store, intent["intent_id"])
    advice.value = replace(
        decision(), decision_id="DEC-TWO", source_decision_id="DEC-TWO",
    )

    with pytest.raises(ActiveOrderPendingError, match="禁止替换"):
        accounts.drive_account_decision(
            "s001-v1", prepared=preparation(advice.value)
        )

    assert store.account_intent(intent["intent_id"])["status"] == "SUBMITTING"
    assert len(store.account_decisions("s001-v1")) == 1
    store.close()


def test_operator_supersession_rolls_back_as_one_transaction(new_store, tmp_path, monkeypatch):
    store = new_store(tmp_path / "supersession-rollback.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    advice = FakeAdvice(decision(OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY")))
    accounts = AccountEngine(store, advice)
    first = accounts.drive_account_decision(
        "s001-v1", prepared=preparation(advice.value)
    )
    old_intent = store.account_intents("s001-v1")[0]
    before = store.virtual_account("s001-v1")
    original = store.create_account_immediate_intents

    def fail_new_intents(**kwargs):
        if kwargs["decision_id"] != first.account_status["last_decision"]["decision_id"]:
            raise RuntimeError("simulated new intent persistence failure")
        return original(**kwargs)

    monkeypatch.setattr(store, "create_account_immediate_intents", fail_new_intents)
    advice.value = replace(
        decision(OrderSpec("BUY", 2000, "LIMIT", 1.67, "DAY")),
        decision_id="DEC-TWO", source_decision_id="DEC-TWO",
    )

    with pytest.raises(RuntimeError, match="simulated new intent"):
        accounts.drive_account_decision(
            "s001-v1", prepared=preparation(advice.value)
        )

    after = store.virtual_account("s001-v1")
    assert after["last_decision_id"] == before["last_decision_id"]
    assert after["cash"] == before["cash"]
    assert after["frozen_cash"] == before["frozen_cash"]
    assert store.account_intent(old_intent["intent_id"])["status"] == "PENDING_SUBMIT"
    decisions = store.account_decisions("s001-v1")
    assert len(decisions) == 1 and decisions[0]["status"] == "PENDING"
    assert store.query_audit_events(event_type="DECISION_SUPERSEDED") == []
    assert store.query_audit_events(event_type="ORDER_INTENT_SUPERSEDED") == []
    store.close()


@pytest.mark.parametrize("existing_quantity", [0, 100])
def test_core_setup_partial_and_duplicate_fills_are_exactly_once(new_store, tmp_path, existing_quantity):
    store = new_store(tmp_path / "partial.db")
    try:
        store.create_virtual_account(
            "core", "test", "legacy", "a" * 64, 100000,
            strategy_id="S003", strategy_name_snapshot="test", strategy_version="v1",
            release_hash="c" * 64, qualification_snapshot="PAPER_READY",
            selection_data_cutoff="2026-09-08", symbol="510500.SH",
        )
        adopt_test_decision(store, account_id="core", decision_id="DEC-TEST", valid_session="2026-09-14", legs=[{
                "sequence": 0, "side": "BUY", "quantity": 1000, "order_type": "LIMIT",
                "limit_price": "7.5000", "plan_mode": "CORE_SETUP", "role": "CORE_SETUP",
                "checkpoint": "OPEN", "submit_after": "09:30:00", "submit_before": "09:35:00",
                "dependency_sequence": None, "dependency_required_status": None,
            }])
        store.set_virtual_paused("core", False)
        [intent] = store.create_account_plan_intents(
            account_id="core", decision_id="DEC-TEST", symbol="510500.SH",
            valid_session="2026-09-14", fee_rate="0.0005", legs=[{
                "sequence": 0, "side": "BUY", "quantity": 1000, "order_type": "LIMIT",
                "limit_price": "7.5000", "plan_mode": "CORE_SETUP", "role": "CORE_SETUP",
                "checkpoint": "OPEN", "submit_after": "09:30:00", "submit_before": "09:35:00",
                "dependency_sequence": None, "dependency_required_status": None,
            }],
        )
        assert claim_test_intent(store, intent["intent_id"])
        store.bind_channel_order(intent["intent_id"], "order", {
            "channel_order_id": "order", "symbol": "510500.SH", "side": "BUY",
            "quantity": 1000, "limit_price": 7.5, "status": "SUBMITTED",
            "cumulative_filled_quantity": 0, "average_fill_price": 0,
            "remark": intent["intent_id"],
        })
        def fill(quantity, price="7.4"):
            return store.apply_fill_increment(
                "order", cumulative_quantity=quantity, average_price=price,
                occurred_at="2026-09-14T01:31:00+00:00",
            )
        if existing_quantity:
            with store._lock, store._connection:
                store._connection.execute(
                    "UPDATE virtual_accounts SET quantity=? WHERE account_id='core'",
                    (existing_quantity,),
                )
            before = store.virtual_account("core")
            with pytest.raises(ValueError, match="initially flat"):
                fill(400)
            assert store.virtual_account("core") == before
            assert store.account_fills("core") == []
            return
        fill(400)
        assert store.virtual_account("core")["quantity"] == 400
        assert fill(400) is None
        fill(700, "7.4")
        fill(1000, "7.43")
        final = store.virtual_account("core")
        assert final["quantity"] == final["cycle_target"] == 1000
        assert float(final["cash"]) + float(final["frozen_cash"]) == pytest.approx(92566.285)
        assert fill(1000, "7.43") is None
        assert len(store.account_fills("core")) == 3
        assert store.account_invariant_violations() == []
        with pytest.raises(ValueError, match="cannot decrease"):
            fill(999)
        with pytest.raises(ValueError, match="exceeds"):
            fill(1001)
        assert store.virtual_account("core") == final
    finally:
        store.close()
