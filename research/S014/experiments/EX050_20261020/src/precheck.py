"""Focused pure first-own-SHOCK action, lifecycle and inherited-contract checks."""
import ast
from dataclasses import fields
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import sys

import numpy as np
import pandas as pd
import requests
from strategy_runtime import ImplementationRef, ParameterSet, RuntimeDefinition, StrategyDefinition, materialize_observation

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
SOURCE = EX / "src/strategy_runtime/strategies/shock_state_policy.py"
OLD = ROOT / "research/S014/experiments/EX046_20261020/src/strategy_runtime/strategies/completed_pause_review.py"
FIXTURE = ROOT / "research/S014/experiments/EX043_20261019/src/precheck.py"
HELPER = ROOT / "research/S014/experiments/EX041_20261019/src/precheck.py"
PROFILES = ("ORIGINAL_C9461_CONTROL", "FIRST_SHOCK_NON_FINAL_DAY_DOMINATED_HOLD", "FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD")


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def main():
    attempts = []

    def deny(*args, **kwargs):
        attempts.append("FORBIDDEN")
        raise RuntimeError("Pure synthetic network forbidden")

    requests.sessions.Session.request = deny
    socket.socket.connect = deny
    socket.create_connection = deny
    old, new = module("ex050_old", OLD), module("ex050_new", SOURCE)
    toy, helper = module("ex050_toy", FIXTURE), module("ex050_helper", HELPER)
    checks = []

    def check(name, value):
        assert bool(value), name
        checks.append(name)

    def equal(name, actual, expected):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        checks.append(name)

    def run(args, profile=PROFILES[0]):
        return new.history(*args, new.PolicyConfig.parse({"policy_profile": profile}))

    rising, flat = toy.fixture(), toy.fixture()
    for i in range(len(flat[0])):
        toy.change(flat, i, close=10.0, open_=10.0)
    for name, args in (("rising", rising), ("flat fee loss", flat)):
        expected = old.history(*args, old.PauseConfig.parse({"pause_profile": "AFTER_NET_LOSS_SKIP1"}))
        equal("control every old column exact " + name, run(args)[expected.columns], expected)
    e = int(np.flatnonzero(run(flat).buy_filled_today)[0])
    check("S2 strict tie holds", new.non_final_day_dominated(10., 10., 10.) is True)
    check("S2 final-day dominance exits", new.non_final_day_dominated(11., 10., 10.) is False)
    check("S2 earlier acceleration holds", new.non_final_day_dominated(11., 10., 8.) is True)
    for values in ((np.inf, 10., 10.), (10., np.nan, 10.), (10., 0., 10.), (1e308, 1e-308, 10.)):
        check("unknown nonfinite or ratio boundary " + str(values), new.non_final_day_dominated(*values) is None)
    genuine_features = new.causal_features

    def forced(args, indices):
        def feature(market):
            out = genuine_features(market)
            out["shock_known"] = True
            out["z5"] = 0.0
            for i in indices:
                if i < len(out):
                    out.iloc[i, out.columns.get_loc("z5")] = 3.0
            return out
        new.causal_features = feature
        return args

    entry = [x.copy(deep=True) for x in flat]
    toy.change(entry, e - 5, close=9.5)
    for i in range(e, len(entry[0])):
        toy.change(entry, i, close=10.2)
    forced(entry, (e, e + 2))
    c, s, a = [run(entry, p) for p in PROFILES]
    check("age0 original and age policy exit immediately", c.selected_shock_exit.iloc[e] and a.selected_shock_exit.iloc[e] and a.first_shock_age.iloc[e] == 0 and not a.shock_disable_latched.iloc[e])
    check("S2 first-node TRUE latches even at entryday", s.first_shock_today.iloc[e] and s.first_shock_hold_decision.iloc[e] and s.shock_disable_latched.iloc[e] and s.shock_action_suppressed.iloc[e] and s.target_position.iloc[e] == 1)
    check("latch suppresses later rawSHOCK without reassessment", s.shock_condition.iloc[e + 2] and s.shock_action_suppressed.iloc[e + 2] and not s.first_shock_today.iloc[e + 2])
    check("H10 mandatory still overrides latch", s.deadline_exit.iloc[e + 9] and s.exit_pending.iloc[e + 9])
    later = [x.copy(deep=True) for x in flat]
    for i in range(e + 2, len(later[0])):
        toy.change(later, i, close=10.2)
    toy.change(later, e - 3, close=9.5)
    forced(later, (e + 2, e + 3))
    for profile in PROFILES[1:]:
        table = run(later, profile)
        check("first later node hold " + profile, table.first_shock_age.iloc[e + 2] == 2 and table.shock_disable_latched.iloc[e + 2])
        check("no day-by-day assessment " + profile, table.first_shock_today.iloc[e + 2] and not table.first_shock_today.iloc[e + 3])
        for stop in (e + 1, e + 3, e + 6, e + 11):
            equal("causal held-prefix " + profile + str(stop), run([x.iloc[:stop].copy() for x in later], profile), table.iloc[:stop])
    broken = [x.copy(deep=True) for x in later]
    toy.change(broken, e + 4, close=8.0)
    broken[3].loc[e + 5, "Status"] = "SUSPENDED"
    toy.change(broken, e + 6, open_=8.0)
    forced(broken, (e + 2,))
    for profile in PROFILES[1:]:
        b = run(broken, profile)
        check("cost/support override new latch " + profile, b.shock_disable_latched.iloc[e + 4] and b.selected_cost_exit.iloc[e + 4] and b.exit_pending.iloc[e + 4])
        check("blocked pending retains absolute anchors " + profile, b.pending_inherited.iloc[e + 5] and not b.sell_filled_today.iloc[e + 5] and b.entry_index.iloc[e + 5] == e and b.deadline_index.iloc[e + 5] == e + 9 and b.reservation_index.iloc[e + 5] == e + 10)
        check("actual delayed SELL resets independent state " + profile, b.sell_filled_today.iloc[e + 6] and not b.shock_state_assessed.iloc[e + 6] and not b.shock_disable_latched.iloc[e + 6] and b.first_shock_age.iloc[e + 6] == -1)
    scalar = new.non_final_day_dominated
    new.non_final_day_dominated = lambda *args: None
    try:
        run(later, PROFILES[1])
    except ValueError as exc:
        check("required UNKNOWN fails explicitly", "Unknown S2" in str(exc))
    else:
        raise AssertionError("UNKNOWN silently accepted")
    new.non_final_day_dominated = scalar
    new.causal_features = genuine_features
    failed = [x.copy(deep=True) for x in flat]
    failed[3].loc[e, "Status"] = "SUSPENDED"
    for profile in PROFILES:
        f = run(failed, profile)
        check("failedBUY makes no cycle latch " + profile, f.failed_buy_reset.iloc[e] and not f.shock_state_assessed.iloc[e] and not f.shock_disable_latched.iloc[e] and f.entry_index.iloc[e] == -1)
    observations = 0
    original_definition = old.CompletedPauseStrategy(ParameterSet({"pause_profile": "AFTER_NET_LOSS_SKIP1"})).definition
    for profile in PROFILES:
        strategy = new.ShockStateStrategy(ParameterSet({"policy_profile": profile}))
        definition = strategy.definition
        runtime = RuntimeDefinition(schema_version=3, strategy_family_id="S014", version="v1", release_id="S014-v1", release_hash="a" * 64,
            implementation=ImplementationRef("strategy_runtime.strategies.shock_state_policy", "ShockStateStrategy", 1, sha256(SOURCE.read_bytes()).hexdigest()),
            **{field.name: getattr(definition, field.name) for field in fields(StrategyDefinition)})
        for args in (rising, flat):
            table = strategy.calculate_history(dict(zip(("market", "raw", "limits", "status"), args)), list(pd.to_datetime(args[0].Date)))
            for row in table.to_dict("records"):
                evidence = {series.value_field: row[series.value_field] for series in definition.observation.series}
                materialize_observation(runtime, helper.observed_plan(runtime, evidence))
                observations += 1
        for name in ("inputs", "decision", "execution", "monitoring", "capabilities"):
            check("unchanged contract " + profile + name, getattr(definition, name) == getattr(original_definition, name))
    trees = [ast.parse(p.read_text(encoding="utf-8")) for p in (OLD, SOURCE)]
    for name in ("completed_sign", "causal_features", "tick", "buy_limit", "calendar_request", "derive_calculation_scope"):
        nodes = [next(n for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name == name) for t in trees]
        check("inheritedhelper ASTexact " + name, ast.dump(nodes[0], include_attributes=False) == ast.dump(nodes[1], include_attributes=False))
    for values in ({}, {"policy_profile": True}, {"policy_profile": "BASE"}, {"policy_profile": PROFILES[0], "date": "2026-01-01"}, {"pause_profile": "AFTER_NET_LOSS_SKIP1"}):
        try:
            new.PolicyConfig.parse(values)
        except ValueError:
            checks.append("reject noncanonical config " + str(values))
        else:
            raise AssertionError(values)
    check("normalLF and zero network", b"\r" not in SOURCE.read_bytes() and not attempts)
    report = {"status": "PASS_PURE_SYNTHETIC_ONLY", "checks_count": len(checks), "checks": checks, "actual_SRT_observation_materializations": observations,
        "source_sha256": sha256(SOURCE.read_bytes()).hexdigest(), "previous_source_sha256": sha256(OLD.read_bytes()).hexdigest(),
        "precheck_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(), "fixture_source_sha256": sha256(FIXTURE.read_bytes()).hexdigest(), "helper_source_sha256": sha256(HELPER.read_bytes()).hexdigest(),
        "real_NOOP_equivalence": "NOT_EXECUTED", "new_market_inputs": 0, "new_accounts": 0, "new_fits": 0, "network_attempts": attempts}
    with (EX / "others/synthetic_precheck.json").open("x", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print("PURE_FIRST_SHOCK_PASS", len(checks), "SRT", observations)


if __name__ == "__main__":
    main()
