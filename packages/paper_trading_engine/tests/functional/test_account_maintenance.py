from dataclasses import asdict, replace
from datetime import date
import json
import shutil
from types import SimpleNamespace

import pytest
from paper_trading_engine.contracts import OrderSpec

from dataflows import DataSpace

from paper_trading_engine import (
    AccountBindingUpdate, AccountBindingUpdateStatus, AccountStrategyBinding,
    update_account_bindings,
)
from paper_trading_engine.runtime_lock import RuntimeAlreadyOwnedError, RuntimeDatabaseLock
from execution_channels.futu.store import PaperStore, RUNTIME_DATABASE_SCHEMA_VERSION
from paper_trading_engine.runtime_config import PteRuntimeConfig
from strategy_manager import Qualification
from pte_support import decision, FakeAdvice, preparation


@pytest.fixture
def maintenance(new_store, maintenance_database, tmp_path, monkeypatch):
    from paper_trading_engine import account_maintenance as module

    runtime = tmp_path / "runtime"
    database = runtime / "shared/state/runtime.db"
    store = new_store(database, seed=maintenance_database)
    binding = AccountStrategyBinding(
        "S001", "v1", "b" * 64, "current strategy", Qualification.PAPER_READY,
        date(2026, 9, 2), "588080.SH", 0.0005,
    )
    release = SimpleNamespace(
        runtime_root=runtime, release_root=runtime / "releases/v1.0.0",
        manifest={"database_schema": {"compatible": [RUNTIME_DATABASE_SCHEMA_VERSION]}}, manifest_sha256="d" * 64,
    )
    monkeypatch.setattr(module, "load_release", lambda *_: release)
    PteRuntimeConfig().save(runtime / "shared/config/pte.json")
    fake = FakeAdvice(decision())
    fake._account_root = lambda account_id: runtime / "shared/data/accounts" / account_id
    fake.validate_account_binding = lambda **kwargs: binding
    fake.latest_completed_signal_date = lambda at: date(2026, 9, 1)
    fake.prepare_account_data = lambda **kwargs: preparation(fake.value)
    monkeypatch.setattr(module, "SrtAdviceClient", lambda **_: fake)
    def dataflows(**kwargs):
        assert isinstance(kwargs["space"], DataSpace)
        return object()
    monkeypatch.setattr(module, "create_dataflows", dataflows)
    yield SimpleNamespace(
        runtime=runtime, database=database, store=store, binding=binding, release=release, fake=fake,
        updates=tuple(AccountBindingUpdate(x, "a" * 64, "b" * 64, "v1") for x in ("one", "two")),
    )
    store.close()


@pytest.fixture(scope="module")
def maintenance_database(empty_paper_database, frozen_seed_root):
    """Reuse only preparation; every maintenance transaction gets private state."""
    path = frozen_seed_root / "maintenance.db"
    shutil.copyfile(empty_paper_database, path)
    store = PaperStore(path)
    for account_id in ("one", "two"):
        store.create_virtual_account(
            account_id, account_id, "S001-v1", "c" * 64, 100000,
            strategy_id="S001", strategy_version="v1", release_hash="a" * 64,
            strategy_name_snapshot="old strategy", qualification_snapshot="PAPER_READY",
            selection_data_cutoff="2026-09-02",
        )
    store.close()
    return path


def _target_version(maintenance, version):
    """Make the installed target and its real preparation request version-explicit."""
    m = maintenance
    target = replace(m.binding, version=version)
    m.fake.value = replace(m.fake.value, strategy={
        **m.fake.value.strategy, "version": version, "release_id": f"S001-{version}",
    })

    def validate(**kwargs):
        assert kwargs["strategy_version"] == version
        return target

    def prepare(**kwargs):
        assert kwargs["strategy_version"] == version
        return preparation(m.fake.value)

    m.fake.validate_account_binding = validate
    m.fake.prepare_account_data = prepare
    return tuple(replace(update, target_version=version) for update in m.updates)


