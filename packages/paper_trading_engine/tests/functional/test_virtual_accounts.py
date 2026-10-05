from argparse import Namespace
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from threading import Barrier, Event, get_ident
import time
from types import SimpleNamespace

import pandas as pd
import pytest
from dataflows import DataSpace

from paper_trading_engine import AccountStrategyBinding
from strategy_manager import Qualification
from paper_trading_engine.store import PaperStore
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine import cli as pte_cli
from paper_trading_engine.web_api import PteWebApi
from paper_trading_engine.runtime_lock import RuntimeAlreadyOwnedError, RuntimeDatabaseLock
from pte_support import decision


def create_account(store, account_id, version, marker):
    return store.create_virtual_account(
        account_id, f"{account_id}模拟账户", "legacy", marker * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version=version, release_hash=marker * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
    )


@pytest.mark.parametrize("action", ["create", "pause", "resume", "create-reconciliation"])
def test_account_cli_writes_require_runtime_ownership(tmp_path, action):
    database = tmp_path / "owned.db"
    with RuntimeDatabaseLock(database):
        with pytest.raises(RuntimeAlreadyOwnedError):
            pte_cli._run_account_command(Namespace(database=database, account_action=action))
    assert not database.exists()


def test_offline_account_pause_and_resume_are_audited(new_store, tmp_path):
    database = tmp_path / "pause.db"
    store = new_store(database)
    create_account(store, "one", "v1", "a")
    for action, paused, event_type in (
        ("pause", True, "ACCOUNT_PAUSED"), ("resume", False, "ACCOUNT_RESUMED"),
    ):
        result = pte_cli._run_account_command(Namespace(
            database=database, account_action=action, account_id="one",
        ))
        assert bool(result["paused"]) is paused
        assert len(store.query_audit_events(event_type=event_type, account_id="one")) == 1
    store.close()


def test_offline_account_pause_rolls_back_if_audit_cannot_be_saved(new_store, tmp_path, monkeypatch):
    database = tmp_path / "pause-rollback.db"
    store = new_store(database)
    create_account(store, "one", "v1", "a")

    def reject(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(pte_cli.AuditRecorder, "record", reject)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        pte_cli._run_account_command(Namespace(
            database=database, account_action="pause", account_id="one",
        ))
    assert store.virtual_account("one")["paused"] == 0
    store.close()


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


def test_readonly_account_list_never_creates_or_migrates_database(new_store, tmp_path):
    database = tmp_path / "missing" / "runtime.db"
    with pytest.raises(sqlite3.OperationalError):
        pte_cli._run_account_command(Namespace(database=database, account_action="list"))
    assert not database.parent.exists()

    store = new_store(database)
    store.set_setting("runtime_database_schema_version", "2")
    store.close()
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="current PTE database schema"):
        pte_cli._run_account_command(Namespace(database=database, account_action="list"))
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT value FROM settings WHERE key='runtime_database_schema_version'"
        ).fetchone()[0] == "2"


def test_readonly_store_keeps_consistent_snapshot_and_rejects_writes(new_store, tmp_path):
    database = tmp_path / "snapshot.db"
    writer = new_store(database)
    create_account(writer, "one", "v1", "a")
    reader = PaperStore.open_readonly(database)
    try:
        assert reader.virtual_account("one")["paused"] == 0
        writer.set_virtual_paused("one", True)
        assert reader.virtual_account("one")["paused"] == 0
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.set_setting("unauthorized", "1")
    finally:
        reader.close()
        writer.close()


def test_performance_cli_uses_readonly_store(new_store, tmp_path, monkeypatch):
    database = tmp_path / "export.db"
    store = new_store(database)
    store.close()
    called = []

    def export(reader, *args, **kwargs):
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.set_setting("forbidden", "1")
        called.append(True)
        return {}

    monkeypatch.setattr("paper_trading_engine.performance_export.export_performance", export)
    assert pte_cli.main([
        "performance", "export", "--repo-root", str(tmp_path), "--database", str(database),
        "--account-id", "audit", "--recorded-by", "tester", "--output", str(tmp_path / "output.json"),
    ]) == 0
    assert called == [True]


@pytest.mark.parametrize("operation", [
    pte_cli._restart_running_pte, pte_cli._repair_running_ledger,
    pte_cli._create_running_reconciliation_account,
])
def test_control_token_lookup_does_not_migrate_database(new_store, tmp_path, monkeypatch, operation):
    database = tmp_path / "control-schema.db"
    store = new_store(database)
    store.set_setting("runtime_database_schema_version", "2")
    store.close()
    before = database.read_bytes()
    monkeypatch.setattr(pte_cli, "_read_json", lambda *_a, **_k: pytest.fail("no HTTP call expected"))
    with pytest.raises(RuntimeError, match="current PTE database schema"):
        operation(Namespace(database=database, host="127.0.0.1"))
    assert database.read_bytes() == before


