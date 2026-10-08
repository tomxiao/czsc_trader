from dataclasses import replace
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import sqlite3
from types import SimpleNamespace

import pytest

from paper_trading_engine.audit import AuditRecorder
from paper_trading_engine.account_engine import AccountDecisionBlockedError, AccountEngine
from paper_trading_engine.broker import (
    BrokerAccount,
    BrokerOrder,
    BrokerOrderRejectedError,
    BrokerPosition,
    BrokerSnapshot,
    OrderIntent,
    PaperTradingSafetyError,
)
from paper_trading_engine.futu_execution import (
    ChannelReconciliationError,
    FutuExecution,
    OrderSubmissionBatchError,
)
from paper_trading_engine.futu_gateway import FutuGateway, FutuGatewayError
from paper_trading_engine.coordinator import PteCoordinator, ReconnectableExecution
from paper_trading_engine.store import PaperStore
from paper_trading_engine.contracts import OrderSpec
from pte_support import FakeAdvice, FakeBroker, broker_snapshot, decision, preparation, adopt_test_decision, claim_test_intent


def test_manual_refresh_propagates_channel_failure(new_store, tmp_path):
    store = new_store(tmp_path / "manual-refresh.db")

    class Accounts:
        def __init__(self):
            self.store = store

    class StrategyCycle:
        called = False

        def latest_completed_signal_date(self, *, at=None):
            del at
            self.called = True
            return date(2026, 9, 1)

    class Execution:
        def refresh(self):
            raise RuntimeError("Futu unavailable")

    accounts = Accounts()
    strategy_cycle = StrategyCycle()
    coordinator = PteCoordinator(accounts, Execution(), strategy_cycle=strategy_cycle)
    with pytest.raises(RuntimeError, match="Futu unavailable"):
        coordinator.refresh()
    assert strategy_cycle.called is False
    events = store.query_audit_events(event_type="DEPENDENCY_DEGRADED")
    assert len(events) == 1
    assert events[0]["details"]["operation"] == "refresh"
    store.close()


def test_startup_only_allows_explicit_unavailable_channel_degradation(new_store, tmp_path):
    store = new_store(tmp_path / "startup-degradation.db")

    class Accounts:
        def __init__(self):
            self.store = store

    class UnavailableChannel:
        def refresh(self):
            raise ConnectionError("OpenD unavailable")

        @staticmethod
        def status():
            return {
                "environment": "SIMULATE", "symbol": "588080.SH",
                "reconciliation_status": "UNAVAILABLE",
                "alerts": ["CHANNEL_UNAVAILABLE"],
            }

    degraded = PteCoordinator(
        Accounts(), UnavailableChannel(), strategy_cycle=object()
    ).startup()
    assert degraded["channel"]["reconciliation_status"] == "UNAVAILABLE"

    class UnsafeChannel(UnavailableChannel):
        @staticmethod
        def status():
            return {
                "environment": "SIMULATE", "symbol": "588080.SH",
                "reconciliation_status": "BLOCKED",
                "alerts": ["CHANNEL_RECONCILIATION_BLOCKED"],
            }

    with pytest.raises(ConnectionError, match="OpenD unavailable"):
        PteCoordinator(
            Accounts(), UnsafeChannel(), strategy_cycle=object()
        ).startup()
    store.close()


def test_blocked_pending_intent_expires_and_releases_reserved_cash(new_store, tmp_path):
    store = new_store(tmp_path / "blocked-expiry.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    adopt_test_decision(store, account_id="s001-v1", decision_id="DEC-EXPIRED",
                        valid_session="2026-09-02", orders=[{"side": "BUY", "quantity": 1000,
                        "order_type": "LIMIT", "limit_price": float("1.680"), "time_in_force": "DAY"}])
    store.set_virtual_paused("s001-v1", False)
    FutuExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    intent = store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-EXPIRED", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-02",
    )
    store.set_virtual_health("s001-v1", "BLOCKED", "等待对账")
    execution = FutuExecution(
        store, FakeBroker(),
        now=lambda: datetime.fromisoformat("2026-09-03T10:00:00+08:00"),
    )
    execution.submit_pending()
    expired = store.account_intent(intent["intent_id"])
    account = store.virtual_account("s001-v1")
    assert expired["status"] == "EXPIRED"
    assert expired["attention_required"] is True
    assert float(account["frozen_cash"]) == 0
    assert len(store.query_audit_events(event_type="DECISION_EXPIRED")) == 1
    store.close()


