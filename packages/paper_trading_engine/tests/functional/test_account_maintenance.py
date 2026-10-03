from dataclasses import asdict, replace
from datetime import date
import json
from types import SimpleNamespace

import pytest

from paper_trading_engine import (
    AccountBindingUpdate, AccountBindingUpdateStatus, AccountStrategyBinding,
    update_account_bindings,
)
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.runtime_lock import RuntimeAlreadyOwnedError, RuntimeDatabaseLock
from paper_trading_engine.store import RUNTIME_DATABASE_SCHEMA_VERSION
from strategy_manager import Qualification
from pte_support import decision, FakeAdvice, preparation


@pytest.fixture
def maintenance(new_store, tmp_path, monkeypatch):
    from paper_trading_engine import account_maintenance as module

    runtime = tmp_path / "runtime"
    database = runtime / "shared/state/runtime.db"
    store = new_store(database)
    binding = AccountStrategyBinding(
        "S001", "v1", "b" * 64, "current strategy", Qualification.PAPER_READY,
        date(2026, 9, 2), "588080.SH", 0.0005,
    )
    for account_id in ("one", "two"):
        store.create_virtual_account(
            account_id, account_id, "S001-v1", "c" * 64, 100000,
            strategy_id="S001", strategy_version="v1", release_hash="a" * 64,
            strategy_name_snapshot="old strategy", qualification_snapshot="PAPER_READY",
            selection_data_cutoff="2026-09-02",
        )
    release = SimpleNamespace(
        runtime_root=runtime, release_root=runtime / "releases/v1.0.0",
        manifest={"database_schema": {"compatible": [RUNTIME_DATABASE_SCHEMA_VERSION]}}, manifest_sha256="d" * 64,
    )
    monkeypatch.setattr(module, "load_release", lambda *_: release)
    monkeypatch.setattr(module, "SrtAdviceClient", lambda **_: SimpleNamespace(
        validate_account_binding=lambda **kwargs: binding,
    ))
    yield SimpleNamespace(
        runtime=runtime, database=database, store=store, binding=binding, release=release,
        updates=tuple(AccountBindingUpdate(x, "a" * 64, "b" * 64) for x in ("one", "two")),
    )
    store.close()


def test_update_preserves_account_economics_and_invalidates_old_execution(maintenance):
    m = maintenance
    payload = asdict(decision())
    payload["cycle_target_quantity"] = 5900
    m.store.save_account_decision("one", payload)
    with m.store._connection:
        m.store._connection.execute(
            "UPDATE virtual_accounts SET quantity=5900,average_cost='5.0000',"
            "realized_pnl='72.0000',observation_start='2026-09-03' WHERE account_id='one'"
        )
        m.store._connection.execute(
            "INSERT INTO account_snapshots VALUES('one','2026-09-03',"
            "'{\"total_assets\":100000,\"session\":\"2026-09-03\"}','now')"
        )
    before = m.store.virtual_account("one")
    m.store.set_setting("last_account_decision_date:one", "2026-09-01")
    m.store.set_setting("last_account_schedule_skip_date:one", "2026-09-01")
    m.store.set_setting("last_prepared_data_id:one", "old")
    m.store.set_setting("unrelated:one", "keep")

    result = update_account_bindings(m.runtime, "v1.0.0", m.updates)

    assert result.status is AccountBindingUpdateStatus.COMMITTED
    assert result.account_ids == ("one", "two")
    after = m.store.virtual_account("one")
    changed = {"release_hash", "strategy_name_snapshot", "qualification_snapshot",
               "last_decision_id", "last_decision_payload", "updated_at"}
    assert {k: v for k, v in after.items() if k not in changed} == {
        k: v for k, v in before.items() if k not in changed
    }
    assert after["release_hash"] == "b" * 64
    assert after["cycle_target"] == after["quantity"] == 5900
    assert after["last_decision_payload"] is None
    old = m.store._connection.execute("SELECT * FROM decisions WHERE account_id='one'").fetchone()
    assert old["status"] == "INVALIDATED"
    assert json.loads(old["payload"])["cycle_target_quantity"] == 5900
    assert json.loads(m.store._connection.execute(
        "SELECT payload FROM account_snapshots"
    ).fetchone()[0]) == {"total_assets": 100000, "session": "2026-09-03"}
    assert m.store.get_setting("last_account_decision_date:one") is None
    assert m.store.get_setting("last_account_schedule_skip_date:one") is None
    assert m.store.get_setting("last_prepared_data_id:one") is None
    assert m.store.get_setting("unrelated:one") == "keep"
    with pytest.raises(ValueError, match="inactive decision"):
        m.store.save_account_decision("one", payload)
    with pytest.raises(ValueError, match="inactive decision"):
        m.store.create_account_intent(
            account_id="one", decision_id=payload["decision_id"], order_sequence=0,
            symbol="588080.SH", side="BUY", quantity=100, limit_price=1,
            valid_session="2026-09-02",
        )
    value = replace(decision(), cycle_target_quantity=5900, target_quantity=5900)
    engine = AccountEngine(m.store, advice=FakeAdvice(value))
    engine.refresh_account("one", prepared=preparation(value))
    rows = m.store._connection.execute("SELECT status FROM decisions WHERE account_id='one'").fetchall()
    assert sorted(row[0] for row in rows) == ["ACTIVE", "INVALIDATED"]


