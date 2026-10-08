from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
from threading import Barrier, Event, get_ident
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from paper_trading_engine import AccountRetirementRequest
from paper_trading_engine.futu_execution import FutuExecution
from paper_trading_engine.store import PaperStore
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine import cli as pte_cli
from paper_trading_engine.web_api import PteWebApi
from paper_trading_engine.runtime_lock import RuntimeDatabaseLock
from pte_support import FakeBroker, decision
from pte_control_support import create_bound_account, engine_arguments, installed_binding


def create_account(store, account_id, version, marker):
    return store.create_virtual_account(
        account_id, f"{account_id}模拟账户", "legacy", marker * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version=version, release_hash=marker * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
    )


@pytest.mark.parametrize("action", ["create", "pause", "resume", "create-reconciliation"])
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


def test_offline_account_pause_and_resume_are_atomic_and_audited(new_store, tmp_path, monkeypatch, capsys):
    database = tmp_path / "pause.db"
    store = new_store(database)
    create_account(store, "one", "v1", "a")
    for action, paused, event_type in (
        ("pause", True, "ACCOUNT_PAUSED"), ("resume", False, "ACCOUNT_RESUMED"),
    ):
        assert pte_cli.main([
            "account", action, "--repo-root", str(tmp_path), "--database", str(database),
            "--account-id", "one",
        ]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "PASS" and payload["command"] == f"pte.account.{action}"
        result = payload["result"]
        assert bool(result["paused"]) is paused
        assert len(store.query_audit_events(event_type=event_type, account_id="one")) == 1
    def reject(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(pte_cli.AuditRecorder, "record", reject)
    assert pte_cli.main([
        "account", "pause", "--repo-root", str(tmp_path), "--database", str(database),
        "--account-id", "one",
    ]) == 5
    assert "audit unavailable" in json.loads(capsys.readouterr().out)["error"]["message"]
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


def test_readonly_account_list_never_creates_or_migrates_database(new_store, tmp_path, capsys):
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


@pytest.mark.parametrize("action", ["restart", "repair-ledger", "create-reconciliation"])
def test_control_token_lookup_does_not_migrate_database(new_store, tmp_path, monkeypatch, action, capsys):
    database = tmp_path / "control-schema.db"
    store = new_store(database)
    store.set_setting("runtime_database_schema_version", "2")
    store.close()
    before = database.read_bytes()
    monkeypatch.setattr(pte_cli, "urlopen", lambda *_a, **_k: pytest.fail("no HTTP call expected"))
    argv = ["control", action, "--repo-root", str(tmp_path), "--database", str(database)]
    if action == "repair-ledger":
        argv += ["--account-id", "one", "--intent-id", "PTE-one"]
    assert pte_cli.main(argv) == 5
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "FAIL" and failure["command"] == "pte.control"
    assert "current PTE database schema" in failure["error"]["message"]
    assert database.read_bytes() == before


@pytest.mark.parametrize("state", ["empty", "invalid_binding"])
def test_startup_reads_existing_bindings_without_default_account_writes(
    new_store, request, tmp_path, monkeypatch, state,
):
    repo_root = tmp_path / "repo"
    store = new_store(tmp_path / "runtime.db")
    if state == "invalid_binding":
        context, _ = request.getfixturevalue("pte_frozen")
        repo_root = context.strategy_root.parent
        binding = installed_binding(context)
        create_bound_account(store, "one", replace(binding, release_hash="e" * 64))
    before = store.virtual_accounts()
    broker = FakeBroker()
    connections = []
    closed = []
    close_store = PaperStore.close

    def close(current):
        close_store(current)
        closed.append(current.path)

    monkeypatch.setattr(PaperStore, "close", close)

    def gateway(**kwargs):
        connections.append(kwargs)
        return broker

    monkeypatch.setattr(pte_cli, "FutuGateway", gateway)
    args = engine_arguments(repo_root, store.path)
    try:
        if state == "invalid_binding":
            with pytest.raises(RuntimeError, match="account release hash differs"):
                pte_cli.build_engine(args)
            assert connections == []
            assert store.path in closed
        else:
            engine = pte_cli.build_engine(args)
            try:
                assert engine.store.virtual_accounts() == []
            finally:
                engine.close()
            # Retired accounts must not require their obsolete strategy to load.
            create_account(store, "retired", "v1", "a")
            store.set_virtual_paused("retired", True)
            FutuExecution(store, broker).retire_account(
                AccountRetirementRequest("retired", "a" * 64, "test", "obsolete binding"),
            )
            before = store.virtual_accounts()
            engine = pte_cli.build_engine(args)
            try:
                assert engine.store.virtual_account("retired")["status"] == "RETIRED"
            finally:
                engine.close()
        assert store.virtual_accounts() == before
        assert broker.placed == broker.cancelled == []
    finally:
        store.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-path regression")
def test_account_chart_accepts_equivalent_windows_extended_path(new_store, tmp_path, monkeypatch):
    from paper_trading_engine.account_chart import AccountChartService

    cache = tmp_path / "charts"
    cache.mkdir()
    root = cache.resolve()
    extended = Path("\\\\?\\" + str(root / "s001-v2"))
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == root / "s001-v2":
            return extended
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    store = new_store(tmp_path / "chart.db")
    service = AccountChartService(store, market_data=None, cache_dir=cache)
    try:
        chart = service.chart_path("s001-v2", "a" * 64)
        chart.parent.mkdir()
        chart.write_text("synthetic chart", encoding="utf-8")
        assert chart == root / "s001-v2" / ("a" * 64 + ".html")
        assert chart.read_text(encoding="utf-8") == "synthetic chart"
        with pytest.raises(ValueError, match="invalid account id"):
            service.chart_path("../outside", "a" * 64)
    finally:
        service.close()
        store.close()


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


def test_startup_validates_each_account_binding_before_broker_connection(
    new_store, pte_frozen, tmp_path, monkeypatch,
):
    from strategy_runtime import RuntimeCompatibilityError

    context, _ = pte_frozen
    store = new_store(tmp_path / "bindings.db")
    binding = installed_binding(context)
    for name in ("one", "two"):
        create_bound_account(store, name, binding)
    calls = []
    validate_binding = pte_cli.SrtAdviceClient.validate_account_binding

    def validate(client, **kwargs):
        calls.append(kwargs)
        return validate_binding(client, **kwargs)

    monkeypatch.setattr(pte_cli.SrtAdviceClient, "validate_account_binding", validate)
    monkeypatch.setattr(pte_cli.SrtAdviceClient, "prepare_account_data",
                        lambda *_a, **_k: pytest.fail("startup must not prepare market data"))
    brokers = []

    def gateway(**kwargs):
        broker = FakeBroker()
        brokers.append(broker)
        return broker

    monkeypatch.setattr(pte_cli, "FutuGateway", gateway)
    args = engine_arguments(context.strategy_root.parent, store.path)
    before = store.virtual_accounts()
    try:
        engine = pte_cli.build_engine(args)
        engine.close()
        assert calls and all(call["symbol"] == "588080.SH" for call in calls)
        assert store.virtual_accounts() == before
        assert len(brokers) == 1 and brokers[0].placed == []
        for field, changed, message in (
            ("release_hash", "b" * 64, "account release hash differs"),
            ("selection_data_cutoff", "2099-01-01", "selection cutoff differs"),
        ):
            original = store.virtual_account("two")[field]
            with store._connection:
                store._connection.execute(f"UPDATE virtual_accounts SET {field}=? WHERE account_id='two'", (changed,))
            corrupted = store.virtual_accounts()
            with pytest.raises(RuntimeError, match=message):
                pte_cli.build_engine(args)
            assert store.virtual_accounts() == corrupted
            assert len(brokers) == 1, "invalid binding must block broker connection"
            with store._connection:
                store._connection.execute(f"UPDATE virtual_accounts SET {field}=? WHERE account_id='two'", (original,))
        # A different coordinate must be validated independently. This installed
        # synthetic author has not opted into symbol rebinding.
        create_bound_account(store, "three", replace(binding, symbol="510500.SH"))
        calls.clear()
        before = store.virtual_accounts()
        with pytest.raises(RuntimeCompatibilityError, match="symbol rebinding"):
            pte_cli.build_engine(args)
        assert {call["symbol"] for call in calls} == {"588080.SH", "510500.SH"}
        assert len(brokers) == 1 and store.virtual_accounts() == before
    finally:
        store.close()


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
    assert request["contract_version"] == "pte_forward_chart.v2"
    assert len(request["market_data"]["bars"]) == 62
    assert request["window"]["context_sessions"] == 60
    assert request["window"]["observation_start"] == "2026-09-03"
    assert request["window"]["omitted_decision_count"] == 0
    assert request["market_data"]["bars"][0]["date"] == dates[125].date().isoformat()
    assert request["market_data"]["bars"][-1]["date"] == "2026-09-04"
    decisions = request["observations"]
    assert {row["account_id"] for row in decisions} == {"s001-v2"}
    assert set(decisions[0]) == {
        "account_id", "symbol", "decision_id", "signal_date", "valid_session", "generated_at",
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

def test_daily_chart_update_retries_then_persists_success_and_skips_closed_days(
    new_store, tmp_path, monkeypatch,
):
    from dataflows import DataError, DataRequest, Dataset
    from paper_trading_engine import account_chart
    from paper_trading_engine.account_chart import AccountChartService
    from paper_trading_engine.chart_market_data import AccountChartDataError
    from paper_trading_engine.trading_window import SHANGHAI

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
    assert "交易日20:30更新" in status["message"]
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


def test_legacy_database_with_active_trading_records_is_rejected(tmp_path):
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

def test_empty_legacy_database_migrates_with_audit(tmp_path):
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


def test_account_chart_preserves_signal_history_across_strategy_packages(new_store, tmp_path):
    from paper_trading_engine.account_chart import AccountChartService
    from paper_trading_engine.forward_chart import render_forward_chart_html

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
        "s001-v2", decision_payload("DEC-BASE", "2026-09-02", 0.0),
    )
    store.save_account_decision(
        "s001-v2", decision_payload("DEC-OLD", "2026-09-04", 0.1),
    )
    store.supersede_account_decision("s001-v2", "DEC-OLD", "DEC-NEW")
    store.save_account_decision(
        "s001-v2", decision_payload("DEC-NEW", "2026-09-04", 0.2),
    )
    historical = decision_payload("DEC-PREVIOUS-CONTENT", "2026-09-03", 0.5)
    historical["strategy"] = {"release_hash": "a" * 64, "release_id": "S999-v7"}
    historical["observation"] = {
        "contract_version": "strategy_observation.v1", "status": "READY",
        "series": historical["observation"]["series"],
    }
    store.supersede_account_decision("s001-v2", "DEC-LEGACY", "DEC-PREVIOUS-CONTENT")
    store.save_account_decision("s001-v2", historical)
    requests = []

    def render(request):
        requests.append(request)
        return render_forward_chart_html(request)

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
        renderer=render,
        executor=ImmediateExecutor(),
        refresh_interval_seconds=0,
    )

    status = service.status("s001-v2")

    assert status["status"] == "READY"
    assert {row["decision_id"] for row in requests[0]["observations"]} == {
        "DEC-BASE", "DEC-OLD", "DEC-NEW", "DEC-PREVIOUS-CONTENT",
    }
    assert requests[0]["window"]["observation_start"] == "2026-09-02"
    assert requests[0]["window"]["omitted_decision_count"] == 1
    chart_history = next(row for row in requests[0]["observations"] if row["decision_id"] == "DEC-PREVIOUS-CONTENT")
    assert chart_history["symbol"] == "588080.SH"
    assert chart_history["observation"]["series"][0]["value"] == 0.5
    assert set(chart_history["observation"]) == {"status", "series", "facts"}
    events = {row["decision_id"]: row for row in requests[0]["execution"]["decisions"]}
    assert set(events) == {"DEC-BASE", "DEC-OLD", "DEC-NEW", "DEC-LEGACY", "DEC-PREVIOUS-CONTENT"}
    assert events["DEC-OLD"]["status"] == "SUPERSEDED"
    assert events["DEC-BASE"]["signal_date"] == "2026-09-02"
    assert events["DEC-BASE"]["valid_session"] == "2026-09-03"
    assert status["message"] == (
        "观察事实自 2026-09-02 开始；其中 1 条决策"
        "缺少可用于本图的观察事实，未绘制策略信号"
        "；行情截至 2026-09-04；交易日20:30更新"
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
        "缺少可用于本图的观察事实，未绘制策略信号"
        "；行情截至 2026-09-03；交易日20:30更新"
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
    pte_frozen, tmp_path, monkeypatch, capsys,
):
    context, _ = pte_frozen
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    identity = installed_binding(context)
    release_hash = identity.release_hash
    database = tmp_path / "runtime.db"
    argv = [
        "account", "create", "--repo-root", str(context.strategy_root.parent),
        "--database", str(database), "--data-dir", str(data_dir), "--config-root", str(tmp_path),
        "--account-id", "s900-v1", "--name", "S900-v1模拟账户", "--strategy", "S900",
        "--strategy-version", "v1", "--initial-cash", "100000",
    ]
    monkeypatch.setattr(pte_cli.SrtAdviceClient, "latest_completed_signal_date",
                        lambda *_a, **_k: date(2026, 9, 15))
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("synthetic market data unavailable")
    monkeypatch.setattr(pte_cli.SrtAdviceClient, "prepare_account_data", unavailable)
    assert pte_cli.main(argv) == 5
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "FAIL" and failure["command"] == "pte.account"
    assert "valid prepared SRT data is required" in failure["error"]["message"]
    empty = PaperStore(database)
    assert empty.virtual_accounts() == []
    assert empty.capital_pool_balance().unallocated_cash == 1_000_000
    empty.close()

    accepted = replace(
        decision(),
        signal_date=date(2026, 9, 15),
        valid_session=date(2026, 9, 16),
        data_cutoff=date(2026, 9, 15),
        strategy={
            "strategy_id": "S900",
            "name": identity.name,
            "version": "v1",
            "release_id": "S900-v1",
            "release_hash": release_hash,
            "qualification": "PAPER_READY",
        },
        fee_rate=identity.fee_rate,
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
        assert kwargs["account_id"] == "s900-v1"
        assert kwargs["prepared"].available_through == date(2026, 9, 15)
        return accepted

    monkeypatch.setattr(
        pte_cli.SrtAdviceClient, "get_decision", preflight_decision,
    )
    assert pte_cli.main(argv) == 0
    success = json.loads(capsys.readouterr().out)
    assert success["status"] == "PASS" and success["command"] == "pte.account.create"
    created = success["result"]
    assert created["account_id"] == "s900-v1"
    assert created["strategy_id"] == "S900"
    assert created["release_hash"] == release_hash
    assert created["initial_cash"] == "100000.0000"