def test_unattributed_futu_cash_blocks_reconciliation_and_submission(new_store, tmp_path):
    store = new_store(tmp_path / "cash-gate.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    FutuExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    broker = FakeBroker()
    broker.value = BrokerSnapshot(
        BrokerAccount("SIMULATE", "CN", 999_900, 999_900, 0), (), (),
    )
    execution = FutuExecution(store, broker)
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


def test_ft_pte03_estimated_fees_reconcile_to_futu_cash_exactly_once(new_store, tmp_path):
    store = new_store(tmp_path / "fee-reconciliation.db")
    store.create_virtual_account(
        "s001-v2", "S001-v2模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v2", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
    )
    store.set_virtual_paused("s001-v2", False)
    FutuExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    store.create_channel_reconciliation_account()
    adopt_test_decision(store, account_id="s001-v2", decision_id="DEC-BUY",
                        valid_session="2026-09-04", orders=[{"side": "BUY", "quantity": 1000,
                        "order_type": "LIMIT", "limit_price": float("1.680"), "time_in_force": "DAY"}])
    buy = store.create_account_intent(
        account_id="s001-v2", decision_id="DEC-BUY", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04", fee_rate="0.0005",
    )
    broker = FakeBroker()
    execution = FutuExecution(
        store, broker, now=lambda: datetime.fromisoformat("2026-09-04T10:00:00+08:00"),
    )
    execution.submit_pending()
    filled_buy = replace(
        broker.value.orders[0], status="FILLED_ALL",
        cumulative_filled_quantity=1000, average_fill_price=1.67,
    )
    broker.value = BrokerSnapshot(
        BrokerAccount("SIMULATE", "CN", 998_326.66, 999_996.66, 0),
        (BrokerPosition("588080.SH", 1000),), (filled_buy,),
    )
    execution.refresh_orders()
    bought = store.virtual_account("s001-v2")
    assert float(bought["cash"]) == pytest.approx(98_329.165)
    assert float(bought["average_cost"]) == pytest.approx(1.670835)
    assert float(store.channel_reconciliation_account()["cash"]) == pytest.approx(-2.505)
    assert store.get_setting("futu_cash_reconciliation_status") == "OK"
    assert len(store.query_audit_events(event_type="CHANNEL_FEE_VARIANCE_RECONCILED")) == 1

    # Repeating the same broker snapshot is idempotent.
    execution.refresh_orders()
    assert float(store.virtual_account("s001-v2")["cash"]) == pytest.approx(98_329.165)
    assert len(store.query_audit_events(event_type="CHANNEL_FEE_VARIANCE_RECONCILED")) == 1

    adopt_test_decision(store, account_id="s001-v2", decision_id="DEC-SELL",
                        valid_session="2026-09-04", orders=[{"side": "SELL", "quantity": 1000,
                        "order_type": "MARKET", "limit_price": float("1.600"), "time_in_force": "DAY"}])
    store.create_account_intent(
        account_id="s001-v2", decision_id="DEC-SELL", order_sequence=0,
        symbol="588080.SH", side="SELL", quantity=1000,
        limit_price="1.600", valid_session="2026-09-04", fee_rate="0.0005",
    )
    execution.submit_pending()
    sell_order = next(row for row in broker.value.orders if row.side == "SELL")
    filled_sell = replace(
        sell_order, status="FILLED_ALL",
        cumulative_filled_quantity=1000, average_fill_price=1.60,
    )
    broker.value = BrokerSnapshot(
        BrokerAccount("SIMULATE", "CN", 999_923.46, 999_923.46, 0),
        (), (filled_buy, filled_sell),
    )
    execution.refresh_orders()
    closed = store.virtual_account("s001-v2")
    assert float(closed["cash"]) == pytest.approx(99_928.365)
    assert float(closed["total_assets"]) == pytest.approx(99_928.365)
    assert float(closed["realized_pnl"]) == pytest.approx(-71.635)
    assert float(store.channel_reconciliation_account()["cash"]) == pytest.approx(-4.905)
    assert store.account_invariant_violations() == []
    assert len(store.query_audit_events(event_type="CHANNEL_FEE_VARIANCE_RECONCILED")) == 2
    assert store.account_intent(buy["intent_id"])["status"] == "FILLED_ALL"
    store.close()

    # Reopening schema v4 preserves financial evidence without implicit rewrites.
    with sqlite3.connect(tmp_path / "fee-reconciliation.db") as connection:
        connection.execute(
            "UPDATE virtual_accounts SET realized_pnl='-75.0000' WHERE account_id='s001-v2'"
        )
        connection.execute(
            "UPDATE fills SET realized_pnl='-75.0000' WHERE account_id='s001-v2' AND side='SELL'"
        )
    migrated = PaperStore(tmp_path / "fee-reconciliation.db")
    assert float(migrated.virtual_account("s001-v2")["realized_pnl"]) == pytest.approx(-75)
    assert sum(float(row["realized_pnl"]) for row in migrated.account_fills("s001-v2")) == (
        pytest.approx(-75)
    )
    migration_count = len(migrated.query_audit_events(event_type="ACCOUNT_EXECUTION_MIGRATED"))
    migrated.close()
    reopened = PaperStore(tmp_path / "fee-reconciliation.db")
    assert len(reopened.query_audit_events(event_type="ACCOUNT_EXECUTION_MIGRATED")) == (
        migration_count
    )
    reopened.close()


def test_ft_pte03_accepts_fixed_futu_fees_for_a_small_order(new_store, tmp_path):
    store = new_store(tmp_path / "small-order-fees.db")
    store.create_virtual_account(
        "s003-v1", "S003-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S003", strategy_name_snapshot="成分资金流宽度早盘延续",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-08",
        symbol="510500.SH",
    )
    store.set_virtual_paused("s003-v1", False)
    FutuExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    store.create_channel_reconciliation_account()
    adopt_test_decision(store, account_id="s003-v1", decision_id="DEC-SMALL-BUY",
                        valid_session="2026-09-21", orders=[{"side": "BUY", "quantity": 400,
                        "order_type": "LIMIT", "limit_price": float("8.613"), "time_in_force": "DAY"}])
    store.create_account_intent(
        account_id="s003-v1", decision_id="DEC-SMALL-BUY", order_sequence=0,
        symbol="510500.SH", side="BUY", quantity=400,
        limit_price="8.613", valid_session="2026-09-21", fee_rate="0.00012",
    )
    broker = FakeBroker()
    execution = FutuExecution(
        store, broker, now=lambda: datetime.fromisoformat("2026-09-21T09:30:00+08:00"),
    )
    execution.submit_pending()
    filled_buy = replace(
        broker.value.orders[0], status="FILLED_ALL",
        cumulative_filled_quantity=400, average_fill_price=7.871,
    )
    broker.value = BrokerSnapshot(
        BrokerAccount("SIMULATE", "CN", 996_833.321, 999_981.721, 0),
        (BrokerPosition("510500.SH", 400),), (filled_buy,),
    )

    execution.refresh_orders()

    account = store.virtual_account("s003-v1")
    assert float(account["cash"]) == pytest.approx(96_851.2222)
    assert float(store.channel_reconciliation_account()["cash"]) == pytest.approx(-17.9012)
    assert store.get_setting("futu_cash_reconciliation_status") == "OK"
    events = store.query_audit_events(event_type="CHANNEL_FEE_VARIANCE_RECONCILED")
    assert events[0]["details"]["actual_fee"] == "18.2790"
    assert events[0]["details"]["maximum_fee"] == "36.7420"
    assert events[0]["details"]["broker_order_count"] == 1
    assert store.account_invariant_violations() == []
    store.close()


def test_ft_pte03_blocks_implausible_small_order_cash_charge(new_store, tmp_path):
    store = new_store(tmp_path / "implausible-small-order-fees.db")
    store.create_virtual_account(
        "s003-v1", "S003-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S003", strategy_name_snapshot="成分资金流宽度早盘延续",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-08",
        symbol="510500.SH",
    )
    store.set_virtual_paused("s003-v1", False)
    FutuExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    store.create_channel_reconciliation_account()
    adopt_test_decision(store, account_id="s003-v1", decision_id="DEC-IMPLAUSIBLE-FEE",
                        valid_session="2026-09-21", orders=[{"side": "BUY", "quantity": 400,
                        "order_type": "LIMIT", "limit_price": float("8.613"), "time_in_force": "DAY"}])
    store.create_account_intent(
        account_id="s003-v1", decision_id="DEC-IMPLAUSIBLE-FEE", order_sequence=0,
        symbol="510500.SH", side="BUY", quantity=400,
        limit_price="8.613", valid_session="2026-09-21", fee_rate="0.00012",
    )
    broker = FakeBroker()
    execution = FutuExecution(
        store, broker, now=lambda: datetime.fromisoformat("2026-09-21T09:30:00+08:00"),
    )
    execution.submit_pending()
    filled_buy = replace(
        broker.value.orders[0], status="FILLED_ALL",
        cumulative_filled_quantity=400, average_fill_price=7.871,
    )
    broker.value = BrokerSnapshot(
        BrokerAccount("SIMULATE", "CN", 996_751.6, 999_900, 0),
        (BrokerPosition("510500.SH", 400),), (filled_buy,),
    )

    with pytest.raises(ChannelReconciliationError, match="OUT_OF_RANGE"):
        execution.refresh_orders()

    assert store.get_setting("futu_cash_reconciliation_status") == "OUT_OF_RANGE"
    assert store.get_setting("channel_reconciliation_status") == "BLOCKED"
    assert store.channel_reconciliation_account()["cash"] == "0.0000"
    store.close()


def test_ft_pte03_rejects_undefined_execution_channel_and_protects_system_account(new_store, tmp_path):
    store = new_store(tmp_path / "strict-channel.db")
    reconciliation = store.create_channel_reconciliation_account()
    with pytest.raises(ValueError, match="running strategy account"):
        store.create_account_intent(
            account_id=reconciliation["account_id"], decision_id="DEC-SYSTEM", order_sequence=0,
            symbol="588080.SH", side="BUY", quantity=100, limit_price="1.680",
            valid_session="2026-09-04",
        )
    broker = FakeBroker()
    broker.channel_id = "futu"
    with pytest.raises(PaperTradingSafetyError, match="futu_simulate_cn"):
        FutuExecution(store, broker).refresh_account()


def test_ft_pte03_multiple_accounts_share_only_safe_futu_channel(new_store, tmp_path):
    store = new_store(tmp_path / "shared-futu.db")
    for account_id, strategy, version, marker, symbol in (
        ("s001-v1", "S001", "v1", "a", "588080.SH"),
        ("s001-v2", "S001", "v2", "b", "588080.SH"),
        ("s002-v1", "S002", "v1", "c", "510500.SH"),
    ):
        store.create_virtual_account(
            account_id, f"{account_id}模拟账户", "legacy", marker * 64, 100_000,
            strategy_id=strategy, strategy_name_snapshot="测试策略",
            strategy_version=version, release_hash=marker * 64,
            qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
            symbol=symbol,
        )
        store.set_virtual_paused(account_id, False)
        FutuExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    adopt_test_decision(store, account_id="s001-v2", decision_id="DEC-2",
                        valid_session="2026-09-04", orders=[{"side": "BUY", "quantity": 1000,
                        "order_type": "LIMIT", "limit_price": float("1.680"), "time_in_force": "DAY"}])
    first_intent = store.create_account_intent(
        account_id="s001-v2", decision_id="DEC-2", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04",
    )
    adopt_test_decision(store, account_id="s002-v1", decision_id="DEC-3",
                        valid_session="2026-09-04", orders=[{"side": "BUY", "quantity": 1000,
                        "order_type": "LIMIT", "limit_price": float("7.500"), "time_in_force": "DAY"}])
    store.create_account_intent(
        account_id="s002-v1", decision_id="DEC-3", order_sequence=0,
        symbol="510500.SH", side="BUY", quantity=1000,
        limit_price="7.500", valid_session="2026-09-04",
    )
    assert first_intent["intent_id"].startswith("PTE-")
    assert len(first_intent["intent_id"]) <= 24
    broker = FakeBroker()
    execution = FutuExecution(store, broker, symbol="588080.SH", today=lambda: date(2026, 9, 4))
    execution.refresh_account()
    execution.submit_pending()
    submitted = broker.value.orders
    filled = tuple(
        replace(
            order, status="FILLED_ALL", cumulative_filled_quantity=1000,
            average_fill_price=1.67 if order.symbol == "588080.SH" else 7.49,
        )
        for order in submitted
    )
    cash = 1_000_000 - sum(
        order.average_fill_price * order.cumulative_filled_quantity * 1.0005
        for order in filled
    )
    broker.value = BrokerSnapshot(
        BrokerAccount("SIMULATE", "CN", cash, 1_000_000, 0),
        (BrokerPosition("588080.SH", 1000), BrokerPosition("510500.SH", 1000)),
        filled,
    )
    execution.refresh_orders()
    assert store.virtual_account("s001-v1")["quantity"] == 0
    assert store.virtual_account("s001-v2")["quantity"] == 1000
    assert store.virtual_account("s002-v1")["quantity"] == 1000

    foreign = replace(
        submitted[0], channel_order_id="9999", quantity=100,
        status="SUBMITTED", cumulative_filled_quantity=0, remark="MANUAL",
    )
    broker.value = BrokerSnapshot(
        broker.value.account,
        (BrokerPosition("588080.SH", 1000), BrokerPosition("510500.SH", 1000)),
        (foreign,),
    )
    with pytest.raises(ChannelReconciliationError, match="无法归属"):
        execution.refresh_orders()
    assert store.get_setting("channel_reconciliation_status") == "BLOCKED"
    store.close()

    class TradeContext:
        def __init__(self): self.place_calls, self.modify_calls = [], []
        def get_acc_list(self): return 0, [{"acc_id": 77, "trd_env": "SIMULATE", "trd_market": "CN"}]
        def accinfo_query(self, **kwargs): return 0, [{
            "cash": 900_000, "market_val": 100_000,
            "total_assets": 1_000_000, "frozen_cash": 0,
        }]
        def position_list_query(self, **kwargs): return 0, []
        def order_list_query(self, **kwargs): return 0, []
        def place_order(self, **kwargs):
            self.place_calls.append(kwargs)
            return 0, [{"order_id": "124", "code": kwargs["code"], "trd_side": kwargs["trd_side"], "qty": kwargs["qty"], "price": kwargs["price"], "order_type": kwargs["order_type"], "order_status": "SUBMITTING", "dealt_qty": 0, "dealt_avg_price": 0, "remark": kwargs["remark"]}]
        def modify_order(self, **kwargs):
            self.modify_calls.append(kwargs)
            return 0, []
        def close(self):
            pass

    sdk = SimpleNamespace(
        RET_OK=0, TrdEnv=SimpleNamespace(SIMULATE="SIMULATE"),
        TrdMarket=SimpleNamespace(CN="CN"), TrdSide=SimpleNamespace(BUY="BUY", SELL="SELL"),
        OrderType=SimpleNamespace(NORMAL="NORMAL", MARKET="MARKET"),
        TimeInForce=SimpleNamespace(DAY="DAY"),
        ModifyOrderOp=SimpleNamespace(CANCEL="CANCEL"),
        SysConfig=SimpleNamespace(enable_console_log=lambda enabled: None),
    )
    audit_store = new_store(tmp_path / "gateway.db")
    trade = TradeContext()
    gateway = FutuGateway(
        symbol="588080.SH", sdk=sdk, trade_context=trade,
        audit=AuditRecorder(audit_store),
    )
    snapshot = gateway.account_snapshot()
    assert snapshot.account.environment == "SIMULATE"
    assert snapshot.account.market_value == pytest.approx(100_000)
    gateway.place_order(OrderIntent("PTE-s001-v1-X", "DEC-X", "588080.SH", "BUY", 1000, 1.68))
    assert trade.place_calls[0]["trd_env"] == "SIMULATE"
    assert trade.place_calls[0]["adjust_limit"] == 0
    gateway.place_order(OrderIntent("PTE-s002-v1-X", "DEC-Y", "510500.SH", "BUY", 1000, 7.5))
    assert trade.place_calls[1]["code"] == "SH.510500"
    gateway.place_order(OrderIntent(
        "PTE-s001-v2-X", "DEC-M", "588080.SH", "SELL", 1000, 1.6,
        order_type="MARKET",
    ))
    assert trade.place_calls[2]["order_type"] == "MARKET"
    with pytest.raises(PaperTradingSafetyError, match="China-market"):
        gateway.place_order(OrderIntent("PTE-X", "DEC-Z", "AAPL.US", "BUY", 1000, 1.0))
    audit_store.close()


def test_ft_pte03_failed_or_cancelled_buy_releases_reserved_cash(new_store, tmp_path):
    store = new_store(tmp_path / "release-cash.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="a" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
    )
    adopt_test_decision(store, account_id="s001-v1", decision_id="DEC-FAIL",
                        valid_session="2026-09-04", orders=[{"side": "BUY", "quantity": 1000,
                        "order_type": "LIMIT", "limit_price": float("1.680"), "time_in_force": "DAY"}])
    store.set_virtual_paused("s001-v1", False)
    FutuExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    intent = store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-FAIL", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04",
    )
    assert float(store.virtual_account("s001-v1")["frozen_cash"]) > 0

    store.release_account_intent(intent["intent_id"], "SUBMISSION_FAILED")
    account = store.virtual_account("s001-v1")
    assert float(account["cash"]) == 100_000
    assert float(account["frozen_cash"]) == 0
    assert store.account_intent(intent["intent_id"])["status"] == "SUBMISSION_FAILED"

    adopt_test_decision(store, account_id="s001-v1", decision_id="DEC-CANCEL",
                        valid_session="2026-09-04", orders=[{"side": "BUY", "quantity": 1000,
                        "order_type": "LIMIT", "limit_price": float("1.680"), "time_in_force": "DAY"}])
    second = store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-CANCEL", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04",
    )
    assert claim_test_intent(store, second["intent_id"])
    store.bind_channel_order(second["intent_id"], "2001", {
        "channel_order_id": "2001", "symbol": "588080.SH", "side": "BUY",
        "quantity": 1000, "limit_price": 1.68, "status": "SUBMITTED",
        "cumulative_filled_quantity": 0, "average_fill_price": 0,
        "remark": second["intent_id"],
    })
    store.update_channel_order_report("2001", {
        "channel_order_id": "2001", "symbol": "588080.SH", "side": "BUY",
        "quantity": 1000, "limit_price": 1.68, "status": "CANCELLED_ALL",
        "cumulative_filled_quantity": 0, "average_fill_price": 0,
        "remark": second["intent_id"],
    })
    account = store.virtual_account("s001-v1")
    assert float(account["cash"]) == 100_000
    assert float(account["frozen_cash"]) == 0
    store.close()


