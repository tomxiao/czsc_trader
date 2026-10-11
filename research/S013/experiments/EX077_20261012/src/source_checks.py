"""Pure input/API/phase checks: no real cache, prices, prepare, allocation or account."""

from datetime import date
import importlib.util
from importlib.metadata import version
import json
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd
from dataflows import DataIdentity
from czsc_trader.research_tools import EvaluationCost, EvaluationWindow
from strategy_runtime import ImplementationDependency, StrategyCandidate, StrategyRuntime


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run():
    base = Path(__file__).resolve().parent
    check = load("integration_fixture_check", base / "integration_checks.py")
    assert check.run()["status"] == "PASS"
    driver = load("price_event_driver_fixture", base / "centre_driver.py")
    packing = base / "packing_fixture/strategy_runtime"
    for name, source in (
        ("policy.py", base / "policy.py"),
        ("price_event.py", base / "integration_adapter_draft.py"),
    ):
        target = packing / "strategies" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == source.read_bytes()
        else:
            target.write_bytes(source.read_bytes())
    candidate = StrategyCandidate("S013", "C9077", driver.payload(packing), packing)
    runtime = StrategyRuntime(driver.ROOT / "strategies")
    definition = runtime.describe(candidate)
    assert dict(definition.parameters.values) == {"lookback": 20, "distance": 1.0}
    dependencies = tuple(
        ImplementationDependency(name, version(name))
        for name in ("numpy", "pandas", "czsc-strategy-runtime")
    )
    content_identity = runtime.identify(candidate, dependencies=dependencies)
    assert len(content_identity.content_sha256) == 64
    audit = load("price_event_audit_fixture", base / "centre_audit.py")
    policy = sys.modules["price_event_fixture.policy"]
    axis = pd.bdate_range("2000-01-03", periods=160)
    prices = np.exp(np.cumsum(np.tile([0.01, -0.02, 0.015, -0.005, 0.008], 32)))
    daily = pd.DataFrame({"Date": axis, "Close": prices})
    sessions = axis[121:]
    native = policy.decisions(pd.Series(prices, index=axis), sessions).rename(
        columns={"reason": "signal_reason"}
    )
    expected = audit.independent_history(daily, sessions)
    audit.compare_history(native, expected)
    changed = native.copy()
    changed.loc[sessions[3], "target_position"] = 1 - changed.loc[sessions[3], "target_position"]
    try:
        audit.compare_history(changed, expected)
    except ValueError:
        pass
    else:
        raise AssertionError("changed target accepted")
    constant = daily.copy()
    constant.Close = 1.0
    null_expected = audit.independent_history(constant, sessions)
    null_native = (
        policy.decisions(pd.Series(1.0, index=axis), sessions)
        .rename(columns={"reason": "signal_reason"})
        .drop(columns=["sigma_locked", "known_trough"])
    )
    audit.compare_history(null_native, null_expected)
    cost = EvaluationCost("baseline", 0.001)
    window = EvaluationWindow("full", date(2020, 1, 2), date(2026, 9, 30))
    metadata = {
        "source_time_field": "Date",
        "availability_time_field": "Date",
        "source_calendar": "SSE",
        "available_at": "2026-09-30",
        "request_range_policy": "SUBSET",
    }
    identity = DataIdentity(
        "etf.ohlcv", "artificial", "510500.SH", "2019-01-01", "2026-09-29", "a" * 64, metadata
    )
    serialized = {
        "cost": {
            "scenario_id": cost.scenario_id,
            "one_way_cost": cost.one_way_cost,
            "measurement_tier": cost.measurement_tier,
        },
        "window": {
            "window_id": window.window_id,
            "start": window.start.isoformat(),
            "end": window.end.isoformat(),
        },
        "identity": {
            n: getattr(identity, n)
            for n in ("dataset", "source", "symbol", "data_start", "data_cutoff", "content_sha256")
        }
        | {"metadata": dict(identity.metadata)},
    }
    json.dumps(serialized, allow_nan=False)
    guards = 0
    for phase in ("declare", "prepare", "execute", "verify"):
        with (
            patch.object(driver, "read", return_value={"phase": "unauthorized"}),
            patch.object(driver, "digest", return_value="fixture"),
            patch.object(driver, "write", side_effect=AssertionError("unauthorized attempt wrote")),
        ):
            try:
                driver.authorize(phase, "artificial-no-file")
            except PermissionError:
                guards += 1
            else:
                raise AssertionError("phase guard accepted")
    return {
        "status": "PASS",
        "integration_artificial_checks": 6,
        "integration_parameter_refusals": 3,
        "independent_state_and_zero_sigma": "PASS",
        "mutated_target_refusal": "PASS",
        "public_dataclass_identity_json": "PASS",
        "public_SRT_describe_identify_packing": "PASS",
        "artificial_runtime_content_sha256": content_identity.content_sha256,
        "unauthorized_phase_refusals": guards,
        "real_price_reads": 0,
        "real_new_policy_signals": 0,
        "prepare": 0,
        "evaluate": 0,
        "allocate": 0,
        "publication": 0,
        "provider": 0,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
