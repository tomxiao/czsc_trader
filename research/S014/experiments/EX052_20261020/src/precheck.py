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
SOURCE = EX / "src/strategy_runtime/strategies/trend_permission.py"
OLD = ROOT / "research/S014/experiments/EX050_20261020/src/strategy_runtime/strategies/shock_state_policy.py"
FIXTURE = ROOT / "research/S014/experiments/EX043_20261019/src/precheck.py"
HELPER = ROOT / "research/S014/experiments/EX041_20261019/src/precheck.py"
PROFILES = ("ORIGINAL_C9502_CONTROL", "AGE_PRIOR_TREND_PERMISSION")


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
    old, new = module("ex052_old", OLD), module("ex052_new", SOURCE)
    toy, helper = module("ex052_toy", FIXTURE), module("ex052_helper", HELPER)
    checks = []

    def check(name, value):
        assert bool(value), name
        checks.append(name)

    def equal(name, actual, expected):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        checks.append(name)

    def run(args, profile=PROFILES[0]):
        return new.history(*args, new.PermissionConfig.parse({"permission_profile": profile}))

    rising, flat = toy.fixture(), toy.fixture()
    for i in range(len(flat[0])):
        toy.change(flat, i, close=10.0, open_=10.0)
    for name, args in (("rising", rising), ("flat", flat)):
        expected = old.history(*args, old.PolicyConfig.parse({"policy_profile": "FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD"}))
        equal("control exact all old columns " + name, run(args)[expected.columns], expected)
    e = int(np.flatnonzero(run(flat).buy_filled_today)[0])
    genuine = new.causal_features

    def forced(event=e + 2, ma=9.0, lag=8.0, later_ma=12.0):
        def features(market):
            out = genuine(market)
            out["shock_known"] = True
            out["z5"] = 0.0
            out["atr20_prior"] = 2.0
            out["atr_positive"] = True
            out["ma20_prior"] = later_ma
            out["ma20_prior_lag5"] = later_ma + 1
            out["ma_known"] = True
            for i in (event, event + 2):
                if i < len(out):
                    out.iloc[i, out.columns.get_loc("z5")] = 3.0
            if event < len(out):
                out.iloc[event, out.columns.get_loc("ma20_prior")] = ma
                out.iloc[event, out.columns.get_loc("ma20_prior_lag5")] = lag
                out.iloc[event, out.columns.get_loc("ma_known")] = bool(np.isfinite([ma, lag]).all())
            return out
        new.causal_features = features

    path = [x.copy(deep=True) for x in flat]
    for i in range(e + 1, len(path[0])):
        toy.change(path, i, close=10.5)
    forced()
    control, allowed = [run(path, p) for p in PROFILES]
    check("TRUE permits and latches at own firstSHOCK", allowed.permission_required_today.iloc[e+2] and allowed.permission_s1_evaluated.iloc[e+2] and allowed.permission_s1_true.iloc[e+2] and allowed.first_shock_hold_decision.iloc[e+2])
    check("later FALSE cannot reclassify TRUE latch", allowed.shock_disable_latched.iloc[e+4] and not allowed.first_shock_today.iloc[e+4] and allowed.permission_first_index.iloc[e+4] == e+2)
    equal("allowed actions exact originalAGE", allowed[control.columns.difference(new.PERMISSION_DIAGNOSTIC)], control[control.columns.difference(new.PERMISSION_DIAGNOSTIC)])
    forced(ma=11.0, lag=10.0)
    refused = run(path, PROFILES[1])
    check("priorClose belowMA refuses at D0", refused.first_shock_today.iloc[e+2] and refused.permission_refused.iloc[e+2] and not refused.permission_s1_true.iloc[e+2] and refused.exit_pending.iloc[e+2] and refused.target_position.iloc[e+2] == 0)
    check("FALSE nextE sells with original clocks", refused.sell_filled_today.iloc[e+3] and refused.reservation_index.iloc[e+2] == e+10 and refused.deadline_index.iloc[e+2] == e+9)
    check("actualSELL clears memory", refused.permission_first_index.iloc[e+3] == -1 and not refused.permission_s1_evaluated.iloc[e+3])
    check("raw SHOCK remains truthful", refused.shock_condition.iloc[e+2] and refused.selected_profit_exit.iloc[e+2] and refused.selected_shock_exit.iloc[e+2])
    blocked = [x.copy(deep=True) for x in path]
    blocked[3].loc[e+3, "Status"] = "SUSPENDED"
    delayed = run(blocked, PROFILES[1])
    check("blockedSELL pending persists no reclassification", delayed.pending_inherited.iloc[e+3] and delayed.exit_pending.iloc[e+3] and delayed.permission_refused.iloc[e+3] and delayed.sell_filled_today.iloc[e+4])
    forced(ma=10.5, lag=10.0)
    check("priorClose equality inclusive", run(path, PROFILES[1]).permission_granted.iloc[e+2])
    forced(ma=10.5, lag=10.5)
    check("MA slope equality refuses strictgreater", run(path, PROFILES[1]).permission_refused.iloc[e+2])
    for invalid in (np.nan, np.inf, -np.inf):
        forced(ma=invalid)
        check("control no new S1 dependency " + str(invalid), run(path).first_shock_hold_decision.iloc[e+2])
        try:
            run(path, PROFILES[1])
        except ValueError as exc:
            check("unknown requiredS1 explicitly fails " + str(invalid), "Unknown S1" in str(exc))
        else:
            raise AssertionError("required S1 unknown must fail")
    day0 = [x.copy(deep=True) for x in flat]
    for i in range(e, len(day0[0])):
        toy.change(day0, i, close=10.5)
    forced(event=e, ma=np.nan)
    z = run(day0, PROFILES[1])
    check("age0 originalexit withoutS1dependency", z.first_shock_age.iloc[e] == 0 and not z.permission_required_today.iloc[e] and not z.permission_s1_evaluated.iloc[e] and z.selected_shock_exit.iloc[e])
    forced()
    support = [x.copy(deep=True) for x in path]
    toy.change(support, e+4, close=8.0)
    protected = run(support, PROFILES[1])
    check("permission never cancels cost support", protected.shock_disable_latched.iloc[e+4] and protected.selected_cost_exit.iloc[e+4] and protected.exit_pending.iloc[e+4])
    for profile in PROFILES:
        complete = run(path, profile)
        for stop in (e+2, e+3, e+5, e+10):
            equal("causal prefix " + profile + str(stop), run([v.iloc[:stop].copy() for v in path], profile), complete.iloc[:stop])
        failed = [x.copy(deep=True) for x in path]
        failed[3].loc[e, "Status"] = "SUSPENDED"
        f = run(failed, profile)
        check("failedBUY noassess nofalsecycle " + profile, f.failed_buy_reset.iloc[e] and not f.shock_state_assessed.iloc[e] and f.permission_first_index.iloc[e] == -1)
    new.causal_features = genuine
    for args in ([x.iloc[:e+5].copy() for x in path], path):
        check("newDIAG all finite", np.isfinite(run(args, PROFILES[1])[list(new.PERMISSION_DIAGNOSTIC)].to_numpy()).all())
    observations = 0
    original_definition = old.ShockStateStrategy(ParameterSet({"policy_profile": "FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD"})).definition
    for profile in PROFILES:
        strategy = new.TrendPermissionStrategy(ParameterSet({"permission_profile": profile}))
        definition = strategy.definition
        runtime = RuntimeDefinition(schema_version=3, strategy_family_id="S014", version="v1", release_id="S014-v1", release_hash="a" * 64,
            implementation=ImplementationRef("strategy_runtime.strategies.trend_permission", "TrendPermissionStrategy", 1, sha256(SOURCE.read_bytes()).hexdigest()),
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
    for values in ({}, {"permission_profile": True}, {"permission_profile": "ONE_CHECK"}, {"permission_profile": PROFILES[0], "atr": 2}, {"policy_profile": "FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD"}):
        try:
            new.PermissionConfig.parse(values)
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
    print("PURE_PERMISSION_PASS", len(checks), "SRT", observations)


if __name__ == "__main__":
    main()
