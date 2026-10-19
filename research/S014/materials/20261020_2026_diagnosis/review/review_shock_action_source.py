"""Bounded independent delta/state review: synthetic data, zero external reads."""

import ast
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sys

import numpy as np
import pandas as pd
import requests
from strategy_runtime import ParameterSet

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
NEW = Path("research/S014/experiments/EX047_20261020/src/strategy_runtime/strategies/shock_action_review.py")
OLD = Path("research/S014/experiments/EX046_20261020/src/strategy_runtime/strategies/completed_pause_review.py")
COUNTS = Counter()


def check(key, condition):
    assert bool(condition), key
    COUNTS[key] += 1


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def no_network(*args, **kwargs):
    raise RuntimeError("Synthetic only")


def node(tree, name):
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)


def dump(value):
    return ast.dump(value, include_attributes=False)


class OriginalHistory(ast.NodeTransformer):
    """Remove exactly the declared gate and two added diagnostics for AST comparison."""

    def visit_Name(self, value):
        if value.id == "ShockConfig":
            value.id = "PauseConfig"
        return value

    def visit_Constant(self, value):
        if value.value == "ShockConfig required":
            value.value = "PauseConfig required"
        return value

    def visit_Assign(self, value):
        if len(value.targets) == 1:
            target = value.targets[0]
            if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant) and target.slice.value == "shock_action_enabled":
                return None
            if isinstance(target, ast.Name) and target.id == "selected_shock":
                gate = value.value.args[0]
                check("one ON gate AST only", isinstance(gate, ast.BoolOp) and isinstance(gate.op, ast.And) and len(gate.values) == 3)
                check("gate canonical ON predicate", ast.unparse(gate.values[0]) == "config.shock_profile is ShockProfile.SHOCK_ON")
                gate.values = gate.values[1:]
        return self.generic_visit(value)

    def visit_Call(self, value):
        value.keywords = [k for k in value.keywords if k.arg != "shock_action_suppressed"]
        return self.generic_visit(value)


def fixture(kind):
    n = 105
    dates = pd.bdate_range("2020-01-02", periods=n)
    prices = np.array([100 + .05 * ((i % 7) - 3) for i in range(n)])
    for i in range(60, 75):
        prices[i] = 100 + 1.3 * (i - 59)
    prices[75:] = 108 + .03 * np.arange(n - 75)
    if kind == "loss_after_shock":
        prices[64:75] = 98 - .8 * np.arange(11)
    opens = np.r_[prices[0], prices[:-1]]
    market = pd.DataFrame({"Date": dates, "Open": opens, "High": np.maximum(prices, opens) + .2, "Low": np.minimum(prices, opens) - .2, "Close": prices})
    # A BUY may fill at lower OPEN or original limit. Oracle checks state transitions,
    # not a fabricated assumption that every planned order fills.
    limits = pd.DataFrame({"Date": dates, "DownLimit": 80., "UpLimit": 150.})
    status = pd.DataFrame({"Date": dates, "Status": "TRADING"})
    if kind == "blocked_sell":
        status.loc[70, "Status"] = "SUSPENDED"
        market.loc[71, ["Open", "High", "Low", "Close"]] = 80.
    return {"market": market, "raw": market.copy(), "limits": limits, "status": status}


