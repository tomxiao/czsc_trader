"""Synthetic-only fixed five roles: execution clock, state and actual SRT boundary."""

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
SOURCE = EX / "src/strategy_runtime/strategies/action_role_review.py"
OLD = (
    ROOT
    / "research/S014/experiments/EX043_20261019/src/strategy_runtime/strategies/exante_hold_exit.py"
)
FIXTURE = ROOT / "research/S014/experiments/EX043_20261019/src/precheck.py"
HELPER = ROOT / "research/S014/experiments/EX041_20261019/src/precheck.py"
CELLS = [
    dict(entry_guard="BASE", exit_domain="POSITIVE_P", cost_stop="BASE"),
    dict(entry_guard="BLOCK_SHOCK", exit_domain="POSITIVE_P", cost_stop="BASE"),
    dict(entry_guard="BASE", exit_domain="ANY_P", cost_stop="BASE"),
    dict(entry_guard="BLOCK_SHOCK", exit_domain="ANY_P", cost_stop="BASE"),
    dict(entry_guard="BASE", exit_domain="POSITIVE_P", cost_stop="NET_LOSS_1ATR"),
]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def main():
    destination = EX / "others/synthetic_precheck.json"
    if destination.exists():
        raise ValueError("Preserve existing synthetic receipt")
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append("FORBIDDEN")
        raise RuntimeError("Pure synthetic precheck forbids network")

    requests.sessions.Session.request = blocked
    socket.socket.connect = blocked
    socket.create_connection = blocked
    old, new = module("ex044_old", OLD), module("ex044_new", SOURCE)
    toy, helper = module("ex044_fixture", FIXTURE), module("ex044_srt_helper", HELPER)
    checks = []

    def check(name, value):
        assert bool(value), name
        checks.append(name)

    def equal(name, actual, expected):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        checks.append(name)

    def reject(name, call):
        try:
            call()
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError(name)

    def run(inputs, cell=0):
        return new.history(*inputs, new.ActionRoleConfig.parse(CELLS[cell]))

    oldconfig = old.HoldExitConfig.parse(dict(hold_rule="ENTRY_GRACE", exit_rule="SHOCK_PROFIT"))
    inputs = toy.fixture()
    baseline = old.history(*inputs, oldconfig)
    equal(
        "new baseline full inherited history exact against frozen GRACE SHOCK",
        run(inputs)[baseline.columns],
        baseline,
    )
    entry = int(np.flatnonzero(baseline.buy_filled_today)[0])
    candidate = entry - 1
    e = entry
    for label, args in [
        ("ordinary", inputs),
        ("distinct price scales", [x.copy(deep=True) for x in inputs]),
    ]:
        if label != "ordinary":
            args[0].loc[:, ["Open", "High", "Low", "Close"]] *= 5.892
        expected = old.history(*args, oldconfig)
        equal("baseline all old columns exact " + label, run(args)[expected.columns], expected)

    gated = run(inputs, 1)
    check("integration Z gate sees original candidate and blocks", gated.entry_guard_blocked.any())
    check(
        "blocked intent has no actual BUY, failedBUY, accepted or phantom anchor",
        not gated.buy_filled_today.any()
        and not gated.failed_buy_reset.any()
        and not gated.entry_signal.any()
        and gated.entry_index.eq(-1).all()
        and gated.reservation_index.eq(-1).all(),
    )
    check(
        "gate re-evaluates after first blocked D",
        gated.original_entry_candidate.iloc[candidate:].all(),
    )
    unrestricted = run(inputs, 2)
    check(
        "real-feature ANY P allows negative-P actual BUY-D acceleration exit",
        unrestricted.selected_shock_exit.iloc[e]
        and unrestricted.net_profit.iloc[e] < 0
        and not unrestricted.selected_profit_exit.iloc[e]
        and unrestricted.exit_pending.iloc[e]
        and unrestricted.sell_filled_today.iloc[e + 1],
    )

    real_features = new.causal_features

    def controlled(args, *, z=None, atr=None, cell=0):
        # Feature injection is solely for exact boundary/state tests. The actual
        # inherited feature function is used for integration/prefix/SRT below.
        feature = real_features(args[0])
        if z is not None:
            feature["z5"] = [z(i) if callable(z) else z for i in range(len(feature))]
            feature["shock_known"] = np.isfinite(feature.z5)
        if atr is not None:
            feature["atr20_prior"] = [atr(i) if callable(atr) else atr for i in range(len(feature))]
            feature["atr_known"] = np.isfinite(feature.atr20_prior)
            feature["atr_positive"] = feature.atr_known & feature.atr20_prior.gt(0)
        new.causal_features = lambda market: feature.loc[pd.to_datetime(market.Date)].copy()
        try:
            return run(args, cell)
        finally:
            new.causal_features = real_features

    only_candidate = controlled(inputs, z=lambda i: 2.1 if i == candidate else 0.0, cell=1)
    check(
        "single gate block followed by later candidate BUY, not permanent cash",
        only_candidate.entry_guard_blocked.iloc[candidate]
        and only_candidate.entry_signal.iloc[candidate + 1]
        and only_candidate.buy_filled_today.iloc[candidate + 2],
    )
    check(
        "only actual later BUY creates fresh original anchors",
        only_candidate.reservation_index.iloc[candidate + 1] == -1
        and only_candidate.entry_index.iloc[candidate + 2] == candidate + 2
        and only_candidate.deadline_index.iloc[candidate + 2] == candidate + 11
        and only_candidate.reservation_index.iloc[candidate + 2] == candidate + 12,
    )
    for z, should_block in [(2.0, False), (np.nextafter(2.0, np.inf), True), (np.nan, False)]:
        row = controlled(inputs, z=z, cell=1).iloc[candidate]
        check(
            f"gate known and strict Z boundary {z}",
            bool(row.entry_guard_blocked) == should_block
            and bool(row.entry_signal) != should_block,
        )
    for z, should_exit in [(2.0, False), (np.nextafter(2.0, np.inf), True), (np.nan, False)]:
        row = controlled(inputs, z=z, cell=2).iloc[e]
        check(
            f"ANY P known and strict Z boundary {z}",
            row.net_profit < 0 and bool(row.selected_shock_exit) == should_exit,
        )

    zero = toy.fixture()
    for frame in zero[:2]:
        frame.loc[e, "Open"] = 8.0
    toy.change(zero, e, 8.0 * 1.001 / 0.999)
    a, b = controlled(zero, z=3.0), controlled(zero, z=3.0, cell=2)
    check(
        "exact current net P zero excluded by old domain included ANY",
        a.net_profit.iloc[e] == b.net_profit.iloc[e] == 0.0
        and not a.selected_profit_exit.iloc[e]
        and b.selected_shock_exit.iloc[e],
    )

    failed = toy.fixture()
    failed[3].loc[e, "Status"] = "SUSPENDED"
    f = controlled(failed, z=lambda i: 3.0 if i == e else 0.0, cell=1)
    check(
        "actual failed BUY stays original reset, not gate or phantom cost",
        f.failed_buy_reset.iloc[e]
        and not f.original_entry_candidate.iloc[e]
        and not f.entry_guard_blocked.iloc[e]
        and f.entry_index.iloc[e] == -1
        and f.entry_signal.iloc[e + 1]
        and f.buy_filled_today.iloc[e + 2],
    )

    ordinary = controlled(inputs, z=0.0)
    loss = ordinary.entry_fill_price.iloc[e] * 1.001 - inputs[0].Close.iloc[e] * 0.999
    check("toy entry already has positive double-fee loss price", loss > 0)
    for atr, should_exit in [
        (loss, True),
        (np.nextafter(loss, np.inf), False),
        (np.nan, False),
        (0.0, False),
    ]:
        row = controlled(inputs, z=0.0, atr=atr, cell=4).iloc[e]
        check(
            f"cost NET inclusive exact boundary or unknown scale {atr}",
            bool(row.selected_cost_exit) == should_exit and row.cost_loss_price == loss,
        )
    check(
        "entry price need not fall to incur net-cost stop including fees",
        inputs[0].Close.iloc[e] == ordinary.entry_fill_price.iloc[e],
    )

    flat = toy.fixture()
    current = float(flat[0].Close.iloc[e])
    for i in range(e + 1, len(flat[0])):
        for frame in flat[:2]:
            frame.loc[i, "Open"] = current
        toy.change(flat, i, current)
    fixed = controlled(flat, z=0.0, atr=lambda i: loss * 2 if i < e + 2 else loss / 2, cell=4)
    check(
        "current prior ATR shrink can create cost trigger without new decline",
        not fixed.selected_cost_exit.iloc[e]
        and not fixed.selected_cost_exit.iloc[e + 1]
        and fixed.selected_cost_exit.iloc[e + 2]
        and flat[0].Close.iloc[e] == flat[0].Close.iloc[e + 2],
    )
    check(
        "cost exit preserves original clock and prior reservation",
        fixed.entry_index.iloc[e + 2] == e
        and fixed.deadline_index.iloc[e + 2] == e + 9
        and fixed.reservation_index.iloc[e + 2] == e + 10,
    )

    blocked_sale = [frame.copy(deep=True) for frame in flat]
    blocked_sale[3].loc[e + 3, "Status"] = "SUSPENDED"
    price = float(blocked_sale[0].Close.iloc[e + 4])
    for frame in blocked_sale[:2]:
        frame.loc[e + 4, ["Open", "High", "Low", "Close"]] = price
    blocked_sale[2].loc[e + 4, "DownLimit"] = price
    t = controlled(blocked_sale, z=0.0, atr=lambda i: loss / 2 if i == e + 2 else loss * 2, cell=4)
    check(
        "prior SELL pending survives suspension and lower limit after cost condition disappears",
        t.pending_inherited.iloc[e + 3]
        and t.pending_inherited.iloc[e + 4]
        and not t.selected_risk_exit.iloc[e + 3]
        and not t.selected_risk_exit.iloc[e + 4]
        and t.sell_filled_today.iloc[e + 5],
    )
    check(
        "blocked sale does not reset original anchors",
        t.entry_index.iloc[e + 4] == e
        and t.deadline_index.iloc[e + 4] == e + 9
        and t.reservation_index.iloc[e + 4] == e + 10,
    )
    check(
        "reservation not shortened by cost sale",
        not fixed.original_entry_candidate.iloc[e + 3 : e + 10].any()
        and fixed.reservation_index.iloc[e + 3 : e + 10].eq(e + 10).all(),
    )

    broken = toy.fixture()
    toy.change(broken, e, 9.0)
    no_cost = controlled(broken, z=0.0)
    with_cost = controlled(broken, z=0.0, atr=0.1, cell=4)
    check(
        "baseline entry grace still works without cost toggle",
        no_cost.support_break.iloc[e]
        and no_cost.entry_grace_applied.iloc[e]
        and not no_cost.exit_pending.iloc[e],
    )
    check(
        "cost risk overrides grace on actual BUY D with next E sale",
        with_cost.selected_cost_exit.iloc[e]
        and with_cost.cost_grace_override.iloc[e]
        and not with_cost.entry_grace_applied.iloc[e]
        and with_cost.exit_pending.iloc[e]
        and with_cost.sell_filled_today.iloc[e + 1],
    )
    due = controlled(flat, z=0.0, atr=lambda i: 0.001 if i == e + 9 else 1000.0, cell=4)
    check(
        "mandatory deadline priority excludes new risk attribution",
        due.deadline_exit.iloc[e + 9]
        and not due.profit_exit_eligible.iloc[e + 9]
        and not due.selected_risk_exit.iloc[e + 9]
        and due.exit_pending.iloc[e + 9],
    )

    for cell in range(5):
        complete = run(inputs, cell)
        for stop in [e, e + 3, e + 12]:
            prefix = [x.iloc[:stop].copy(deep=True) for x in inputs]
            equal(
                f"causal history prefix cell{cell} stop{stop}",
                run(prefix, cell),
                complete.iloc[:stop],
            )
        check(
            f"unknown raw cost is not fake valid numeric cell{cell}",
            complete.loc[~complete.held_at_close, "cost_loss_price"].isna().all(),
        )

    observations = 0
    sessions = list(pd.to_datetime(inputs[0].Date))
    data = dict(zip(("market", "raw", "limits", "status"), inputs))
    previous = old.HoldExitStrategy(
        ParameterSet(dict(hold_rule="ENTRY_GRACE", exit_rule="SHOCK_PROFIT"))
    ).definition
    for cell, params in enumerate(CELLS):
        strategy = new.ActionRoleStrategy(ParameterSet(params))
        table = strategy.calculate_history(data, sessions)
        definition = strategy.definition
        runtime = RuntimeDefinition(
            schema_version=3,
            strategy_family_id="S014",
            version="v1",
            release_id="S014-v1",
            release_hash="a" * 64,
            implementation=ImplementationRef(
                "strategy_runtime.strategies.action_role_review",
                "ActionRoleStrategy",
                1,
                sha256(SOURCE.read_bytes()).hexdigest(),
            ),
            **{field.name: getattr(definition, field.name) for field in fields(StrategyDefinition)},
        )
        for row in table.to_dict("records"):
            evidence = {
                series.value_field: row[series.value_field]
                for series in definition.observation.series
            }
            materialize_observation(runtime, helper.observed_plan(runtime, evidence))
            observations += 1
        check(f"actual SRT finite float observations all rows cell{cell}", True)
        for field in ("inputs", "decision", "execution", "monitoring", "capabilities"):
            check(
                f"original execution/data contract exact cell{cell} {field}",
                getattr(definition, field) == getattr(previous, field),
            )

    oldtree, newtree = (
        ast.parse(OLD.read_text(encoding="utf-8")),
        ast.parse(SOURCE.read_text(encoding="utf-8")),
    )

    def named(tree, name):
        return next(x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef) and x.name == name)

    for name in (
        "causal_features",
        "tick",
        "buy_limit",
        "calendar_request",
        "derive_calculation_scope",
    ):
        check(
            "inherited feature/execution helper AST exact " + name,
            ast.dump(named(oldtree, name), include_attributes=False)
            == ast.dump(named(newtree, name), include_attributes=False),
        )
    for values in [
        {},
        dict(CELLS[0], date="2024-10-08"),
        dict(CELLS[0], entry_guard=True),
        dict(CELLS[0], exit_domain="UNKNOWN"),
        dict(CELLS[4], entry_guard="BLOCK_SHOCK"),
        dict(CELLS[4], exit_domain="ANY_P"),
    ]:
        reject(
            "strict canonical five-cell schema " + str(values),
            lambda values=values: new.ActionRoleConfig.parse(values),
        )
    invalid = toy.fixture()
    invalid[0].loc[e, "Close"] = np.nan
    reject("missing market OHLC rejects, no new data or fallback", lambda: run(invalid))
    check("new source normal LF bytes", b"\r" not in SOURCE.read_bytes())
    check("zero network attempts", not attempts)
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
        "boundary_features": "Only pure synthetic z/ATR boundary tests inject controlled in-memory features; production causal_features AST exact and real-feature integration/prefix/SRT tests also pass",
        "real_market_inputs_read": False,
        "real_account_dispatches": 0,
        "formal_candidate_registrations": 0,
        "network_attempts": attempts,
        "real_NOOP_equivalence": "NOT_EXECUTED",
        "new_fits": 0,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print("PURE_SYNTHETIC_PASS", len(checks), observations, result["source_sha256"])


if __name__ == "__main__":
    main()
