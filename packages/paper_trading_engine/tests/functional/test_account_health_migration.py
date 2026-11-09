"""Health migration changes only the legacy encoding, never trading facts."""

import json
import sqlite3

import pytest

from execution_channels.futu.account_health_migration import (
    AccountHealthMigrationError,
    HEALTH_RECEIPT_KEY,
    HEALTH_SCHEMA_KEY,
    migrate_account_health,
)
from execution_channels.futu.lifecycle import AccountHealth
from execution_channels.futu.store import PaperStore
from test_release_runtime import release_verification_runtime  # noqa: F401


NOW = "2026-10-20T23:30:00+08:00"


@pytest.fixture(scope="module")
def legacy_health_seed(frozen_seed_root):
    """Create the real legacy schema once; migration always uses a private copy."""
    original = frozen_seed_root / "legacy-health.db"
    connection = sqlite3.connect(original)
    # This is fixture construction, not the migration under test. Commit the
    # fixed seed once instead of forcing a durable commit for every DDL/row.
    connection.executescript("""
        BEGIN;
        CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        INSERT INTO settings VALUES('runtime_database_schema_version','4');
        CREATE TABLE virtual_accounts(account_id TEXT PRIMARY KEY,health TEXT,last_error TEXT,
            updated_at TEXT,account_type TEXT,run_state TEXT,cash TEXT,frozen_cash TEXT,
            quantity INTEGER,last_decision_id TEXT,release_hash TEXT);
        INSERT INTO virtual_accounts VALUES('running','READY',NULL,'unchanged','STRATEGY',
            'RUNNING','123.4500','5.0000',100,'decision','frozen-hash');
        INSERT INTO virtual_accounts VALUES('paused','READY','historical-error','unchanged',
            'STRATEGY','PAUSED','50.0000','0.0000',0,NULL,'frozen-hash');
        INSERT INTO virtual_accounts VALUES('retired','READY',NULL,'unchanged','STRATEGY',
            'RETIRED','0.0000','0.0000',0,NULL,'frozen-hash');
        INSERT INTO virtual_accounts VALUES('channel','READY',NULL,'unchanged',
            'CHANNEL_RECONCILIATION',NULL,'0.0000','0.0000',0,NULL,NULL);
        INSERT INTO virtual_accounts VALUES('recovered','OK',NULL,'unchanged','STRATEGY',
            'RUNNING','100.0000','0.0000',0,NULL,'frozen-hash');
        INSERT INTO virtual_accounts VALUES('blocked','BLOCKED','unresolved-order','unchanged',
            'STRATEGY','RUNNING','100.0000','10.0000',0,'decision','frozen-hash');
        CREATE TABLE decisions(payload TEXT);
        INSERT INTO decisions VALUES('{"decision_id":"decision","status":"COMPLETED"}');
        CREATE TABLE orders(payload TEXT);
        INSERT INTO orders VALUES('{"intent_id":"intent","status":"FILLED_ALL"}');
        CREATE TABLE fills(payload TEXT);
        INSERT INTO fills VALUES('{"quantity":100,"price":"1.2345"}');
        CREATE TABLE ledger(payload TEXT);
        INSERT INTO ledger VALUES('{"cash_delta":"-123.4500"}');
        CREATE TABLE events(payload TEXT);
        INSERT INTO events VALUES('{"historical_health":"READY"}');
        COMMIT;
    """)
    connection.close()
    original_bytes = original.read_bytes()
    yield original, original_bytes
    assert original.read_bytes() == original_bytes


@pytest.fixture
def legacy_health_db(legacy_health_seed, tmp_path):
    original, original_bytes = legacy_health_seed
    assert original.read_bytes() == original_bytes
    target = tmp_path / "migration-copy.db"
    target.write_bytes(original_bytes)
    migrated = sqlite3.connect(target)
    try:
        yield migrated
    finally:
        migrated.close()
        assert original.read_bytes() == original_bytes


def _snapshot(connection):
    return {
        table: connection.execute(f"SELECT * FROM {table}").fetchall()
        for table in ("virtual_accounts", "decisions", "orders", "fills", "ledger", "events", "settings")
    }


# Independent risk: EC31; responsibility-level assertions.
def test_legacy_health_migration_preserves_business_facts_and_receipt(legacy_health_db):
    connection = legacy_health_db
    before = _snapshot(connection)
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        migrate_account_health(connection, NOW)
    after = _snapshot(connection)
    expected_accounts = [
        (row[0], "OK" if row[1] == "READY" else row[1], *row[2:])
        for row in before["virtual_accounts"]
    ]
    assert after["virtual_accounts"] == expected_accounts
    for table in ("decisions", "orders", "fills", "ledger", "events"):
        assert after[table] == before[table]
    settings = dict(after["settings"])
    # The caller advances the overall database schema after all migrations succeed.
    assert settings["runtime_database_schema_version"] == "4"
    assert settings[HEALTH_SCHEMA_KEY] == "1"
    receipt = json.loads(settings[HEALTH_RECEIPT_KEY])
    assert receipt["occurred_at"] == NOW
    assert receipt["source_counts"] == {"READY": 4, "OK": 1, "BLOCKED": 1}
    assert receipt["changes"] == [
        {"account_id": account, "from": "READY", "to": "OK"}
        for account in ("channel", "paused", "retired", "running")
    ]
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        migrate_account_health(connection, "2026-10-21T00:00:00+08:00")
    assert _snapshot(connection) == after