@pytest.mark.parametrize("accounts", [[], [{"strategy_id": "S001", "strategy_version": "v1", "release_hash": "e" * 64}]])
def test_startup_reads_existing_bindings_without_default_account_writes(tmp_path, monkeypatch, accounts):
    class ReachedDeploymentValidation(RuntimeError):
        pass

    # A read-only surface deliberately offers no account creation/rename/migration methods.
    closed = []
    store = SimpleNamespace(strategy_virtual_accounts=lambda: accounts, close=lambda: closed.append(True))
    monkeypatch.setattr(pte_cli, "PaperStore", lambda _: store)
    for name in ("AuditRecorder", "SrtAdviceClient", "FutuGateway", "FutuExecution", "ReconnectableExecution"):
        monkeypatch.setattr(pte_cli, name, lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(pte_cli, "FutuGateway", lambda **_: pytest.fail("invalid bindings must block connection"))

    def validate(client, references):
        assert references == accounts
        raise ReachedDeploymentValidation()

    monkeypatch.setattr(pte_cli, "_strategy_deployments", validate)
    args = Namespace(action="once", database=tmp_path / "runtime.db", repo_root=tmp_path,
                     data_dir=tmp_path / "data", data_space=DataSpace(Path("market")), config_root=tmp_path, asset="ETF", symbol="588080.SH",
                     opend_host="127.0.0.1", opend_port=11111)
    with pytest.raises(ReachedDeploymentValidation):
        pte_cli.build_engine(args)
    assert closed == [True]


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-path regression")
def test_account_chart_accepts_equivalent_windows_extended_path(tmp_path, monkeypatch):
    from paper_trading_engine.account_chart import AccountChartService

    cache = tmp_path / "charts"
    cache.mkdir()
    root = cache.resolve()
    extended = Path("\\\\?\\" + str(root / "s001-v2"))
    resolutions = iter((root, extended))
    monkeypatch.setattr(Path, "resolve", lambda self: next(resolutions))
    service = AccountChartService.__new__(AccountChartService)
    service.cache_dir = cache

    assert service._account_dir("s001-v2") == root / "s001-v2"


def test_pte_cli_rejects_retired_account_and_scheduler_aliases(tmp_path):
    parser = pte_cli.build_parser()
    current = parser.parse_args([
        "serve", "--repo-root", str(tmp_path),
        "--data-prepare-interval", "7",
    ])
    assert current.data_prepare_interval == 7

    with pytest.raises(SystemExit):
        parser.parse_args(["serve", "--repo-root", str(tmp_path), "--advice-executable", "old.exe"])

    with pytest.raises(SystemExit):
        parser.parse_args([
            "account", "create", "--repo-root", str(tmp_path),
            "--account-id", "legacy", "--name", "Legacy",
            "--baseline", "baseline_20260903",
        ])
    with pytest.raises(SystemExit):
        parser.parse_args([
            "serve", "--repo-root", str(tmp_path),
            "--data-refresh-time", "20:30",
        ])
    with pytest.raises(SystemExit):
        parser.parse_args([
            "serve", "--repo-root", str(tmp_path),
            "--position-size", "50000",
        ])
    with pytest.raises(SystemExit):
        parser.parse_args([
            "serve", "--repo-root", str(tmp_path),
            "--decision-interval", "7",
        ])


def test_strategy_bindings_reuse_same_coordinate_and_validate_each_account(monkeypatch):
    calls = []
    def validate(**kwargs):
        calls.append(kwargs)
        return AccountStrategyBinding("S001", "v1", "a" * 64, "Test", Qualification.PAPER_READY,
                                      date(2026, 9, 2), kwargs["symbol"], .001)
    client = SimpleNamespace(validate_account_binding=validate)
    accounts = [dict(account_id=name, strategy_id="S001", strategy_version="v1", release_hash="a" * 64,
                     symbol=symbol, asset_type="etf", selection_data_cutoff="2026-09-02")
                for name, symbol in (("one", "588080.SH"), ("two", "588080.SH"), ("three", "510500.SH"))]
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("binding must not spawn a process"))
    bindings = pte_cli._strategy_deployments(client, accounts)
    assert set(bindings) == {"one", "two", "three"}
    assert bindings["one"] is bindings["two"]
    assert bindings["three"].symbol == "510500.SH"
    assert len(calls) == 2
    accounts[1]["release_hash"] = "b" * 64
    with pytest.raises(RuntimeError, match="account release hash differs"):
        pte_cli._strategy_deployments(client, accounts)
    accounts[1]["release_hash"] = "a" * 64
    accounts[1]["selection_data_cutoff"] = "2026-09-03"
    with pytest.raises(RuntimeError, match="selection cutoff differs"):
        pte_cli._strategy_deployments(client, accounts)


