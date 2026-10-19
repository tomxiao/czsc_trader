"""Synthetic fixed nine-cell policy, causal features, and actual SRT numeric boundary."""

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
SOURCE = EX / "src/strategy_runtime/strategies/exante_hold_exit.py"
OLD = ROOT / "research/S014/experiments/EX023_20261018/src/strategy_runtime/strategies/repair.py"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def fixture():
    days = pd.DatetimeIndex(
        [pd.Timestamp("2019-12-31"), *pd.bdate_range("2020-01-02", periods=110)]
    )
    close = 8.0 + np.arange(len(days)) * 0.03
    raw = pd.DataFrame(
        dict(
            Date=days,
            Open=close,
            High=close + 0.2,
            Low=close - 0.2,
            Close=close,
            Volume=100000.0,
            Amount=1000000.0,
        )
    )
    return [
        raw.copy(),
        raw,
        pd.DataFrame(dict(Date=days, DownLimit=1.0, UpLimit=100.0)),
        pd.DataFrame(dict(Date=days, Status="TRADING")),
    ]


def change(inputs, index, close=None, open_=None):
    for frame in inputs[:2]:
        if open_ is not None:
            frame.loc[index, "Open"] = open_
        if close is not None:
            frame.loc[index, "Close"] = close
        frame.loc[index, "High"] = max(frame.loc[index, "Open"], frame.loc[index, "Close"]) + 0.2
        frame.loc[index, "Low"] = min(frame.loc[index, "Open"], frame.loc[index, "Close"]) - 0.2


