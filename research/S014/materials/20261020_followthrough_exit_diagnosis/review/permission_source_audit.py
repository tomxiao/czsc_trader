"""Focused EX052 scalar prior-trend permission and own-cycle lifecycle audit."""

import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import sys

import numpy as np
import pandas as pd

ROOT = Path.cwd()
BASE = ROOT / "research/S014/materials/20261020_followthrough_exit_diagnosis"
SOURCE = ROOT / "research/S014/experiments/EX052_20261020/src/strategy_runtime/strategies/trend_permission.py"
OLD = ROOT / "research/S014/experiments/EX050_20261020/src/strategy_runtime/strategies/shock_state_policy.py"
FIXTURE = ROOT / "research/S014/experiments/EX043_20261019/src/precheck.py"
CHECKS = []
HASHES = {}


def bind(path, expected=None):
    content = path.read_bytes()
    actual = sha256(content).hexdigest()
    if expected is not None:
        assert actual == expected
    HASHES[path.relative_to(ROOT).as_posix()] = actual
    return content


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def check(label, condition):
    assert bool(condition), label
    CHECKS.append(label)


def deny(*args, **kwargs):
    raise RuntimeError("B EX052 synthetic check forbids network")


def main():
    socket.socket.connect = deny
    socket.create_connection = deny
    current = bind(SOURCE, "ba01530dc434d32a540ba0a8e6ec9078a638137dcbaf683eb366171291ee67f2")
    old_bytes = bind(OLD, "ac4fcdbdc5c46b1d43f31f53dda2de0635fea8f4f0cff8889a083a86f87e76f3")
    bind(FIXTURE)
    new, old, toy = load("b_ex052", SOURCE), load("b_ex052_old", OLD), load("b_ex052_toy", FIXTURE)
    for name in ("causal_features", "tick", "buy_limit", "completed_sign", "non_final_day_dominated", "calendar_request", "derive_calculation_scope"):
        nodes = [next(n for n in ast.walk(ast.parse(content)) if isinstance(n, ast.FunctionDef) and n.name == name) for content in (old_bytes, current)]
        check("Inherited helper AST exact " + name, ast.dump(nodes[0]) == ast.dump(nodes[1]))
    profiles = [p.value for p in new.PermissionProfile]
    check("Exactly two locked profiles", profiles == ["ORIGINAL_C9502_CONTROL", "AGE_PRIOR_TREND_PERMISSION"])
    check("No EX051 price anchor state", b"anchor_index" not in current and b"selected_anchor_exit" not in current)
    args = toy.fixture()
    control = new.history(*args, new.PermissionConfig.parse({"permission_profile": profiles[0]}))
    expected = old.history(*args, old.PolicyConfig.parse({"policy_profile": "FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD"}))
    pd.testing.assert_frame_equal(control[expected.columns], expected, check_exact=True)
    CHECKS.append("All original C9502 columns exact synthetic control")
    entry = int(np.flatnonzero(control.buy_filled_today)[0])
    d0 = entry + 1
    for prior, ma, lag, value in ((10.0, 10.0, 9.0, True), (10.0, 10.0, 10.0, False), (np.nextafter(10.0, -np.inf), 10.0, 9.0, False), (10.0, 10.0, np.nextafter(10.0, -np.inf), True)):
        check("S1 scalar exact boundary " + repr((prior, ma, lag)), new.prior_trend_permission(prior, ma, lag) is value)
    for values in ((np.nan, 10.0, 9.0), (10.0, np.inf, 9.0), (10.0, 10.0, -np.inf)):
        check("Required finite operand " + repr(values), new.prior_trend_permission(*values) is None)
    genuine = new.causal_features

    def scenario():
        frames = toy.fixture()
        for i in range(entry, len(frames[0])):
            toy.change(frames, i, close=11.0)
        return frames

    def run(frames, profile, shock_indices=(d0,), ma=10.0, lag=9.0, flip_at=None, flip_ma=12.0, atr=100.0):
        def forced(market):
            features = genuine(market)
            features["shock_known"] = True
            features["z5"] = 0.0
            features["atr20_prior"] = atr
            features["atr_positive"] = True
            features["ma20_prior"] = ma
            features["ma20_prior_lag5"] = lag
            if flip_at is not None and flip_at < len(features):
                features.iloc[flip_at:, features.columns.get_loc("ma20_prior")] = flip_ma
            for i in shock_indices:
                if i < len(features):
                    features.iloc[i, features.columns.get_loc("z5")] = 3.0
            return features
        new.causal_features = forced
        try:
            return new.history(*frames, new.PermissionConfig.parse({"permission_profile": profile}))
        finally:
            new.causal_features = genuine

    yes = run(scenario(), profiles[1], shock_indices=(d0, d0 + 1), flip_at=d0 + 1)
    check("First eligible held SHOCK TRUE permission holds", yes.permission_required_today.iloc[d0] and yes.permission_granted.iloc[d0] and yes.shock_disable_latched.iloc[d0] and not yes.selected_shock_exit.iloc[d0])
    check("Later MA reversal does not reassess latch", yes.shock_condition.iloc[d0 + 1] and not yes.first_shock_today.iloc[d0 + 1] and yes.shock_action_suppressed.iloc[d0 + 1] and yes.permission_s1_true.iloc[d0 + 1])
    check("Original H10 remains mandatory", yes.deadline_exit.iloc[entry + 9] and yes.target_position.iloc[entry + 9] == 0.0)
    no = run(scenario(), profiles[1], ma=12.0)
    check("First FALSE exits on D0 original SHOCK", no.permission_refused.iloc[d0] and no.selected_shock_exit.iloc[d0] and no.target_position.iloc[d0] == 0.0)
    check("Next E actual SELL clears permission", no.sell_filled_today.iloc[d0 + 1] and no.permission_first_index.iloc[d0 + 1] == -1)
    age0 = run(scenario(), profiles[1], shock_indices=(entry,), ma=np.nan)
    check("Age0 original exit no S1 dependency", age0.selected_shock_exit.iloc[entry] and not age0.permission_s1_evaluated.iloc[entry])
    unused = run(scenario(), profiles[0], ma=np.nan)
    check("Control no new S1 dependency", unused.shock_disable_latched.iloc[d0] and not unused.permission_s1_evaluated.iloc[d0])
    try:
        run(scenario(), profiles[1], ma=np.nan)
    except ValueError:
        CHECKS.append("Required held-domain unknown explicitly fails")
    else:
        raise AssertionError("Required unknown silently converted to FALSE")
    blocked_args = scenario()
    blocked_args[3].loc[d0 + 1, "Status"] = "SUSPENDED"
    blocked = run(blocked_args, profiles[1], ma=12.0, flip_at=d0 + 1, flip_ma=10.0)
    check("FALSE blockedSELL pending survives later TRUE trend", blocked.pending_inherited.iloc[d0 + 1] and blocked.exit_pending.iloc[d0 + 1] and not blocked.permission_granted.iloc[d0 + 1])
    check("Pending retains original deadline and reservation", blocked.deadline_index.iloc[d0 + 1] == entry + 9 and blocked.reservation_index.iloc[d0 + 1] == entry + 10)
    risk_args = scenario()
    toy.change(risk_args, d0 + 1, close=9.0)
    risk = run(risk_args, profiles[1], atr=0.1)
    check("Permission does not disable cost or support", risk.shock_disable_latched.iloc[d0 + 1] and risk.selected_cost_exit.iloc[d0 + 1] and risk.ordinary_support_exit.iloc[d0 + 1] and risk.target_position.iloc[d0 + 1] == 0.0)
    failed_args = scenario()
    failed_args[3].loc[entry, "Status"] = "SUSPENDED"
    failed = run(failed_args, profiles[1], shock_indices=(entry,))
    check("Failed BUY cannot create permission cycle", failed.failed_buy_reset.iloc[entry] and failed.permission_first_index.iloc[entry] == -1)
    for profile in profiles:
        full = run(scenario(), profile)
        short = [frame.iloc[:d0 + 2].copy() for frame in scenario()]
        prefix = run(short, profile)
        pd.testing.assert_frame_equal(prefix, full.iloc[:d0 + 2], check_exact=True)
        CHECKS.append("Own causal prefix " + profile)
    bind(BASE / "permission_decision.json", "e4854b3b2b738b09b0670d8422410f1ee2ce43258f36226aba16617e09f530ca")
    bind(BASE / "review/permission_locked_method_review.json", "874c5c2c893577324fd8d0bf20ca79e053da9e0c79091bdd215aab7173c97a04")
    bind(Path(__file__).resolve())
    result = {"status": "PASS_FOCUSED_SOURCE_PENDING_RUNNER", "reviewer": "B", "blocking_findings": [],
              "reviewed_hashes": HASHES, "checks_count": len(CHECKS), "checks": CHECKS,
              "scope": "Only firstSHOCK prior-trend permission scalar boundaries, required finite domain, firstassessment/independent latch/reset, inherited protection/pending and prefix. Seven oldhelper AST exact and full oldtoy control. No new actualinputs, jointcounts, labels or account.",
              "remaining_gate": "Final runner/design/focused SRT receipts then publiclock and independent fresh C9502 actualexact control before sole treatment.",
              "new_funded_accounts": 0, "new_market_calls": 0, "new_prepared_fetches": 0, "new_labels": 0}
    path = BASE / "review/permission_source_review.json"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest(), "checks": len(CHECKS)}))


if __name__ == "__main__":
    main()