# Independent risk: PTE17; responsibility-level assertions.
@pytest.mark.parametrize("target_version", [
    "v1",
], ids=['PTE17-C01'])
def test_update_preserves_economics_completed_history_and_health(maintenance, target_version):
    m = maintenance
    value = replace(decision(), strategy={**decision().strategy, "release_hash": "a" * 64},
                    cycle_target_quantity=5900, target_quantity=5900)
    payload = asdict(value)
    m.store.save_account_decision("one", payload)
    with m.store._connection:
        m.store._connection.execute(
            "UPDATE virtual_accounts SET quantity=5900,average_cost='5.0000',"
            "realized_pnl='72.0000',observation_start='2026-09-03',health='BLOCKED',"
            "last_error='existing health issue' WHERE account_id='one'"
        )
        m.store._connection.execute("INSERT INTO account_snapshots VALUES(?,?,?,?)",
            ("one", "2026-09-03", json.dumps({"total_assets": 100000, "session": "2026-09-03"}), "now"))
    m.fake.value = replace(decision(), cycle_target_quantity=5900, target_quantity=5900)
    updates = _target_version(m, target_version)
    before = m.store.virtual_account("one")
    old_before = m.store.account_decision("one", payload["decision_id"])
    history = {
        table: [tuple(row) for row in m.store._connection.execute(f"SELECT * FROM {table}")]
        for table in ("orders", "fills", "account_ledger", "account_snapshots")
    }
    m.store.set_setting("last_prepared_data_id:one", "old")
    m.store.set_setting("unrelated:one", "keep")

    result = update_account_bindings(m.runtime, "v1.0.0", updates)

    assert result.status is AccountBindingUpdateStatus.COMMITTED
    assert result.account_ids == ("one", "two")
    after = m.store.virtual_account("one")
    changed = {"strategy_version", "release_hash", "name", "strategy_name_snapshot", "qualification_snapshot",
               "last_decision_id", "last_decision_payload", "updated_at"}
    assert {k: v for k, v in after.items() if k not in changed} == {
        k: v for k, v in before.items() if k not in changed
    }
    assert after["release_hash"] == "b" * 64
    assert after["strategy_version"] == target_version
    assert after["name"] == f"S001-{target_version}模拟账户"
    assert after["run_state"] == "PAUSED"
    assert after["health"] == "BLOCKED"
    assert after["cycle_target"] == after["quantity"] == 5900
    assert after["last_decision_id"] != payload["decision_id"]
    assert m.store.account_decision("one", payload["decision_id"]) == old_before
    assert m.store.account_decision("one", after["last_decision_id"])["status"] == "COMPLETED"
    assert m.store.get_setting("last_prepared_data_id:one") is None
    assert m.store.get_setting("unrelated:one") == "keep"
    assert m.store.account_intents("one") == []
    for table, rows in history.items():
        assert [tuple(row) for row in m.store._connection.execute(f"SELECT * FROM {table}")] == rows
    event = m.store.query_audit_events(event_type="ACCOUNT_STRATEGY_BOUND", account_id="one")[0]
    assert event["strategy_version"] == target_version
    assert event["details"]["previous_version"] == "v1"
    assert event["details"]["target_version"] == target_version
    assert event["details"]["previous_release_hash"] == "a" * 64


# Independent risk: PTE17; responsibility-level assertions.


# Independent risk: PTE17; responsibility-level assertions.
def test_PTE17_C05_running_writer_blocks_maintenance(maintenance):
    m = maintenance
    with RuntimeDatabaseLock(m.database), pytest.raises(RuntimeAlreadyOwnedError):
        update_account_bindings(m.runtime, "v1.0.0", m.updates)
    assert m.store.virtual_account("one")["release_hash"] == "a" * 64


# Independent risk: PTE17; responsibility-level assertions.


