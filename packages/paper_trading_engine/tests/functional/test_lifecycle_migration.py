"""Migration preserves execution evidence and refuses unsupported conclusions."""

import json
import sqlite3

import pytest

from paper_trading_engine.lifecycle_migration import LifecycleMigrationError, migrate_lifecycle


NOW = "2026-10-08T23:30:00+08:00"
ORDER = {"side": "SELL", "quantity": 100, "order_type": "LIMIT", "limit_price": 1.2}


@pytest.fixture
def legacy_db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE virtual_accounts(account_id TEXT PRIMARY KEY,account_type TEXT,status TEXT,
            paused INTEGER,last_decision_id TEXT,cash TEXT,frozen_cash TEXT,quantity INTEGER);
        CREATE TABLE decisions(account_id TEXT,decision_id TEXT,payload TEXT,signal_date TEXT,
            valid_session TEXT,generated_at TEXT,status TEXT,superseded_by TEXT,superseded_at TEXT,
            PRIMARY KEY(account_id,decision_id));
        CREATE UNIQUE INDEX uq_decisions_active_signal_date ON decisions(account_id,signal_date) WHERE status='ACTIVE';
        CREATE TABLE intents(intent_id TEXT PRIMARY KEY,account_id TEXT,decision_id TEXT,order_sequence INTEGER,
            side TEXT,quantity INTEGER,limit_price TEXT,payload TEXT,status TEXT,channel_order_id TEXT);
        CREATE TABLE orders(channel_order_id TEXT,intent_id TEXT,account_id TEXT,decision_id TEXT,
            cumulative_filled_quantity INTEGER,payload TEXT);
        CREATE TABLE fills(fill_id TEXT,account_id TEXT,decision_id TEXT,order_id TEXT,side TEXT,quantity INTEGER);
        CREATE TABLE events(event_type TEXT,account_id TEXT,decision_id TEXT,occurred_at TEXT,payload TEXT);
        INSERT INTO virtual_accounts VALUES('acct','STRATEGY','RUNNING',1,NULL,'123.4500','0.0000',100);
        INSERT INTO virtual_accounts VALUES('retired','STRATEGY','RETIRED',1,NULL,'0.0000','0.0000',0);
        INSERT INTO virtual_accounts VALUES('channel','CHANNEL_RECONCILIATION','RUNNING',0,NULL,'0.0000','0.0000',0);
    """)
    yield connection
    connection.close()


def decision(connection, decision_id="decision", *, orders=(), status="INVALIDATED", session="2026-09-30", replacement=None):
    connection.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?)", (
        "acct", decision_id, json.dumps({"orders": list(orders), "symbol": "510500.SH"}),
        "2026-09-29", session, "2026-09-29T12:30:00+00:00", status, replacement,
        "2026-10-08T12:26:00+00:00" if replacement else None))


def intent(connection, intent_id="intent", *, state="FILLED_ALL", channel_id="order", order_type="LIMIT", sequence=0):
    connection.execute("INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?,?)", (
        intent_id, "acct", "decision", sequence, "SELL", 100, "1.2000",
        json.dumps({"order_type": order_type}), state, channel_id))


def filled(connection, intent_id="intent", channel_id="order", quantity=100):
    connection.execute("INSERT INTO orders VALUES(?,?,?,?,?,?)", (
        channel_id, intent_id, "acct", "decision", quantity, json.dumps({"status": "FILLED_ALL"})))
    connection.execute("INSERT INTO fills VALUES(?,?,?,?,?,?)", (
        "fill-" + intent_id, "acct", "decision", channel_id, "SELL", quantity))


def migrate(connection):
    if not connection.in_transaction:
        connection.execute("BEGIN")
    migrate_lifecycle(connection, NOW)


def state(connection, decision_id="decision"):
    return connection.execute("SELECT state FROM decision_state_events WHERE decision_id=?", (decision_id,)).fetchone()[0]


def test_no_order_history_and_legacy_replacement_preserved(legacy_db):
    decision(legacy_db, "first", status="SUPERSEDED", replacement="second")
    decision(legacy_db, "second")
    legacy_db.execute("UPDATE virtual_accounts SET last_decision_id='second' WHERE account_id='acct'")
    before = [tuple(row) for row in legacy_db.execute("SELECT * FROM decisions ORDER BY decision_id")]
    migrate(legacy_db)
    assert state(legacy_db, "first") == state(legacy_db, "second") == "COMPLETED"
    row = legacy_db.execute("SELECT * FROM decision_state_events WHERE decision_id='first'").fetchone()
    evidence = json.loads(row["evidence"])
    assert row["occurred_at"] == NOW
    assert evidence["generated_at"] == "2026-09-29T12:30:00+00:00"
    assert evidence["legacy_status"] == "SUPERSEDED"
    assert evidence["legacy_relations"][0]["decision_id"] == "second"
    assert row["related_decision_id"] is None  # Completed conclusion was not superseded under the new machine.
    assert [tuple(row) for row in legacy_db.execute("SELECT * FROM decisions ORDER BY decision_id")] == before
    assert tuple(legacy_db.execute("SELECT * FROM decision_adoptions").fetchone()) == ("acct", "2026-09-30", "second")
    accounts = {row["account_id"]: dict(row) for row in legacy_db.execute("SELECT * FROM virtual_accounts")}
    assert accounts["acct"]["run_state"] == "PAUSED"
    assert accounts["retired"]["run_state"] == "RETIRED"
    assert accounts["channel"]["run_state"] is None
    assert accounts["acct"]["cash"] == "123.4500"
    assert accounts["acct"]["legacy_paused"] == 1
    migrate_lifecycle(legacy_db, "2026-10-09T00:00:00+08:00")
    assert legacy_db.execute("SELECT COUNT(*) FROM decision_state_events").fetchone()[0] == 2
    assert legacy_db.execute("SELECT MIN(occurred_at) FROM decision_state_events").fetchone()[0] == NOW


@pytest.mark.parametrize("quantity,expected", [(100, "COMPLETED"), (99, None)])
def test_completion_requires_exact_order_and_fill_evidence(legacy_db, quantity, expected):
    decision(legacy_db, orders=(ORDER,))
    intent(legacy_db)
    filled(legacy_db, quantity=quantity)
    if expected:
        migrate(legacy_db)
        assert state(legacy_db) == expected
    else:
        with pytest.raises(LifecycleMigrationError, match="completion"):
            migrate(legacy_db)
        assert "status" in {row[1] for row in legacy_db.execute("PRAGMA table_info(decisions)")}
        assert legacy_db.execute("SELECT name FROM sqlite_master WHERE name='decision_state_events'").fetchone() is None


def test_unknown_submission_stays_executing_even_after_valid_session(legacy_db):
    decision(legacy_db, orders=(ORDER,))
    intent(legacy_db, state="SUBMISSION_UNCERTAIN", channel_id=None)
    migrate(legacy_db)
    assert state(legacy_db) == "EXECUTING"


@pytest.mark.parametrize("session,expected", [("2026-10-09", "PENDING"), ("2026-10-07", "INCOMPLETE")])
def test_unsubmitted_plan_state_uses_valid_session_not_invalidated_label(legacy_db, session, expected):
    decision(legacy_db, orders=(ORDER,), session=session)
    migrate(legacy_db)
    assert state(legacy_db) == expected


def test_changed_order_type_retry_preserves_compensation_but_not_original_success(legacy_db):
    decision(legacy_db, orders=(ORDER,))
    intent(legacy_db, "original", state="REJECTED", channel_id=None)
    intent(legacy_db, "retry", order_type="MARKET", sequence=1)
    filled(legacy_db, "retry")
    legacy_db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (
        "ORDER_INTENT_CREATED", "acct", "decision", "2026-09-30T06:20:00+00:00",
        json.dumps({"retry_of": "original", "intent_id": "retry", "order_sequence": 1,
                    "side": "SELL", "quantity": 100, "order_type": "MARKET"})))
    fills_before = [tuple(row) for row in legacy_db.execute("SELECT * FROM fills")]
    migrate(legacy_db)
    assert state(legacy_db) == "INCOMPLETE"
    assert [tuple(row) for row in legacy_db.execute("SELECT * FROM fills")] == fills_before
    evidence = json.loads(legacy_db.execute("SELECT evidence FROM decision_state_events").fetchone()[0])
    assert evidence["legacy_relations"] == [{"kind": "operator_retry_with_changed_order_type",
        "original_intent": "original", "retry_intent": "retry", "compensating_fill_quantity": 100}]


def test_missing_plan_metadata_blocks_migration_without_mutation(legacy_db):
    decision(legacy_db)
    legacy_db.execute("UPDATE decisions SET payload='{}'")
    with pytest.raises(LifecycleMigrationError, match="explicit order-plan"):
        migrate(legacy_db)
    assert "run_state" not in {row[1] for row in legacy_db.execute("PRAGMA table_info(virtual_accounts)")}


def test_empty_database_and_transaction_contract(legacy_db):
    with pytest.raises(RuntimeError, match="transaction"):
        migrate_lifecycle(legacy_db, NOW)
    migrate(legacy_db)
    assert legacy_db.execute("SELECT COUNT(*) FROM decision_state_events").fetchone()[0] == 0


@pytest.mark.parametrize("orphan", ["intent", "order", "fill"])
def test_orphan_execution_evidence_blocks_migration_before_schema_changes(legacy_db, orphan):
    if orphan == "intent":
        intent(legacy_db)
    else:
        filled(legacy_db)
        if orphan == "fill":
            legacy_db.execute("DELETE FROM orders")
    with pytest.raises(LifecycleMigrationError, match="originating"):
        migrate(legacy_db)
    assert "run_state" not in {row[1] for row in legacy_db.execute("PRAGMA table_info(virtual_accounts)")}
