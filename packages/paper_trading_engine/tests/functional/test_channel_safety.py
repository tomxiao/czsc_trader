from dataclasses import replace
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from execution_channels.futu.lifecycle import AccountHealth
from execution_channels.futu.broker import (
    BrokerAccount,
    BrokerOrder,
    BrokerOrderRejectedError,
    BrokerSnapshot,
)
from execution_channels.futu.futu_execution import (
    ChannelReconciliationError,
    ChannelExecution,
)
from execution_channels.futu.store import PaperStore
from pte_support import FakeBroker, broker_snapshot, decision, adopt_test_decision, claim_test_intent


# Independent risk: EC21; responsibility-level assertions.
def test_unattributed_futu_cash_blocks_reconciliation_and_submission(memory_store):
    store = memory_store()
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    ChannelExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    broker = FakeBroker()
    broker.value = BrokerSnapshot(
        BrokerAccount("SIMULATE", "CN", 999_900, 999_900, 0), (), (),
    )
    execution = ChannelExecution(store, broker)
    with pytest.raises(ChannelReconciliationError, match="UNATTRIBUTED"):
        execution.refresh_orders()
    assert store.get_setting("futu_cash_reconciliation_status") == "UNATTRIBUTED"
    assert store.get_setting("channel_reconciliation_status") == "BLOCKED"
    assert "FUTU_CASH_RECONCILIATION_UNATTRIBUTED" in execution.status()["alerts"]

    store.set_setting("channel_reconciliation_status", "OK")
    with pytest.raises(ChannelReconciliationError, match="UNATTRIBUTED"):
        execution.submit_pending(reconcile=False)
    assert broker.placed == []
    store.close()


# Independent risk: EC21; responsibility-level assertions.
def test_cn_channel_cash_adjustment_does_not_increase_allocatable_capital(memory_store):
    store = memory_store()
    store.create_channel_reconciliation_account()
    broker = FakeBroker()
    execution = ChannelExecution(store, broker)
    execution.refresh_orders()
    capital = store.capital_pool_balance()
    broker.value = replace(broker.value, account=replace(broker.value.account, cash=1_000_012.34))
    execution.refresh_orders()
    execution.refresh_orders()
    assert float(store.channel_reconciliation_account()["cash"]) == pytest.approx(12.34)
    assert store.capital_pool_balance() == capital
    assert store.account_invariant_violations() == []
    event, = store.query_audit_events(event_type="CHANNEL_CASH_ADJUSTMENT_RECONCILED")
    assert event["details"]["origin"] == "UNCLASSIFIED"


# Independent risk: EC16; responsibility-level assertions.
def test_EC16_C03_system_account_cannot_reserve_for_strategy_order(memory_store):
    store = memory_store()
    reconciliation = store.create_channel_reconciliation_account()
    with pytest.raises(ValueError, match="running strategy account"):
        store.create_account_intent(
            account_id=reconciliation["account_id"], decision_id="DEC-SYSTEM", order_sequence=0,
            symbol="588080.SH", side="BUY", quantity=100, limit_price="1.680",
            valid_session="2026-09-04",
        )