def main():
    dest = EX / "others/synthetic_precheck.json"
    if dest.exists():
        raise RuntimeError("Preserve completed synthetic evidence")
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append("ATTEMPT")
        raise RuntimeError("Synthetic precheck forbids network")

    requests.sessions.Session.request = forbidden
    socket.socket.connect = forbidden
    old, new = module("ex043_original", OLD), module("ex043_new", SOURCE)
    helper = module(
        "ex043_srt_synthetic_helper",
        ROOT / "research/S014/experiments/EX041_20261019/src/precheck.py",
    )
    checks = []

    def check(name, value):
        assert bool(value), name
        checks.append(name)

    def equal(name, a, b):
        pd.testing.assert_frame_equal(a, b, check_exact=True)
        checks.append(name)

    def reject(name, action):
        try:
            action()
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError(name)

    def config(hold="BASE", exit_="BASE"):
        return new.HoldExitConfig.parse({"hold_rule": hold, "exit_rule": exit_})

    def run(inputs, hold="BASE", exit_="BASE"):
        return new.history(*inputs, config(hold, exit_))

    inputs = fixture()
    baseline = old.history(*inputs, "support_exit_reserve_H10")
    equal("BASE BASE full original history/target exact", run(inputs)[baseline.columns], baseline)
    e = int(baseline.buy_filled_today.to_numpy().nonzero()[0][0])
    grace = fixture()
    change(grace, e, 9.50)
    change(grace, e + 1, 9.40)
    a = run(grace, "ENTRY_GRACE")
    r = old.history(*grace, "support_exit_reserve_H10")
    equal(
        "entry grace original full prefix before actual BUY exact",
        a.iloc[:e][r.columns],
        r.iloc[:e],
    )
    check(
        "actual entry support break suppressed once without falsifying support",
        a.buy_filled_today.iloc[e]
        and a.support_break.iloc[e]
        and a.support_exit_suppressed.iloc[e]
        and not a.exit_pending.iloc[e],
    )
    check(
        "ENTRY_GRACE restores support exit at next close",
        a.support_break.iloc[e + 1]
        and a.exit_pending.iloc[e + 1]
        and not a.entry_grace_applied.iloc[e + 1]
        and a.sell_filled_today.iloc[e + 2],
    )
    check(
        "entry grace keeps entry deadline reservation and no fake failure",
        a.entry_index.iloc[e] == e
        and a.deadline_index.iloc[e] == e + 9
        and a.reservation_index.iloc[e] == e + 10
        and not a.failed_buy_reset.iloc[e],
    )
    trend = fixture()
    prior_floor = min(trend[0].Close.iloc[e - 5 : e])
    change(trend, e, prior_floor - 0.05)
    change(trend, e + 1, prior_floor - 0.08)
    h = run(trend, "TREND_CYCLE")
    check(
        "fixed shallow uptrend activates only actual entry break",
        h.trend_cycle_activated.iloc[e]
        and h.support_break.iloc[e]
        and h.trend_cycle_eligible.iloc[e]
        and h.trend_cycle_active.iloc[e],
    )
    check(
        "trend cycle ignores later support break without extending deadline",
        h.support_exit_suppressed.iloc[e + 1]
        and not h.exit_pending.iloc[e + 1]
        and h.deadline_index.iloc[e + 1] == e + 9
        and h.reservation_index.iloc[e + 1] == e + 10,
    )
    check(
        "mandatory H10 deadline overrides trend protection",
        h.exit_pending.iloc[e + 9]
        and h.deadline_exit.iloc[e + 9]
        and not h.support_exit_suppressed.iloc[e + 9]
        and h.sell_filled_today.iloc[e + 10],
    )
    check(
        "real sale clears peak/protection and original reservation remains",
        not h.trend_cycle_active.iloc[e + 10]
        and pd.isna(h.peak_close.iloc[e + 10])
        and h.reservation_index.iloc[e + 10] == e + 10,
    )
    check(
        "real fresh BUY resets original clocks and peak to real Close",
        h.buy_filled_today.iloc[e + 11]
        and h.entry_index.iloc[e + 11] == e + 11
        and h.peak_close.iloc[e + 11] == trend[0].Close.iloc[e + 11]
        and h.giveback_price.iloc[e + 11] == 0,
    )
    deep = fixture()
    change(deep, e, prior_floor - 2.0)
    q = run(deep, "TREND_CYCLE")
    check(
        "deep support break does not receive trend protection",
        q.support_break.iloc[e] and not q.trend_cycle_activated.iloc[e] and q.exit_pending.iloc[e],
    )
    partial = fixture()
    change(partial, e, prior_floor - 0.05)
    partial[3].loc[e, "Status"] = "SUSPENDED"
    u = run(partial, "TREND_CYCLE")
    check(
        "failed actual BUY creates no peak or protection",
        u.failed_buy_reset.iloc[e]
        and not u.held_at_close.iloc[e]
        and not u.trend_cycle_active.iloc[e]
        and pd.isna(u.peak_close.iloc[e]),
    )
    giveback = fixture()
    change(giveback, e + 1, 11.5)
    change(giveback, e + 2, 9.78)
    t = run(giveback, "BASE", "PROFIT_GIVEBACK")
    check(
        "giveback after real profit can trigger while current P negative",
        t.giveback_condition.iloc[e + 2]
        and t.selected_profit_exit.iloc[e + 2]
        and t.net_profit.iloc[e + 2] < 0,
    )
    check(
        "giveback triggers without support break and is added to BASE HOLD",
        not t.support_break.iloc[e + 2]
        and t.profit_exit_added_vs_base_support.iloc[e + 2]
        and t.exit_pending.iloc[e + 2],
    )
    check(
        "peak is real closing maximum, not intraday High or fill seed",
        t.peak_close.iloc[e] == giveback[0].Close.iloc[e]
        and t.giveback_price.iloc[e] == 0
        and t.peak_close.iloc[e + 2] == 11.5,
    )
    overlap = fixture()
    change(overlap, e, prior_floor - 0.05)
    change(overlap, e + 1, 11.5)
    change(overlap, e + 2, 9.50)
    p = run(overlap, "TREND_CYCLE", "PROFIT_GIVEBACK")
    check(
        "profit exit overrides protected support break",
        p.trend_cycle_active.iloc[e + 2]
        and p.support_break.iloc[e + 2]
        and p.selected_profit_exit.iloc[e + 2]
        and p.exit_pending.iloc[e + 2]
        and not p.support_exit_suppressed.iloc[e + 2],
    )
    check(
        "original BASE overlap and same-hold added diagnostics distinct",
        p.profit_support_overlap.iloc[e + 2]
        and not p.profit_exit_added_vs_base_support.iloc[e + 2]
        and p.profit_exit_added_vs_selected_hold.iloc[e + 2],
    )
    blocked = [x.copy(deep=True) for x in overlap]
    blocked[3].loc[e + 3, "Status"] = "SUSPENDED"
    b = run(blocked, "TREND_CYCLE", "PROFIT_GIVEBACK")
    check(
        "inherited blocked SELL takes priority over protection/new exits",
        b.pending_inherited.iloc[e + 3]
        and b.exit_pending.iloc[e + 3]
        and b.held_at_close.iloc[e + 3]
        and not b.profit_exit_eligible.iloc[e + 3]
        and b.sell_filled_today.iloc[e + 4],
    )
    check(
        "blocked sale retains entry fixed clocks and observed peak",
        b.entry_index.iloc[e + 3] == e
        and b.deadline_index.iloc[e + 3] == e + 9
        and b.reservation_index.iloc[e + 3] == e + 10
        and b.peak_close.iloc[e + 3] >= b.peak_close.iloc[e + 2],
    )
    blocked_limit = [x.copy(deep=True) for x in overlap]
    for frame in blocked_limit[:2]:
        frame.loc[e + 3, ["Open", "High", "Low", "Close"]] = 9.0
    blocked_limit[2].loc[e + 3, "DownLimit"] = 9.0
    z = run(blocked_limit, "TREND_CYCLE", "PROFIT_GIVEBACK")
    check(
        "lower-limit blocked SELL stays pending",
        z.pending_inherited.iloc[e + 3]
        and not z.sell_filled_today.iloc[e + 3]
        and z.sell_filled_today.iloc[e + 4],
    )
    shock = run(inputs, "BASE", "SHOCK_PROFIT")
    check(
        "shock exit uses positive after-both-fees mark with nonoverlap Z",
        shock.shock_condition.any()
        and shock.loc[shock.selected_profit_exit.eq(1), "net_profit"].gt(0).all()
        and shock.loc[shock.selected_profit_exit.eq(1), "z5"].gt(2).all(),
    )
    check(
        "Z5 positive shock cannot overlap S5 downside break",
        not (shock.shock_condition.eq(1) & shock.support_break).any(),
    )
    flat = fixture()
    for frame in flat[:2]:
        frame.loc[:, ["Open", "High", "Low", "Close"]] = [10.0, 10.2, 9.8, 10.0]
    unknown = run(flat, "BASE", "SHOCK_PROFIT")
    check(
        "zero volatility is explicit unknown, never infinite shock",
        not unknown.shock_known.any()
        and unknown.z5.isna().all()
        and not unknown.selected_profit_exit.any(),
    )
    check(
        "unmatured raw features remain missing with false flags",
        pd.isna(unknown.ma20_prior.iloc[0])
        and pd.isna(unknown.atr20_prior.iloc[0])
        and not unknown.ma_known.iloc[0]
        and not unknown.atr_known.iloc[0],
    )
    features = new.causal_features(inputs[0])
    i = 75
    closes = inputs[0].Close.to_numpy()
    trs = [
        max(
            inputs[0].High.iloc[j] - inputs[0].Low.iloc[j],
            abs(inputs[0].High.iloc[j] - closes[j - 1]),
            abs(inputs[0].Low.iloc[j] - closes[j - 1]),
        )
        for j in range(i - 20, i)
    ]
    pre_returns = [np.log(closes[j] / closes[j - 1]) for j in range(i - 24, i - 4)]
    check(
        "MA20 prior and five-session lag independently reconstructed",
        np.isclose(features.ma20_prior.iloc[i], np.mean(closes[i - 20 : i]), rtol=1e-12)
        and np.isclose(
            features.ma20_prior_lag5.iloc[i], np.mean(closes[i - 25 : i - 5]), rtol=1e-12
        ),
    )
    check(
        "ATR20 simple mean ending D-1 independently reconstructed",
        np.isclose(features.atr20_prior.iloc[i], np.mean(trs), rtol=1e-12),
    )
    expected_z = np.log(closes[i] / closes[i - 5]) / (np.sqrt(5) * np.std(pre_returns, ddof=1))
    check(
        "Z5 numerator and ddof1 pre-D5 sigma independently reconstructed",
        np.isclose(features.z5.iloc[i], expected_z, rtol=1e-10),
    )
    observations = 0
    data = dict(zip(("market", "raw", "limits", "status"), overlap))
    sessions = list(pd.to_datetime(overlap[0].Date))
    for hold in new.HoldRule:
        for exit_ in new.ExitRule:
            values = {"hold_rule": hold.value, "exit_rule": exit_.value}
            strategy = new.HoldExitStrategy(ParameterSet(values))
            table = strategy.calculate_history(data, sessions)
            definition = strategy.definition
            runtime = RuntimeDefinition(
                schema_version=3,
                strategy_family_id="S014",
                version="v1",
                release_id="S014-v1",
                release_hash="a" * 64,
                implementation=ImplementationRef(
                    "strategy_runtime.strategies.exante_hold_exit",
                    "HoldExitStrategy",
                    1,
                    sha256(SOURCE.read_bytes()).hexdigest(),
                ),
                **{
                    field.name: getattr(definition, field.name)
                    for field in fields(StrategyDefinition)
                },
            )
            for row in table.to_dict("records"):
                evidence = {
                    series.value_field: row[series.value_field]
                    for series in definition.observation.series
                }
                materialize_observation(runtime, helper.observed_plan(runtime, evidence))
                observations += 1
            check(
                f"actual SRT numeric observation all synthetic rows {hold.value}/{exit_.value}",
                True,
            )
            original_definition = old.RepairStrategy(
                ParameterSet({"variant": "support_exit_reserve_H10"})
            ).definition
            for field in ("inputs", "decision", "execution", "monitoring", "capabilities"):
                check(
                    f"original contract {hold.value}/{exit_.value} {field}",
                    getattr(definition, field) == getattr(original_definition, field),
                )
            full = run(overlap, hold.value, exit_.value)
            for stop in (e + 1, e + 3, e + 10):
                equal(
                    f"causal prefix {hold.value}/{exit_.value}/{stop}",
                    run([x.iloc[:stop].copy() for x in overlap], hold.value, exit_.value),
                    full.iloc[:stop],
                )
    for name in ("tick", "buy_limit", "calendar_request", "derive_calculation_scope"):

        def find(path):
            return next(
                n
                for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                if isinstance(n, ast.FunctionDef) and n.name == name
            )

        check(
            "original helper/data-request AST " + name,
            ast.dump(find(SOURCE)) == ast.dump(find(OLD)),
        )
    for values in (
        {},
        {"hold_rule": "BASE"},
        {"hold_rule": True, "exit_rule": "BASE"},
        {"hold_rule": "BASE", "exit_rule": "BAD"},
        {"hold_rule": "BASE", "exit_rule": "BASE", "date": "2025-05-30"},
    ):
        reject(
            "strict exact enum schema " + repr(values),
            lambda values=values: new.HoldExitConfig.parse(values),
        )
    missing = fixture()
    missing[0].loc[e, "Close"] = np.nan
    reject("missing original OHLC rejects without fallback", lambda: run(missing))
    scaled = fixture()
    scaled[0].loc[:, ["Open", "High", "Low", "Close"]] *= 5.892
    scaled_old = old.history(*scaled, "support_exit_reserve_H10")
    equal(
        "BASE BASE original projection exact with distinct HFQ/raw scales",
        run(scaled)[scaled_old.columns],
        scaled_old,
    )
    check("no network attempts", not attempts)
    receipt = {
        "status": "PASS_PURE_SYNTHETIC_ONLY",
        "checks_count": len(checks),
        "checks": checks,
        "actual_SRT_observation_materializations": observations,
        "source_sha256": sha256(SOURCE.read_bytes()).hexdigest(),
        "original_source_sha256": sha256(OLD.read_bytes()).hexdigest(),
        "precheck_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "helper_source_sha256": sha256(
            (ROOT / "research/S014/experiments/EX041_20261019/src/precheck.py").read_bytes()
        ).hexdigest(),
        "new_account_dispatches": 0,
        "real_market_inputs_read": False,
        "network_attempts": attempts,
        "new_fits": 0,
        "real_NOOP_equivalence": "NOT_EXECUTED",
    }
    dest.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "checks": len(checks),
                "actual_observations": observations,
                "source_sha256": receipt["source_sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
