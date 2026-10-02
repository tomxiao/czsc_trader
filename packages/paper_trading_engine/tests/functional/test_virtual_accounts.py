from argparse import Namespace
from concurrent.futures import Future
from dataclasses import replace
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from threading import Event, get_ident
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from paper_trading_engine.store import PaperStore
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine import cli as pte_cli
from paper_trading_engine.web_api import PteWebApi
from pte_support import decision


def create_account(store, account_id, version, marker):
    return store.create_virtual_account(
        account_id, f"{account_id}模拟账户", "legacy", marker * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version=version, release_hash=marker * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
    )


@pytest.mark.parametrize("accounts", [[], [{"strategy_id": "S001", "strategy_version": "v1", "release_hash": "e" * 64}]])
def test_startup_reads_existing_bindings_without_default_account_writes(tmp_path, monkeypatch, accounts):
    class ReachedDeploymentValidation(BaseException):
        pass

    # A read-only surface deliberately offers no account creation/rename/migration methods.
    store = SimpleNamespace(strategy_virtual_accounts=lambda: accounts)
    monkeypatch.setattr(pte_cli, "PaperStore", lambda _: store)
    for name in ("AuditRecorder", "SrtAdviceClient", "FutuGateway", "FutuExecution", "ReconnectableExecution"):
        monkeypatch.setattr(pte_cli, name, lambda *args, **kwargs: SimpleNamespace())

    def validate(executable, root, references):
        assert references == [(x["strategy_id"], x["strategy_version"]) for x in accounts]
        raise ReachedDeploymentValidation()

    monkeypatch.setattr(pte_cli, "_strategy_deployments", validate)
    args = Namespace(action="once", database=tmp_path / "runtime.db", repo_root=tmp_path,
                     data_dir=tmp_path / "data", asset="ETF", symbol="588080.SH",
                     opend_host="127.0.0.1", opend_port=11111, advice_executable=None)
    with pytest.raises(ReachedDeploymentValidation):
        pte_cli.build_engine(args)


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


def test_ft_pte01_strategy_account_requires_srt_deployment(monkeypatch, tmp_path):
    payload = {
        "status": "PASS",
        "result": {
            "strategy_id": "S008",
            "version": "v1",
            "strategy_version_hash": "a" * 64,
            "qualification": "PAPER_READY",
            "selection_data_cutoff": "2026-09-02",
            "strategy_version_id": "S008-v1",
        },
    }
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps(payload), stderr=""
        ),
    )
    with pytest.raises(RuntimeError, match="not deployed"):
        pte_cli._strategy_info(tmp_path / "czsc-trader", tmp_path, "S008-v1")

    payload["result"]["deployment_state"] = "SRT_DEPLOYED"
    assert pte_cli._strategy_info(
        tmp_path / "czsc-trader", tmp_path, "S008-v1"
    )["deployment_state"] == "SRT_DEPLOYED"


def test_strategy_deployments_queries_all_accounts_in_one_process(monkeypatch, tmp_path):
    calls = []
    payload = {
        "status": "PASS",
        "result": {
            "strategies": [
                {
                    "strategy_id": strategy_id,
                    "version": version,
                    "strategy_version_id": f"{strategy_id}-{version}",
                    "strategy_version_hash": marker * 64,
                    "qualification": "PAPER_READY",
                    "governance_status": "SGC_VALIDATED",
                    "selection_data_cutoff": "2026-09-02",
                    "deployment_state": "SRT_DEPLOYED",
                }
                for strategy_id, version, marker in (
                    ("S001", "v1", "a"), ("S007", "v1", "b"),
                )
            ]
        },
    }

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    result = pte_cli._strategy_deployments(
        tmp_path / "czsc-trader",
        tmp_path,
        [("S001", "v1"), ("S007", "v1"), ("S001", "v1")],
    )

    assert set(result) == {("S001", "v1"), ("S007", "v1")}
    assert len(calls) == 1
    assert calls[0][0] == [
        str(tmp_path / "czsc-trader"), "strategy", "list",
        "--repo-root", str(tmp_path),
    ]
    assert calls[0][1]["timeout"] == 30


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


