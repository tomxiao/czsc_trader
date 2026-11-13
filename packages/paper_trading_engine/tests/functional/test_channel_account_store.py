"""Channel-account partitions share storage, never balances or write authority."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3
from threading import Barrier
from types import SimpleNamespace

import pytest

from execution_channels.instruments import AssetClass, BarFrequency, InstrumentId, MarketId
from execution_channels.policy import AccountPolicy, CashAvailabilityPolicy, ResearchExecutionSpec, UsEquitySpec
from execution_channels.futu.audit import AuditRecorder
from execution_channels.futu.channel import (
    ChannelAccountConfig, FUTU_SIMULATE_CN_CHANNEL_ID, FUTU_US_SIM_CHANNEL_ID,
)
from execution_channels.futu.channel_accounts import DEFAULT_CHANNEL_ACCOUNT
from execution_channels.futu.equity_contracts import EquityAccountRules
from execution_channels.futu.store import PaperStore, RUNTIME_DATABASE_SCHEMA_VERSION
from paper_trading_engine.scheduler import RuntimeScheduler
from paper_trading_engine.web_api import PteWebApi
from scheduler_support import Engine


def _config(name="us-primary", *, broker=42, channel=FUTU_US_SIM_CHANNEL_ID):
    return ChannelAccountConfig(name, channel, broker)


def _rules():
    execution = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy("USD", CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
    return EquityAccountRules(InstrumentId(MarketId.US, AssetClass.STOCK, "MU"), execution)


def _account(store, account_id, *, us=False, capital="1000"):
    return store.create_virtual_account(account_id, account_id, "v1", "a" * 64, capital,
        symbol="MU" if us else "588080.SH", asset_type="stock" if us else "etf",
        strategy_id="S999", strategy_name_snapshot="Fixture", strategy_version="v1",
        release_hash="b" * 64, qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-30",
        equity_rules=_rules() if us else None)


def _partition_accounts(root):
    root.register_channel_account(_config(DEFAULT_CHANNEL_ACCOUNT, broker=7,
        channel=FUTU_SIMULATE_CN_CHANNEL_ID), capital=Decimal("1000000"))
    us = root.register_channel_account(_config(), capital=Decimal("20000"))
    cn = root.scope(DEFAULT_CHANNEL_ACCOUNT)
    _account(cn, "cn-strategy")
    _account(us, "us-strategy", us=True, capital="2000")
    return root, cn, us


# Independent risk: EC26; responsibility-level assertions.
@pytest.mark.parametrize('denied_name,action,rolled_back_name', [
    ('orders', sqlite3.SQLITE_CREATE_TABLE, 'events'),
])
def test_initial_schema_failure_releases_writer_and_retries_without_partial_ddl(
    tmp_path, monkeypatch, denied_name, action, rolled_back_name,
):
    """A real SQLite authorization failure must roll back its initialization block."""
    from execution_channels.futu import store as module

    path = tmp_path / 'initialization.db'
    original_connect = sqlite3.connect
    failed_connections = []

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        failed_connections.append(connection)
        connection.set_authorizer(lambda operation, name, *_:
            sqlite3.SQLITE_DENY if operation == action and name == denied_name else sqlite3.SQLITE_OK)
        return connection

    with monkeypatch.context() as patch:
        patch.setattr(module.sqlite3, 'connect', connect)
        with pytest.raises(sqlite3.DatabaseError, match='not authorized'):
            PaperStore(path)
    assert len(failed_connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        failed_connections[0].execute('SELECT 1')
    probe = original_connect(path, timeout=0)
    try:
        assert probe.execute('SELECT name FROM sqlite_master WHERE name=?',
                             (rolled_back_name,)).fetchone() is None
        probe.execute('BEGIN IMMEDIATE')  # No abandoned write lock remains.
        probe.rollback()
    finally:
        probe.close()

    root = PaperStore(path)
    try:
        assert root.get_setting('runtime_database_schema_version') == str(RUNTIME_DATABASE_SCHEMA_VERSION)
        assert root._connection.execute("PRAGMA quick_check").fetchone()[0] == 'ok'
        assert root._connection.execute("SELECT name FROM sqlite_master WHERE name='idx_events_order'").fetchone()
        _, cn, us = _partition_accounts(root)
        accounts = {scope.channel_account_id: scope.virtual_accounts() for scope in (cn, us)}
    finally:
        root.close()
    reopened = PaperStore(path)
    try:
        assert {key: reopened.scope(key).virtual_accounts() for key in accounts} == accounts
    finally:
        reopened.close()


@pytest.fixture
def partitions(memory_store):
    # Ownership, currency and query boundaries need real SQL but no disk reopen.
    return _partition_accounts(memory_store())


@pytest.fixture
def disk_partitions(tmp_path, new_store):
    # Persistence and atomic rollback cases retain the ordinary file-backed DB.
    root = new_store(tmp_path / "partition.db")
    try:
        yield _partition_accounts(root)
    finally:
        root.close()


def test_account_snapshot_and_strategy_workers_share_connection_safely(disk_partitions):
    root, cn, us = disk_partitions
    _account(us, "us-peer", us=True)
    expected = {"us-strategy": '{"identity":"us-strategy"}', "us-peer": '{"identity":"us-peer"}'}
    with root.atomic_decision_update():
        root._connection.executemany("INSERT INTO equity_strategy_state VALUES (?, ?)", expected.items())
    for account_id in expected:
        us.set_virtual_paused(account_id, False)

    ready = Barrier(8, timeout=10)

    class ScheduleProvider:
        def due_decision(self, account, observed_at):
            assert account["account_v4_json"] == expected[account["account_id"]]
            return None

    runtime = SimpleNamespace(store=root, services={
        scope.channel_account_id: SimpleNamespace(
            store=scope, accounts=SimpleNamespace(status=scope.virtual_account),
        ) for scope in (cn, us)
    })
    api = PteWebApi(SimpleNamespace(store=root, channel=None, virtual=None), multichannel_runtime=runtime)
    scheduler = RuntimeScheduler(Engine(), None, root, schedule_provider=ScheduleProvider())
    now = datetime.now(timezone.utc)

    def read(worker):
        account_id = tuple(expected)[(worker // 2) % len(expected)]
        ready.wait()
        for _ in range(150):
            if worker % 2:
                snapshot = api.virtual_account_snapshot(account_id)
                assert snapshot["scope"]["account_id"] == account_id
                assert snapshot["scope"]["channel_account_id"] == us.channel_account_id
            else:
                scheduler._scheduled_account_cycle({"account_id": account_id,
                                                    "channel_account_id": us.channel_account_id}, now)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(read, range(8)))
    assert root.operation_failures() == []
    assert root.query_audit_events(event_type="SCHEDULER_OPERATION_FAILED") == []


def test_scheduler_audit_failure_and_recovery_are_visible_under_owning_market(disk_partitions):
    root, cn, us = disk_partitions
    failing = True

    def fail_until_recovered(*_):
        if failing:
            raise RuntimeError("fixture failure")

    scheduler = RuntimeScheduler(Engine(), None, root,
        schedule_provider=SimpleNamespace(due_decision=fail_until_recovered),
        channel_operations={us.channel_account_id: SimpleNamespace(
            refresh_account=fail_until_recovered, refresh_orders=fail_until_recovered,
        )}, account_interval=5)
    for scope, account_id in ((cn, "cn-strategy"), (us, "us-strategy")):
        scope.set_virtual_paused(account_id, False)
    start = datetime.now(timezone.utc)
    scheduler.tick_fast(start)
    scheduler.tick_daily(start)
    for worker in scheduler._account_workers.values():
        worker.join(5)
        assert not worker.is_alive()
    assert len(root.operation_failures()) == 4

    failing = False
    retry = start + timedelta(seconds=5)
    scheduler.tick_fast(retry)
    scheduler.tick_daily(retry)
    for worker in scheduler._account_workers.values():
        worker.join(5)
        assert not worker.is_alive()

    api = PteWebApi(SimpleNamespace(store=root, channel=None, virtual=None))
    for market, scope, account_id in (("CN", cn, "cn-strategy"), ("US", us, "us-strategy")):
        events = [event for event in api.audit_events({"market": market})["events"]
                  if event["source"] == "scheduler"]
        operations = {f"account_strategy_cycle:{account_id}": account_id}
        if market == "US":
            operations.update({f"{name}:{scope.channel_account_id}": None for name in ("account", "orders")})
        assert len(events) == len(operations) * 2
        for event in events:
            assert event["channel_account_id"] == scope.channel_account_id
            assert event["channel"] == scope.execution_channel_id
            assert event["account_id"] == operations[event["details"]["operation"]]
        for operation in operations:
            assert [event["event_type"] for event in events if event["details"]["operation"] == operation] == [
                "SCHEDULER_OPERATION_RECOVERED", "SCHEDULER_OPERATION_FAILED",
            ]
    assert root.operation_failures() == []


# Independent risk: EC15; responsibility-level assertions.
def test_partition_balances_settings_snapshots_and_reopen(disk_partitions):
    root, cn, us = disk_partitions
    assert {a["account_id"] for a in root.virtual_accounts()} == {"cn-strategy", "us-strategy"}
    assert [a["account_id"] for a in cn.strategy_virtual_accounts()] == ["cn-strategy"]
    assert [a["account_id"] for a in us.strategy_virtual_accounts()] == ["us-strategy"]
    assert cn.capital_pool_balance().unallocated_cash == Decimal("999000")
    assert us.capital_pool_balance().unallocated_cash == Decimal("18000")
    cn.set_paused(True)
    us.set_paused(False)
    cn.set_setting("channel_reconciliation_status", "BLOCKED")
    us.set_setting("channel_reconciliation_status", "OK")
    assert us.get_setting("channel_reconciliation_status") == "OK"
    assert not root._connection.in_transaction
    cn.save_snapshot({"currency": "CNY"})
    us.save_snapshot({"currency": "USD"})
    assert cn.is_paused() and not us.is_paused()
    assert cn.latest_snapshot() == {"currency": "CNY"}
    assert us.latest_snapshot() == {"currency": "USD"}
    us.close()  # A scoped view does not own the root connection.
    assert cn.virtual_account("cn-strategy")["cash"] == "1000.0000"
    root.close()
    reopened = PaperStore(root.path)
    try:
        cn2, us2 = reopened.scope(DEFAULT_CHANNEL_ACCOUNT), reopened.scope("us-primary")
        assert cn2.is_paused() and not us2.is_paused()
        assert cn2.get_setting("channel_reconciliation_status") == "BLOCKED"
        assert us2.get_setting("channel_reconciliation_status") == "OK"
        assert us2.capital_pool_balance().unallocated_cash == Decimal("18000")
    finally:
        reopened.close()


# Independent risk: EC15; responsibility-level assertions.
def test_EC15_C03_scoped_reads_and_writes_refuse_foreign_resources(partitions):
    root, cn, us = partitions
    before = tuple(root._connection.iterdump())
    with pytest.raises(ValueError, match='another channel|cross channel'):
        cn.virtual_account('us-strategy')
    with pytest.raises(ValueError, match='another channel|cross channel'):
        cn.set_virtual_paused('us-strategy', False)
    with pytest.raises(ValueError, match='another channel|cross channel'):
        cn.account_orders('us-strategy')
    assert tuple(root._connection.iterdump()) == before
    assert us.virtual_account('us-strategy')['run_state'] == 'PAUSED'


# Independent risk: EC15; responsibility-level assertions.
def test_audit_and_failure_queries_are_scope_local(partitions):
    _, cn, us = partitions
    AuditRecorder(us).record("ORDER_REJECTED", source="fixture", account_id="us-strategy",
                             channel=FUTU_US_SIM_CHANNEL_ID)
    assert us.has_audit_event("ORDER_REJECTED")
    assert not cn.has_audit_event("ORDER_REJECTED")
    assert cn.query_audit_events(event_type="ORDER_REJECTED") == []
    assert us.audit_event_counts(event_type="ORDER_REJECTED")["TRADING"] == 1
    assert us.query_audit_events(event_type="ORDER_REJECTED")[0]["channel_account_id"] == "us-primary"
    cn.set_operation_failure("orders", {"error": "CN"})
    us.set_operation_failure("orders", {"error": "US"})
    assert [r["error"] for r in cn.operation_failures()] == ["CN"]
    assert [r["error"] for r in us.operation_failures()] == ["US"]
    us.clear_operation_failure("orders")
    assert us.operation_failures() == [] and len(cn.operation_failures()) == 1


# Independent risk: EC15; responsibility-level assertions.
def test_unscoped_capital_cannot_mix_currencies(partitions):
    root, _, _ = partitions
    with pytest.raises(ValueError, match="scope|channel"):
        root.capital_pool_balance()


# Independent risk: EC26; responsibility-level assertions.
def test_schema7_migration_preserves_legacy_balances_and_events(tmp_path):
    import sqlite3

    path = tmp_path / "schema7.db"
    root = PaperStore(path)
    original = _account(root, "legacy")
    root.set_setting("channel_reconciliation_status", "OK")
    root.save_snapshot({"cash": "1000.0000"})
    event_ids = [row["event_id"] for row in root.query_audit_events()]
    root.close()
    # Reconstruct schema 7, including the pre-retirement lifecycle constraint,
    # so opening it exercises both the channel-scope and retirement migrations.
    with sqlite3.connect(path) as connection:
        connection.execute("DROP INDEX virtual_accounts_channel_scope")
        connection.execute("DROP INDEX events_channel_scope")
        for table in ("virtual_accounts", "events", "snapshots"):
            connection.execute(f"ALTER TABLE {table} DROP COLUMN channel_account_id")
        connection.execute("DROP TABLE channel_accounts")
        connection.execute("DROP TABLE equity_strategy_state")
        connection.execute("DROP TABLE account_retirement_requests")
        ddl = connection.execute("SELECT sql FROM sqlite_master WHERE name='virtual_accounts'").fetchone()[0]
        objects = connection.execute("SELECT sql FROM sqlite_master WHERE tbl_name='virtual_accounts' "
                                     "AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
        assert "'RETIRING'," in ddl
        connection.execute(ddl.replace('virtual_accounts', 'schema7_accounts', 1).replace("'RETIRING',", ''))
        connection.execute('INSERT INTO schema7_accounts SELECT * FROM virtual_accounts')
        connection.execute('DROP TABLE virtual_accounts')
        connection.execute('ALTER TABLE schema7_accounts RENAME TO virtual_accounts')
        for row in objects:
            connection.execute(row[0])
        connection.execute("UPDATE settings SET value='7' WHERE key='runtime_database_schema_version'")
    migrated = PaperStore(path)
    try:
        scope = migrated.scope(DEFAULT_CHANNEL_ACCOUNT)
        assert scope.virtual_account("legacy") == original
        assert [row["event_id"] for row in scope.query_audit_events()] == event_ids
        assert scope.latest_snapshot() == {"cash": "1000.0000"}
        assert migrated.get_setting("runtime_database_schema_version") == "10"
        assert "'RETIRING'" in migrated._connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='virtual_accounts'").fetchone()[0]
        assert migrated._connection.execute('SELECT * FROM account_retirement_requests').fetchall() == []
        assert scope.get_setting("channel_reconciliation_status") == "OK"
        migrated.register_channel_account(_config(), capital=Decimal("20000"))
        assert scope.virtual_account("legacy") == original
        assert scope.capital_pool_balance().unallocated_cash == Decimal("999000")
    finally:
        migrated.close()


# Independent risk: EC15; responsibility-level assertions.
def test_us_broker_id_collision_preserves_order_fill_and_cancel_ownership(partitions):
    from dataclasses import asdict
    from pte_support import decision
    from execution_channels.futu.broker import BrokerOrder, OrderIntent, PaperTradingSafetyError
    from execution_channels.futu.scoped_broker import ScopedBroker

    root, _, first = partitions
    second_config = _config("us-secondary", broker=43)
    second = root.register_channel_account(second_config, capital=Decimal("20000"))
    _account(second, "second-strategy", us=True, capital="2000")

    class Broker:
        def __init__(self, config):
            self.channel_id = config.channel_id
            self.channel_account_id = config.channel_account_id
            self.cancelled = []

        def place_order(self, intent):
            return BrokerOrder("raw:42", intent.symbol, intent.side, intent.quantity,
                intent.limit_price, "SUBMITTED", 0, 0, intent.intent_id,
                channel_account_id=self.channel_account_id)

        def cancel_order(self, identity):
            self.cancelled.append(identity)

    bindings = []
    start = datetime.fromisoformat("2026-11-05T09:30:00-05:00")
    for store, account_id, config in ((first, "us-strategy", _config()),
                                      (second, "second-strategy", second_config)):
        store.set_virtual_paused(account_id, False)
        account = store.virtual_account(account_id)
        payload = decision().to_store_payload()
        payload.update(contract_version="advice.equity.v1", decision_id=account_id,
            symbol="MU", strategy={"strategy_id": "S999", "version": "v1", "release_hash": "b" * 64},
            signal_date="2026-11-05", valid_session="2026-11-05",
            available_cash=float(account["cash"]), target_quantity=2, delta_quantity=2,
            cycle_target_quantity=2, action="BUY",
            orders=[{"side": "BUY", "quantity": 2, "order_type": "LIMIT", "limit_price": 100}],
            equity_execution_interval={"start": start.isoformat(), "end": "2026-11-05T10:00:00-05:00"},
            equity_observed_through=start.isoformat())
        store.save_account_decision(account_id, payload)
        intent = store.create_account_intent(account_id=account_id, decision_id=account_id,
            order_sequence=0, symbol="MU", side="BUY", quantity=2, limit_price=100,
            valid_session="2026-11-05")
        store.set_setting("channel_reconciliation_status", "OK")
        store.set_setting("futu_cash_reconciliation_status", "OK")
        assert store.claim_account_intent(intent["intent_id"], moment=start)
        broker = ScopedBroker(Broker(config), config)
        order = broker.place_order(OrderIntent(intent["intent_id"], account_id, "MU", "BUY", 2, 100,
            account_id=account_id, channel_account_id=config.channel_account_id))
        store.bind_channel_order(intent["intent_id"], order.channel_order_id, asdict(order))
        bindings.append((store, broker, order))

    _, broker1, order1 = bindings[0]
    _, broker2, order2 = bindings[1]
    assert order1.broker_order_id == order2.broker_order_id == "raw:42"
    assert order1.channel_order_id != order2.channel_order_id
    first.apply_fill_increment(order1.channel_order_id, cumulative_quantity=1,
        average_price="99.1234", occurred_at=start.isoformat())
    assert first.virtual_account("us-strategy")["quantity"] == 1
    assert second.virtual_account("second-strategy")["quantity"] == 0
    assert len(first.account_fills("us-strategy")) == 1
    assert second.account_fills("second-strategy") == []
    with pytest.raises(ValueError, match="another channel"):
        second.apply_fill_increment(order1.channel_order_id, cumulative_quantity=2,
            average_price=99, occurred_at=start.isoformat())
    with pytest.raises(ValueError, match="another channel"):
        first.account_order(order2.channel_order_id)
    with pytest.raises(PaperTradingSafetyError, match="another channel"):
        broker2.cancel_order(order1.channel_order_id)
    assert broker2.broker.cancelled == []
    broker1.cancel_order(order1.channel_order_id)
    assert broker1.broker.cancelled == ["raw:42"]
