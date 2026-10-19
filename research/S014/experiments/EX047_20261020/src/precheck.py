"""Pure SHOCK-action ablation and original C9461 contract boundary checks."""
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
SOURCE = EX / "src/strategy_runtime/strategies/shock_action_review.py"
OLD = ROOT / "research/S014/experiments/EX046_20261020/src/strategy_runtime/strategies/completed_pause_review.py"
FIXTURE = ROOT / "research/S014/experiments/EX043_20261019/src/precheck.py"
HELPER = ROOT / "research/S014/experiments/EX041_20261019/src/precheck.py"
PROFILES = ("SHOCK_ON", "SHOCK_OFF")


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def main():
    dest = EX / "others/synthetic_precheck.json"
    assert not dest.exists(), "Preserve prior synthetic evidence"
    attempts = []

    def deny_network(*args, **kwargs):
        attempts.append("FORBIDDEN")
        raise RuntimeError("Synthetic network forbidden")

    requests.sessions.Session.request = deny_network
    socket.socket.connect = deny_network
    socket.create_connection = deny_network
    old, new = module("ex047_old", OLD), module("ex047_new", SOURCE)
    toy, helper = module("ex047_toy", FIXTURE), module("ex047_helper", HELPER)
    checks = []

    def check(name, value):
        assert bool(value), name
        checks.append(name)

    def equal(name, actual, expected):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        checks.append(name)

    def run(args, profile="SHOCK_ON"):
        return new.history(*args, new.ShockConfig.parse({"shock_profile": profile}))

    rising, flat, varied = toy.fixture(), toy.fixture(), toy.fixture()
    for i in range(len(flat[0])):
        toy.change(flat, i, close=10.0, open_=10.0)
        p = 10.0 + 0.1 * np.sin(i * 1.2)
        toy.change(varied, i, close=p, open_=p)
    oldconfig = old.PauseConfig.parse({"pause_profile": "AFTER_NET_LOSS_SKIP1"})
    for label, args in (("rising", rising), ("flat fee loss", flat), ("varied", varied)):
        expected = old.history(*args, oldconfig)
        equal("SHOCK_ON complete old history exact " + label, run(args)[expected.columns], expected)
    on, off = run(rising), run(rising, "SHOCK_OFF")
    e = int(np.flatnonzero(on.buy_filled_today)[0])
    D = int(np.flatnonzero(on.selected_shock_exit)[0])
    check("rising fixture covers original positive-P shock", on.shock_condition.iloc[D] and on.selected_shock_exit.iloc[D] and on.exit_pending.iloc[D])
    check("OFF raw positive-P shock retained with actualaction suppressed", off.shock_condition.iloc[D] and off.selected_profit_exit.iloc[D] and off.shock_action_suppressed.iloc[D] and not off.selected_shock_exit.iloc[D])
    check("first raw shock OFF keeps held when no otherexit", off.held_at_close.iloc[D] and off.target_position.iloc[D] == 1 and not off.exit_pending.iloc[D])
    equal("prefix until first raw shock old fields exact", off[old.history(*rising, oldconfig).columns].iloc[:D], on[old.history(*rising, oldconfig).columns].iloc[:D])
    check("no selectedshock in OFF despite truthfulraw conditions", not off.selected_shock_exit.any() and off.shock_condition.any())
    check("new constant modeflag is not an old-field divergence", not off.shock_action_enabled.any() and on.shock_action_enabled.all())
    check("original H10 deadline mandatory in OFF", off.deadline_index.iloc[e] == e + 9 and off.reservation_index.iloc[e] == e + 10 and off.exit_pending.iloc[e + 9] and off.sell_filled_today.iloc[e + 10])
    flat_on, flat_off = run(flat), run(flat, "SHOCK_OFF")
    oldcolumns = old.history(*flat, oldconfig).columns
    equal("no raw shock means exact old economics both modes", flat_on[oldcolumns], flat_off[oldcolumns])
    check("original loss completion and single-slot continue", flat_off.completed_loss_today.any() and flat_off.pause_slot_consumed.any())
    check("OFF retains exact strict net sign helper", new.completed_sign(-1e-300) == -1 and new.completed_sign(0.0) == 0 and new.completed_sign(1e-300) == 1)
    broken = [x.copy(deep=True) for x in rising]
    toy.change(broken, e + 2, close=8.0)
    broken[3].loc[e + 3, "Status"] = "SUSPENDED"
    toy.change(broken, e + 4, open_=8.0)
    b = run(broken, "SHOCK_OFF")
    check("OFF does not disable existing cost/support protection", b.selected_cost_exit.iloc[e + 2] and b.exit_pending.iloc[e + 2] and b.target_position.iloc[e + 2] == 0)
    check("inherited blockedSELL persists underOFF", b.pending_inherited.iloc[e + 3] and b.exit_pending.iloc[e + 3] and b.sell_filled_today.iloc[e + 4])
    check("pending keeps actual original anchors", b.entry_index.iloc[e + 3] == e and b.deadline_index.iloc[e + 3] == e + 9 and b.reservation_index.iloc[e + 3] == e + 10)
    check("actual delayed netloss feeds own once pause", b.completed_loss_today.iloc[e + 4] and b.pause_armed.iloc[e + 4] and b.pause_slot_consumed.any())
    failed = [x.copy(deep=True) for x in rising]
    failed[3].loc[e, "Status"] = "SUSPENDED"
    f = run(failed, "SHOCK_OFF")
    check("realfailedBUY neither completes nor arms", f.failed_buy_reset.iloc[e] and not f.completed_cycle_today.iloc[e] and not f.pause_armed.iloc[e] and f.entry_index.iloc[e] == -1)
    for profile in PROFILES:
        for label, args in (("rising", rising), ("flat", flat), ("varied", varied), ("pending", broken)):
            complete = run(args, profile)
            for stop in (e + 1, D + 1, e + 10, e + 16):
                prefix = [x.iloc[:stop].copy(deep=True) for x in args]
                equal(f"causal own policy prefix {profile}/{label}/{stop}", run(prefix, profile), complete.iloc[:stop])
            held = complete.held_at_close.astype(bool)
            for _, row in complete.loc[held].iterrows():
                expected = bool(row.profit_exit_eligible and row.shock_known and row.z5 > 2 and row.net_profit > 0)
                assert bool(row.shock_condition) == expected
                assert bool(row.selected_shock_exit) == bool(expected and profile == "SHOCK_ON")
                assert bool(row.shock_action_suppressed) == bool(expected and profile == "SHOCK_OFF")
            checks.append("condition separate from selected action " + profile + "/" + label)
    observations = 0
    previous_definition = old.CompletedPauseStrategy(ParameterSet(dict(pause_profile="AFTER_NET_LOSS_SKIP1"))).definition
    for profile in PROFILES:
        strategy = new.ShockActionStrategy(ParameterSet(dict(shock_profile=profile)))
        definition = strategy.definition
        runtime = RuntimeDefinition(schema_version=3, strategy_family_id="S014", version="v1", release_id="S014-v1", release_hash="a" * 64,
            implementation=ImplementationRef("strategy_runtime.strategies.shock_action_review", "ShockActionStrategy", 1, sha256(SOURCE.read_bytes()).hexdigest()),
            **{field.name: getattr(definition, field.name) for field in fields(StrategyDefinition)})
        for args in (rising, flat, varied):
            table = strategy.calculate_history(dict(zip(("market", "raw", "limits", "status"), args)), list(pd.to_datetime(args[0].Date)))
            for row in table.to_dict("records"):
                evidence = {series.value_field: row[series.value_field] for series in definition.observation.series}
                materialize_observation(runtime, helper.observed_plan(runtime, evidence))
                observations += 1
        for name in ("inputs", "decision", "execution", "monitoring", "capabilities"):
            check("originalcontract exact " + profile + "/" + name, getattr(definition, name) == getattr(previous_definition, name))
    trees = [ast.parse(p.read_text(encoding="utf-8")) for p in (OLD, SOURCE)]
    for name in ("completed_sign", "causal_features", "tick", "buy_limit", "calendar_request", "derive_calculation_scope"):
        nodes = [next(n for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name == name) for t in trees]
        check("inheritedhelper ASTexact " + name, ast.dump(nodes[0], include_attributes=False) == ast.dump(nodes[1], include_attributes=False))
    for values in ({}, {"shock_profile": True}, {"shock_profile": "OFF"}, {"shock_profile": "SHOCK_ON", "pause_profile": "BASE"}, {"shock_profile": "SHOCK_OFF", "date": "2026-01-01"}):
        try:
            new.ShockConfig.parse(values)
        except ValueError:
            checks.append("reject noncanonical config " + str(values))
        else:
            raise AssertionError(values)
    check("normalLF and zero network", b"\r" not in SOURCE.read_bytes() and not attempts)
    report = {"status": "PASS_PURE_SYNTHETIC_ONLY", "checks_count": len(checks), "checks": checks, "actual_SRT_observation_materializations": observations,
        "source_sha256": sha256(SOURCE.read_bytes()).hexdigest(), "previous_source_sha256": sha256(OLD.read_bytes()).hexdigest(),
        "precheck_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(), "fixture_source_sha256": sha256(FIXTURE.read_bytes()).hexdigest(), "helper_source_sha256": sha256(HELPER.read_bytes()).hexdigest(),
        "real_NOOP_equivalence": "NOT_EXECUTED", "new_market_inputs": 0, "new_accounts": 0, "new_fits": 0, "network_attempts": attempts}
    with dest.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print("PURE_SHOCK_ABLATION_PASS", len(checks), observations, report["source_sha256"])


if __name__ == "__main__":
    main()
