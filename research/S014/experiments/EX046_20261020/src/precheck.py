"""Pure synthetic completed-net-sign pause checks and real SRT observations."""
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
SOURCE = EX / "src/strategy_runtime/strategies/completed_pause_review.py"
OLD = ROOT / "research/S014/experiments/EX044_20261019/src/strategy_runtime/strategies/action_role_review.py"
FIXTURE = ROOT / "research/S014/experiments/EX043_20261019/src/precheck.py"
HELPER = ROOT / "research/S014/experiments/EX041_20261019/src/precheck.py"
PROFILES = ("BASE", "AFTER_NET_LOSS_SKIP1", "AFTER_NET_PROFIT_SKIP1")


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def main():
    destination = EX / "others/synthetic_precheck.json"
    assert not destination.exists(), "Preserve synthetic receipt"
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append("FORBIDDEN")
        raise RuntimeError("Synthetic network block")

    requests.sessions.Session.request = blocked
    socket.socket.connect = blocked
    socket.create_connection = blocked
    old, new = module("ex046_old", OLD), module("ex046_new", SOURCE)
    toy, helper = module("ex046_toy", FIXTURE), module("ex046_helper", HELPER)
    checks = []

    def check(name, condition):
        assert bool(condition), name
        checks.append(name)

    def equal(name, actual, expected):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        checks.append(name)

    def run(args, profile="BASE"):
        return new.history(*args, new.PauseConfig.parse({"pause_profile": profile}))

    oldconfig = old.ActionRoleConfig.parse(dict(entry_guard="BASE", exit_domain="POSITIVE_P", cost_stop="NET_LOSS_1ATR"))
    rising = toy.fixture()
    flat = toy.fixture()
    for i in range(len(flat[0])):
        toy.change(flat, i, close=10.0, open_=10.0)
    for label, args in (("rising", rising), ("flat loss after fees", flat)):
        expected = old.history(*args, oldconfig)
        equal("BASE all old columns exact " + label, run(args)[expected.columns], expected)
    features = new.causal_features

    def controlled(args, profile="BASE"):
        f = features(args[0])
        f["z5"] = 0.0
        f["shock_known"] = True
        f["atr20_prior"] = 100.0
        f["atr_known"] = True
        f["atr_positive"] = True
        new.causal_features = lambda market: f.loc[pd.to_datetime(market.Date)].copy()
        try:
            return run(args, profile)
        finally:
            new.causal_features = features

    base = controlled(flat)
    e = int(np.flatnonzero(base.buy_filled_today)[0])
    sale = int(np.flatnonzero(base.sell_filled_today)[0])
    loss = controlled(flat, PROFILES[1])
    profit = controlled(flat, PROFILES[2])
    check("flat full cycle is net loss after both fees", base.completed_loss_today.iloc[sale] and base.completed_net_unit.iloc[sale] < 0)
    check("BASE never arms nor consumes", not base.pause_armed.any() and not base.pause_slot_consumed.any())
    check("same-D actual SELL original-eligible consumes loss pause", loss.sell_filled_today.iloc[sale] and loss.original_entry_candidate.iloc[sale] and loss.pause_armed_before_candidate.iloc[sale] and loss.pause_slot_consumed.iloc[sale])
    check("consumption clears armed immediately", not loss.pause_armed.iloc[sale] and not loss.pause_armed.iloc[sale + 1:sale + 11].any())
    check("one planned next-E plus H10 reservation", loss.reservation_before_pause.iloc[sale] == e + 10 and loss.reservation_index.iloc[sale] == sale + 11 and loss.planned_slot_until.iloc[sale] == sale + 11)
    check("no phantom position entry cost fee or failed BUY", loss.target_position.iloc[sale] == 0 and loss.entry_index.iloc[sale] == -1 and loss.deadline_index.iloc[sale] == -1 and pd.isna(loss.entry_fill_price.iloc[sale]) and not loss.failed_buy_reset.iloc[sale] and not loss.entry_signal.iloc[sale])
    check("persistent prior loss does not rearm at expiry", loss.entry_signal.iloc[sale + 11] and not loss.pause_slot_consumed.iloc[sale + 11] and loss.buy_filled_today.iloc[sale + 12])
    equal("profit profile does not pause actual losing closes", profit[base.columns], base.assign(pause_profit_profile=1.0)[base.columns])
    p = controlled(rising, PROFILES[2])
    ps = int(np.flatnonzero(p.sell_filled_today)[0])
    check("positive completed fill arms opposite profile", p.completed_profit_today.iloc[ps] and p.pause_armed_before_candidate.iloc[ps])
    check("positive profile consumes first original candidate", p.pause_slot_consumed.any() and not p.pause_armed.iloc[int(np.flatnonzero(p.pause_slot_consumed)[0])])
    failed = [x.copy(deep=True) for x in flat]
    failed[3].loc[e, "Status"] = "SUSPENDED"
    f = controlled(failed, PROFILES[1])
    check("failed BUY neither completes nor arms", f.failed_buy_reset.iloc[e] and not f.completed_cycle_today.iloc[e] and not f.pause_armed.iloc[e] and not f.pause_slot_consumed.iloc[e])
    pending = [x.copy(deep=True) for x in flat]
    pending[3].loc[sale:sale + 1, "Status"] = "SUSPENDED"
    h = controlled(pending, PROFILES[1])
    check("unfilled SELL is no completed outcome or pause", h.pending_inherited.iloc[sale] and not h.completed_cycle_today.iloc[sale:sale + 2].any() and not h.pause_armed.iloc[sale:sale + 2].any())
    check("actual delayed SELL can consume same D after old expiry", h.sell_filled_today.iloc[sale + 2] and h.pause_slot_consumed.iloc[sale + 2] and h.reservation_index.iloc[sale + 2] == sale + 13)
    early = [x.copy(deep=True) for x in flat]
    toy.change(early, e + 1, close=8.0)
    # Support exit is retained; restore known close by the next actual sale.
    k = controlled(early, PROFILES[1])
    es = int(np.flatnonzero(k.sell_filled_today)[0])
    check("early close before reservation stays armed without early slot", es < e + 10 and k.pause_armed.iloc[es] and not k.pause_slot_consumed.iloc[es] and k.reservation_index.iloc[es] == e + 10)
    check("early completion waits first original eligible date", k.pause_slot_consumed.iloc[e + 10] and not k.pause_slot_consumed.iloc[es:e + 10].any())
    for value, expected in ((-1e-300, -1), (0.0, 0), (1e-300, 1)):
        check("strict sign no epsilon " + str(value), new.completed_sign(value) == expected)
    for value in (np.nan, np.inf, -np.inf):
        try:
            new.completed_sign(value)
        except ValueError:
            checks.append("reject non-finite completed sign " + str(value))
        else:
            raise AssertionError(value)
    for profile in PROFILES:
        for label, args in (("flat", flat), ("rising", rising), ("failed", failed), ("pending", pending)):
            complete = run(args, profile)
            for stop in (e + 1, sale + 1, sale + 7, sale + 14):
                prefix = [x.iloc[:stop].copy(deep=True) for x in args]
                equal(f"causal own-history prefix {profile}/{label}/{stop}", run(prefix, profile), complete.iloc[:stop])
    observations = 0
    previous_definition = old.ActionRoleStrategy(ParameterSet(oldconfig.__dict__)).definition if False else old.ActionRoleStrategy(ParameterSet(dict(entry_guard="BASE", exit_domain="POSITIVE_P", cost_stop="NET_LOSS_1ATR"))).definition
    for profile in PROFILES:
        strategy = new.CompletedPauseStrategy(ParameterSet(dict(pause_profile=profile)))
        definition = strategy.definition
        runtime = RuntimeDefinition(schema_version=3, strategy_family_id="S014", version="v1", release_id="S014-v1", release_hash="a" * 64,
            implementation=ImplementationRef("strategy_runtime.strategies.completed_pause_review", "CompletedPauseStrategy", 1, sha256(SOURCE.read_bytes()).hexdigest()),
            **{field.name: getattr(definition, field.name) for field in fields(StrategyDefinition)})
        for args in (rising, flat):
            data = dict(zip(("market", "raw", "limits", "status"), args))
            table = strategy.calculate_history(data, list(pd.to_datetime(args[0].Date)))
            for row in table.to_dict("records"):
                evidence = {series.value_field: row[series.value_field] for series in definition.observation.series}
                materialize_observation(runtime, helper.observed_plan(runtime, evidence))
                observations += 1
        for field in ("inputs", "decision", "execution", "monitoring", "capabilities"):
            check("old contract exact " + profile + "/" + field, getattr(definition, field) == getattr(previous_definition, field))
    trees = [ast.parse(path.read_text(encoding="utf-8")) for path in (OLD, SOURCE)]
    for name in ("causal_features", "tick", "buy_limit", "calendar_request", "derive_calculation_scope"):
        functions = [next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name) for tree in trees]
        check("inherited AST exact " + name, ast.dump(functions[0], include_attributes=False) == ast.dump(functions[1], include_attributes=False))
    for values in ({}, dict(pause_profile=True), dict(pause_profile="UNKNOWN"), dict(pause_profile="BASE", date="2024-01-01"), dict(pause_profile="BASE", cost_stop="BASE")):
        try:
            new.PauseConfig.parse(values)
        except ValueError:
            checks.append("strict enum rejects " + str(values))
        else:
            raise AssertionError(values)
    check("normal LF and zero network attempts", b"\r" not in SOURCE.read_bytes() and not attempts)
    result = {"status": "PASS_PURE_SYNTHETIC_ONLY", "checks_count": len(checks), "checks": checks,
        "actual_SRT_observation_materializations": observations, "source_sha256": sha256(SOURCE.read_bytes()).hexdigest(),
        "previous_source_sha256": sha256(OLD.read_bytes()).hexdigest(), "precheck_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixture_source_sha256": sha256(FIXTURE.read_bytes()).hexdigest(), "helper_source_sha256": sha256(HELPER.read_bytes()).hexdigest(),
        "controlled_features": "Toy timing tests only disable shock/cost to isolate completed-sign/slot; integration/prefix/SRT use original feature calculation",
        "new_market_inputs": 0, "new_fits": 0, "new_accounts": 0, "network_attempts": attempts, "real_NOOP_equivalence": "NOT_EXECUTED"}
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print("PURE_PAUSE_PASS", len(checks), observations, result["source_sha256"])


if __name__ == "__main__":
    main()