# Independent risk: PTE17; responsibility-level assertions.
@pytest.mark.parametrize("failure", [
    "preparation",
], ids=['PTE17-C03'])
def test_replacement_preparation_failure_keeps_original_binding(maintenance, failure):
    m = maintenance
    original = m.fake.get_decision
    def compute(actual_quantity, available_cash, **kwargs):
        assert not m.store._connection.in_transaction
        if failure == "generation":
            raise ValueError("target cannot compute a replacement")
        if failure == "portfolio_changed":
            with m.store._connection:
                m.store._connection.execute("UPDATE virtual_accounts SET quantity=100 WHERE account_id='two'")
        result = original(actual_quantity, available_cash, **kwargs)
        if failure == "quantity":
            result = replace(result, actual_quantity=999)
        elif failure == "revision":
            result = replace(result, portfolio_revision=999)
        elif failure == "identity":
            result = replace(result, strategy={**result.strategy, "release_hash": "c" * 64})
        return result
    m.fake.get_decision = compute
    if failure == "preparation":
        m.fake.prepare_account_data = lambda **kwargs: None
    before = list(m.store._connection.iterdump())
    with pytest.raises(ValueError):
        update_account_bindings(m.runtime, "v1.0.0", m.updates)
    assert m.store.virtual_account("one")["release_hash"] == "a" * 64
    assert m.store.virtual_account("two")["release_hash"] == "a" * 64
    assert m.store.account_decisions() == []
    if failure != "portfolio_changed":
        assert list(m.store._connection.iterdump()) == before


# Independent risk: PTE17; responsibility-level assertions.
def test_PTE17_C04_running_account_requires_explicit_pause(maintenance):
    m = maintenance
    m.store.set_virtual_paused("two", False)
    before = list(m.store._connection.iterdump())
    with pytest.raises(ValueError, match="paused strategy account"):
        update_account_bindings(m.runtime, "v1.0.0", m.updates)
    assert list(m.store._connection.iterdump()) == before


# Independent risk: PTE17; responsibility-level assertions.
def test_PTE17_C06_target_version_must_match_authenticated_installed_binding(maintenance):
    m = maintenance
    before = list(m.store._connection.iterdump())
    updates = tuple(replace(update, target_version="v2") for update in m.updates)
    with pytest.raises(ValueError, match="strategy identity, symbol or selection cutoff differs"):
        update_account_bindings(m.runtime, "v1.0.0", updates)
    assert list(m.store._connection.iterdump()) == before


# Independent risk: PTE17; separate execution/refusal boundary.
@pytest.mark.parametrize("target_version", [
    "v2",
], ids=['PTE17-C02'])
def test_second_adoption_failure_rolls_back_binding_decisions_and_reservations(maintenance, monkeypatch, target_version):
    m = maintenance
    old = replace(decision(OrderSpec("BUY", 100, "LIMIT", 1.0, "DAY")),
                  strategy={**decision().strategy, "release_hash": "a" * 64}, available_cash=100000)
    m.store.save_account_decision("one", asdict(old))
    m.store.set_virtual_paused("one", False)
    m.store.create_account_intent(account_id="one", decision_id=old.decision_id,
        order_sequence=0, symbol=old.symbol, side="BUY", quantity=100,
        limit_price=1.0, valid_session="2026-09-02")
    m.store.set_virtual_paused("one", True)
    updates = _target_version(m, target_version)
    before = list(m.store._connection.iterdump())
    original = PaperStore.save_account_decision
    def save(store, account_id, payload, **kwargs):
        if account_id == "two":
            raise ValueError("second adoption failure")
        return original(store, account_id, payload, **kwargs)
    monkeypatch.setattr(PaperStore, "save_account_decision", save)
    with pytest.raises(ValueError, match="second adoption failure"):
        update_account_bindings(m.runtime, "v1.0.0", updates)
    assert list(m.store._connection.iterdump()) == before


# Independent risk: PTE17; separate execution/refusal boundary.