def main():
    expected = sys.argv[1]
    destination = HERE / "source_state_review.json"
    if destination.exists():
        raise FileExistsError(destination)
    check("new frozen source bytes", sha(NEW) == expected)
    check("prior frozen source bytes", sha(OLD) == "5e775c5b27bfd7b1ac5bec9c2839ce24ae62f32f1829c21a13091868a174b846")
    design = HERE.parent / "design_decision.json"
    check("root method lock exact", sha(design) == "4d6d77c325bdb63fb5c3c2e5e724aab2b1b9bd86ebe06e06f60e79686a82b81b")
    requests.sessions.Session.request = no_network
    socket.socket.connect = no_network
    socket.create_connection = no_network
    new, old = load(NEW, "independent_shock_action"), load(OLD, "independent_old_pause")
    nt, ot = ast.parse(NEW.read_bytes()), ast.parse(OLD.read_bytes())
    for name in ["causal_features", "tick", "buy_limit", "calendar_request", "derive_calculation_scope", "completed_sign"]:
        check("inherited helper AST exact", dump(node(nt, name)) == dump(node(ot, name)))
    check("history AST only declared delta", dump(OriginalHistory().visit(node(nt, "history"))) == dump(node(ot, "history")))
    # The strongly typed parameter surface admits only the two locked profiles.
    for values in [{}, {"shock_profile": "OFF"}, {"shock_profile": 0}, {"shock_profile": "SHOCK_ON", "pause_profile": "BASE"}]:
        try:
            new.ShockConfig.parse(values)
        except ValueError:
            check("invalid parameter rejected", True)
        else:
            raise AssertionError("invalid parameter accepted")
    on = new.ShockConfig.parse({"shock_profile": "SHOCK_ON"})
    off = new.ShockConfig.parse({"shock_profile": "SHOCK_OFF"})
    prior = old.PauseConfig.parse({"pause_profile": "AFTER_NET_LOSS_SKIP1"})
    check("fixed actual loss pause", on.pause_profile.value == off.pause_profile.value == "AFTER_NET_LOSS_SKIP1")
    for kind in ["uptrend", "loss_after_shock", "blocked_sell"]:
        data = fixture(kind)
        reference = old.history(**data, config=prior)
        positive = new.history(**data, config=on)
        negative = new.history(**data, config=off)
        check("ON all inherited columns exact", reference.equals(positive[reference.columns]))
        check("ON diagnostic numeric", positive.shock_action_enabled.eq(1.).all() and positive.shock_action_suppressed.eq(0.).all())
        check("OFF action disabled raw retained", negative.shock_action_enabled.eq(0.).all() and negative.selected_shock_exit.eq(0.).all() and negative.shock_condition.any())
        check("OFF selected risk is cost only", negative.selected_risk_exit.equals(negative.selected_cost_exit))
        check("OFF suppression truthful", negative.shock_action_suppressed.equals(negative.shock_condition))
        check("raw legacy selected profit truthful", negative.selected_profit_exit.equals(negative.shock_condition))
        for row in negative.itertuples():
            if row.shock_action_suppressed:
                check("shock excluded protective/mandatory sameD", not (row.selected_cost_exit or row.ordinary_support_exit or row.deadline_exit or row.pending_inherited))
                check("OFF suppressed shock really holds", row.target_position == 1 and row.exit_pending == 0)
            if row.pending_inherited or row.deadline_exit or row.selected_cost_exit or row.ordinary_support_exit:
                check("OFF inherited other exit still exits", row.target_position == 0)
            check("numeric SRT diagnostic finitefloat", isinstance(row.shock_action_enabled, float) and isinstance(row.shock_action_suppressed, float) and np.isfinite(row.shock_action_enabled) and np.isfinite(row.shock_action_suppressed))
            if row.pause_slot_consumed:
                check("actual own loss consumed no pseudo trade", row.last_completed_sign == -1 and not row.pause_armed and row.target_position == 0 and row.entry_index == -1 and row.deadline_index == -1 and not row.entry_signal)
        # New OFF must obey the existing exact state machine on its own BUY/SELL path.
        for cut in [63, 79]:
            prefix = new.history(**{k: v.iloc[:cut].copy() for k, v in data.items()}, config=off)
            check("OFF prefix causal exact", prefix.equals(negative.iloc[:cut]))
        mutated = {k: v.copy() for k, v in data.items()}
        for key in ["market", "raw"]:
            mutated[key].loc[83:, ["Open", "High", "Low", "Close"]] *= .91
        changed = new.history(**mutated, config=off)
        check("future perturbation no prior state effect", changed.iloc[:83].equals(negative.iloc[:83]))
    a = old.CompletedPauseStrategy(ParameterSet({"pause_profile": "AFTER_NET_LOSS_SKIP1"})).definition
    b = new.ShockActionStrategy(ParameterSet({"shock_profile": "SHOCK_ON"})).definition
    for field in ["inputs", "decision", "execution", "monitoring", "capabilities"]:
        check("five runtime contracts exact", getattr(a, field) == getattr(b, field))
    output = {
        "status": "PASS", "blocking_findings": [],
        "reviewed_hashes": {p.relative_to(ROOT).as_posix() if p.is_absolute() else p.as_posix(): sha(p) for p in [NEW, OLD, design, Path(__file__)]},
        "checks": dict(COUNTS), "check_count": sum(COUNTS.values()),
        "scope": "Independent bounded AST and pure synthetic source/action/priority/clock review. No old full-feature oracle repeated; no actual new policy results inspected.",
        "raw_observation_semantics": "shock_condition and selected_profit_exit remain original legacy positive-P condition; selected_shock_exit and selected_risk_exit are actual adopted actions. New shock_action_enabled/suppressed finitefloat; do not treat a legacy condition as actual SELL under OFF.",
        "preserved": "Causal feature/helperAST, all inherited execution contracts and state-history except declared action gate exact. Own actual completion and finite loss pause are retained; pending/deadline/support/cost may still exit OFF, not fixedH10.",
        "remaining_gates": ["Separate runner/source immutable local lock review", "Fresh ON exact C9461 realaccount and independent funded audit", "Then single authorized OFF realaccount and all-seven-year funded/state audit"],
        "new_accounts": 0, "new_market_calls": 0, "prepared_fetches": 0, "new_strategy_replays": 0, "fits": 0,
    }
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": "PASS", "checks": output["check_count"], "review_sha256": sha(destination)}))


if __name__ == "__main__":
    main()