def test_strategy_name_sync_is_release_guarded_idempotent_and_audited(tmp_path):
    store = PaperStore(tmp_path / "strategy-name.db")
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


def test_account_metrics_use_prior_snapshot_as_window_baseline(tmp_path):
    store = PaperStore(tmp_path / "window-metrics.db")
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


def test_account_comparison_uses_each_accounts_observation_window(tmp_path):
    store = PaperStore(tmp_path / "comparison-metrics.db")
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


def test_ft_pte03_account_chart_builds_bounded_scope_and_reuses_cache(tmp_path, monkeypatch):
    from paper_trading_engine import account_chart
    from paper_trading_engine.account_chart import AccountChartService

    store = PaperStore(tmp_path / "chart.db")
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
    market_data = SimpleNamespace(
        history=lambda **_kwargs: (
            "a" * 64,
            pd.DataFrame(rows),
        )
    )
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
    assert refreshed["fingerprint"] != first["fingerprint"]
    assert len(calls) == 2
    refreshed_path = service.chart_path("s001-v2", refreshed["fingerprint"])
    assert refreshed_path != first_path
    assert refreshed_path.read_text(encoding="utf-8") == "<html>chart-2</html>"
    assert first_path.read_text(encoding="utf-8") == "<html>chart-1</html>"
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


def test_account_chart_runs_market_fetch_and_render_on_dedicated_worker(tmp_path):
    from paper_trading_engine.account_chart import AccountChartService

    store = PaperStore(tmp_path / "chart-thread.db")
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
    frame = pd.DataFrame(
        [
            {"dt": "2026-09-02", "open": 1, "high": 1.1, "low": 0.9, "close": 1},
            {"dt": "2026-09-03", "open": 1, "high": 1.1, "low": 0.9, "close": 1},
        ]
    )

    def history(**_kwargs):
        worker_ids.append(("dfls", get_ident()))
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
    release.set()
    deadline = time.monotonic() + 2
    ready = service.status("s001-v2")
    while ready["status"] != "READY" and time.monotonic() < deadline:
        time.sleep(0.01)
        ready = service.status("s001-v2")
    assert ready["status"] == "READY"
    assert {name for name, _thread_id in worker_ids} == {"dfls", "render"}
    assert all(thread_id != caller for _name, thread_id in worker_ids)
    assert len({thread_id for _name, thread_id in worker_ids}) == 2
    service.close()
    store.close()


@pytest.mark.parametrize("old_content", [False, True])
def test_account_chart_uses_only_active_decisions(tmp_path, old_content):
    from paper_trading_engine.account_chart import AccountChartService

    store = PaperStore(tmp_path / "chart-active-decisions.db")
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


def test_account_chart_waits_for_first_observation_without_rejecting_legacy_decision(
    tmp_path,
):
    from paper_trading_engine.account_chart import AccountChartService

    store = PaperStore(tmp_path / "chart-legacy-decision.db")
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


def test_account_chart_persists_unexpected_executor_failure(tmp_path):
    from paper_trading_engine.account_chart import AccountChartService

    store = PaperStore(tmp_path / "chart-executor-failure.db")
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


def test_account_chart_dfls_timeout_is_reported(tmp_path):
    from paper_trading_engine.account_chart import AccountChartService

    store = PaperStore(tmp_path / "chart-timeout.db")
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


def test_account_chart_close_does_not_wait_for_stuck_dfls(tmp_path):
    from paper_trading_engine.account_chart import AccountChartService

    store = PaperStore(tmp_path / "chart-close.db")
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


def test_ft_pte02_selection_cutoff_is_required_immutable_and_safely_backfilled(tmp_path):
    store = PaperStore(tmp_path / "cutoff.db")
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
    identity = {
        "strategy_id": "S007",
        "name": "多源机会风险门控",
        "version": "v1",
        "strategy_version_id": "S007-v1",
        "strategy_version_hash": release_hash,
        "qualification": "PAPER_READY",
        "selection_data_cutoff": "2026-09-02",
        "fee_rate": 0.001,
    }
    args = Namespace(
        account_action="create",
        database=tmp_path / "runtime.db",
        data_dir=data_dir,
        repo_root=tmp_path,
        advice_executable=Path("czsc-trader"),
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
