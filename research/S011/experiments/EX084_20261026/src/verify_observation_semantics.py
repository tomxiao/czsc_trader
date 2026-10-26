"""Synthetic observation branch verification; not a market-performance test."""
from pathlib import Path
import importlib.util
import json
import math
import sys

import pandas as pd
from czsc_trader.application import RepositoryContext, validate_frozen_observation_upgrade
from strategy_manager.freeze_contracts import FrozenVersionReference
from strategy_runtime import StrategyCandidate, implementation_sha256, RuntimeContractError
from strategy_runtime.signal_panel import materialize_signal_panel

ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]
FAMILY = HOME.parent.parent.name
REFERENCE = FAMILY + "-v1"
SOURCE = HOME / "src" / REFERENCE / "strategy_runtime"


def rejected(call):
    try:
        call()
    except (RuntimeContractError, ValueError):
        return
    raise AssertionError("invalid observation unexpectedly accepted")


def run():
    sys.dont_write_bytecode = True
    original = json.loads((ROOT / "strategies" / FAMILY / "versions/v1.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "strategies" / FAMILY / "releases/v1/release_manifest.json").read_text(encoding="utf-8"))
    payload = original["strategy_payload"]
    p = payload["parameters"]
    payload["runtime"]["source_files"].append("strategies/observation_explanation.py")
    payload["runtime"]["source_sha256"] = implementation_sha256(tuple(payload["runtime"]["source_files"]), source_root=SOURCE)
    definition = validate_frozen_observation_upgrade(RepositoryContext.discover(ROOT),
        FrozenVersionReference(FAMILY, "v1", original["release_hash"], manifest["package_hash"]),
        StrategyCandidate(FAMILY, "C9950", payload, SOURCE))
    spec = importlib.util.spec_from_file_location("observation_semantics_" + FAMILY, SOURCE / "strategies/observation_explanation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if FAMILY == "S011":
        rows = [("CASH", p["entry"] - 1e-9, 0), ("PRESSURE_ENTRY", p["entry"], 0),
                ("HOLD", p["exit"] + 1e-9, 1), ("PRESSURE_RELEASED", p["exit"], p["max_days"]),
                ("SIGNAL_EXPIRED", p["exit"] + 1e-9, p["max_days"])]
        history = pd.DataFrame(rows, columns=("reason", "score", "intent_age"))
        expected = ["cash", "entered", "hold", "released", "expired"]
        bad = history.copy(); bad.loc[0, "reason"] = "UNKNOWN"
        rejected(lambda: module.observation_history(bad, p))
    else:
        # Each subtype is gated by the recorded entry/exit state. Threshold values
        # are exactly equal at exit boundaries. No new trading decisions are made.
        def row(m, close, ready, active, entered, exited, target=1.1, origin=1.0, gain=.05):
            return dict(m=math.log(m), p=math.log(close), feature_ready=ready,
                target_position=float(active), entry_signal=float(entered), exit_signal=float(exited),
                repair_target=math.log(target), invalidation_origin=math.log(origin),
                center_gain=gain, repair_space=math.expm1(math.log(m)-math.log(close)))
        history = pd.DataFrame([
            row(1.,1.,False,False,False,False), row(1.1,1.2,True,False,False,False,gain=-.1),
            row(1.1,1.,True,True,True,False), row(1.12,1.09,True,True,False,False),
            row(1.12,1.1,True,False,False,True), row(1.,1.05,True,False,False,True),
            row(1.,1.1,True,False,False,True),
        ])
        expected = ["warmup", "inactive", "entered", "active", "exit_target", "exit_center", "exit_both"]
        bad = history.copy(); bad.loc[3, "exit_signal"] = 1.
        rejected(lambda: module.observation_history(bad, p))
    before = history.copy(deep=True)
    evidence = module.observation_history(history, p)
    pd.testing.assert_frame_equal(history, before)
    panel = definition.observation.signal_panel
    snapshots = [materialize_signal_panel(panel, row.to_dict()).to_dict() for _, row in evidence.iterrows()]
    assert [x["explanation"]["case_key"] for x in snapshots] == expected
    assert all(x["explanation"]["judgment"] and x["explanation"]["basis"] and x["explanation"]["next_watch"] for x in snapshots)
    first = evidence.iloc[-1].to_dict()
    rejected(lambda: materialize_signal_panel(panel, {**first, "obs_decision":"unknown"}))
    broken = dict(first); broken.pop("obs_decision")
    rejected(lambda: materialize_signal_panel(panel, broken))
    if FAMILY == "S011":
        assert "0.325" in snapshots[1]["explanation"]["basis"][0]["text"]
        changed = dict(p, entry=.4, max_days=3, premium=.005)
        revised = module.observation_definition(changed).signal_panel
        alternate = module.observation_history(history, changed).iloc[1].to_dict()
        narrative = materialize_signal_panel(revised, alternate).explanation
        assert "0.400" in narrative.basis[0].text and "3" in narrative.next_watch and "0.50%" in narrative.explanation
        rejected(lambda: materialize_signal_panel(panel, {**first, "obs_score":float("nan")}))
    else:
        assert all(x["status"] == "UNAVAILABLE" for x in snapshots[0]["series"] if x["key"] in ("repair_space", "center_change", "center", "close"))
        assert all(x["status"] == "INACTIVE" for x in snapshots[1]["series"] if x["key"] in ("repair_target", "invalidation_origin"))
        assert all(x["status"] == "AVAILABLE" for x in snapshots[4]["series"] if x["key"] in ("repair_target", "invalidation_origin"))
        assert "1.100" in snapshots[4]["explanation"]["basis"][0]["text"]
        changed = dict(p, lookback=5, minimum_repair_space=.02, allocation=.5)
        alternate = module.observation_history(history, changed).iloc[2].to_dict()
        narrative = materialize_signal_panel(module.observation_definition(changed).signal_panel, alternate).explanation
        assert "2.00%" in narrative.basis[0].text and "5" in narrative.explanation and "50.00%" in narrative.explanation
        rejected(lambda: materialize_signal_panel(panel, {**first,"obs_feature_status":"UNAVAILABLE","obs_feature_reason":"缺少价格"}))
    report = {"status":"PASS", "scope":"SYNTHETIC_OBSERVATION_SEMANTICS_AND_PUBLIC_UPGRADE_SOURCE_VALIDATION", 
        "reference":REFERENCE, "observation_sha256":definition.observation.sha256,
        "covered_states":expected, "cases":snapshots,
        "checks":["Trading AST and contracts retained by public validator", "Original series/facts retained", "Source history not mutated", "All explanation branches materialized", "Parameter references change with actual parameters", "Unknown and missing states fail", "Unavailable values never fabricate numeric explanation"],
        "limits":["Synthetic branch projection tests are not historical strategy equivalence or performance evidence; parent workflow performs actual replay."]}
    output = HOME / "others/observation_semantics_v2.json"
    if output.exists():
        raise FileExistsError(output)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(REFERENCE, "SEMANTICS_PASS", len(expected), definition.observation.sha256)


if __name__ == "__main__":
    run()