def test_ft_pte03_channel_and_account_pause_block_pending_submission(new_store, tmp_path):
    store = new_store(tmp_path / "pause.db")
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
    FutuExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-PAUSE", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04",
    )
    broker = FakeBroker()
    execution = FutuExecution(store, broker, symbol="588080.SH", today=lambda: date(2026, 9, 4))
    execution.refresh_account()
    execution.pause()
    execution.submit_pending()
    assert broker.placed == []
    execution.resume()
    store.set_virtual_paused("s001-v1", True)
    execution.submit_pending()
    assert broker.placed == []
    store.close()


@pytest.mark.parametrize("failure", ["lost_response", "local_binding"])
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
    FutuExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    intent = store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-UNCERTAIN", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04",
    )
    broker = FailingBroker()
    execution = FutuExecution(store, broker, today=lambda: date(2026, 9, 4))
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
    execution = FutuExecution(store, broker, today=lambda: date(2026, 9, 4))
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


def test_ft_pte03_explicit_rejection_releases_cash_and_duplicate_submit_is_atomic(new_store, tmp_path, monkeypatch):
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
    FutuExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    rejected = store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-REJECT", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04",
    )
    broker = RejectingBroker()
    execution = FutuExecution(
        store, broker, now=lambda: datetime.fromisoformat("2026-09-04T10:00:00+08:00")
    )
    with pytest.raises(OrderSubmissionBatchError, match="BrokerOrderRejectedError"):
        execution.submit_pending()
    assert store.account_intent(rejected["intent_id"])["status"] == "REJECTED"
    assert float(store.virtual_account("s001-v1")["frozen_cash"]) == 0
    assert store.account_invariant_violations() == []
    assert len(store.query_audit_events(event_type="ORDER_REJECTED")) == 1

    execution.acknowledge_execution_gap(
        "s001-v1", rejected["intent_id"], "已确认拒单无成交，创建独立替代计划",
    )
    assert store.account_decision("s001-v1", "DEC-REJECT")["status"] == "INCOMPLETE"
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
    first = FutuExecution(
        store, safe_broker, now=lambda: datetime.fromisoformat("2026-09-04T10:00:00+08:00")
    )
    other_store = PaperStore(tmp_path / "reject.db")
    second_runner = FutuExecution(
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
    assert migrated_rejection["resolution_note"] == "已确认拒单无成交，创建独立替代计划"
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


def test_ft_pte03_incomplete_and_unknown_orders_never_silently_recover(new_store, tmp_path):
    partial_store = new_store(tmp_path / "partial-cancel.db")
    partial_store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    adopt_test_decision(partial_store, account_id="s001-v1", decision_id="DEC-PARTIAL",
                        valid_session="2026-09-02", orders=[{"side": "BUY", "quantity": 1000,
                        "order_type": "LIMIT", "limit_price": float("1.680"), "time_in_force": "DAY"}])
    partial_store.set_virtual_paused("s001-v1", False)
    FutuExecution(partial_store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    partial = partial_store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-PARTIAL", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-02",
    )
    partial_broker = FakeBroker()
    partial_execution = FutuExecution(
        partial_store, partial_broker, today=lambda: date(2026, 9, 2),
    )
    partial_execution.submit_pending()
    cancelled = replace(
        partial_broker.value.orders[0], status="CANCELLED_PART",
        cumulative_filled_quantity=400, average_fill_price=1.67,
    )
    partial_broker.value = broker_snapshot(orders=(cancelled,), quantity=400)
    partial_execution.refresh_orders()
    account = partial_store.virtual_account("s001-v1")
    intent = partial_store.account_intent(partial["intent_id"])
    assert intent["status"] == "CANCELLED_PART"
    assert intent["attention_required"] is True
    assert account["health"] == "BLOCKED"
    assert float(account["frozen_cash"]) == 0
    assert partial_store.account_invariant_violations() == []
    partial_execution.acknowledge_execution_gap(
        "s001-v1", partial["intent_id"], "已确认部分成交，保留实际400股持仓",
    )
    assert partial_store.virtual_account("s001-v1")["health"] == "OK"
    assert partial_store.attention_account_intents("s001-v1") == []
    adopt_test_decision(partial_store, account_id="s001-v1", decision_id="DEC-CLOSE",
                        valid_session="2026-09-02", orders=[{"side": "SELL", "quantity": 400,
                        "order_type": "MARKET", "limit_price": float("1.600"), "time_in_force": "DAY"}])
    partial_store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-CLOSE", order_sequence=0,
        symbol="588080.SH", side="SELL", quantity=400,
        limit_price="1.600", valid_session="2026-09-02", order_type="MARKET",
    )
    partial_execution.submit_pending()
    sell_order = next(order for order in partial_broker.value.orders if order.side == "SELL")
    sold = replace(
        sell_order, status="FILLED_ALL", cumulative_filled_quantity=400,
        average_fill_price=1.60,
    )
    partial_broker.value = broker_snapshot(orders=(cancelled, sold), quantity=0)
    partial_execution.refresh_orders()
    closed = partial_store.virtual_account("s001-v1")
    assert closed["quantity"] == 0
    assert float(closed["cash"]) - 100_000 == pytest.approx(float(closed["realized_pnl"]))
    assert partial_store.account_invariant_violations() == []
    partial_store.close()

    timeout_store = new_store(tmp_path / "timeout.db")
    timeout_store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    adopt_test_decision(timeout_store, account_id="s001-v1", decision_id="DEC-TIMEOUT",
                        valid_session="2026-09-02", orders=[{"side": "BUY", "quantity": 1000,
                        "order_type": "LIMIT", "limit_price": float("1.680"), "time_in_force": "DAY"}])
    timeout_store.set_virtual_paused("s001-v1", False)
    FutuExecution(timeout_store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    timeout = timeout_store.create_account_intent(
        account_id="s001-v1", decision_id="DEC-TIMEOUT", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-02",
    )
    timeout_broker = FakeBroker()
    timeout_execution = FutuExecution(
        timeout_store, timeout_broker, today=lambda: date(2026, 9, 2),
    )
    timeout_execution.submit_pending()
    unknown = replace(timeout_broker.value.orders[0], status="TIMEOUT")
    timeout_broker.value = replace(
        timeout_broker.value,
        orders=(replace(unknown, status="FUTURE_UNKNOWN_STATUS"),),
    )
    with pytest.raises(ChannelReconciliationError, match="不一致"):
        timeout_execution.refresh_orders()
    timeout_broker.value = replace(timeout_broker.value, orders=(unknown,))
    timeout_execution.refresh_orders()
    assert timeout_store.virtual_account("s001-v1")["health"] == "BLOCKED"
    assert [row["intent_id"] for row in timeout_store.unresolved_account_intents()] == [
        timeout["intent_id"]
    ]
    filled = replace(
        unknown, status="FILLED_ALL", cumulative_filled_quantity=1000,
        average_fill_price=1.67,
    )
    timeout_broker.value = broker_snapshot(orders=(filled,), quantity=1000)
    timeout_execution.refresh_orders()
    assert timeout_store.virtual_account("s001-v1")["health"] == "OK"
    assert timeout_store.unresolved_account_intents() == []
    assert timeout_store.account_invariant_violations() == []
    timeout_store.close()


def test_ft_pte03_rejected_decision_remains_blocked_until_operator_review(new_store, tmp_path):
    class RejectingBroker(FakeBroker):
        def place_order(self, intent):
            self.placed.append(intent)
            raise BrokerOrderRejectedError("模拟拒单")

    store = new_store(tmp_path / "persistent-rejection.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    FutuExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
    advice = FakeAdvice(decision(OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY")))
    accounts = AccountEngine(
        store, advice,
        now=lambda: datetime.fromisoformat("2026-09-01T20:30:00+08:00"),
    )
    prepared = preparation(advice.value)
    accounts.refresh_account("s001-v1", prepared=prepared)
    execution = FutuExecution(
        store, RejectingBroker(), now=lambda: datetime.fromisoformat("2026-09-02T10:00:00+08:00"),
    )
    with pytest.raises(OrderSubmissionBatchError, match="BrokerOrderRejectedError"):
        execution.submit_pending()
    with pytest.raises(AccountDecisionBlockedError, match="已阻塞"):
        accounts.refresh_account("s001-v1", prepared=prepared)
    assert store.virtual_account("s001-v1")["health"] == "BLOCKED"
    assert len(store.account_intents("s001-v1")) == 1
    assert len(store.attention_account_intents("s001-v1")) == 1
    store.close()


def test_ft_pte03_missing_broker_order_and_overfill_block_without_mutating_ledger(new_store, tmp_path):
    store = new_store(tmp_path / "reconcile.db")
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
    FutuExecution(store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-01T09:30:00+08:00")).refresh_orders()
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

    execution = FutuExecution(
        store, FakeBroker(), now=lambda: datetime.fromisoformat("2026-09-04T10:00:00+08:00")
    )
    with pytest.raises(ChannelReconciliationError, match="不存在"):
        execution.refresh_orders()
    assert store.get_setting("channel_reconciliation_status") == "BLOCKED"
    assert store.virtual_account("s001-v1")["health"] == "BLOCKED"
    store.close()


def test_ft_pte03_opend_can_reconnect_without_restarting_pte(new_store, tmp_path):
    store = new_store(tmp_path / "reconnect.db")
    attempts = 0

    def factory():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("OpenD unavailable")
        return FutuExecution(store, FakeBroker())

    execution = ReconnectableExecution(store, "588080.SH", factory)
    with pytest.raises(ConnectionError, match="OpenD unavailable"):
        execution.refresh_account()
    assert execution.status()["reconciliation_status"] == "UNAVAILABLE"
    status = execution.refresh_account()
    assert status["account"]["environment"] == "SIMULATE"
    assert execution.status()["reconciliation_status"] != "UNAVAILABLE"
    assert attempts == 2
    execution.close()

    recovered_store = new_store(tmp_path / "reconnect-established.db")
    replacement = FutuExecution(recovered_store, FakeBroker())

    class BrokenBroker:
        def __init__(self): self.closed = False
        def close(self): self.closed = True

    class BrokenExecution:
        def __init__(self): self.broker = BrokenBroker()
        def refresh_account(self): raise FutuGatewayError("connection permanently lost")
        def status(self): return {"reconciliation_status": "UNAVAILABLE"}

    broken = BrokenExecution()
    established = ReconnectableExecution(
        recovered_store, "588080.SH", lambda: replacement, initial=broken,
    )
    with pytest.raises(FutuGatewayError, match="permanently lost"):
        established.refresh_account()
    assert broken.broker.closed is True
    assert established.refresh_account()["account"]["environment"] == "SIMULATE"
    established.close()
