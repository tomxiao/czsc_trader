"""Pure synthetic runtime checks; no real bars, accounts, candidates or preparations."""

import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket

import pandas as pd
import requests
from strategy_runtime import ParameterSet


HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").exists())
OLD = ROOT / "research/S014/experiments/EX023_20261018/src/strategy_runtime/strategies/repair.py"
NEW = HERE / "strategy_runtime/strategies/repair_action_review.py"
VARIANT = "support_exit_reserve_H10"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def fixture():
    dates = pd.DatetimeIndex(
        [pd.Timestamp("2019-12-31"), *pd.bdate_range("2020-01-02", periods=110)]
    )
    raw = pd.DataFrame(
        dict(
            Date=dates, Open=10.0, High=10.2, Low=9.8, Close=10.0, Volume=100000.0, Amount=1000000.0
        )
    )
    limits = pd.DataFrame(dict(Date=dates, DownLimit=5.0, UpLimit=20.0))
    status = pd.DataFrame(dict(Date=dates, Status="TRADING"))
    return [raw.copy(), raw, limits, status]


def main():
    destination = HERE.parent / "others/synthetic_precheck.json"
    if destination.exists():
        raise RuntimeError("Preserve completed precheck")
    attempts = []

    def prohibited(*args, **kwargs):
        attempts.append("ATTEMPTED")
        raise RuntimeError("Synthetic precheck prohibits network")

    requests.sessions.Session.request = prohibited
    socket.socket.connect = prohibited
    checks = []

    def check(name, value):
        if not bool(value):
            raise AssertionError(name)
        checks.append(name)

    def reject(name, fn):
        try:
            fn()
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError(name)

    old, new = module("c0056_original_synthetic", OLD), module("c0056_review_synthetic", NEW)
    args = fixture()
    baseline = old.history(*args, VARIANT)
    noop = new.history(*args, VARIANT)
    pd.testing.assert_frame_equal(baseline, noop[baseline.columns], check_exact=True)
    check("NOOP every original history cell exact", True)
    check(
        "NOOP diagnostic columns separate and false",
        set(noop) - set(baseline) == set(new.DIAGNOSTIC)
        and not noop[list(new.DIAGNOSTIC)].to_numpy().any(),
    )
    original = old.RepairStrategy(ParameterSet({"variant": VARIANT})).definition
    revised = new.RepairStrategy(
        ParameterSet(dict(variant=VARIANT, intervention_mode="NOOP", intervention_decision_date=""))
    ).definition
    for field in (
        "tradable_symbol",
        "inputs",
        "decision",
        "execution",
        "monitoring",
        "capabilities",
    ):
        check(
            "original SRT definition exact " + field,
            getattr(original, field) == getattr(revised, field),
        )
    check(
        "original observation projection exact",
        revised.observation.series[: len(original.observation.series)]
        == original.observation.series,
    )
    trees = [ast.parse(p.read_text(encoding="utf-8")) for p in (OLD, NEW)]
    for name in ("tick", "buy_limit"):
        nodes = [
            next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == name)
            for t in trees
        ]
        check("unchanged execution helper AST " + name, ast.dump(nodes[0]) == ast.dump(nodes[1]))
    for name in ("calendar_request", "derive_calculation_scope"):
        nodes = [
            next(
                n
                for c in t.body
                if isinstance(c, ast.ClassDef)
                for n in c.body
                if isinstance(n, ast.FunctionDef) and n.name == name
            )
            for t in trees
        ]
        check("unchanged public data-request AST " + name, ast.dump(nodes[0]) == ast.dump(nodes[1]))
    d = int(baseline.entry_signal.to_numpy().nonzero()[0][0])
    e = d + 1

    def day(i):
        return baseline.index[i].date().isoformat()

    def run(mode, i, inputs=None):
        return new.history(*(args if inputs is None else inputs), VARIANT, mode, day(i))

    skip = run("SKIP_BUY_ONCE", d)
    pd.testing.assert_frame_equal(
        skip.iloc[:d][baseline.columns], baseline.iloc[:d], check_exact=True
    )
    check("skip only once", skip.intervention_today.sum() == 1)
    check(
        "skip cancels intent and target without failed BUY or virtual anchor",
        not skip.entry_signal.iloc[d]
        and skip.target_position.iloc[d] == 0
        and not skip.failed_buy_reset.iloc[d]
        and skip.entry_index.iloc[d] == -1
        and skip.deadline_index.iloc[d] == -1
        and skip.reservation_index.iloc[d] == -1,
    )
    check(
        "next close can produce fresh ordinary signal",
        skip.entry_signal.iloc[e]
        and not skip.buy_filled_today.iloc[e]
        and skip.entry_index.iloc[e] == -1
        and skip.reservation_index.iloc[e] == -1,
    )
    check(
        "only real new fill establishes fresh H10 anchor",
        skip.buy_filled_today.iloc[e + 1]
        and skip.entry_index.iloc[e + 1] == e + 1
        and skip.deadline_index.iloc[e + 1] == e + 10
        and skip.reservation_index.iloc[e + 1] == e + 11,
    )
    force = run("FORCE_SELL_ONCE", e)
    pd.testing.assert_frame_equal(
        force.iloc[:e][baseline.columns], baseline.iloc[:e], check_exact=True
    )
    check(
        "force sets SELL pending and keeps original anchors",
        force.exit_pending.iloc[e]
        and force.target_position.iloc[e] == 0
        and all(
            force.iloc[e][k] == baseline.iloc[e][k]
            for k in ("entry_index", "deadline_index", "reservation_index")
        ),
    )
    check(
        "force sells next executable day once",
        force.sell_filled_today.iloc[e + 1] and force.intervention_today.sum() == 1,
    )
    reservation = e + 10
    check(
        "successful early sale does not unlock original reservation",
        not force.entry_signal.iloc[e + 1 : reservation].any()
        and force.reservation_index.iloc[e + 1 : reservation + 1].eq(reservation).all(),
    )
    check(
        "normal policy resumes at original reservation then new fill anchors",
        force.entry_signal.iloc[reservation]
        and force.buy_filled_today.iloc[reservation + 1]
        and force.reservation_index.iloc[reservation + 1] == reservation + 11,
    )
    suspended = fixture()
    suspended[3].loc[e + 1, "Status"] = "SUSPENDED"
    delayed = run("FORCE_SELL_ONCE", e, suspended)
    check(
        "suspended SELL remains held and pending, later fills",
        delayed.held_at_close.iloc[e + 1]
        and delayed.exit_pending.iloc[e + 1]
        and not delayed.sell_filled_today.iloc[e + 1]
        and delayed.sell_filled_today.iloc[e + 2],
    )
    check(
        "delayed SELL preserves original reservation",
        delayed.reservation_index.iloc[e : e + 3].eq(reservation).all(),
    )
    lower = fixture()
    for f in lower[:2]:
        f.loc[e + 1, ["Open", "High", "Low", "Close"]] = 9.0
        f.loc[e + 2, ["Open", "High", "Low", "Close"]] = [9.0, 9.01, 9.0, 9.0]
    lower[2].loc[e + 1 : e + 2, "DownLimit"] = 9.0
    limit = run("FORCE_SELL_ONCE", e, lower)
    check(
        "locked lower-limit SELL blocked, touch above lower later executable",
        not limit.sell_filled_today.iloc[e + 1]
        and limit.exit_pending.iloc[e + 1]
        and limit.sell_filled_today.iloc[e + 2],
    )
    prolonged = fixture()
    prolonged[3].loc[e + 1 : reservation + 1, "Status"] = "SUSPENDED"
    late = run("FORCE_SELL_ONCE", e, prolonged)
    check(
        "pending sale beyond reservation uses original fill rules",
        late.held_at_close.iloc[reservation + 1]
        and late.exit_pending.iloc[reservation + 1]
        and late.sell_filled_today.iloc[reservation + 2],
    )
    check(
        "after delayed fill and elapsed reservation ordinary reentry resumes",
        late.entry_signal.iloc[reservation + 2]
        and late.buy_filled_today.iloc[reservation + 3]
        and late.entry_index.iloc[reservation + 3] == reservation + 3,
    )
    failed = fixture()
    failed[3].loc[e, "Status"] = "SUSPENDED"
    old_failed = old.history(*failed, VARIANT)
    new_failed = new.history(*failed, VARIANT)
    pd.testing.assert_frame_equal(old_failed, new_failed[old_failed.columns], check_exact=True)
    check(
        "failed BUY NOOP semantics exact with no same-day retry",
        new_failed.failed_buy_reset.iloc[e]
        and not new_failed.entry_signal.iloc[e]
        and new_failed.entry_signal.iloc[e + 1],
    )
    reject("skip on failed-BUY reset rejects", lambda: run("SKIP_BUY_ONCE", e, failed))
    for mode, i in (
        ("SKIP_BUY_ONCE", e),
        ("SKIP_BUY_ONCE", 1),
        ("FORCE_SELL_ONCE", d),
        ("FORCE_SELL_ONCE", e + 9),
    ):
        reject(f"ineligible original node rejects {mode} {i}", lambda mode=mode, i=i: run(mode, i))
    reject(
        "missing intervention date rejects",
        lambda: new.history(*args, VARIANT, "SKIP_BUY_ONCE", "2025-06-18"),
    )
    for mode, value in (
        ("BAD", ""),
        (None, ""),
        ("NOOP", "2020-03-26"),
        ("NOOP", None),
        ("SKIP_BUY_ONCE", ""),
        ("FORCE_SELL_ONCE", "20200326"),
        ("FORCE_SELL_ONCE", "2020-3-26"),
        ("FORCE_SELL_ONCE", "2020-02-30"),
        ("FORCE_SELL_ONCE", "2020-03-26T00:00:00"),
        ("FORCE_SELL_ONCE", "2019-12-31"),
    ):
        reject(
            f"strict mode/date schema rejects {mode!r} {value!r}",
            lambda mode=mode, value=value: new.validate_intervention(mode, value),
        )
    for values in (
        {"variant": VARIANT},
        {
            "variant": VARIANT,
            "intervention_mode": "NOOP",
            "intervention_decision_date": "",
            "extra": 1,
        },
        {
            "variant": "support_exit_H10",
            "intervention_mode": "NOOP",
            "intervention_decision_date": "",
        },
    ):
        reject(
            "exact constructor schema rejects " + str(values),
            lambda values=values: new.RepairStrategy(ParameterSet(values)),
        )
    for mode, i, full in (("SKIP_BUY_ONCE", d, skip), ("FORCE_SELL_ONCE", e, force)):
        prefix = run(mode, i, [f.iloc[: i + 1].copy() for f in args])
        pd.testing.assert_frame_equal(prefix, full.iloc[: i + 1], check_exact=True)
        check("causal prefix independent of future bars " + mode, True)
    scaled = fixture()
    scaled[0].loc[:, ["Open", "High", "Low", "Close"]] *= 5.892
    old_scaled, new_scaled = old.history(*scaled, VARIANT), new.history(*scaled, VARIANT)
    pd.testing.assert_frame_equal(old_scaled, new_scaled[old_scaled.columns], check_exact=True)
    check("NOOP exact with distinct adjusted/raw price scales", True)
    check("no network attempts", not attempts)
    report = dict(
        status="PASS_SYNTHETIC_ONLY",
        checks=checks,
        check_count=len(checks),
        real_account_evaluations=0,
        real_branch_histories=0,
        new_candidates=0,
        new_fits=0,
        network_attempts=attempts,
        real_NOOP_equivalence="PENDING_FUTURE_AUTHORIZATION",
        input_binding_reuse="NOT_EXECUTED_NOT_PROVEN",
        source_sha256={
            str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p.read_bytes()).hexdigest()
            for p in (OLD, NEW, Path(__file__))
        },
    )
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "checks": len(checks),
                "sha256": sha256(destination.read_bytes()).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()
