from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime
import json
import os
import sqlite3
from threading import Barrier, Event, get_ident
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from execution_channels.futu.lifecycle import AccountHealth
from execution_channels.futu.store import PaperStore
from paper_trading_engine import cli as pte_cli
from paper_trading_engine.runtime_lock import RuntimeDatabaseLock
from pte_support import (
    FakeBroker,
)
from pte_control_support import create_bound_account, engine_arguments, installed_binding


def create_account(store, account_id, version, marker):
    return store.create_virtual_account(
        account_id, f"{account_id}模拟账户", "legacy", marker * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version=version, release_hash=marker * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
    )


# Independent risk: EC16; responsibility-level assertions.
def test_new_accounts_are_healthy_without_starting_strategy_execution(memory_store):
    store = memory_store()
    account = create_account(store, "one", "v1", "a")
    assert account["run_state"] == "PAUSED"
    assert account["health"] is AccountHealth.OK
    assert account["last_error"] is None
    reconciliation = store.create_channel_reconciliation_account()
    assert reconciliation["health"] is AccountHealth.OK
    assert reconciliation["last_error"] is None
    assert store.account_decisions("one") == []
    assert store.account_intents("one") == []
    store.close()


def test_display_name_normalization_changes_only_the_account_label_and_audit(memory_store):
    store = memory_store()
    try:
        old = create_account(store, "s001-v1", "v1", "a")
        updated = store.update_virtual_account_name("s001-v1", "S001-v1模拟账户")
        assert updated == {**old, "name": "S001-v1模拟账户", "updated_at": updated["updated_at"]}
        assert store.update_virtual_account_name("s001-v1", updated["name"]) == updated
        events = store.query_audit_events(account_id="s001-v1", event_type="ACCOUNT_DISPLAY_NAME_UPDATED")
        assert len(events) == 1
        assert events[0]["details"] == {"previous_name": old["name"], "name": updated["name"]}
    finally:
        store.close()


# Independent risk: PTE16; responsibility-level assertions.
@pytest.mark.parametrize("action", [
    "create",
], ids=['PTE16-C04'])
def test_account_cli_writes_require_runtime_ownership(tmp_path, action, capsys):
    database = tmp_path / "owned.db"
    argv = ["account", action, "--repo-root", str(tmp_path), "--database", str(database)]
    if action in {"create", "pause", "resume"}:
        argv += ["--account-id", "one"]
    if action == "create":
        argv += ["--name", "One", "--strategy", "S900", "--strategy-version", "v1"]
    with RuntimeDatabaseLock(database):
        assert pte_cli.main(argv) == 5
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "FAIL" and failure["command"] == "pte.account"
    assert "already owned" in failure["error"]["message"]
    assert not database.exists()


# Independent risk: EC16; responsibility-level assertions.
def test_account_capital_allocation_is_atomic_across_connections(new_store, tmp_path):
    database = tmp_path / "capital.db"
    stores = [new_store(database), PaperStore(database)]
    barrier = Barrier(2)

    def create(index):
        store = stores[index]
        balance = store.capital_pool_balance

        def checked_balance():
            assert store._connection.in_transaction, "capital read must be in the write transaction"
            return balance()

        store.capital_pool_balance = checked_balance
        barrier.wait(timeout=5)
        try:
            store.create_virtual_account(
                f"account-{index}", "Audit", "S001-v1", "a" * 64, "600000",
                selection_data_cutoff="2026-09-02",
            )
            return "CREATED"
        except ValueError as exc:
            assert "unallocated capital" in str(exc)
            return "REJECTED"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(create, range(2))) == ["CREATED", "REJECTED"]
        assert len(stores[0].virtual_accounts()) == 1
        assert stores[0]._connection.execute(
            "SELECT sum(CAST(initial_cash AS REAL)) FROM virtual_accounts"
        ).fetchone()[0] == 600000
    finally:
        for store in stores:
            store.close()


