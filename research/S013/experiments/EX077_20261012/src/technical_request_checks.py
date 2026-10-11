"""Artificial prices and original public request metadata only; zero prepare/account."""

from datetime import date
from hashlib import sha256
import importlib.util
from importlib.metadata import version
import json
from pathlib import Path
import sys
import types

import numpy as np
import pandas as pd
from dataflows import DataCoverageRequirement, DataRequest
from strategy_runtime import (
    ImplementationDependency,
    ParameterSet,
    StrategyCandidate,
    StrategyRuntime,
    TradableWindow,
)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run():
    base = Path(__file__).resolve().parent
    root = next(p for p in base.parents if (p / "pyproject.toml").exists())
    package = types.ModuleType("price_event_reuse_fixture")
    package.__path__ = [str(base)]
    sys.modules[package.__name__] = package
    policy = load(package.__name__ + ".policy", base / "policy.py")
    adapter = load(package.__name__ + ".adapter", base / "integration_adapter_reuse_r2.py")
    instance = adapter.PriceEvent(ParameterSet({"lookback": 20, "distance": 1.0}))
    # Read public metadata only. Never baseline pickle/native numeric prices.
    plan = json.loads(
        (root / "research/S013/experiments/EX077_20261012/protocols/plan.json").read_text(
            encoding="utf-8-sig"
        )
    )
    original = plan["baseline_input_bindings"]["full"]["plan"]
    calendar = tuple(date.fromisoformat(x) for x in original["calendar_dates"])
    window = TradableWindow(date(2020, 1, 2), date(2026, 9, 30))
    scope = instance.derive_calculation_scope(window, calendar)
    actual = {"calendar": instance.calendar_request(window), **scope.inputs}
    for name, raw in original["requests"].items():
        values = {
            k: v for k, v in raw.items() if k not in ("parameters", "parameter_type", "coverage")
        }
        values["coverage"] = DataCoverageRequirement(**raw["coverage"]) if raw["coverage"] else None
        expected = DataRequest(**values)
        assert actual[name] == expected, name
    assert {str(k): str(v) for k, v in scope.signal_dates.items()} == original["signal_dates"]
    assert [str(x) for x in scope.calculation_dates] == original["calculation_dates"]
    assert instance.definition.inputs.requirements[0].lookback_sessions == 121
    axis = pd.bdate_range("2000-01-03", periods=200)
    prices = np.exp(np.cumsum(np.tile([0.01, -0.02, 0.015, -0.005, 0.008], 40)))
    full = pd.Series(prices, index=axis)
    signals = axis[179:]
    for lookback in (2, 20, 120):
        more = policy.decisions(full, signals, lookback=lookback, distance=1.0)
        minimal = policy.decisions(full.iloc[59:], signals, lookback=lookback, distance=1.0)
        pd.testing.assert_frame_equal(more, minimal, check_exact=True)
        assert more.iloc[0].state_before == "FLAT"
    packing = base / "packing_fixture_r2/strategy_runtime"
    for name, source in (
        ("policy.py", base / "policy.py"),
        ("price_event.py", base / "integration_adapter_reuse_r2.py"),
    ):
        target = packing / "strategies" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == source.read_bytes()
        else:
            target.write_bytes(source.read_bytes())
    files = ["strategies/policy.py", "strategies/price_event.py"]
    from strategy_runtime import implementation_sha256

    candidate = StrategyCandidate(
        "S013",
        "C9078",
        {
            "parameters": {"lookback": 20, "distance": 1.0},
            "runtime": {
                "contract_version": 1,
                "module": "strategy_runtime.strategies.price_event",
                "qualname": "PriceEvent",
                "source_files": files,
                "source_sha256": implementation_sha256(files, source_root=packing),
            },
        },
        packing,
    )
    runtime = StrategyRuntime(root / "strategies")
    definition = runtime.describe(candidate)
    assert dict(definition.parameters.values) == {"lookback": 20, "distance": 1.0}
    dependencies = tuple(
        ImplementationDependency(x, version(x))
        for x in ("numpy", "pandas", "czsc-strategy-runtime")
    )
    identity = runtime.identify(candidate, dependencies=dependencies)
    return {
        "status": "PASS",
        "calendar_daily_execution_requests_exact_original": True,
        "signal_calculation_prefix_exact_original": True,
        "extra180_vs121_warm_bitexact_for_L": [2, 20, 120],
        "initial_state": "FLAT",
        "definition_minimum_history": 121,
        "actual_daily_request_coverage": 180,
        "SRT_describe_identify": "PASS",
        "candidate_id_unregistered": "C9078",
        "content_sha256": identity.content_sha256,
        "original_policy_sha256": sha256((base / "policy.py").read_bytes()).hexdigest(),
        "real_price_reads": 0,
        "real_new_policy_signals": 0,
        "prepare": 0,
        "evaluate": 0,
        "provider": 0,
        "allocate": 0,
        "publish": 0,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