# Independent risk: EC18; responsibility-level assertions.
@pytest.mark.parametrize("failure", ["lost_response"], ids=["EC18-C02"])
def test_ft_pte03_uncertain_submission_recovers_remote_order_once(new_store, tmp_path, monkeypatch, failure):
    class FailingBroker(FakeBroker):
        def place_order(self, intent):
            order = super().place_order(intent)
            if failure == "lost_response":
                raise TimeoutError("broker response lost")
            return order

    store = new_store(tmp_path / "uncertain.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="a" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
    )
    adopt_test_decision(store, account_id="s001-v1", decision_id="DEC-UNCERTAIN",
                        valid_session="2026-09-04", orders=[{"side": "BUY", "quantity": 1000,
                        "order_type": "LIMIT", "limit_price": float("1.680"), "time_in_force": "DAY"}])
    store.set_virtual_paused("s001-v1", False)
    ChannelExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    intent = store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-UNCERTAIN", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04",
    )
    broker = FailingBroker()
    execution = ChannelExecution(store, broker, today=lambda: date(2026, 9, 4))
    if failure == "local_binding":
        original_insert = store._insert_audit_event

        def fail_binding(event):
            if event.event_type == "ORDER_SUBMITTED":
                raise TimeoutError("local binding response lost")
            return original_insert(event)

        monkeypatch.setattr(store, "_insert_audit_event", fail_binding)
    with pytest.raises(TimeoutError, match="response lost"):
        execution.submit_pending()
    account = store.virtual_account("s001-v1")
    assert float(account["frozen_cash"]) > 0
    assert account["health"] == "BLOCKED"
    assert store.account_intent(intent["intent_id"])["status"] == "SUBMISSION_UNCERTAIN"
    assert store.account_decision("s001-v1", "DEC-UNCERTAIN")["status"] == "EXECUTING"
    with pytest.raises(TypeError, match="IntentControlState"):
        store.update_account_intent_status(intent["intent_id"], "PENDING_SUBMIT")
    assert not claim_test_intent(store, intent["intent_id"])
    assert len(broker.placed) == 1
    assert len(broker.value.orders) == 1
    assert store.account_orders("s001-v1") == []
    store.close()
    store = PaperStore(tmp_path / "uncertain.db")
    execution = ChannelExecution(store, broker, today=lambda: date(2026, 9, 4))
    execution.refresh_orders()
    assert store.account_intent(intent["intent_id"])["status"] == "SUBMITTED"
    assert store.virtual_account("s001-v1")["frozen_cash"] == account["frozen_cash"]
    filled = replace(broker.value.orders[0], status="FILLED_ALL",
                     cumulative_filled_quantity=1000, average_fill_price=1.67)
    broker.value = broker_snapshot(orders=(filled,), quantity=1000)
    execution.refresh()
    execution.refresh()
    assert len(broker.placed) == 1
    assert len(store.account_orders("s001-v1")) == 1
    assert len(store.account_fills("s001-v1")) == 1
    assert store.virtual_account("s001-v1")["quantity"] == 1000
    assert float(store.virtual_account("s001-v1")["frozen_cash"]) == 0
    assert store.virtual_account("s001-v1")["health"] == "OK"
    assert len(store.query_audit_events(event_type="ORDER_INTENT_RECOVERED")) == 1
    assert len(store.query_audit_events(event_type="ORDER_FILLED")) == 1
    assert store.account_invariant_violations() == []
    store.close()