# Independent risk: EC31; responsibility-level assertions.
def test_failed_receipt_write_rolls_back_health_with_callers_transaction(legacy_health_db):
    connection = legacy_health_db
    connection.execute(f"""CREATE TRIGGER receipt_failure BEFORE INSERT ON settings
        WHEN NEW.key='{HEALTH_RECEIPT_KEY}' BEGIN SELECT RAISE(ABORT,'receipt write failed'); END""")
    connection.commit()
    before = _snapshot(connection)
    with pytest.raises(sqlite3.IntegrityError, match="receipt write failed"):
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            migrate_account_health(connection, NOW)
    assert _snapshot(connection) == before


# Independent risk: EC31; responsibility-level assertions.
@pytest.mark.parametrize("key,value", [
    (HEALTH_SCHEMA_KEY, "1"),
])
def test_partial_or_unsupported_health_migration_rejected(legacy_health_db, key, value):
    connection = legacy_health_db
    connection.execute("INSERT INTO settings VALUES(?,?)", (key, value))
    connection.commit()
    before = _snapshot(connection)
    with pytest.raises(AccountHealthMigrationError, match="partially migrated"):
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            migrate_account_health(connection, NOW)
    assert _snapshot(connection) == before


# Independent risk: EC31; responsibility-level assertions.
def test_migrated_contract_rejects_reintroduced_ready(legacy_health_db):
    connection = legacy_health_db
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        migrate_account_health(connection, NOW)
    connection.execute("UPDATE virtual_accounts SET health='READY' WHERE account_id='running'")
    connection.commit()
    before = _snapshot(connection)
    with pytest.raises(AccountHealthMigrationError, match="running: invalid account health"):
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            migrate_account_health(connection, NOW)
    assert _snapshot(connection) == before


def _create_strategy_account(store, account_id):
    return store.create_virtual_account(
        account_id, account_id, "legacy", "a" * 64, 1000,
        strategy_id="S001", strategy_name_snapshot="Synthetic account",
        strategy_version="v1", release_hash="a" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
    )


def _full_database_facts(connection):
    tables = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "AND name<>'settings' ORDER BY name"
    )]
    return {table: connection.execute(f'SELECT * FROM "{table}"').fetchall() for table in tables}


def _legacy_complete_store(new_store, tmp_path, *, invalid=False):
    path = tmp_path / "legacy-complete.db"
    store = new_store(path)
    _create_strategy_account(store, "legacy")
    _create_strategy_account(store, "blocked")
    store.set_virtual_health("blocked", AccountHealth.BLOCKED, "unresolved order")
    store.close()
    with sqlite3.connect(path) as connection:
        # This reconstructs the actual v4 default without invoking production.
        triggers = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name='virtual_accounts'"
        ).fetchall()
        assert all("health" not in row[0].lower() for row in triggers)
        connection.execute("ALTER TABLE virtual_accounts DROP COLUMN health")
        connection.execute("ALTER TABLE virtual_accounts ADD COLUMN health TEXT NOT NULL DEFAULT 'READY'")
        connection.execute("UPDATE virtual_accounts SET health=? WHERE account_id='blocked'",
                           ("UNKNOWN" if invalid else "BLOCKED",))
        connection.execute("DELETE FROM settings WHERE key IN (?,?)", (HEALTH_SCHEMA_KEY, HEALTH_RECEIPT_KEY))
        connection.execute("UPDATE settings SET value='4' WHERE key='runtime_database_schema_version'")
    return path


# Independent risk: EC26; responsibility-level assertions.
def test_store_rolls_back_invalid_v4_health_without_advancing_schema(new_store, tmp_path):
    path = _legacy_complete_store(new_store, tmp_path, invalid=True)
    with sqlite3.connect(path) as connection:
        before = _full_database_facts(connection)
        settings_before = connection.execute("SELECT * FROM settings ORDER BY key").fetchall()
    with pytest.raises(AccountHealthMigrationError, match="blocked: invalid account health"):
        PaperStore(path)
    with sqlite3.connect(path) as connection:
        assert _full_database_facts(connection) == before
        assert connection.execute("SELECT * FROM settings ORDER BY key").fetchall() == settings_before
        assert connection.execute("SELECT health FROM virtual_accounts WHERE account_id='legacy'").fetchone()[0] == "READY"