@pytest.mark.parametrize("failure", ["hash", "target", "cutoff", "retired", "frozen", "intent", "attention", "order"])
def test_failed_second_account_rolls_back_entire_batch(maintenance, failure):
    m = maintenance
    updates = m.updates
    with m.store._connection as c:
        if failure == "hash":
            updates = (updates[0], AccountBindingUpdate("two", "d" * 64, "b" * 64))
        elif failure == "target":
            updates = (updates[0], AccountBindingUpdate("two", "a" * 64, "d" * 64))
        elif failure == "cutoff":
            c.execute("UPDATE virtual_accounts SET selection_data_cutoff='2026-09-01' WHERE account_id='two'")
        elif failure == "retired":
            c.execute("UPDATE virtual_accounts SET status='RETIRED' WHERE account_id='two'")
        elif failure == "frozen":
            c.execute("UPDATE virtual_accounts SET frozen_cash='1.0000' WHERE account_id='two'")
        elif failure in {"intent", "attention"}:
            c.execute(
                "INSERT INTO intents(intent_id,account_id,decision_id,order_sequence,symbol,side,"
                "quantity,limit_price,valid_session,payload,status,attention_required,created_at,updated_at) "
                "VALUES('i','two','d',0,'588080.SH','SELL',100,'1','2026-09-02','{}',?,?,'now','now')",
                ("PENDING_SUBMIT" if failure == "intent" else "REJECTED", int(failure == "attention")),
            )
        else:
            c.execute(
                "INSERT INTO orders(channel_order_id,intent_id,account_id,decision_id,payload,"
                "cumulative_filled_quantity,created_at,updated_at) VALUES('o','i','two','d',?,0,'now','now')",
                (json.dumps({"status": "TIMEOUT"}),),
            )
    before = list(m.store._connection.iterdump())
    with pytest.raises(ValueError):
        update_account_bindings(m.runtime, "v1.0.0", updates)
    assert list(m.store._connection.iterdump()) == before


def test_running_writer_blocks_maintenance(maintenance):
    m = maintenance
    with RuntimeDatabaseLock(m.database), pytest.raises(RuntimeAlreadyOwnedError):
        update_account_bindings(m.runtime, "v1.0.0", m.updates)
    assert m.store.virtual_account("one")["release_hash"] == "a" * 64


@pytest.mark.parametrize("values", [("", "a" * 64, "b" * 64), ("one", "old", "b" * 64),
                                   ("one", "a" * 64, "a" * 64), ("one", "a" * 64, None)])
def test_binding_update_rejects_invalid_contract(values):
    with pytest.raises(ValueError):
        AccountBindingUpdate(*values)


def test_duplicate_empty_and_untyped_updates_rejected(maintenance):
    m = maintenance
    for updates in ((), (m.updates[0], m.updates[0]), list(m.updates), ({},)):
        with pytest.raises((TypeError, ValueError)):
            update_account_bindings(m.runtime, "v1.0.0", updates)


@pytest.mark.parametrize("failure", ["unknown", "schema", "package_changed", "qualification"])
def test_preflight_failure_does_not_change_database(maintenance, monkeypatch, failure):
    from paper_trading_engine import account_maintenance as module

    m = maintenance
    updates = m.updates
    if failure == "unknown":
        updates = (AccountBindingUpdate("missing", "a" * 64, "b" * 64),)
    elif failure == "schema":
        m.store.set_setting("runtime_database_schema_version", "1")
    elif failure == "package_changed":
        releases = iter((m.release, SimpleNamespace(manifest_sha256="e" * 64)))
        monkeypatch.setattr(module, "load_release", lambda *_: next(releases))
    else:
        def reject(**kwargs):
            raise ValueError("strategy requires paper trading qualification")
        monkeypatch.setattr(module, "SrtAdviceClient", lambda **_: SimpleNamespace(validate_account_binding=reject))
    before = list(m.store._connection.iterdump())
    with pytest.raises(ValueError):
        update_account_bindings(m.runtime, "v1.0.0", updates)
    assert list(m.store._connection.iterdump()) == before


def test_real_installed_package_binding_is_validated(new_store, pte_frozen, tmp_path):
    from test_watchdog_service import create_release

    context, version = pte_frozen
    runtime = tmp_path / "runtime"
    create_release(context.strategy_root, runtime, "v1.0.0", "a")
    store = new_store(runtime / "shared/state/runtime.db")
    try:
        store.create_virtual_account(
            "one", "one", "S900-v1", "a" * 64, 100000,
            strategy_id="S900", strategy_version="v1", release_hash="a" * 64,
            strategy_name_snapshot="old", qualification_snapshot="PAPER_READY",
            selection_data_cutoff=version.selection_data_cutoff,
        )
        update_account_bindings(runtime, "v1.0.0", (
            AccountBindingUpdate("one", "a" * 64, version.release_hash),
        ))
        assert store.virtual_account("one")["release_hash"] == version.release_hash
    finally:
        store.close()