# Independent risk: EC18; responsibility-level assertions.
@pytest.mark.parametrize('phase',['rejection','competition'],ids=['EC18-C03','EC18-C04'])
def test_rejection_and_submission_claim_contract(new_store,tmp_path,monkeypatch,phase):
    class RejectingBroker(FakeBroker):
        def place_order(self, intent):
            self.placed.append(intent)
            raise BrokerOrderRejectedError("报单价格不在涨跌停区间")

    store = new_store(tmp_path / "reject.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="a" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
    )
    adopt_test_decision(store, account_id="s001-v1", decision_id="DEC-REJECT",
                        valid_session="2026-09-04", orders=[{"side": "BUY", "quantity": 1000,
                        "order_type": "LIMIT", "limit_price": float("1.680"), "time_in_force": "DAY"}])
    store.set_virtual_paused("s001-v1", False)
    ChannelExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    rejected = store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-REJECT", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04",
    )
    broker = RejectingBroker()
    execution = ChannelExecution(
        store, broker, now=lambda: datetime.fromisoformat("2026-09-04T10:00:00+08:00")
    )
    execution.submit_pending()
    execution.submit_pending()
    assert len(broker.placed) == 1
    assert store.account_intent(rejected["intent_id"])["status"] == "REJECTED"
    assert store.account_intent(rejected["intent_id"])["payload"]["termination_reason"] == "ORDER_REJECTED"
    assert store.virtual_account("s001-v1")["health"] == "OK"
    assert float(store.virtual_account("s001-v1")["frozen_cash"]) == 0
    assert store.account_invariant_violations() == []
    assert len(store.query_audit_events(event_type="ORDER_REJECTED")) == 1

    assert store.account_decision("s001-v1", "DEC-REJECT")["status"] == "INCOMPLETE"
    if phase == "rejection":
        store.close()
        return
    adopt_test_decision(store, account_id="s001-v1", decision_id="DEC-RETRY",
                        valid_session="2026-09-04", orders=[{"side": "BUY", "quantity": 1000,
                        "order_type": "LIMIT", "limit_price": float("1.680"), "time_in_force": "DAY"}])
    assert store.account_decision("s001-v1", "DEC-RETRY")["state_events"][0]["related_decision_id"] == "DEC-REJECT"
    second = store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-RETRY", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04",
    )
    safe_broker = FakeBroker()
    first = ChannelExecution(
        store, safe_broker, now=lambda: datetime.fromisoformat("2026-09-04T10:00:00+08:00")
    )
    other_store = PaperStore(tmp_path / "reject.db")
    second_runner = ChannelExecution(
        other_store, safe_broker, now=lambda: datetime.fromisoformat("2026-09-04T10:00:00+08:00")
    )
    first.refresh_account()
    second_runner.refresh_account()
    barrier = Barrier(2)

    def competing_read(read):
        def read_pending():
            rows = read()
            assert [row["intent_id"] for row in rows] == [second["intent_id"]]
            barrier.wait(timeout=5)
            return rows
        return read_pending

    try:
        with monkeypatch.context() as patch:
            for connection in (store, other_store):
                patch.setattr(connection, "pending_account_intents",
                              competing_read(connection.pending_account_intents))
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda runner: runner.submit_pending(reconcile=False), (first, second_runner)))
    finally:
        other_store.close()
    assert len(safe_broker.placed) == 1
    assert store.account_intent(second["intent_id"])["status"] == "SUBMITTED"
    filled = replace(
        safe_broker.value.orders[0], status="FILLED_ALL",
        cumulative_filled_quantity=1000, average_fill_price=1.67,
    )
    safe_broker.value = broker_snapshot(orders=(filled,), quantity=1000)
    first.refresh_orders()
    store.close()

    # Restart preserves the rejected plan and its independently completed successor.
    migrated = PaperStore(tmp_path / "reject.db")
    migrated_rejection = migrated.account_intent(rejected["intent_id"])
    assert migrated_rejection["attention_required"] is False
    assert not migrated_rejection["resolution_note"]
    assert migrated.account_decision("s001-v1", "DEC-REJECT")["status"] == "INCOMPLETE"
    assert migrated.account_decision("s001-v1", "DEC-RETRY")["status"] == "COMPLETED"
    assert migrated.attention_account_intents("s001-v1") == []
    migration_count = len(migrated.query_audit_events(
        event_type="ACCOUNT_EXECUTION_MIGRATED",
    ))
    migrated.close()
    reopened = PaperStore(tmp_path / "reject.db")
    assert len(reopened.query_audit_events(
        event_type="ACCOUNT_EXECUTION_MIGRATED",
    )) == migration_count
    reopened.close()


# Independent risk: EC31; responsibility-level assertions.
def test_confirmed_rejection_preserves_unrelated_health_block(memory_store):
    class RejectingBroker(FakeBroker):
        def place_order(self, intent):
            self.placed.append(intent)
            store.set_virtual_health("s001-v1", AccountHealth.BLOCKED, "人工资金复核未完成")
            raise BrokerOrderRejectedError("报单价格不在涨跌停区间")

    store = memory_store()
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="a" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
    )
    store.set_virtual_paused("s001-v1", False)
    adopt_test_decision(
        store, account_id="s001-v1", decision_id="DEC-REJECT", valid_session="2026-09-04",
        orders=[{"side": "BUY", "quantity": 1000, "order_type": "LIMIT", "limit_price": 1.68}],
    )
    ChannelExecution(
        store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00"),
    ).refresh_orders()
    intent = store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-REJECT", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04",
    )
    broker = RejectingBroker()
    execution = ChannelExecution(
        store, broker, now=lambda: datetime.fromisoformat("2026-09-04T10:00:00+08:00"),
    )
    execution.submit_pending()
    resolved = store.account_intent(intent["intent_id"])
    assert resolved["attention_required"] is False
    account = store.virtual_account("s001-v1")
    assert account["health"] is AccountHealth.BLOCKED
    assert account["last_error"] == "人工资金复核未完成"
    assert store.attention_account_intents("s001-v1") == []
    assert store.query_audit_events(event_type="EXECUTION_GAP_ACKNOWLEDGED") == []
    assert store.query_audit_events(event_type="ACCOUNT_RECONCILIATION_RECOVERED") == []
    assert store.account_orders("s001-v1") == []
    assert store.account_fills("s001-v1") == []
    store.close()