def test_ft_pte01_account_model_migration_and_independent_futu_ledgers(tmp_path):
    store = PaperStore(tmp_path / "account-centric.db")
    create_account(store, "s001-v1", "v1", "a")
    create_account(store, "s001-v2", "v2", "b")
    assert {row["channel_id"] for row in store.virtual_accounts()} == {"futu_simulate_cn"}
    assert {row["selection_data_cutoff"] for row in store.virtual_accounts()} == {"2026-09-02"}
    assert len(store.query_audit_events(event_type="ACCOUNT_STRATEGY_BOUND")) == 2
    assert len(store.query_audit_events(event_type="ACCOUNT_CHANNEL_BOUND", channel="futu_simulate_cn")) == 2
    tables = {row[0] for row in store._connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert not {"virtual_intents", "virtual_orders", "virtual_fills", "virtual_snapshots"} & tables

    intent = store.create_account_intent(
        account_id="s001-v2", decision_id="DEC-2", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=1000,
        limit_price="1.680", valid_session="2026-09-04", fee_rate="0.0005",
    )
    assert store.claim_account_intent(intent["intent_id"])
    store.bind_channel_order(intent["intent_id"], "1001", {
        "channel_order_id": "1001", "symbol": "588080.SH", "side": "BUY",
        "quantity": 1000, "limit_price": 1.68, "status": "SUBMITTED",
        "cumulative_filled_quantity": 0, "average_fill_price": 0,
        "remark": intent["intent_id"],
    })
    store.apply_fill_increment(
        "1001", cumulative_quantity=1000, average_price="1.670",
        occurred_at="2026-09-04T01:31:00+00:00",
    )
    assert store.virtual_account("s001-v1")["quantity"] == 0
    assert store.virtual_account("s001-v2")["quantity"] == 1000
    assert store.virtual_account("s001-v2")["cash"] == "98329.1650"
    assert store.virtual_account("s001-v2")["total_assets"] == "99999.1650"
    assert store.account_fills("s001-v2")[0]["channel_id"] == "futu_simulate_cn"

    sell_intent = store.create_account_intent(
        account_id="s001-v2", decision_id="DEC-3", order_sequence=0,
        symbol="588080.SH", side="SELL", quantity=1000,
        limit_price="1.650", valid_session="2026-09-04", fee_rate="0.0005",
        order_type="MARKET",
    )
    assert store.claim_account_intent(sell_intent["intent_id"])
    store.bind_channel_order(sell_intent["intent_id"], "1002", {
        "channel_order_id": "1002", "symbol": "588080.SH", "side": "SELL",
        "quantity": 1000, "limit_price": 1.65, "status": "SUBMITTED",
        "cumulative_filled_quantity": 0, "average_fill_price": 0,
        "remark": sell_intent["intent_id"], "order_type": "MARKET",
    })
    store.apply_fill_increment(
        "1002", cumulative_quantity=1000, average_price="1.600",
        occurred_at="2026-09-04T01:32:00+00:00",
    )
    assert store.virtual_account("s001-v2")["quantity"] == 0
    assert store.virtual_account("s001-v2")["cash"] == "99928.3650"
    assert store.virtual_account("s001-v2")["total_assets"] == "99928.3650"
    assert store.account_fills("s001-v2")[0]["price"] == "1.600"
    store.close()


def test_strategy_name_sync_is_release_guarded_idempotent_and_audited(new_store, tmp_path):
    store = new_store(tmp_path / "strategy-name.db")
    create_account(store, "s001-v1", "v1", "a")

    assert store.synchronize_account_strategy_name(
        "s001-v1", "a" * 64, "科创50多因子趋势策略"
    )
    assert not store.synchronize_account_strategy_name(
        "s001-v1", "a" * 64, "科创50多因子趋势策略"
    )
    assert store.virtual_account("s001-v1")["strategy_name_snapshot"] == (
        "科创50多因子趋势策略"
    )
    events = store.query_audit_events(event_type="ACCOUNT_STRATEGY_NAME_UPDATED")
    assert len(events) == 1
    assert events[0]["details"] == {
        "previous_name": "综合基线策略",
        "name": "科创50多因子趋势策略",
    }
    with pytest.raises(ValueError, match="release hash differs"):
        store.synchronize_account_strategy_name(
            "s001-v1", "b" * 64, "不应写入"
        )
    store.close()


def test_account_metrics_use_prior_snapshot_as_window_baseline(new_store, tmp_path):
    store = new_store(tmp_path / "window-metrics.db")
    create_account(store, "s001-v2", "v2", "b")
    store.save_account_snapshot("s001-v2", "2026-09-09", {
        "quantity": 0, "total_assets": "102000.0000",
    })
    store.save_account_snapshot("s001-v2", "2026-09-10", {
        "quantity": 0, "total_assets": "100980.0000",
    })

    metrics = AccountEngine(store, advice=None).metrics(
        "s001-v2", start="2026-09-10", end="2026-09-10",
    )

    assert metrics["baseline_assets"] == 102000
    assert metrics["total_return"] == pytest.approx(-0.01)
    assert metrics["calmar_ratio"] is None
    assert metrics["annualization_status"] == "INSUFFICIENT_OBSERVATIONS"
    store.close()


def test_account_comparison_uses_each_accounts_observation_window(new_store, tmp_path):
    store = new_store(tmp_path / "comparison-metrics.db")
    create_account(store, "s001-v1", "v1", "a")
    create_account(store, "s001-v2", "v2", "b")
    store.save_account_snapshot("s001-v1", "2026-09-03", {
        "quantity": 0, "total_assets": "100000.0000",
    })
    store.save_account_snapshot("s001-v1", "2026-09-04", {
        "quantity": 0, "total_assets": "90000.0000",
    })
    store.save_account_snapshot("s001-v2", "2026-09-04", {
        "quantity": 0, "total_assets": "110000.0000",
    })
    virtual = AccountEngine(store, advice=None)
    api = PteWebApi(SimpleNamespace(store=store, virtual=virtual, channel=None))

    result = api.comparison([])

    assert result["metric_basis"] == "ACCOUNT_OBSERVATION_WINDOW"
    assert "common_window" not in result
    by_account = {row["account_id"]: row["metrics"] for row in result["accounts"]}
    assert by_account["s001-v1"]["observation_start"] == "2026-09-03"
    assert by_account["s001-v1"]["observation_count"] == 2
    assert by_account["s001-v1"]["total_return"] == pytest.approx(-0.10)
    assert by_account["s001-v2"]["observation_start"] == "2026-09-04"
    assert by_account["s001-v2"]["observation_count"] == 1
    assert by_account["s001-v2"]["total_return"] == pytest.approx(0.10)
    store.close()


def test_ft_pte03_account_chart_builds_bounded_scope_and_reuses_cache(new_store, tmp_path, monkeypatch):
    from paper_trading_engine import account_chart
    from paper_trading_engine.account_chart import AccountChartService

    store = new_store(tmp_path / "chart.db")
    create_account(store, "s001-v2", "v2", "b")
    store.save_account_decision(
        "s001-v2",
        {
            "account_id": "s001-v2",
            "decision_id": "DEC-1",
            "signal_date": "2026-09-03",
            "valid_session": "2026-09-04",
            "action": "WAIT",
            "target_quantity": 0,
            "signal_identity":"e"*64, "plan_identity":"f"*64, "runtime_sha256":"c"*64, "symbol":"588080.SH",
            "strategy":{"release_id":"S001-v2", "release_hash":"b"*64},
            "observation": {
                "contract_version": "strategy_observation.v2",
                "strategy": {"strategy_id":"S001", "reference_id":"S001-v2", "release_hash":"b"*64, "runtime_sha256":"c"*64, "symbol":"588080.SH"},
                "definition_sha256":"d"*64, "signal_identity":"e"*64, "plan_identity":"f"*64,
                "signal_date":"2026-09-03", "valid_session":"2026-09-04", "facts":[],
                "status": "READY",
                "action": "WAIT",
                "target_position": 0.0,
                "series": [
                    {
                        "key": "factor_score",
                        "label": "策略得分",
                        "value": 0.2,
                        "guides": [
                            {"key": "entry", "label": "买入阈值", "value": 0.175}
                        ],
                    }
                ],
            },
        },
    )
    dates = list(pd.bdate_range(end="2026-09-02", periods=185)) + list(
        pd.bdate_range("2026-09-03", "2026-09-04")
    )
    rows = []
    for index, dt in enumerate(dates):
        close = 1 + index / 1000
        rows.append(
            {
                "dt": dt.date().isoformat(),
                "open": close,
                "high": close + 0.01,
                "low": close - 0.01,
                "close": close,
            }
        )
    market_requests = []
    source_fails = [False]

    def history(**kwargs):
        market_requests.append(kwargs)
        if source_fails[0]:
            raise ValueError("supplier daily publication unavailable")
        return "a" * 64, pd.DataFrame(rows)

    market_data = SimpleNamespace(history=history)
    calls = []

    def renderer(request):
        calls.append(request)
        return f"<html>chart-{len(calls)}</html>"

    class ImmediateExecutor:
        def submit(self, fn, *args):
            future = Future()
            try:
                future.set_result(fn(*args))
            except Exception as exc:  # pragma: no cover - asserted through service state
                future.set_exception(exc)
            return future

    service = AccountChartService(
        store,
        market_data=market_data,
        cache_dir=tmp_path / "charts",
        renderer=renderer,
        executor=ImmediateExecutor(),
        refresh_interval_seconds=3600,
    )
    first = service.status("s001-v2")
    assert first["status"] == "READY", first["message"]
    assert first["scope"] == {"account_id": "s001-v2", "release_id": "S001-v2"}
    first_path = service.chart_path("s001-v2", first["fingerprint"])
    assert first_path.read_text(encoding="utf-8") == "<html>chart-1</html>"
    request = calls[0]
    assert request["contract_version"] == "pte_forward_chart.v1"
    assert len(request["market_data"]["bars"]) == 62
    assert request["window"]["context_sessions"] == 60
    assert request["window"]["observation_start"] == "2026-09-03"
    assert request["window"]["omitted_decision_count"] == 0
    assert request["market_data"]["bars"][0]["date"] == dates[125].date().isoformat()
    assert request["market_data"]["bars"][-1]["date"] == "2026-09-04"
    decisions = request["observations"]
    assert {row["account_id"] for row in decisions} == {"s001-v2"}
    assert set(decisions[0]) == {
        "account_id", "decision_id", "signal_date", "valid_session", "generated_at",
        "action", "target_quantity", "observation",
    }
    assert request["strategy"]["release_id"] == "S001-v2"
    assert request["strategy"]["name"] == "综合基线策略"

    second = service.status("s001-v2")
    assert second["fingerprint"] == first["fingerprint"]
    assert len(calls) == 1
    assert [item["refresh_source"] for item in market_requests] == [False]

    monkeypatch.setattr(
        store,
        "account_orders",
        lambda _account_id: [
            {
                "account_id": "s001-v2",
                "created_at": "2026-09-04T09:30:00+08:00",
                "updated_at": "2026-09-04T09:30:05+08:00",
                "status": "FILLED_ALL",
            }
        ],
    )
    order_refresh = service.status("s001-v2")
    assert order_refresh["fingerprint"] == first["fingerprint"]
    assert len(calls) == 1

    monkeypatch.setattr(account_chart, "CACHE_RENDER_REVISION", "next-layout")
    throttled = service.status("s001-v2")
    assert throttled["fingerprint"] == first["fingerprint"]
    assert len(calls) == 1

    refreshed = service.refresh("s001-v2")
    assert [item["refresh_source"] for item in market_requests] == [False, True]
    assert refreshed["fingerprint"] != first["fingerprint"]
    assert len(calls) == 2
    refreshed_path = service.chart_path("s001-v2", refreshed["fingerprint"])
    assert refreshed_path != first_path
    assert refreshed_path.read_text(encoding="utf-8") == "<html>chart-2</html>"
    assert first_path.read_text(encoding="utf-8") == "<html>chart-1</html>"
    source_fails[0] = True
    assert service.refresh("s001-v2")["status"] == "UNAVAILABLE"
    source_fails[0] = False
    assert service.refresh("s001-v2")["status"] == "READY"
    assert all(item["refresh_source"] for item in market_requests[1:])
    service.close()
    store.close()

    legacy = tmp_path / "unsafe-legacy.db"
    connection = sqlite3.connect(legacy)
    connection.executescript(
        "CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
        "CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,event_type TEXT NOT NULL,payload TEXT NOT NULL);"
        "CREATE TABLE intents(intent_id TEXT PRIMARY KEY,decision_id TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,status TEXT NOT NULL,channel_order_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);"
        "CREATE TABLE orders(channel_order_id TEXT PRIMARY KEY,payload TEXT NOT NULL,cumulative_filled_quantity INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);"
    )
    connection.execute(
        "INSERT INTO intents VALUES(?,?,?,?,?,?,?)",
        ("OLD", "DEC", json.dumps({}), "PENDING_SUBMIT", None, "x", "x"),
    )
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError, match="requires empty legacy trading tables"):
        PaperStore(legacy)

    safe_legacy = tmp_path / "safe-legacy.db"
    connection = sqlite3.connect(safe_legacy)
    connection.executescript(
        "CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
        "CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,event_type TEXT NOT NULL,payload TEXT NOT NULL);"
        "CREATE TABLE intents(intent_id TEXT PRIMARY KEY,decision_id TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,status TEXT NOT NULL,channel_order_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);"
        "CREATE TABLE orders(channel_order_id TEXT PRIMARY KEY,payload TEXT NOT NULL,cumulative_filled_quantity INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);"
    )
    connection.close()
    migrated = PaperStore(safe_legacy)
    assert migrated.get_setting("account_execution_schema") == "account_execution.v1"
    assert migrated.query_audit_events(event_type="ACCOUNT_EXECUTION_MIGRATED")
    migrated.close()


