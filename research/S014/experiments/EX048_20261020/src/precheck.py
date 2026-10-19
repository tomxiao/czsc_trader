"""Pure own-completed-loss pause interaction under fixed SHOCK_OFF and cost."""
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
SOURCE = EX / "src/strategy_runtime/strategies/loss_interaction_review.py"
OLD = ROOT / "research/S014/experiments/EX047_20261020/src/strategy_runtime/strategies/shock_action_review.py"
FIXTURE = ROOT / "research/S014/experiments/EX043_20261019/src/precheck.py"
HELPER = ROOT / "research/S014/experiments/EX041_20261019/src/precheck.py"
PROFILES = ("AFTER_NET_LOSS_SKIP1", "BASE")


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
    old, new = module("ex048_old", OLD), module("ex048_new", SOURCE)
    toy, helper = module("ex048_toy", FIXTURE), module("ex048_helper", HELPER)
    checks = []

    def check(name, value):
        assert bool(value), name
        checks.append(name)

    def equal(name, actual, expected):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        checks.append(name)

    def run(args, profile="AFTER_NET_LOSS_SKIP1"):
        return new.history(*args, new.InteractionConfig.parse({"pause_profile": profile}))

    rising, flat, varied = toy.fixture(), toy.fixture(), toy.fixture()
    for i in range(len(flat[0])):
        toy.change(flat, i, close=10.0, open_=10.0)
        p = 10.0 + 0.1 * np.sin(i * 1.2)
        toy.change(varied, i, close=p, open_=p)
    oldconfig = old.ShockConfig.parse({"shock_profile": "SHOCK_OFF"})
    for label, args in (("rising", rising), ("flat fee loss", flat), ("varied", varied)):
        expected = old.history(*args, oldconfig)
        equal("fresh LOSS all original history exact " + label, run(args), expected)
    loss, base = run(flat), run(flat, "BASE")
    e = int(np.flatnonzero(loss.buy_filled_today)[0])
    skip = int(np.flatnonzero(loss.pause_slot_consumed)[0])
    check("LOSS real net fee loss arms and consumes once", loss.completed_loss_today.iloc[skip] and loss.sell_filled_today.iloc[skip] and loss.pause_armed_before_candidate.iloc[skip] and not loss.pause_armed.iloc[skip])
    check("same actual SELL D may consume at original eligibility", loss.original_entry_candidate.iloc[skip] and loss.reservation_before_pause.iloc[skip] <= loss.warmup_sessions.iloc[skip])
    check("slot is planned i+11 without phantom filled entry", loss.reservation_index.iloc[skip] == loss.warmup_sessions.iloc[skip] + 11 and loss.target_position.iloc[skip] == 0 and loss.entry_index.iloc[skip] == -1 and loss.deadline_index.iloc[skip] == -1 and pd.isna(loss.entry_fill_price.iloc[skip]))
    check("BASE truthful completion but never arms or consumes", base.completed_loss_today.any() and base.completed_net_known.any() and not base.pause_armed_before_candidate.any() and not base.pause_armed.any() and not base.pause_slot_consumed.any())
    check("BASE same eligible D uses original BUY intent", base.entry_signal.iloc[skip] and base.buy_filled_today.iloc[skip + 1])
    check("profile constants separately declared", loss.pause_loss_profile.all() and not base.pause_loss_profile.any() and not loss.pause_profit_profile.any() and not base.pause_profit_profile.any())
    check("LOSS disarmed old loss does not repeatedly skip", not loss.pause_slot_consumed.iloc[skip + 1:skip + 11].any() and not loss.pause_armed.iloc[skip + 1:skip + 11].any())
    check("strict sign including exact0", new.completed_sign(-1e-300) == -1 and new.completed_sign(0.0) == 0 and new.completed_sign(1e-300) == 1)
    broken = [x.copy(deep=True) for x in rising]
    toy.change(broken, e + 2, close=8.0)
    broken[3].loc[e + 3, "Status"] = "SUSPENDED"
    toy.change(broken, e + 4, open_=8.0)
    b = run(broken)
    check("fixed cost and support protection retained", b.selected_cost_exit.iloc[e + 2] and b.exit_pending.iloc[e + 2] and b.target_position.iloc[e + 2] == 0)
    check("pending blockedSELL not completed and anchors stay", b.pending_inherited.iloc[e + 3] and not b.completed_cycle_today.iloc[e + 3] and b.entry_index.iloc[e + 3] == e and b.deadline_index.iloc[e + 3] == e + 9 and b.reservation_index.iloc[e + 3] == e + 10)
    check("only actual delayed loss completion may arm", b.sell_filled_today.iloc[e + 4] and b.completed_loss_today.iloc[e + 4] and b.pause_armed.iloc[e + 4])
    failed = [x.copy(deep=True) for x in rising]
    failed[3].loc[e, "Status"] = "SUSPENDED"
    for profile in PROFILES:
        f = run(failed, profile)
        check("actualfailedBUY no completion or arm " + profile, f.failed_buy_reset.iloc[e] and not f.completed_cycle_today.iloc[e] and not f.pause_armed.iloc[e] and f.entry_index.iloc[e] == -1)
        for label, args in (("rising", rising), ("flat", flat), ("varied", varied), ("pending", broken)):
            complete = run(args, profile)
            for stop in (e + 1, e + 4, e + 10, e + 16):
                prefix = [x.iloc[:stop].copy(deep=True) for x in args]
                equal(f"own causal prefix {profile}/{label}/{stop}", run(prefix, profile), complete.iloc[:stop])
            check("SHOCK_OFF fixed raw true action suppressed " + profile + "/" + label, not complete.shock_action_enabled.any() and not complete.selected_shock_exit.any() and (complete.shock_action_suppressed == complete.shock_condition).all())
            expected_sign = complete.completed_net_unit.dropna().map(new.completed_sign)
            check("completion signs stay truthful on own path " + profile + "/" + label, (expected_sign == complete.loc[expected_sign.index, "last_completed_sign"]).all())
    observations = 0
    previous_definition = old.ShockActionStrategy(ParameterSet(dict(shock_profile="SHOCK_OFF"))).definition
    for profile in PROFILES:
        strategy = new.LossInteractionStrategy(ParameterSet(dict(pause_profile=profile)))
        definition = strategy.definition
        runtime = RuntimeDefinition(schema_version=3, strategy_family_id="S014", version="v1", release_id="S014-v1", release_hash="a" * 64,
            implementation=ImplementationRef("strategy_runtime.strategies.loss_interaction_review", "LossInteractionStrategy", 1, sha256(SOURCE.read_bytes()).hexdigest()),
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
    for values in ({}, {"pause_profile": True}, {"pause_profile": "LOSS"}, {"pause_profile": "AFTER_NET_PROFIT_SKIP1"}, {"pause_profile": "BASE", "shock_profile": "SHOCK_ON"}, {"pause_profile": "BASE", "date": "2026-01-01"}):
        try:
            new.InteractionConfig.parse(values)
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
    print("PURE_LOSS_INTERACTION_PASS", len(checks), observations, report["source_sha256"])


if __name__ == "__main__":
    main()
