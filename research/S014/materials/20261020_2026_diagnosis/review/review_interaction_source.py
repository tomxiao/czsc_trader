"""Minimal independent config/history inheritance and synthetic state review."""

import ast
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from strategy_runtime import ParameterSet

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
NEW = Path("research/S014/experiments/EX048_20261020/src/strategy_runtime/strategies/loss_interaction_review.py")
OLD = Path("research/S014/experiments/EX047_20261020/src/strategy_runtime/strategies/shock_action_review.py")
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


def fn(tree, name):
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def dump(node):
    return ast.dump(node, include_attributes=False)


class Original(ast.NodeTransformer):
    def visit_Name(self, node):
        if node.id == "InteractionConfig":
            node.id = "ShockConfig"
        return node

    def visit_Constant(self, node):
        if node.value == "InteractionConfig required":
            node.value = "ShockConfig required"
        return node


def main():
    expected = sys.argv[1]
    destination = HERE / "interaction_source_state_review.json"
    if destination.exists():
        raise FileExistsError(destination)
    design = HERE.parent / "interaction_design_decision.json"
    check("exact stable source", sha(NEW) == expected)
    check("exact prior source", sha(OLD) == "ea8f6c82dc7901b12edd00fe13cf1db6ed6d274563ac65479bf06058ed11bf4b")
    check("exact locked rootmethod", sha(design) == "07e29822842e997e7757bf45dc39d22f84af6af7d7f78df45c49b472b1af6da4")
    helpers_path = HERE / "review_shock_action_source.py"
    helpers = load(helpers_path, "independent_prior_review_helpers")
    import requests
    import socket
    requests.sessions.Session.request = helpers.no_network
    socket.socket.connect = helpers.no_network
    socket.create_connection = helpers.no_network
    new, old = load(NEW, "independent_loss_interaction"), load(OLD, "independent_prior_shock")
    nt, ot = ast.parse(NEW.read_bytes()), ast.parse(OLD.read_bytes())
    for name in ["causal_features", "tick", "buy_limit", "calendar_request", "derive_calculation_scope", "completed_sign"]:
        check("inherited helperAST exact", dump(fn(nt, name)) == dump(fn(ot, name)))
    check("history AST exact except typedname", dump(Original().visit(fn(nt, "history"))) == dump(fn(ot, "history")))
    loss = new.InteractionConfig.parse({"pause_profile": "AFTER_NET_LOSS_SKIP1"})
    base = new.InteractionConfig.parse({"pause_profile": "BASE"})
    old_off = old.ShockConfig.parse({"shock_profile": "SHOCK_OFF"})
    check("SHOCK fixed OFF both profiles", loss.shock_profile.value == base.shock_profile.value == "SHOCK_OFF")
    for values in [{}, {"pause_profile": "AFTER_NET_PROFIT_SKIP1"}, {"pause_profile": 0}, {"pause_profile": "BASE", "shock_profile": "SHOCK_ON"}]:
        try:
            new.InteractionConfig.parse(values)
        except ValueError:
            check("illegal parameter rejected", True)
        else:
            raise AssertionError("illegal profile accepted")
    for kind in ["uptrend", "loss_after_shock", "blocked_sell"]:
        data = helpers.fixture(kind)
        prior = old.history(**data, config=old_off)
        control = new.history(**data, config=loss)
        unpaused = new.history(**data, config=base)
        check("LOSS all oldobserved exact", prior.equals(control))
        check("BASE no pause arm or consume", unpaused.pause_armed.eq(0).all() and unpaused.pause_slot_consumed.eq(0).all() and unpaused.pause_armed_before_candidate.eq(0).all())
        check("BASE authentic raw loss remains", unpaused.completed_loss_today.any() and unpaused.completed_net_known.any())
        check("BASE has no virtual planned slot", unpaused.planned_slot_active.eq(0).all() and unpaused.planned_slot_until.eq(-1).all())
        check("both raw shock observation adopted OFF", control.selected_shock_exit.eq(0).all() and unpaused.selected_shock_exit.eq(0).all() and unpaused.shock_condition.any())
        entry = None
        last_sign = 0
        for i, row in enumerate(unpaused.itertuples()):
            if row.buy_filled_today:
                entry = float(data["market"].Open.iloc[i])
            if row.sell_filled_today:
                check("BASE actual prior entry for completion", entry is not None)
                unit = float(data["market"].Open.iloc[i]) * .999 - entry * 1.001
                last_sign = (unit > 0) - (unit < 0)
                check("BASE authentic completed net", row.completed_net_unit == unit)
                entry = None
            check("BASE completed lastsign truthful", row.last_completed_sign == last_sign)
            check("finite numeric mode diagnostic", all(isinstance(getattr(row, k), float) and np.isfinite(getattr(row, k)) for k in ["pause_loss_profile", "pause_profit_profile", "shock_action_enabled", "shock_action_suppressed"]))
            if row.selected_cost_exit or row.ordinary_support_exit or row.deadline_exit or row.pending_inherited:
                check("BASE preserves all original exits", row.target_position == 0)
        for cut in [63, 79]:
            prefix = new.history(**{k: v.iloc[:cut].copy() for k, v in data.items()}, config=base)
            check("BASE ownprefix causal exact", prefix.equals(unpaused.iloc[:cut]))
    a = old.ShockActionStrategy(ParameterSet({"shock_profile": "SHOCK_OFF"})).definition
    b = new.LossInteractionStrategy(ParameterSet({"pause_profile": "AFTER_NET_LOSS_SKIP1"})).definition
    for field in ["inputs", "decision", "execution", "monitoring", "capabilities"]:
        check("runtime contracts exact", getattr(a, field) == getattr(b, field))
    output = {
        "status": "PASS", "blocking_findings": [],
        "reviewed_hashes": {(p.relative_to(ROOT) if p.is_absolute() else p).as_posix(): sha(p) for p in [NEW, OLD, design, helpers_path, Path(__file__)]},
        "checks": dict(COUNTS), "check_count": sum(COUNTS.values()),
        "scope": "Pure synthetic inheritance and changed-parameter state review only; no realnew policy outcomes, market/preparedfetch, fitting or repeated complete featureoracle.",
        "findings": ["Newhistory exact except strongconfigtypename; only admitted pauseprofile changes, fixedSHOCKOFF and originalcost/support/grace/H10 preserved.", "FreshLOSS oldwholeobserved exact on threefixtures. BASE neverarms/consumes but actual own completion/net/sign observations remain truthful.", "RawSHOCK and actualsuppression inherited; modeconstant pause_loss_profile must be certified separately by runner/A, not firstdynamicoldstate anchor.", "Actual new funded ON/control and all7annual audits remain separate prerequisites, not satisfied by synthetic review."],
        "new_accounts": 0, "new_market_calls": 0, "prepared_fetches": 0, "new_strategy_replays": 0, "fits": 0,
    }
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": "PASS", "checks": output["check_count"], "sha256": sha(destination)}))


if __name__ == "__main__":
    main()