# Independent risk: PTE16; responsibility-level assertions.
def test_PTE16_C05_readonly_account_list_never_creates_or_migrates_database(new_store, tmp_path, capsys):
    database = tmp_path / "missing" / "runtime.db"
    argv = ["account", "list", "--repo-root", str(tmp_path), "--database", str(database)]
    assert pte_cli.main(argv) == 5
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "FAIL" and failure["command"] == "pte.account"
    assert not database.parent.exists()

    store = new_store(database)
    store.set_setting("runtime_database_schema_version", "2")
    store.close()
    before = database.read_bytes()
    assert pte_cli.main(argv) == 5
    assert "current PTE database schema" in json.loads(capsys.readouterr().out)["error"]["message"]
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT value FROM settings WHERE key='runtime_database_schema_version'"
        ).fetchone()[0] == "2"


# Independent risk: EC26; responsibility-level assertions.
def test_readonly_store_keeps_consistent_snapshot_and_rejects_writes(new_store, tmp_path):
    database = tmp_path / "snapshot.db"
    writer = new_store(database)
    create_account(writer, "one", "v1", "a")
    writer.set_virtual_paused("one", False)
    reader = PaperStore.open_readonly(database)
    try:
        assert reader.virtual_account("one")["run_state"] == "RUNNING"
        writer.set_virtual_paused("one", True)
        assert reader.virtual_account("one")["run_state"] == "RUNNING"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.set_setting("unauthorized", "1")
    finally:
        reader.close()
        writer.close()


# Independent risk: PTE16; responsibility-level assertions.


# Independent risk: PTE02; responsibility-level assertions.
def test_PTE02_C04_startup_validates_each_account_binding_before_broker_connection(new_store, pte_frozen, tmp_path, monkeypatch):
    context, _ = pte_frozen
    store = new_store(tmp_path / "bindings.db")
    first = installed_binding(context)
    second = replace(first, version="v2", release_hash="b"*64)
    create_bound_account(store, "one", first)
    create_bound_account(store, "two", second)
    store.set_virtual_paused("one", False)
    store.set_virtual_paused("two", False)
    calls, brokers = [], []
    # PTE02 C01-C03 own release authentication. Here each version coordinate
    # must reach that boundary and every account must match its returned binding.
    def validate(client, **kwargs):
        calls.append(kwargs)
        assert kwargs["strategy_id"] == "S900"
        return {"v1": first, "v2": second}[kwargs["strategy_version"]]
    def gateway(**kwargs):
        broker = FakeBroker()
        brokers.append(broker)
        return broker
    monkeypatch.setattr(pte_cli.SrtAdviceClient, "validate_account_binding", validate)
    monkeypatch.setattr(pte_cli.SrtAdviceClient, "prepare_account_data", lambda *a, **kw: pytest.fail("startup must not prepare data"))
    monkeypatch.setattr(pte_cli, "FutuGateway", gateway)
    args = engine_arguments(context.strategy_root.parent, store.path)
    before = store.virtual_accounts()
    try:
        engine = pte_cli.build_engine(args)
        engine.close()
        assert {c["strategy_version"] for c in calls} == {"v1", "v2"}
        assert store.virtual_accounts() == before
        assert len(brokers) == 1 and brokers[0].placed == []
        with store._connection:
            store._connection.execute("UPDATE virtual_accounts SET release_hash=? WHERE account_id='two'", ("c"*64,))
        with pytest.raises(RuntimeError, match="two: account release hash differs"):
            pte_cli.build_engine(args)
        assert len(brokers) == 1
    finally:
        store.close()


