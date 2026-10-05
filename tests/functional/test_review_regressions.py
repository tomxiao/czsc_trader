"""Boundary regressions for the September code review; all state is temporary."""

import shutil
from test_current_contracts import current_frozen as current_frozen, inspection as inspection, completed as completed, managed_evaluation as managed_evaluation

import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from czsc_trader.backtesting.metrics import calculate_metrics
from czsc_trader.strategy_metrics import strategy_comparison_metrics
from czsc_trader.research_tools.evaluation import _observation
from strategy_evaluator.benchmark_audit import _metrics


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
    observation = _observation(context, "C0001", "test", "SCREENING", "standard", result)
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