@pytest.mark.parametrize("has_forward", [True, False])
def test_cached_chart_background_checks_are_quiet_and_manual_refresh_is_visible(
    new_store, tmp_path, monkeypatch, has_forward,
):
    from paper_trading_engine.account_chart import AccountChartService

    class QueuedExecutor:
        def __init__(self):
            self.jobs = []

        def submit(self, fn, *args):
            future = Future()
            self.jobs.append(future)
            return future

    store = new_store(tmp_path / "chart-progress.db")
    create_account(store, "s001-v2", "v2", "b")
    executor = QueuedExecutor()
    clock = [100.0]
    monkeypatch.setattr("paper_trading_engine.account_chart.time.monotonic", lambda: clock[0])
    service = AccountChartService(
        store, market_data=SimpleNamespace(), cache_dir=tmp_path / "charts", executor=executor,
    )
    directory = tmp_path / "charts" / "s001-v2"
    directory.mkdir(parents=True)
    fingerprint = "a" * 64
    (directory / f"{fingerprint}.html").write_text("<html>cached chart</html>", encoding="utf-8")
    (directory / "observation.meta.json").write_text(json.dumps({
        "fingerprint": fingerprint, "has_forward": has_forward,
        "has_observation": has_forward,
    }), encoding="utf-8")
    expected = "READY" if has_forward else "EMPTY"

    automatic = service.status("s001-v2")
    assert automatic["status"] == expected
    assert automatic["message"] is None if has_forward else (
        "2026-09-02" in automatic["message"] and "此后交易日" in automatic["message"]
    )
    assert len(executor.jobs) == 1 and not executor.jobs[0].done()
    manual = service.refresh("s001-v2")
    assert manual["status"] == "REFRESHING" and manual["message"] == "正在刷新观察图"
    assert manual["chart_url"] == automatic["chart_url"]
    assert len(executor.jobs) == 1  # Manual intent waits for the background job.
    executor.jobs[0].set_result(None)
    assert service.status("s001-v2")["status"] == "REFRESHING"
    assert len(executor.jobs) == 2
    executor.jobs[1].set_result(None)
    assert service.status("s001-v2")["status"] == expected

    clock[0] += 61
    assert service.status("s001-v2")["status"] == expected
    executor.jobs[2].set_exception(ValueError("source unavailable"))
    failed = service.status("s001-v2")
    assert failed["status"] == "UNAVAILABLE" and failed["message"] == "source unavailable"
    clock[0] += 61
    assert service.status("s001-v2")["status"] == "UNAVAILABLE"
    service.close()
    store.close()