# Independent risk: PTE24; responsibility-level assertions.
def test_PTE24_C03_daily_chart_update_retries_then_persists_success_and_skips_closed_days(
    new_store, tmp_path, monkeypatch,
):
    from dataflows import DataError, DataRequest, Dataset
    from paper_trading_engine import account_chart
    from paper_trading_engine.account_chart import AccountChartService
    from paper_trading_engine.chart_market_data import AccountChartDataError
    from execution_channels.futu.trading_window import SHANGHAI

    store = new_store(tmp_path / "daily-charts.db")
    create_account(store, "s001-v1", "v1", "a")
    due = datetime(2026, 9, 4, 20, 30, tzinfo=SHANGHAI)
    calls, clock, failed = [], [0.0], [True]
    render_failed, published = [True], [due.date()]
    monkeypatch.setattr(account_chart.time, "monotonic", lambda: clock[0])

    def history(**kwargs):
        calls.append(kwargs)
        if failed[0]:
            raise AccountChartDataError(
                DataRequest(Dataset.ETF_OHLCV, "588080.SH", "2026-03-06", "2026-09-04", "2026-09-04"),
                DataError("INCOMPLETE_DATA", "published dataframe does not reach the required cutoff",
                          retryable=True, context={"actual_cutoff": "2026-09-03", "full_evidence": "x" * 600}),
            )
        return "a" * 64, pd.DataFrame({
            "Date": ["2026-09-02", published[0].isoformat()],
            "Open": [1, 1], "High": [1, 1], "Low": [1, 1], "Close": [1, 1],
        })

    class ImmediateExecutor:
        def submit(self, fn, *args):
            future = Future()
            try:
                future.set_result(fn(*args))
            except Exception as exc:
                future.set_exception(exc)
            return future

    def render(_request):
        if render_failed[0]:
            raise ValueError("图表渲染失败")
        return "<html>daily chart</html>"

    options = dict(
        market_data=SimpleNamespace(
            history=history, is_trading_day=lambda **kw: (
                kw["session"].weekday() < 5 and kw["session"] != date(2026, 9, 7)
            ),
        ), cache_dir=tmp_path / "charts", executor=ImmediateExecutor(),
        renderer=render,
    )
    service = AccountChartService(store, **options)
    service.refresh_daily(due.replace(hour=20, minute=29))
    assert calls == []
    service.refresh_daily(due)
    assert "实际截至 2026-09-03" in service.current_error("s001-v1")
    events = store.query_audit_events(event_type="ACCOUNT_CHART_GENERATION_FAILED")
    assert events[0]["details"]["data_error"]["context"]["full_evidence"] == "x" * 600
    service.refresh_daily(due)
    assert len(calls) == 1  # Failed updates retain their retry interval.
    failed[0], clock[0] = False, 60.0
    service.refresh_daily(due)
    assert service.current_error("s001-v1") == "图表渲染失败"
    render_failed[0], clock[0] = False, 120.0
    service.refresh_daily(due)
    assert service.current_error("s001-v1") is None
    assert len(calls) == 3 and all(call["refresh_source"] for call in calls)
    assert store.query_audit_events(event_type="ACCOUNT_CHART_RECOVERED")
    status = service.status("s001-v1")
    assert status["market_data_cutoff"] == "2026-09-04"
    assert status["message"] == "等待首个信号"
    assert status["forward_observation_start"] is None
    service.close()

    # A restart and ordinary redraw preserve the completed daily update.
    service = AccountChartService(store, **options)
    service.status("s001-v1")
    calls.clear()
    service.refresh_daily(due)
    service.refresh_daily(due.replace(day=5))
    service.refresh_daily(due.replace(day=5))
    service.refresh_daily(due.replace(day=7))
    assert calls == []
    published[0], clock[0] = date(2026, 9, 8), 180.0
    service.refresh_daily(due.replace(day=8))
    assert len(calls) == 1 and calls[0]["refresh_source"] is True
    assert service.status("s001-v1")["market_data_cutoff"] == "2026-09-08"
    service.close()
    store.close()


