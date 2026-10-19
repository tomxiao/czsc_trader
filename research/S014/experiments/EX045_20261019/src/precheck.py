"""Minimal pure synthetic checks for two fixed blocked-opportunity clocks."""

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
from strategy_runtime import (
    ImplementationRef,
    ParameterSet,
    RuntimeDefinition,
    StrategyDefinition,
    materialize_observation,
)

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
SOURCE = EX / "src/strategy_runtime/strategies/blocked_clock_review.py"
OLD = (
    ROOT
    / "research/S014/experiments/EX044_20261019/src/strategy_runtime/strategies/action_role_review.py"
)
FIXTURE = ROOT / "research/S014/experiments/EX043_20261019/src/precheck.py"
HELPER = ROOT / "research/S014/experiments/EX041_20261019/src/precheck.py"
PROFILES = ("RETRY_EACH_D", "KEEP_PLANNED_SLOT")


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def main():
    destination = EX / "others/synthetic_precheck.json"
    if destination.exists():
        raise ValueError("Preserve existing receipt")
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append("FORBIDDEN")
        raise RuntimeError("Synthetic-only network block")

    requests.sessions.Session.request = blocked
    socket.socket.connect = blocked
    socket.create_connection = blocked
    old, new = module("ex045_old", OLD), module("ex045_new", SOURCE)
    toy, helper = module("ex045_fixture", FIXTURE), module("ex045_helper", HELPER)
    checks = []

    def check(name, value):
        assert bool(value), name
        checks.append(name)

    def equal(name, actual, expected):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        checks.append(name)

    def run(args, profile="RETRY_EACH_D"):
        return new.history(*args, new.ClockConfig.parse(dict(clock_profile=profile)))

    oldconfig = old.ActionRoleConfig.parse(
        dict(entry_guard="BLOCK_SHOCK", exit_domain="POSITIVE_P", cost_stop="BASE")
    )
    inputs = toy.fixture()
    varied = toy.fixture()
    prices = 10.0 + 0.1 * np.sin(np.arange(len(varied[0])) * 1.2)
    for i, value in enumerate(prices):
        for frame in varied[:2]:
            frame.loc[i, "Open"] = value
        toy.change(varied, i, value)
    for label, args in (("high-Z all-blocked", inputs), ("varied actual fills", varied)):
        expected = old.history(*args, oldconfig)
        equal("RETRY old full history exact " + label, run(args)[expected.columns], expected)
    check(
        "varied control covers actual inventory",
        run(varied).buy_filled_today.any() and run(varied).sell_filled_today.any(),
    )
    retry, slot = run(inputs), run(inputs, "KEEP_PLANNED_SLOT")
    d = int(np.flatnonzero(retry.original_entry_candidate)[0])
    check(
        "slot consumes only blocked original candidate",
        slot.gate_slot_consumed.iloc[d]
        and slot.entry_guard_blocked.iloc[d]
        and slot.original_entry_candidate.iloc[d],
    )
    check(
        "pre-gate and post-gate reservation explicitly different",
        slot.reservation_before_gate.iloc[d] == -1
        and slot.reservation_index.iloc[d] == d + 11
        and slot.planned_slot_until.iloc[d] == d + 11,
    )
    check(
        "planned window creates no inventory, orders, phantom anchors or cost",
        not slot.entry_signal.any()
        and not slot.buy_filled_today.any()
        and not slot.failed_buy_reset.any()
        and not slot.held_at_close.any()
        and not slot.exit_pending.any()
        and slot.entry_index.eq(-1).all()
        and slot.deadline_index.eq(-1).all()
        and slot.entry_fill_price.isna().all()
        and slot.cost_loss_price.isna().all(),
    )
    check(
        "slot waits exact planning horizon then reblocks at expiry",
        not slot.original_entry_candidate.iloc[d + 1 : d + 11].any()
        and slot.planned_slot_active.iloc[d : d + 11].all()
        and slot.original_entry_candidate.iloc[d + 11]
        and slot.gate_slot_consumed.iloc[d + 11]
        and slot.reservation_before_gate.iloc[d + 11] == d + 11
        and slot.reservation_index.iloc[d + 11] == d + 22,
    )
    check(
        "RETRY clock unchanged with daily reconsideration",
        not retry.gate_slot_consumed.any()
        and retry.reservation_index.eq(-1).all()
        and retry.original_entry_candidate.iloc[d:].all(),
    )

    inherited_features = new.causal_features

    def controlled(args, profile, high_days):
        feature = inherited_features(args[0])
        feature["z5"] = [3.0 if i in high_days else 0.0 for i in range(len(feature))]
        feature["shock_known"] = True
        new.causal_features = lambda market: feature.loc[pd.to_datetime(market.Date)].copy()
        try:
            return run(args, profile)
        finally:
            new.causal_features = inherited_features

    retry_once = controlled(inputs, "RETRY_EACH_D", {d})
    slot_once = controlled(inputs, "KEEP_PLANNED_SLOT", {d})
    check(
        "same known high day produces next-D retry or exact slot expiry",
        retry_once.entry_signal.iloc[d + 1]
        and retry_once.buy_filled_today.iloc[d + 2]
        and slot_once.entry_signal.iloc[d + 11]
        and slot_once.buy_filled_today.iloc[d + 12],
    )
    e = d + 12
    check(
        "real BUY after slot creates actual H10 clocks only then",
        slot_once.entry_index.iloc[e] == e
        and slot_once.deadline_index.iloc[e] == e + 9
        and slot_once.reservation_index.iloc[e] == e + 10
        and slot_once.planned_slot_until.iloc[e] == -1
        and not slot_once.planned_slot_active.iloc[e],
    )
    failed = toy.fixture()
    failed[3].loc[e, "Status"] = "SUSPENDED"
    f = controlled(failed, "KEEP_PLANNED_SLOT", {d, e, e + 1})
    check(
        "real failed BUY never consumes new slot or creates actual cost",
        f.failed_buy_reset.iloc[e]
        and not f.original_entry_candidate.iloc[e]
        and not f.gate_slot_consumed.iloc[e]
        and f.reservation_index.iloc[e] == d + 11
        and f.entry_index.iloc[e] == -1
        and np.isnan(f.entry_fill_price.iloc[e]),
    )
    check(
        "after failed reset later eligible high candidate may consume",
        f.original_entry_candidate.iloc[e + 1]
        and f.gate_slot_consumed.iloc[e + 1]
        and f.reservation_index.iloc[e + 1] == e + 12,
    )
    future_unfillable = toy.fixture()
    future_unfillable[3].loc[d + 1, "Status"] = "SUSPENDED"
    g = controlled(future_unfillable, "KEEP_PLANNED_SLOT", {d})
    check(
        "planned block never uses future hypothetical BUY fillability",
        g.gate_slot_consumed.iloc[d]
        and g.reservation_index.iloc[d] == d + 11
        and not g.failed_buy_reset.iloc[d + 1],
    )
    broken = toy.fixture()
    toy.change(broken, e + 2, 8.0)
    broken[3].loc[e + 3, "Status"] = "SUSPENDED"
    p = controlled(broken, "KEEP_PLANNED_SLOT", {d})
    check(
        "real held pending SELL unaffected by planning clock",
        p.buy_filled_today.iloc[e]
        and p.exit_pending.iloc[e + 2]
        and p.pending_inherited.iloc[e + 3]
        and p.sell_filled_today.iloc[e + 4]
        and not p.gate_slot_consumed.iloc[e + 2 : e + 5].any(),
    )
    check(
        "blocked SELL preserves actual reservation and deadline",
        p.reservation_index.iloc[e + 3] == e + 10 and p.deadline_index.iloc[e + 3] == e + 9,
    )
    for profile in PROFILES:
        for args, label in ((inputs, "high-Z"), (varied, "actual fills")):
            complete = run(args, profile)
            for stop in (d + 1, d + 5, d + 12, d + 24):
                prefix = [x.iloc[:stop].copy(deep=True) for x in args]
                equal(
                    f"causal prefix {profile}/{label}/{stop}",
                    run(prefix, profile),
                    complete.iloc[:stop],
                )
    observations = 0
    previous_definition = old.ActionRoleStrategy(
        ParameterSet(dict(entry_guard="BLOCK_SHOCK", exit_domain="POSITIVE_P", cost_stop="BASE"))
    ).definition
    for profile in PROFILES:
        strategy = new.BlockedClockStrategy(ParameterSet(dict(clock_profile=profile)))
        definition = strategy.definition
        runtime = RuntimeDefinition(
            schema_version=3,
            strategy_family_id="S014",
            version="v1",
            release_id="S014-v1",
            release_hash="a" * 64,
            implementation=ImplementationRef(
                "strategy_runtime.strategies.blocked_clock_review",
                "BlockedClockStrategy",
                1,
                sha256(SOURCE.read_bytes()).hexdigest(),
            ),
            **{field.name: getattr(definition, field.name) for field in fields(StrategyDefinition)},
        )
        for args in (inputs, varied):
            data = dict(zip(("market", "raw", "limits", "status"), args))
            table = strategy.calculate_history(data, list(pd.to_datetime(args[0].Date)))
            for row in table.to_dict("records"):
                evidence = {
                    series.value_field: row[series.value_field]
                    for series in definition.observation.series
                }
                materialize_observation(runtime, helper.observed_plan(runtime, evidence))
                observations += 1
        check("actual SRT numeric slot observations " + profile, True)
        for field in ("inputs", "decision", "execution", "monitoring", "capabilities"):
            check(
                "old contract exact " + profile + " " + field,
                getattr(definition, field) == getattr(previous_definition, field),
            )
    oldtree, newtree = (
        ast.parse(OLD.read_text(encoding="utf-8")),
        ast.parse(SOURCE.read_text(encoding="utf-8")),
    )
    for name in (
        "causal_features",
        "tick",
        "buy_limit",
        "calendar_request",
        "derive_calculation_scope",
    ):

        def find(tree):
            return next(
                x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef) and x.name == name
            )

        check(
            "exact inherited helper AST " + name,
            ast.dump(find(oldtree), include_attributes=False)
            == ast.dump(find(newtree), include_attributes=False),
        )
    for values in (
        {},
        dict(clock_profile=True),
        dict(clock_profile="UNKNOWN"),
        dict(clock_profile="KEEP_PLANNED_SLOT", entry_guard="BLOCK_SHOCK"),
        dict(clock_profile="KEEP_PLANNED_SLOT", date="2024-10-08"),
    ):
        try:
            new.ClockConfig.parse(values)
        except ValueError:
            checks.append("strict single enum rejects " + str(values))
        else:
            raise AssertionError(values)
    check("normal LF source and zero network", b"\r" not in SOURCE.read_bytes() and not attempts)
    result = {
        "status": "PASS_PURE_SYNTHETIC_ONLY",
        "checks_count": len(checks),
        "checks": checks,
        "actual_SRT_observation_materializations": observations,
        "source_sha256": sha256(SOURCE.read_bytes()).hexdigest(),
        "previous_source_sha256": sha256(OLD.read_bytes()).hexdigest(),
        "precheck_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixture_source_sha256": sha256(FIXTURE.read_bytes()).hexdigest(),
        "helper_source_sha256": sha256(HELPER.read_bytes()).hexdigest(),
        "controlled_features": "toy clock boundaries only; actual inherited features used for real-feature integration, prefix and SRT cases; feature AST exact",
        "new_market_inputs": 0,
        "new_fits": 0,
        "new_accounts": 0,
        "network_attempts": attempts,
        "real_NOOP_equivalence": "NOT_EXECUTED",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print("PURE_CLOCK_PASS", len(checks), observations, result["source_sha256"])


if __name__ == "__main__":
    main()