def test_account_chart_runs_market_fetch_and_render_on_dedicated_worker(new_store, tmp_path):
    from paper_trading_engine.account_chart import AccountChartService

    store = new_store(tmp_path / "chart-thread.db")
    create_account(store, "s001-v2", "v2", "b")
    store.save_account_decision(
        "s001-v2",
        {
            "account_id": "s001-v2",
            "decision_id": "DEC-1",
            "signal_date": "2026-09-03",
            "valid_session": "2026-09-04",
            "action": "WAIT",
            "target_quantity": 0,
            "signal_identity":"e"*64, "plan_identity":"f"*64, "runtime_sha256":"c"*64, "symbol":"588080.SH",
            "strategy":{"release_id":"S001-v2", "release_hash":"b"*64},
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
        assert release.wait(2)
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
    started = time.perf_counter()
    first = service.status("s001-v2")
    elapsed = time.perf_counter() - started

    assert first["status"] == "BUILDING"
    assert elapsed < 0.5
    assert entered.wait(1)
    assert service.refresh("s001-v2")["status"] == "BUILDING"
    assert source_refreshes == [False]
    release.set()
    deadline = time.monotonic() + 2
    ready = service.status("s001-v2")
    while ready["status"] != "READY" and time.monotonic() < deadline:
        time.sleep(0.01)
        ready = service.status("s001-v2")
    assert ready["status"] == "READY"
    assert source_refreshes == [False, True]
    assert {name for name, _thread_id in worker_ids} == {"dfls", "render"}
    assert all(thread_id != caller for _name, thread_id in worker_ids)
    assert len({thread_id for name, thread_id in worker_ids if name == "render"}) == 1
    service.close()
    store.close()


@pytest.mark.parametrize("old_content", [False, True])
def test_account_chart_uses_only_active_decisions(new_store, tmp_path, old_content):
    from paper_trading_engine.account_chart import AccountChartService

    store = new_store(tmp_path / "chart-active-decisions.db")
    create_account(store, "s001-v2", "v2", "b")

    def decision_payload(decision_id, signal_date, value):
        return {
            "account_id": "s001-v2",
            "decision_id": decision_id,
            "signal_date": signal_date,
            "valid_session": (date.fromisoformat(signal_date)+timedelta(days=1)).isoformat(),
            "action": "WAIT",
            "target_quantity": 0,
            "signal_identity":"e"*64, "plan_identity":"f"*64, "runtime_sha256":"c"*64, "symbol":"588080.SH",
            "strategy":{"release_id":"S001-v2", "release_hash":"b"*64},
            "observation": {
                "contract_version": "strategy_observation.v2",
                "strategy": {"strategy_id":"S001", "reference_id":"S001-v2", "release_hash":"b"*64, "runtime_sha256":"c"*64, "symbol":"588080.SH"},
                "definition_sha256":"d"*64, "signal_identity":"e"*64, "plan_identity":"f"*64,
                "signal_date":signal_date, "valid_session":(date.fromisoformat(signal_date)+timedelta(days=1)).isoformat(), "facts":[],
                "status": "READY",
                "action": "WAIT",
                "target_position": 0.0,
                "series": [{
                    "key": "factor_score", "label": "策略得分", "value": value,
                    "guides": [],
                }],
            },
        }

    legacy = decision_payload("DEC-LEGACY", "2026-09-03", 0.0)
    legacy.pop("observation")
    store.save_account_decision("s001-v2", legacy)
    store.save_account_decision(
        "s001-v2", decision_payload("DEC-OLD", "2026-09-04", 0.1),
    )
    store.supersede_account_decision("s001-v2", "DEC-OLD", "DEC-NEW")
    store.save_account_decision(
        "s001-v2", decision_payload("DEC-NEW", "2026-09-04", 0.2),
    )
    if old_content:
        historical = decision_payload("DEC-PREVIOUS-CONTENT", "2026-09-05", 0.5)
        historical["strategy"]["release_hash"] = "a" * 64
        historical["observation"] = {"contract_version": "strategy_observation.v1", "status": "READY"}
        store.save_account_decision("s001-v2", historical)
    requests = []

    class ImmediateExecutor:
        def submit(self, fn, *args):
            future = Future()
            future.set_result(fn(*args))
            return future

    service = AccountChartService(
        store,
        market_data=SimpleNamespace(history=lambda **_kwargs: (
            "a" * 64,
            pd.DataFrame([
                {
                    "dt": "2026-09-03", "open": 1, "high": 1.1,
                    "low": 0.9, "close": 1,
                },
                {
                    "dt": "2026-09-04", "open": 1, "high": 1.1,
                    "low": 0.9, "close": 1,
                },
            ]),
        )),
        cache_dir=tmp_path / "charts",
        renderer=lambda request: requests.append(request) or "<html>chart</html>",
        executor=ImmediateExecutor(),
        refresh_interval_seconds=0,
    )

    status = service.status("s001-v2")

    assert status["status"] == "READY"
    assert [row["decision_id"] for row in requests[0]["observations"]] == ["DEC-NEW"]
    assert requests[0]["window"]["observation_start"] == "2026-09-04"
    assert requests[0]["window"]["omitted_decision_count"] == 1 + int(old_content)
    assert status["message"] == (
        f"观察事实自 2026-09-04 开始；其中 {1 + int(old_content)} 条决策"
        "缺少可用的观察事实，未绘制策略解释"
    )
    service.close()
    store.close()


def test_account_chart_waits_for_first_observation_without_rejecting_legacy_decision(new_store,
    tmp_path,
):
    from paper_trading_engine.account_chart import AccountChartService

    store = new_store(tmp_path / "chart-legacy-decision.db")
    create_account(store, "s001-v2", "v2", "b")
    store.save_account_decision(
        "s001-v2",
        {
            "account_id": "s001-v2",
            "decision_id": "DEC-LEGACY",
            "signal_date": "2026-09-03",
            "valid_session": "2026-09-04",
            "action": "WAIT",
            "target_quantity": 0,
        },
    )
    requests = []

    class ImmediateExecutor:
        def submit(self, fn, *args):
            future = Future()
            future.set_result(fn(*args))
            return future

    service = AccountChartService(
        store,
        market_data=SimpleNamespace(history=lambda **_kwargs: (
            "a" * 64,
            pd.DataFrame([{
                "dt": "2026-09-03", "open": 1, "high": 1.1,
                "low": 0.9, "close": 1,
            }]),
        )),
        cache_dir=tmp_path / "charts",
        renderer=lambda request: requests.append(request) or "<html>chart</html>",
        executor=ImmediateExecutor(),
        refresh_interval_seconds=3600,
    )

    status = service.status("s001-v2")

    assert status["status"] == "EMPTY"
    assert status["chart_url"]
    assert status["message"] == (
        "等待第一条策略观察事实；其中 1 条决策"
        "缺少可用的观察事实，未绘制策略解释"
    )
    assert requests[0]["observations"] == []
    assert requests[0]["window"]["observation_start"] is None
    assert requests[0]["window"]["omitted_decision_count"] == 1
    service.close()
    store.close()


def test_account_chart_persists_unexpected_executor_failure(new_store, tmp_path):
    from paper_trading_engine.account_chart import AccountChartService

    store = new_store(tmp_path / "chart-executor-failure.db")
    create_account(store, "s001-v2", "v2", "b")

    class FailingExecutor:
        def submit(self, _fn, *_args):
            future = Future()
            future.set_exception(RuntimeError("worker exploded"))
            return future

    service = AccountChartService(
        store,
        market_data=SimpleNamespace(),
        cache_dir=tmp_path / "charts",
        executor=FailingExecutor(),
        refresh_interval_seconds=3600,
    )

    status = service.status("s001-v2")

    assert status["status"] == "UNAVAILABLE"
    assert status["message"] == "worker exploded"
    failures = store.query_audit_events(event_type="ACCOUNT_CHART_GENERATION_FAILED")
    assert len(failures) == 1
    service.close()
    store.close()


def test_account_chart_dfls_timeout_is_reported(new_store, tmp_path):
    from paper_trading_engine.account_chart import AccountChartService

    store = new_store(tmp_path / "chart-timeout.db")
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
        fetch_timeout_seconds=0.05,
        shutdown_timeout_seconds=0.05,
        refresh_interval_seconds=3600,
    )
    assert service.status("s001-v2")["status"] == "BUILDING"
    assert entered.wait(1)
    deadline = time.monotonic() + 1
    unavailable = service.status("s001-v2")
    while unavailable["status"] != "UNAVAILABLE" and time.monotonic() < deadline:
        time.sleep(0.01)
        unavailable = service.status("s001-v2")
    assert unavailable["status"] == "UNAVAILABLE"
    assert "DFLS fetch exceeded 0.05 seconds" in unavailable["message"]
    service.close()
    release.set()
    store.close()


def test_account_chart_close_does_not_wait_for_stuck_dfls(new_store, tmp_path):
    from paper_trading_engine.account_chart import AccountChartService

    store = new_store(tmp_path / "chart-close.db")
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


def test_ft_pte02_selection_cutoff_is_required_immutable_and_safely_backfilled(new_store, tmp_path):
    store = new_store(tmp_path / "cutoff.db")
    columns = {
        row[1] for row in store._connection.execute("PRAGMA table_info(virtual_accounts)")
    }
    assert "selection_data_cutoff" in columns

    with pytest.raises(ValueError, match="selection_data_cutoff"):
        store.create_virtual_account(
            "missing", "缺少截止日", "legacy", "c" * 64, 100_000,
            strategy_id="S001", strategy_name_snapshot="综合基线策略",
            strategy_version="v1", release_hash="c" * 64,
            qualification_snapshot="PAPER_READY", selection_data_cutoff="",
        )

    account = create_account(store, "s001-v1", "v1", "a")
    assert account["selection_data_cutoff"] == "2026-09-02"
    with store._connection:
        store._connection.execute(
            "UPDATE virtual_accounts SET selection_data_cutoff=NULL WHERE account_id='s001-v1'"
        )
    assert store.backfill_account_selection_cutoff("s001-v1", "x" * 64, "2026-08-28") is False
    assert store.virtual_account("s001-v1")["selection_data_cutoff"] is None
    assert store.backfill_account_selection_cutoff("s001-v1", "a" * 64, "2026-08-28") is True
    assert store.virtual_account("s001-v1")["selection_data_cutoff"] == "2026-08-28"
    assert store.backfill_account_selection_cutoff("s001-v1", "a" * 64, "2026-09-01") is False
    assert store.virtual_account("s001-v1")["selection_data_cutoff"] == "2026-08-28"
    store.close()


def test_ft_pte02_new_account_is_created_only_after_strategy_runtime_preflight(
    tmp_path, monkeypatch,
):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    release_hash = "7" * 64
    identity = AccountStrategyBinding(
        "S007", "v1", release_hash, "多源机会风险门控", Qualification.PAPER_READY,
        date(2026, 9, 2), "588080.SH", .001,
    )
    args = Namespace(
        account_action="create",
        database=tmp_path / "runtime.db",
        data_dir=data_dir,
        data_space=DataSpace(Path("market")),
        config_root=tmp_path,
        repo_root=tmp_path,
        account_id="s007-v1",
        name="S007-v1模拟账户",
        strategy="S007",
        strategy_version="v1",
        symbol="588080.SH",
        asset="etf",
        initial_cash="100000",
    )
    monkeypatch.setattr(pte_cli, "_validate_strategy", lambda _args: identity)
    with pytest.raises(RuntimeError, match="valid prepared SRT data is required"):
        pte_cli._run_account_command(args)
    empty = PaperStore(args.database)
    assert empty.virtual_accounts() == []
    empty.close()

    accepted = replace(
        decision(),
        signal_date=date(2026, 9, 15),
        valid_session=date(2026, 9, 16),
        data_cutoff=date(2026, 9, 15),
        strategy={
            "strategy_id": "S007",
            "name": "多源机会风险门控",
            "version": "v1",
            "release_id": "S007-v1",
            "release_hash": release_hash,
            "qualification": "PAPER_READY",
        },
        fee_rate=0.001,
    )
    monkeypatch.setattr(
        pte_cli.SrtAdviceClient,
        "latest_completed_signal_date",
        lambda _self, *_args, **_kwargs: date(2026, 9, 15),
    )
    monkeypatch.setattr(
        pte_cli.SrtAdviceClient,
        "prepare_account_data",
        lambda _self, **_kwargs: SimpleNamespace(
            available_through=date(2026, 9, 15),
            tradable_window=SimpleNamespace(
                start=date(2026, 9, 16), end=date(2026, 9, 16)
            ),
        ),
    )
    def preflight_decision(_self, *_args, **kwargs):
        assert kwargs["account_id"] == args.account_id
        assert kwargs["prepared"].available_through == date(2026, 9, 15)
        return accepted

    monkeypatch.setattr(
        pte_cli.SrtAdviceClient, "get_decision", preflight_decision,
    )
    created = pte_cli._run_account_command(args)
    assert created["account_id"] == "s007-v1"
    assert created["strategy_id"] == "S007"
    assert created["release_hash"] == release_hash
    assert created["initial_cash"] == "100000.0000"
