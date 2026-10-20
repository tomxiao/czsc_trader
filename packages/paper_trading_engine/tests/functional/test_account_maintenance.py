from dataclasses import asdict, replace
from datetime import date
import json
import shutil
from types import SimpleNamespace

import pytest

from dataflows import DataSpace

from paper_trading_engine import (
    AccountBindingUpdate, AccountBindingUpdateStatus, AccountStrategyBinding,
    update_account_bindings,
)
from paper_trading_engine.runtime_lock import RuntimeAlreadyOwnedError, RuntimeDatabaseLock
from paper_trading_engine.store import PaperStore, RUNTIME_DATABASE_SCHEMA_VERSION
from paper_trading_engine.runtime_config import PteRuntimeConfig
from paper_trading_engine.contracts import OrderSpec
from strategy_manager import Qualification
from pte_support import adopt_test_decision, claim_test_intent, decision, FakeAdvice, preparation


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


@pytest.mark.parametrize("target_version", ["v1", "v2"])
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
    changed = {"strategy_version", "release_hash", "strategy_name_snapshot", "qualification_snapshot",
               "last_decision_id", "last_decision_payload", "updated_at"}
    assert {k: v for k, v in after.items() if k not in changed} == {
        k: v for k, v in before.items() if k not in changed
    }
    assert after["release_hash"] == "b" * 64
    assert after["strategy_version"] == target_version
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


def test_pending_replacement_releases_reservations_atomically(maintenance):
    m = maintenance
    order = OrderSpec("BUY", 100, "LIMIT", 1.0, "DAY")
    old = replace(decision(order), strategy={**decision().strategy, "release_hash": "a" * 64},
                  available_cash=100000)
    m.store.save_account_decision("one", asdict(old))
    m.store.set_virtual_paused("one", False)
    intent = m.store.create_account_intent(account_id="one", decision_id=old.decision_id,
        order_sequence=0, symbol=old.symbol, side="BUY", quantity=100,
        limit_price=1.0, valid_session="2026-09-02")
    m.store.set_virtual_paused("one", True)
    before = m.store.virtual_account("one")
    m.fake.value = decision(order)
    result = update_account_bindings(m.runtime, "v1.0.0", m.updates)
    after = m.store.virtual_account("one")
    assert result.status is AccountBindingUpdateStatus.COMMITTED
    assert after["cash"] == "100000.0000" and after["frozen_cash"] == "0.0000"
    assert after["total_assets"] == before["total_assets"]
    assert m.store.account_intent(intent["intent_id"])["status"] == "SUPERSEDED"
    old_row = m.store.account_decision("one", old.decision_id)
    assert old_row["status"] == "SUPERSEDED"
    assert old_row["superseded_by"] == after["last_decision_id"]
    assert m.store.account_decision("one", after["last_decision_id"])["status"] == "PENDING"
    assert len(m.store.account_intents("one")) == 1


