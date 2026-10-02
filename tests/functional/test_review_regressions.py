"""Boundary regressions for the September code review; all state is temporary."""

import http.client
import shutil
from test_current_contracts import current_frozen as current_frozen, inspection as inspection, completed as completed, managed_evaluation as managed_evaluation

import subprocess
import sys
from threading import Thread
from types import SimpleNamespace

import pandas as pd
import pytest

from czsc_trader.backtesting.metrics import calculate_metrics
from czsc_trader.strategy_metrics import strategy_comparison_metrics
from czsc_trader.candidate_evaluation import _observation
from paper_trading_engine.store import PaperStore
from paper_trading_engine.web import create_server
from strategy_evaluator.benchmark_audit import _metrics
from strategy_manager import StrategyRegistry
from strategy_manager.errors import RegistryError


def test_static_resource_rejects_parent_absolute_and_encoded_paths():
    server = create_server(SimpleNamespace(system_status=lambda: {}), port=0)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        for suffix in (
            "../web.py", "..\\web.py", "%2e%2e%2fweb.py", "C:/Windows/win.ini",
            "../../../../../pyproject.toml", "app.js:stream", "%252e%252e/web.py",
        ):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                connection.request("GET", "/static/" + suffix)
                response = connection.getresponse()
                assert response.status == 404, suffix
                response.read()
            finally:
                connection.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(3)


@pytest.mark.parametrize("existing_quantity", [0, 100])
def test_core_setup_partial_and_duplicate_fills_are_exactly_once(tmp_path, existing_quantity):
    store = PaperStore(tmp_path / "partial.db")
    try:
        store.create_virtual_account(
            "core", "test", "legacy", "a" * 64, 100000,
            strategy_id="S003", strategy_name_snapshot="test", strategy_version="v1",
            release_hash="c" * 64, qualification_snapshot="PAPER_READY",
            selection_data_cutoff="2026-09-08", symbol="510500.SH",
        )
        [intent] = store.create_account_plan_intents(
            account_id="core", decision_id="DEC-TEST", symbol="510500.SH",
            valid_session="2026-09-14", fee_rate="0.0005", legs=[{
                "sequence": 0, "side": "BUY", "quantity": 1000, "order_type": "LIMIT",
                "limit_price": "7.5000", "plan_mode": "CORE_SETUP", "role": "CORE_SETUP",
                "checkpoint": "OPEN", "submit_after": "09:30:00", "submit_before": "09:35:00",
                "dependency_sequence": None, "dependency_required_status": None,
            }],
        )
        assert store.claim_account_intent(intent["intent_id"])
        store.bind_channel_order(intent["intent_id"], "order", {
            "channel_order_id": "order", "symbol": "510500.SH", "side": "BUY",
            "quantity": 1000, "limit_price": 7.5, "status": "SUBMITTED",
            "cumulative_filled_quantity": 0, "average_fill_price": 0,
            "remark": intent["intent_id"],
        })
        def fill(quantity, price="7.4"):
            return store.apply_fill_increment(
                "order", cumulative_quantity=quantity, average_price=price,
                occurred_at="2026-09-14T01:31:00+00:00",
            )
        if existing_quantity:
            with store._lock, store._connection:
                store._connection.execute(
                    "UPDATE virtual_accounts SET quantity=? WHERE account_id='core'",
                    (existing_quantity,),
                )
            before = store.virtual_account("core")
            with pytest.raises(ValueError, match="initially flat"):
                fill(400)
            assert store.virtual_account("core") == before
            assert store.account_fills("core") == []
            return
        fill(400)
        assert store.virtual_account("core")["quantity"] == 400
        assert fill(400) is None
        fill(700, "7.4")
        fill(1000, "7.43")
        final = store.virtual_account("core")
        assert final["quantity"] == final["cycle_target"] == 1000
        assert float(final["cash"]) + float(final["frozen_cash"]) == pytest.approx(92566.285)
        assert fill(1000, "7.43") is None
        assert len(store.account_fills("core")) == 3
        assert store.account_invariant_violations() == []
        with pytest.raises(ValueError, match="cannot decrease"):
            fill(999)
        with pytest.raises(ValueError, match="exceeds"):
            fill(1001)
        assert store.virtual_account("core") == final
    finally:
        store.close()