# Independent risk: EC18; responsibility-level assertions.


# Independent risk: EC19; responsibility-level assertions.
def test_ft_pte03_missing_broker_order_and_overfill_block_without_mutating_ledger(memory_store):
    store = memory_store()
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="a" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
    )
    adopt_test_decision(store, account_id="s001-v1", decision_id="DEC-MISSING",
                        valid_session="2026-09-04", orders=[{"side": "BUY", "quantity": 1000,
                        "order_type": "LIMIT", "limit_price": float("1.680"), "time_in_force": "DAY"}])
    store.set_virtual_paused("s001-v1", False)
    ChannelExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    intent = store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-MISSING", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04",
    )
    assert claim_test_intent(store, intent["intent_id"])
    order = BrokerOrder(
        "3001", "588080.SH", "BUY", 1000, 1.68,
        "SUBMITTED", 0, 0, intent["intent_id"],
    )
    store.bind_channel_order(intent["intent_id"], "3001", order.__dict__)
    account_before = store.virtual_account("s001-v1")
    with pytest.raises(ValueError, match="exceeds intent quantity"):
        store.apply_fill_increment(
            "3001", cumulative_quantity=1100, average_price=1.67,
            occurred_at="2026-09-04T10:01:00+08:00",
        )
    account_after = store.virtual_account("s001-v1")
    assert account_after["cash"] == account_before["cash"]
    assert account_after["frozen_cash"] == account_before["frozen_cash"]
    assert account_after["quantity"] == 0
    assert store.account_fills("s001-v1") == []

    execution = ChannelExecution(
        store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-04T10:00:00+08:00")
    )
    with pytest.raises(ChannelReconciliationError, match="不存在"):
        execution.refresh_orders()
    assert store.get_setting("channel_reconciliation_status") == "BLOCKED"
    assert store.virtual_account("s001-v1")["health"] == "BLOCKED"
    store.close()


# Independent risk: EC17; separate execution/refusal boundary.
def test_ft_pte03_channel_and_account_pause_block_pending_submission(memory_store):
    store = memory_store()
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="a" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
    )
    adopt_test_decision(store, account_id="s001-v1", decision_id="DEC-PAUSE",
                        valid_session="2026-09-04", orders=[{"side": "BUY", "quantity": 1000,
                        "order_type": "LIMIT", "limit_price": float("1.680"), "time_in_force": "DAY"}])
    store.set_virtual_paused("s001-v1", False)
    ChannelExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-PAUSE", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04",
    )
    broker = FakeBroker()
    execution = ChannelExecution(store, broker, symbol="588080.SH", today=lambda: date(2026, 9, 4))
    execution.refresh_account()
    execution.pause()
    execution.submit_pending()
    assert broker.placed == []
    execution.resume()
    store.set_virtual_paused("s001-v1", True)
    execution.submit_pending()
    assert broker.placed == []
    store.close()


# Independent risk: EC19; terminal partial reports are not completion.



# Independent risk: EC18; timeout is not a confirmed zero fill.


def test_EC16_C04_system_account_cannot_adopt_strategy_identity(memory_store):
    store = memory_store()
    account = store.create_channel_reconciliation_account()
    before = tuple(store._connection.iterdump())
    with pytest.raises(ValueError,match='inactive account cannot save decisions'):
        store.save_account_decision(account['account_id'],decision().to_store_payload())
    assert tuple(store._connection.iterdump()) == before
    assert store.virtual_account(account['account_id'])['account_type'] == account['account_type']
