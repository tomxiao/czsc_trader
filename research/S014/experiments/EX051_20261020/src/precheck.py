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
SOURCE = EX / "src/strategy_runtime/strategies/followthrough_anchor.py"
OLD = ROOT / "research/S014/experiments/EX050_20261020/src/strategy_runtime/strategies/shock_state_policy.py"
FIXTURE = ROOT / "research/S014/experiments/EX043_20261019/src/precheck.py"
HELPER = ROOT / "research/S014/experiments/EX041_20261019/src/precheck.py"
PROFILES = ("ORIGINAL_C9502_CONTROL", "SHOCK_ANCHOR_ZERO", "SHOCK_ANCHOR_FROZEN_1ATR")


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
    old, new = module("ex051_old", OLD), module("ex051_new", SOURCE)
    toy, helper = module("ex051_toy", FIXTURE), module("ex051_helper", HELPER)
    checks = []

    def check(name, value):
        assert bool(value), name
        checks.append(name)

    def equal(name, actual, expected):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        checks.append(name)

    def run(args, profile=PROFILES[0]):
        return new.history(*args, new.AnchorConfig.parse({"anchor_profile": profile}))

    rising, flat = toy.fixture(), toy.fixture()
    for i in range(len(flat[0])):
        toy.change(flat, i, close=10.0, open_=10.0)
    for name, args in (("rising", rising), ("flat fee loss", flat)):
        expected = old.history(*args, old.PolicyConfig.parse({"policy_profile": "FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD"}))
        equal("control every old column exact " + name, run(args)[expected.columns], expected)
    e = int(np.flatnonzero(run(flat).buy_filled_today)[0])
    genuine = new.causal_features

    def forced(event=e + 2, atr0=.25):
        def feature(market):
            out = genuine(market)
            out["shock_known"] = True
            out["z5"] = 0.0
            out["atr20_prior"] = .25
            out["atr_known"] = True
            out["atr_positive"] = True
            if event < len(out):
                out.iloc[event, out.columns.get_loc("z5")] = 3.0
                out.iloc[event, out.columns.get_loc("atr20_prior")] = atr0
                out.iloc[event, out.columns.get_loc("atr_known")] = np.isfinite(atr0)
                out.iloc[event, out.columns.get_loc("atr_positive")] = bool(np.isfinite(atr0) and atr0 > 0)
            for i in range(event + 1, len(out)):
                out.iloc[i, out.columns.get_loc("atr20_prior")] = .01
            if event + 2 < len(out):
                out.iloc[event + 2, out.columns.get_loc("z5")] = 3.0
            return out
        new.causal_features = feature

    path = [x.copy(deep=True) for x in flat]
    for i in range(e + 2, len(path[0])):
        toy.change(path, i, close=10.5)
    toy.change(path, e + 4, close=10.375)
    toy.change(path, e + 5, close=10.25)
    forced()
    base, zero, atr = [run(path, p) for p in PROFILES]
    check("baseline no new anchor state", not base.anchor_known.any() and not base.selected_anchor_exit.any())
    for profile, table in ((PROFILES[1], zero), (PROFILES[2], atr)):
        check("own firstSHOCK creates one anchor " + profile, table.anchor_created_today.iloc[e + 2] and table.anchor_index.iloc[e + 2] == e + 2 and table.shock_anchor_close_RUNTIME_HFQ.iloc[e + 2] == 10.5)
        check("no sameSHOCKD comparison " + profile, not table.anchor_later_session.iloc[e + 2] and not table.selected_anchor_exit.iloc[e + 2])
        check("nextD equality does not trigger " + profile, not table.selected_anchor_exit.iloc[e + 3])
        check("later repeatedSHOCK does not move event anchor " + profile, table.shock_anchor_close_RUNTIME_HFQ.iloc[e + 4] == 10.5 and not table.anchor_created_today.iloc[e + 4])
    check("ZERO persistent monitor catches later decline after firstcheck passed", zero.selected_anchor_exit.iloc[e + 4] and zero.exit_pending.iloc[e + 4])
    check("ZERO has no frozenATR dependency", not zero.anchor_atr_known.any() and zero.shock_anchor_ATR0_RUNTIME_HFQ.isna().all())
    check("ATR uses frozen .25 despite futureATR .01", atr.shock_anchor_ATR0_RUNTIME_HFQ.iloc[e + 4] == .25 and not atr.selected_anchor_exit.iloc[e + 4])
    check("ATR direct subtraction inclusive exactboundary", atr.shock_anchor_close_RUNTIME_HFQ.iloc[e + 5] - path[0].Close.iloc[e + 5] == .25 and atr.selected_anchor_exit.iloc[e + 5])
    check("new risk preserves original rawrisk truth", atr.selected_combined_risk_exit.iloc[e + 5] and not atr.selected_risk_exit.iloc[e + 5] and atr.anchor_exit_added.iloc[e + 5])
    check("Tplus1 gap can turn positive mark to completed loss", atr.net_profit.iloc[e + 5] > 0 and atr.sell_filled_today.iloc[e + 6] and atr.completed_loss_today.iloc[e + 6])
    blocked = [x.copy(deep=True) for x in path]
    blocked[3].loc[e + 6, "Status"] = "SUSPENDED"
    b = run(blocked, PROFILES[2])
    check("blockedSELL carries original pending anchors", b.pending_inherited.iloc[e + 6] and not b.sell_filled_today.iloc[e + 6] and b.anchor_index.iloc[e + 6] == e + 2 and b.entry_index.iloc[e + 6] == e and b.deadline_index.iloc[e + 6] == e + 9 and b.reservation_index.iloc[e + 6] == e + 10)
    check("price recovery does not cancel pending", b.target_position.iloc[e + 6] == 0 and not b.selected_anchor_exit.iloc[e + 6])
    check("actualSELL clears independent anchor", b.sell_filled_today.iloc[e + 7] and not b.anchor_known.iloc[e + 7] and b.anchor_index.iloc[e + 7] == -1 and pd.isna(b.shock_anchor_close_RUNTIME_HFQ.iloc[e + 7]))
    overlap = [x.copy(deep=True) for x in path]
    toy.change(overlap, e + 4, close=8.0)
    o = run(overlap, PROFILES[2])
    check("cost support and newexit overlap retained", o.selected_anchor_exit.iloc[e + 4] and o.selected_cost_exit.iloc[e + 4] and o.anchor_cost_overlap.iloc[e + 4] and o.anchor_support_overlap.iloc[e + 4] and not o.anchor_exit_added.iloc[e + 4])
    expiry = [x.copy(deep=True) for x in path]
    for i in range(e + 2, len(expiry[0])):
        toy.change(expiry, i, close=10.5)
    toy.change(expiry, e + 9, close=10.0)
    x = run(expiry, PROFILES[2])
    check("mandatoryexpiry preempts new selectedexit but raw overlap retained", x.deadline_exit.iloc[e + 9] and x.anchor_raw_condition.iloc[e + 9] and x.anchor_deadline_overlap.iloc[e + 9] and not x.selected_anchor_exit.iloc[e + 9] and x.exit_pending.iloc[e + 9])
    for profile in PROFILES:
        complete = run(path, profile)
        for stop in (e + 2, e + 3, e + 5, e + 9):
            equal("causal source prefix " + profile + str(stop), run([z.iloc[:stop].copy() for z in path], profile), complete.iloc[:stop])
    for invalid in (np.nan, np.inf, 0.0, -1.0):
        forced(atr0=invalid)
        check("control andZERO no new requiredATR " + str(invalid), not run(path, PROFILES[0]).anchor_known.any() and run(path, PROFILES[1]).anchor_created_today.iloc[e + 2])
        try:
            run(path, PROFILES[2])
        except ValueError as exc:
            check("requiredATR explicit failure " + str(invalid), "frozen ATR0 required" in str(exc))
        else:
            raise AssertionError("Invalid ATR silently accepted")
    forced(event=e)
    age0 = [z.copy(deep=True) for z in path]
    toy.change(age0, e, close=10.5)
    for profile in PROFILES:
        a = run(age0, profile)
        check("age0 original SHOCK exit no event anchor " + profile, a.selected_shock_exit.iloc[e] and not a.anchor_known.iloc[e] and a.target_position.iloc[e] == 0)
    new.causal_features = genuine
    failed = [z.copy(deep=True) for z in flat]
    failed[3].loc[e, "Status"] = "SUSPENDED"
    for profile in PROFILES:
        f = run(failed, profile)
        check("failedBUY no phantom anchor " + profile, f.failed_buy_reset.iloc[e] and not f.anchor_known.iloc[e] and f.entry_index.iloc[e] == -1)
    observations = 0
    original_definition = old.ShockStateStrategy(ParameterSet({"policy_profile": "FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD"})).definition
    for profile in PROFILES:
        strategy = new.FollowthroughStrategy(ParameterSet({"anchor_profile": profile}))
        definition = strategy.definition
        runtime = RuntimeDefinition(schema_version=3, strategy_family_id="S014", version="v1", release_id="S014-v1", release_hash="a" * 64,
            implementation=ImplementationRef("strategy_runtime.strategies.followthrough_anchor", "FollowthroughStrategy", 1, sha256(SOURCE.read_bytes()).hexdigest()),
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
    for name in ("completed_sign", "causal_features", "tick", "buy_limit", "calendar_request", "derive_calculation_scope", "non_final_day_dominated"):
        nodes = [next(n for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name == name) for t in trees]
        check("inheritedhelper ASTexact " + name, ast.dump(nodes[0], include_attributes=False) == ast.dump(nodes[1], include_attributes=False))
    for values in ({}, {"anchor_profile": True}, {"anchor_profile": "ONE_CHECK"}, {"anchor_profile": PROFILES[0], "atr": 2}, {"policy_profile": "FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD"}):
        try:
            new.AnchorConfig.parse(values)
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
    print("PURE_ANCHOR_PASS", len(checks), "SRT", observations)


if __name__ == "__main__":
    main()
