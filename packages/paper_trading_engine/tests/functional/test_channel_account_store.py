"""Channel-account partitions share storage, never balances or write authority."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from dataflows import AssetClass, BarFrequency, InstrumentId, MarketId
from strategy_runtime import AccountPolicy, CashAvailabilityPolicy, ResearchExecutionSpec, UsEquitySpec
from execution_channels.futu.audit import AuditRecorder
from execution_channels.futu.channel import (
    ChannelAccountConfig, FUTU_SIMULATE_CN_CHANNEL_ID, FUTU_US_SIM_CHANNEL_ID,
    TradingSession,
)
from execution_channels.futu.channel_accounts import DEFAULT_CHANNEL_ACCOUNT
from execution_channels.futu.equity_contracts import EquityAccountRules
from execution_channels.futu.lifecycle import AccountHealth
from execution_channels.futu.store import PaperStore


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


@pytest.fixture
def partitions(tmp_path):
    root = PaperStore(tmp_path / "partition.db")
    root.register_channel_account(_config(DEFAULT_CHANNEL_ACCOUNT, broker=7,
        channel=FUTU_SIMULATE_CN_CHANNEL_ID), capital=Decimal("1000000"))
    us = root.register_channel_account(_config(), capital=Decimal("20000"))
    cn = root.scope(DEFAULT_CHANNEL_ACCOUNT)
    _account(cn, "cn-strategy")
    _account(us, "us-strategy", us=True, capital="2000")
    try:
        yield root, cn, us
    finally:
        root.close()


def test_partition_balances_settings_snapshots_and_reopen(partitions):
    root, cn, us = partitions
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


@pytest.mark.parametrize("operation", [
    lambda store: store.virtual_account("us-strategy"),
    lambda store: store.set_virtual_paused("us-strategy", False),
    lambda store: store.set_virtual_health("us-strategy", AccountHealth.BLOCKED, "foreign"),
    lambda store: store.rename_virtual_account("us-strategy", "stolen", "foreign"),
    lambda store: store.account_orders("us-strategy"),
    lambda store: store.account_fills("us-strategy"),
    lambda store: store.account_snapshots("us-strategy"),
    lambda store: store.scope("us-primary"),
])
def test_scoped_operations_reject_foreign_resources(partitions, operation):
    _, cn, us = partitions
    original = us.virtual_account("us-strategy")
    with pytest.raises(ValueError, match="another channel|cross channel"):
        operation(cn)
    assert us.virtual_account("us-strategy") == original


def test_default_scope_cannot_address_another_scopes_settings(partitions):
    _, cn, us = partitions
    us.set_setting("isolation-marker", "original")
    with pytest.raises(ValueError, match="reserved|scope|channel"):
        cn.set_setting("channel:us-primary:isolation-marker", "overwritten")
    with pytest.raises(ValueError, match="reserved|scope|channel"):
        cn.get_setting("channel:us-primary:isolation-marker")
    assert us.get_setting("isolation-marker") == "original"


def test_cross_scope_registration_has_no_partial_write_in_outer_transaction(partitions):
    root, cn, _ = partitions
    with root.atomic_decision_update():
        with pytest.raises(ValueError, match="cross channel|scope|another channel"):
            cn.register_channel_account(_config("foreign-new", broker=99), capital=Decimal("1000"))
    assert "foreign-new" not in {item["channel_account_id"] for item in root.channel_accounts()}


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


def test_scoped_audit_cannot_claim_foreign_account(partitions):
    _, cn, us = partitions
    before = len(us.query_audit_events())
    with pytest.raises(ValueError, match="another channel"):
        AuditRecorder(cn).record("ORDER_REJECTED", source="fixture", account_id="us-strategy",
                                 channel=FUTU_US_SIM_CHANNEL_ID)
    assert len(us.query_audit_events()) == before


def test_same_fee_reference_is_independent_and_idempotent_per_scope(partitions):
    _, cn, us = partitions
    results = []
    for scope, amount in ((cn, Decimal("-1.25")), (us, Decimal("-1.99"))):
        reconciliation = scope.create_channel_reconciliation_account()
        event = AuditRecorder(scope).build("CHANNEL_FEE_VARIANCE_RECONCILED", source="fixture",
            account_id=reconciliation["account_id"], channel=scope.execution_channel_id)
        args = dict(adjustment=amount, reference="same-broker-checkpoint",
                    occurred_at=datetime.now(timezone.utc).isoformat(), event=event)
        first = scope.apply_channel_fee_variance(**args)
        second = scope.apply_channel_fee_variance(**args)
        assert first["applied"] and not second["applied"]
        assert Decimal(scope.virtual_account(reconciliation["account_id"])["cash"]) == amount
        results.append(first["ledger_entry_id"])
    assert results[0] != results[1]
    assert cn.virtual_account("cn-strategy")["cash"] == "1000.0000"
    assert us.virtual_account("us-strategy")["cash"] == "2000.0000"
    assert not cn.account_invariant_violations() and not us.account_invariant_violations()


def test_shared_connection_scope_writes_roll_back_together(partitions):
    root, cn, us = partitions
    class Rollback(Exception):
        pass
    with pytest.raises(Rollback):
        with root.atomic_decision_update():
            cn.set_setting("rollback-marker", "cn")
            us.set_setting("rollback-marker", "us")
            raise Rollback
    assert cn.get_setting("rollback-marker") is None
    assert us.get_setting("rollback-marker") is None
    assert not root._connection.in_transaction


def test_us_requires_explicit_matching_equity_rules(partitions):
    _, _, us = partitions
    with pytest.raises(ValueError, match="rules|market"):
        us.create_virtual_account("invalid", "invalid", "v1", "a" * 64, 100,
            symbol="MU", asset_type="stock", selection_data_cutoff="2026-09-30")
    assert not any(a["account_id"] == "invalid" for a in us.virtual_accounts())


def test_external_identity_and_capital_cannot_silently_change(partitions):
    root, _, _ = partitions
    with pytest.raises(ValueError, match="immutable"):
        root.register_channel_account(ChannelAccountConfig("us-primary", FUTU_US_SIM_CHANNEL_ID,
            42, TradingSession.ETH), capital=Decimal("20000"))
    with pytest.raises(ValueError, match="capital"):
        root.register_channel_account(_config(), capital=Decimal("20001"))
    with pytest.raises(ValueError, match="already registered"):
        root.register_channel_account(_config("us-duplicate"), capital=Decimal("20000"))


def test_unscoped_capital_cannot_mix_currencies(partitions):
    root, _, _ = partitions
    with pytest.raises(ValueError, match="scope|channel"):
        root.capital_pool_balance()


def test_explicit_channel_mismatch_rejected(partitions):
    _, cn, _ = partitions
    with pytest.raises(ValueError, match="channel"):
        cn.create_virtual_account("wrong-channel", "wrong", "v1", "a" * 64, 100,
            symbol="MU", asset_type="stock", selection_data_cutoff="2026-09-30",
            channel_id=FUTU_US_SIM_CHANNEL_ID, equity_rules=_rules())


def test_reconciliation_account_rejects_explicit_wrong_channel(partitions):
    _, cn, us = partitions
    with pytest.raises(ValueError, match="channel"):
        cn.channel_reconciliation_account(FUTU_US_SIM_CHANNEL_ID)
    with pytest.raises(ValueError, match="channel"):
        us.channel_reconciliation_account(FUTU_SIMULATE_CN_CHANNEL_ID)


def test_multiple_same_day_decisions_survive_reopen(tmp_path):
    from pte_support import adopt_test_decision

    root = PaperStore(tmp_path / "multiple-decisions.db")
    _account(root, "legacy")
    for identity in ("first", "second"):
        adopt_test_decision(root, account_id="legacy", decision_id=identity,
                            valid_session="2026-11-05", orders=[])
    root.close()
    reopened = PaperStore(root.path)
    try:
        assert len(reopened.account_decisions("legacy")) == 2
        adopt_test_decision(reopened, account_id="legacy", decision_id="third",
                            valid_session="2026-11-05", orders=[])
        assert len(reopened.account_decisions("legacy")) == 3
    finally:
        reopened.close()


def test_schema7_migration_preserves_legacy_balances_and_events(tmp_path):
    import sqlite3

    path = tmp_path / "schema7.db"
    root = PaperStore(path)
    original = _account(root, "legacy")
    root.set_setting("channel_reconciliation_status", "OK")
    root.save_snapshot({"cash": "1000.0000"})
    event_ids = [row["event_id"] for row in root.query_audit_events()]
    root.close()
    # Remove precisely schema 8's additions to exercise actual ALTER migration.
    with sqlite3.connect(path) as connection:
        connection.execute("DROP INDEX virtual_accounts_channel_scope")
        connection.execute("DROP INDEX events_channel_scope")
        for table in ("virtual_accounts", "events", "snapshots"):
            connection.execute(f"ALTER TABLE {table} DROP COLUMN channel_account_id")
        connection.execute("DROP TABLE channel_accounts")
        connection.execute("DROP TABLE equity_strategy_state")
        connection.execute("UPDATE settings SET value='7' WHERE key='runtime_database_schema_version'")
    migrated = PaperStore(path)
    try:
        scope = migrated.scope(DEFAULT_CHANNEL_ACCOUNT)
        assert scope.virtual_account("legacy") == original
        assert [row["event_id"] for row in scope.query_audit_events()] == event_ids
        assert scope.latest_snapshot() == {"cash": "1000.0000"}
        assert migrated.get_setting("runtime_database_schema_version") == "8"
        assert scope.get_setting("channel_reconciliation_status") == "OK"
        migrated.register_channel_account(_config(), capital=Decimal("20000"))
        assert scope.virtual_account("legacy") == original
        assert scope.capital_pool_balance().unallocated_cash == Decimal("999000")
    finally:
        migrated.close()


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