@pytest.mark.parametrize("failure", ["hash", "target", "cutoff", "retired", "frozen", "intent", "submitting", "uncertain", "submitted", "attention", "order"])
def test_failed_second_account_rolls_back_entire_batch(maintenance, failure):
    m = maintenance
    updates = m.updates
    with m.store._connection as c:
        if failure == "hash":
            updates = (updates[0], AccountBindingUpdate("two", "d" * 64, "b" * 64, "v1"))
        elif failure == "target":
            updates = (updates[0], AccountBindingUpdate("two", "a" * 64, "d" * 64, "v1"))
        elif failure == "cutoff":
            c.execute("UPDATE virtual_accounts SET selection_data_cutoff='2026-09-01' WHERE account_id='two'")
        elif failure == "retired":
            c.execute("UPDATE virtual_accounts SET run_state='RETIRED' WHERE account_id='two'")
        elif failure == "frozen":
            c.execute("UPDATE virtual_accounts SET frozen_cash='1.0000' WHERE account_id='two'")
        elif failure in {"intent", "submitting", "uncertain", "submitted", "attention"}:
            c.execute(
                "INSERT INTO intents(intent_id,account_id,decision_id,order_sequence,symbol,side,"
                "quantity,limit_price,valid_session,payload,status,attention_required,created_at,updated_at) "
                "VALUES('i','two','d',0,'588080.SH','SELL',100,'1','2026-09-02','{}',?,?,'now','now')",
                ({"intent": "PENDING_SUBMIT", "submitting": "SUBMITTING", "uncertain": "SUBMISSION_UNCERTAIN", "submitted": "SUBMITTED", "attention": "REJECTED"}[failure], int(failure == "attention")),
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


@pytest.mark.parametrize("values", [("", "a" * 64, "b" * 64, "v2"), ("one", "old", "b" * 64, "v2"),
                                   ("one", "a" * 64, "a" * 64, "v2"), ("one", "a" * 64, None, "v2"),
                                   ("one", "a" * 64, "b" * 64, "v0"), ("one", "a" * 64, "b" * 64, None)])
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
        updates = (AccountBindingUpdate("missing", "a" * 64, "b" * 64, "v1"),)
    elif failure == "schema":
        m.store.set_setting("runtime_database_schema_version", "1")
    elif failure == "package_changed":
        releases = iter((m.release, SimpleNamespace(manifest_sha256="e" * 64)))
        monkeypatch.setattr(module, "load_release", lambda *_: next(releases))
    else:
        def reject(**kwargs):
            raise ValueError("strategy requires paper trading qualification")
        m.fake.validate_account_binding = reject
    before = list(m.store._connection.iterdump())
    with pytest.raises(ValueError):
        update_account_bindings(m.runtime, "v1.0.0", updates)
    assert list(m.store._connection.iterdump()) == before


def test_real_installed_package_binding_is_validated(new_store, pte_frozen, tmp_path, monkeypatch):
    from test_watchdog_service import create_release
    from paper_trading_engine import account_maintenance as module
    from paper_trading_engine.srt_advice_client import SrtAdviceClient

    context, version = pte_frozen
    runtime = tmp_path / "runtime"
    create_release(context.strategy_root, runtime, "v1.0.0", "a")
    PteRuntimeConfig().save(runtime / "shared/config/pte.json")
    def dataflows(**kwargs):
        assert isinstance(kwargs["space"], DataSpace)
        return object()
    monkeypatch.setattr(module, "create_dataflows", dataflows)
    monkeypatch.setattr(SrtAdviceClient, "latest_completed_signal_date", lambda self, at: date(2026, 9, 1))
    value = replace(decision(), strategy={**decision().strategy, "strategy_id": "S900",
        "release_id": "S900-v1", "release_hash": version.release_hash})
    fake = FakeAdvice(value)
    monkeypatch.setattr(SrtAdviceClient, "prepare_account_data", lambda self, **kwargs: preparation(value))
    monkeypatch.setattr(SrtAdviceClient, "get_decision", lambda self, *args, **kwargs: fake.get_decision(*args, **kwargs))
    store = new_store(runtime / "shared/state/runtime.db")
    try:
        store.create_virtual_account(
            "one", "one", "S900-v1", "a" * 64, 100000,
            strategy_id="S900", strategy_version="v1", release_hash="a" * 64,
            strategy_name_snapshot="old", qualification_snapshot="PAPER_READY",
            selection_data_cutoff=version.selection_data_cutoff,
        )
        update_account_bindings(runtime, "v1.0.0", (AccountBindingUpdate("one", "a" * 64, version.release_hash, "v1"),))
        assert store.virtual_account("one")["release_hash"] == version.release_hash
        assert store.virtual_account("one")["run_state"] == "PAUSED"
    finally:
        store.close()


@pytest.mark.parametrize("failure", ["generation", "quantity", "revision", "identity", "preparation", "portfolio_changed"])
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


def test_running_account_requires_explicit_pause(maintenance):
    m = maintenance
    m.store.set_virtual_paused("two", False)
    before = list(m.store._connection.iterdump())
    with pytest.raises(ValueError, match="paused strategy account"):
        update_account_bindings(m.runtime, "v1.0.0", m.updates)
    assert list(m.store._connection.iterdump()) == before


@pytest.mark.parametrize("target_version", ["v1", "v2"])
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


def test_target_version_must_match_authenticated_installed_binding(maintenance):
    m = maintenance
    before = list(m.store._connection.iterdump())
    updates = tuple(replace(update, target_version="v2") for update in m.updates)
    with pytest.raises(ValueError, match="strategy identity, symbol or selection cutoff differs"):
        update_account_bindings(m.runtime, "v1.0.0", updates)
    assert list(m.store._connection.iterdump()) == before


def test_binding_update_requires_explicit_target_version():
    with pytest.raises(TypeError, match="target_version"):
        AccountBindingUpdate("one", "a" * 64, "b" * 64)


def test_version_upgrade_preserves_completed_fills_and_nonzero_portfolio(maintenance):
    m = maintenance
    m.store.set_virtual_paused("one", False)
    adopt_test_decision(m.store, account_id="one", decision_id="OLD-BUY", valid_session="2026-09-02",
                        orders=[{"side": "BUY", "quantity": 1000, "order_type": "LIMIT", "limit_price": 1.68}])
    intent = m.store.create_account_intent(
        account_id="one", decision_id="OLD-BUY", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000, limit_price="1.680",
        valid_session="2026-09-02", fee_rate="0.0005",
    )
    assert claim_test_intent(m.store, intent["intent_id"])
    m.store.bind_channel_order(intent["intent_id"], "old-order", {
        "channel_order_id": "old-order", "symbol": "588080.SH", "side": "BUY",
        "quantity": 1000, "limit_price": 1.68, "status": "SUBMITTED",
        "cumulative_filled_quantity": 0, "average_fill_price": 0, "remark": intent["intent_id"],
    })
    m.store.apply_fill_increment("old-order", cumulative_quantity=1000,
                                 average_price="1.670", occurred_at="2026-09-02T01:31:00+00:00")
    report = m.store.account_order("old-order")
    m.store.update_channel_order_report("old-order", {**report, "status": "FILLED_ALL"})
    m.store.set_virtual_paused("one", True)
    m.fake.value = replace(decision(), target_quantity=1000, cycle_target_quantity=1000)
    updates = _target_version(m, "v2")
    before = m.store.virtual_account("one")
    old_decision = m.store.account_decision("one", "OLD-BUY")
    history = {
        table: [tuple(row) for row in m.store._connection.execute(f"SELECT * FROM {table}")]
        for table in ("intents", "orders", "fills", "account_ledger")
    }
    assert before["quantity"] == 1000 and before["cash"] == "98329.1650"
    assert len(history["fills"]) == 1 and history["account_ledger"]

    update_account_bindings(m.runtime, "v1.0.0", updates)

    after = m.store.virtual_account("one")
    assert after["strategy_version"] == "v2"
    for key in ("cash", "frozen_cash", "total_assets", "initial_cash", "quantity", "average_cost", "realized_pnl", "cycle_target"):
        assert after[key] == before[key]
    for table, rows in history.items():
        assert [tuple(row) for row in m.store._connection.execute(f"SELECT * FROM {table}")] == rows
    assert m.store.account_decision("one", "OLD-BUY") == old_decision


@pytest.mark.parametrize('scenario', [
    'prepare-existing', 'prepare-missing', 'adoption-existing', 'success',
])
@pytest.mark.parametrize('target_version', ['v1', 'v2'])
def test_binding_transaction_restores_current_cache_indexes_on_failure(
    maintenance, monkeypatch, scenario, target_version,
):
    from paper_trading_engine.srt_advice_client import SrtAdviceClient

    m = maintenance
    updates = _target_version(m, target_version)

    def index(account_id, version, release_hash):
        return {'schema_version': 3, 'account_id': account_id, 'symbol': '588080.SH',
                'signal_date': '2026-09-01', 'trading_date': '2026-09-02',
                'releases': {f'S001-{version}': {'release_hash': release_hash}}}

    originals = {}
    old_records = {}
    for account_id in ('one', 'two'):
        root = m.fake._account_root(account_id)
        path = root / 'current.json'
        if scenario != 'prepare-missing':
            SrtAdviceClient._write_index(root, index(account_id, 'v1', 'a' * 64))
            # Retain exact original bytes, including valid insignificant whitespace.
            path.write_bytes(path.read_bytes() + b' \n')
            originals[path] = path.read_bytes()
            old_records.update({record: record.read_bytes() for record in (root / 'preparation-records').glob('*.json')})
        else:
            originals[path] = None

    def prepare(**kwargs):
        root = m.fake._account_root(kwargs['account_id'])
        SrtAdviceClient._write_index(root, index(kwargs['account_id'], kwargs['strategy_version'], 'b' * 64))
        if scenario.startswith('prepare-') and kwargs['account_id'] == 'two':
            raise ValueError('second cache preparation failure')
        return preparation(m.fake.value)

    m.fake.prepare_account_data = prepare
    if scenario == 'adoption-existing':
        original_save = PaperStore.save_account_decision

        def save(store, account_id, payload, **kwargs):
            if account_id == 'two':
                raise ValueError('second cache adoption failure')
            return original_save(store, account_id, payload, **kwargs)

        monkeypatch.setattr(PaperStore, 'save_account_decision', save)
    before = list(m.store._connection.iterdump())

    if scenario == 'success':
        result = update_account_bindings(m.runtime, 'v1.0.0', updates)
        assert result.status is AccountBindingUpdateStatus.COMMITTED
        for path in originals:
            assert json.loads(path.read_bytes())['releases'][f'S001-{target_version}']['release_hash'] == 'b' * 64
            assert m.store.virtual_account(path.parent.name)['strategy_version'] == target_version
    else:
        with pytest.raises(ValueError, match='second cache'):
            update_account_bindings(m.runtime, 'v1.0.0', updates)
        assert list(m.store._connection.iterdump()) == before
        for path, original in originals.items():
            if original is None:
                assert not path.exists()
            else:
                assert path.read_bytes() == original
                assert 'S001-v1' in json.loads(path.read_bytes())['releases']
    for record, original in old_records.items():
        assert record.read_bytes() == original