@pytest.mark.parametrize("values, expected", [
    ([80, 90], -.2), ([80], -.2), ([100], 0), ([110, 120], 0),
    ([80, 120, 90], -.25), ([0], -1),
])
def test_metrics_include_initial_capital(values, expected):
    equity = pd.Series(values, index=pd.date_range("2026-01-05", periods=len(values)), dtype=float)
    trades = pd.DataFrame(columns=["status", "net_return", "exit_date"])
    result = SimpleNamespace(
        equity=equity, account_daily=pd.DataFrame({"equity": equity, "quantity_before": 0}),
        trades=trades, fills=pd.DataFrame(),
    )
    assert calculate_metrics(result, 100)["max_drawdown"] == pytest.approx(expected)
    assert strategy_comparison_metrics(equity, pd.DataFrame(), 100)["max_drawdown"] == pytest.approx(expected)
    assert _metrics(equity, 100, trades)["max_drawdown"] == pytest.approx(expected)
    context = SimpleNamespace(init_cash=100, frequency_window_days=1)
    observation = _observation(context, "C001", "test", "SCREENING", "standard", result)
    assert observation.max_drawdown == pytest.approx(expected)


def test_frozen_loader_rejects_changed_code_even_with_updated_binding(current_frozen, tmp_path):
    context, _ = current_frozen
    shutil.copytree(context.strategy_root, tmp_path / "copy/strategies")
    root = tmp_path / "copy"
    script = r'''
import json, sys
from pathlib import Path
from strategy_runtime import StrategyRelease, RuntimeCompatibilityError
from strategy_runtime.loader import StrategyLoader
from strategy_runtime.implementation_identity import implementation_sha256
strategy_root = Path(sys.argv[1]) / "strategies"
package = strategy_root / "S900/releases/v1/src/strategy_runtime"
release = StrategyRelease.from_mapping(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
if sys.argv[3] == "loaded":
    StrategyLoader(strategy_root).load(release)
source = package / "strategies/candidate_fixture.py"
source.write_text(source.read_text(encoding="utf-8") + "\n# changed after startup\n", encoding="utf-8")
binding_path = package.parent.parent / "runtime_binding.json"
binding = json.loads(binding_path.read_text(encoding="utf-8"))
binding["implementation_sha256"] = implementation_sha256(
    tuple(binding["source_files"]), source_root=package,
)
binding_path.write_text(json.dumps(binding), encoding="utf-8")
try:
    StrategyLoader(strategy_root).load(release)
except RuntimeCompatibilityError as exc:
    assert "file differs" in str(exc), str(exc)
else:
    raise AssertionError("changed runtime was accepted")
'''
    for mode in ("loaded", "not-yet-loaded"):
        completed = subprocess.run([
            sys.executable, "-B", "-c", script, str(root),
            str(root / "strategies/S900/versions/v1.json"), mode,
        ], capture_output=True, text=True, timeout=30)
        assert completed.returncode == 0, completed.stdout + completed.stderr


def test_registry_lock_excludes_other_process_and_releases_after_failure(tmp_path):
    registry = StrategyRegistry(tmp_path)
    destination = tmp_path / "value.json"
    script = '''
from pathlib import Path
import sys
from strategy_manager import StrategyRegistry
from strategy_manager.errors import RegistryError
registry = StrategyRegistry(sys.argv[1])
try:
    registry._atomic_write(Path(sys.argv[1]) / "other.json", "other")
except RegistryError as exc:
    assert "write lock" in str(exc)
else:
    raise AssertionError("competing writer acquired lock")
'''
    with pytest.raises(RuntimeError, match="abort"):
        with registry._write_lock.hold():
            registry._atomic_write(destination, "first")
            completed = subprocess.run(
                [sys.executable, "-B", "-c", script, str(tmp_path)],
                capture_output=True, text=True, timeout=15,
            )
            assert completed.returncode == 0, completed.stdout + completed.stderr
            assert not (tmp_path / "other.json").exists()
            raise RuntimeError("abort")
    reopened = StrategyRegistry(tmp_path)
    reopened._atomic_write(destination, "second", b"first")
    with pytest.raises(RegistryError, match="concurrent change"):
        reopened._atomic_write(destination, "stale", b"first")
    assert destination.read_text() == "second"