# Independent risk: PTE24; responsibility-level assertions.
def test_PTE24_C02_account_chart_runs_market_fetch_and_render_on_dedicated_worker(memory_store, tmp_path, monkeypatch):
    from paper_trading_engine import file_publication
    from paper_trading_engine.account_chart import AccountChartService

    store = memory_store()
    create_account(store, "s001-v2", "v2", "b")
    store.save_account_decision(
        "s001-v2",
        {
            "account_id": "s001-v2",
            "decision_id": "DEC-1",
            "signal_date": "2026-09-03",
            "valid_session": "2026-09-04",
            "action": "WAIT",
            "orders": [],
            "target_quantity": 0,
            "signal_identity":"e"*64, "plan_identity":"f"*64, "runtime_sha256":"c"*64, "symbol":"588080.SH",
            "strategy":{"strategy_id":"S001", "version":"v2", "release_id":"S001-v2", "release_hash":"b"*64},
            "observation": {
                "contract_version": "strategy_observation.v2",
                "strategy": {"strategy_id":"S001", "reference_id":"S001-v2", "release_hash":"b"*64, "runtime_sha256":"c"*64, "symbol":"588080.SH"},
                "definition_sha256":"d"*64, "signal_identity":"e"*64, "plan_identity":"f"*64,
                "signal_date":"2026-09-03", "valid_session":"2026-09-04", "facts":[],
                "status": "READY",
                "action": "WAIT",
                "target_position": 0.0,
                "series": [{
                    "key": "factor_score", "label": "策略得分", "value": 0.2,
                    "guides": [],
                }],
            },
        },
    )
    entered = Event()
    release = Event()
    worker_ids = []
    source_refreshes = []
    original_replace = os.replace
    denied = Event()

    def replace_with_metadata_contention(source, target):
        if target.name == "observation.meta.json" and target.is_file() and not denied.is_set():
            denied.set()
            error = PermissionError("synthetic Windows chart metadata conflict")
            error.winerror = 5
            raise error
        return original_replace(source, target)

    monkeypatch.setattr(os, "replace", replace_with_metadata_contention)
    monkeypatch.setattr(file_publication, "_FILE_REPLACE_DELAYS", (0.025, 0.050, 0.100, 0.200))
    frame = pd.DataFrame(
        [
            {"dt": "2026-09-02", "open": 1, "high": 1.1, "low": 0.9, "close": 1},
            {"dt": "2026-09-03", "open": 1, "high": 1.1, "low": 0.9, "close": 1},
        ]
    )

    def history(**kwargs):
        worker_ids.append(("dfls", get_ident()))
        source_refreshes.append(kwargs["refresh_source"])
        entered.set()
        # The caller controls this barrier, not a supplier timeout. Always
        # release it in finally, including when a responsiveness assertion fails.
        release.wait()
        return "a" * 64, frame

    def render(_request):
        worker_ids.append(("render", get_ident()))
        return "<html>chart</html>"

    caller = get_ident()
    service = AccountChartService(
        store,
        market_data=SimpleNamespace(history=history),
        cache_dir=tmp_path / "charts",
        renderer=render,
        refresh_interval_seconds=3600,
    )
    try:
        started = time.perf_counter()
        first = service.status("s001-v2")
        elapsed = time.perf_counter() - started

        assert first["status"] == "BUILDING", first
        assert elapsed < 0.5, {"elapsed": elapsed, "status": first}
        assert entered.wait(1)
        assert service.refresh("s001-v2")["status"] == "BUILDING"
        assert source_refreshes == [False]
        release.set()
        deadline = time.monotonic() + 2
        ready = service.status("s001-v2")
        while ready["status"] != "READY" and time.monotonic() < deadline:
            time.sleep(0.01)
            ready = service.status("s001-v2")
        assert ready["status"] == "READY", {
            "status": ready, "source_refreshes": source_refreshes, "worker_ids": worker_ids,
            "failures": store.query_audit_events(event_type="ACCOUNT_CHART_GENERATION_FAILED"),
        }
        assert source_refreshes == [False, True]
        assert denied.is_set()
        assert {name for name, _thread_id in worker_ids} == {"dfls", "render"}
        assert all(thread_id != caller for _name, thread_id in worker_ids)
        assert len({thread_id for name, thread_id in worker_ids if name == "render"}) == 1
    finally:
        release.set()
        service.close()
        store.close()


# Independent risk: PTE24; responsibility-level assertions.
def test_PTE24_C04_account_chart_close_does_not_wait_for_stuck_dfls(memory_store, tmp_path):
    from paper_trading_engine.account_chart import AccountChartService

    store = memory_store()
    create_account(store, "s001-v2", "v2", "b")
    entered = Event()
    release = Event()

    def history(**_kwargs):
        entered.set()
        release.wait(2)
        return "a" * 64, pd.DataFrame()

    service = AccountChartService(
        store,
        market_data=SimpleNamespace(history=history),
        cache_dir=tmp_path / "charts",
        fetch_timeout_seconds=10,
        shutdown_timeout_seconds=0.05,
        refresh_interval_seconds=3600,
    )
    assert service.status("s001-v2")["status"] == "BUILDING"
    assert entered.wait(1)

    started = time.perf_counter()
    service.close()
    elapsed = time.perf_counter() - started
    store.close()
    release.set()

    assert elapsed < 0.2


def test_EC26_C06_readonly_missing_database_does_not_create_a_file(tmp_path):
    path = tmp_path / 'never-created.db'
    with pytest.raises(sqlite3.OperationalError,match='unable to open database file'):
        PaperStore.open_readonly(path)
    assert not path.exists()
