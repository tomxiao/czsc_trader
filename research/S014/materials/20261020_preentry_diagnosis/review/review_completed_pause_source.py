"""Independent pure-synthetic own-completion state audit; zero price fetch/accounts."""

import ast
from collections import Counter
from hashlib import sha256
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
SOURCE = (
    ROOT
    / "research/S014/experiments/EX046_20261020/src/strategy_runtime/strategies/completed_pause_review.py"
)
OLD = (
    ROOT
    / "research/S014/experiments/EX044_20261019/src/strategy_runtime/strategies/action_role_review.py"
)
COUNTS = Counter()
ATTEMPTS = []


def check(name, condition):
    if not bool(condition):
        raise AssertionError(name)
    COUNTS[name] += 1


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def prohibit(*args, **kwargs):
    ATTEMPTS.append("network")
    raise RuntimeError("Pure synthetic inputs only")


def fixture(kind):
    days = pd.bdate_range("2020-01-02", periods=115)
    market = pd.DataFrame(
        {"Date": days, "Open": 100.0, "High": 100.0, "Low": 100.0, "Close": 100.0}
    )
    bounds = pd.DataFrame({"Date": days, "DownLimit": 90.0, "UpLimit": 120.0})
    states = pd.DataFrame({"Date": days, "Status": "TRADING"})
    if kind == "profit":
        for i in range(61, len(days)):
            market.loc[i, ["Open", "High", "Low", "Close"]] = min(110.0, 100.0 + i - 60)
    if kind == "blocked_sell":
        states.loc[70, "Status"] = "SUSPENDED"
        market.loc[71, ["Open", "High", "Low", "Close"]] = 90.0
    if kind == "failed_buy":
        market.loc[60, ["Open", "High", "Low", "Close"]] = [104.0, 104.0, 103.0, 103.0]
    return dict(market=market, raw=market.copy(), limits=bounds, status=states)


def oracle(history, frames, profile):
    """Track prior actual entry/SELL prices, sign, armed and reserve independently."""
    last_net, last_sign = None, 0
    entry = None
    armed = False
    reserve = -1
    planned = -1
    market = frames["market"]
    for i, r in enumerate(history.itertuples()):
        bought, sold = bool(r.buy_filled_today), bool(r.sell_filled_today)
        if bought:
            check("buy has no inherited armed pause", not armed)
            entry = float(market.Open.iloc[i])
            reserve, planned = i + 10, -1
        net = None
        if sold:
            check("actual SELL completes own prior BUY", entry is not None)
            net = float(market.Open.iloc[i]) * 0.999 - entry * 1.001
            last_net = net
            last_sign = -1 if net < 0 else 1 if net > 0 else 0
            armed = bool(
                (profile == "AFTER_NET_LOSS_SKIP1" and last_sign < 0)
                or (profile == "AFTER_NET_PROFIT_SKIP1" and last_sign > 0)
            )
            entry = None
        check(
            "actual completion flags exact",
            bool(r.completed_cycle_today) == sold
            and bool(r.completed_loss_today) == bool(sold and last_sign < 0)
            and bool(r.completed_profit_today) == bool(sold and last_sign > 0)
            and bool(r.completed_zero_today) == bool(sold and last_sign == 0),
        )
        check(
            "unknown raw completion not zero imputed",
            pd.isna(r.completed_net_unit) if net is None else r.completed_net_unit == net,
        )
        check(
            "own last completed raw state exact",
            pd.isna(r.last_completed_net_unit)
            if last_net is None
            else r.last_completed_net_unit == last_net,
        )
        check(
            "known/sign exact own actual history",
            bool(r.completed_net_known) == (last_net is not None)
            and r.last_completed_sign == last_sign,
        )
        prior_closes = market.Close.iloc[max(0, i - 5) : i]
        support_ok = i >= 5 and float(market.Close.iloc[i]) >= min(prior_closes)
        candidate = bool(
            not r.held_at_close
            and not r.failed_buy_reset
            and i + 1 >= 60
            and support_ok
            and i >= reserve
        )
        check(
            "original candidate independent pre-pause reserve",
            bool(r.original_entry_candidate) == candidate and r.reservation_before_pause == reserve,
        )
        check(
            "armed before candidate includes sameD SELL",
            bool(r.pause_armed_before_candidate) == armed,
        )
        consume = bool(candidate and armed)
        if consume:
            reserve, planned, armed = i + 11, i + 11, False
        check(
            "single consumption and immediate disarm",
            bool(r.pause_slot_consumed) == consume and bool(r.pause_armed) == armed,
        )
        check(
            "independent reservation/planned boundary",
            r.reservation_index == reserve
            and r.planned_slot_until == planned
            and bool(r.planned_slot_active)
            == bool(not r.held_at_close and planned >= 0 and i < planned),
        )
        check(
            "original BUY intent unless consumed",
            bool(r.entry_signal) == bool(candidate and not consume),
        )
        if consume:
            check(
                "consume never phantom actual cycle",
                r.target_position == 0
                and r.entry_signal == 0
                and r.held_at_close == 0
                and r.entry_index == -1
                and r.deadline_index == -1
                and r.failed_buy_reset == 0
                and pd.isna(r.entry_fill_price)
                and pd.isna(r.peak_close)
                and pd.isna(r.cost_loss_price),
            )


def main():
    expected = sys.argv[1]
    destination = HERE / "source_state_review.json"
    if destination.exists():
        raise FileExistsError(destination)
    check("final expected source bytes", digest(SOURCE) == expected)
    check(
        "fixed original source bytes",
        digest(OLD) == "e176e01873d67fff2c869915373f36b35f1f507524a5583c49b138b3c146b527",
    )
    design = HERE.parent / "design_decision.json"
    check(
        "root final method lock",
        digest(design) == "7db4e057818200a176c823c953e6d05d9b1d00385364518a495de835b2804d2e",
    )
    requests.sessions.Session.request = prohibit
    socket.socket.connect = prohibit
    socket.create_connection = prohibit
    code, old = (
        load(SOURCE, "independent_completed_pause"),
        load(OLD, "independent_completed_prior"),
    )
    trees = [ast.parse(p.read_text(encoding="utf-8")) for p in [SOURCE, OLD]]
    for name in [
        "causal_features",
        "tick",
        "buy_limit",
        "calendar_request",
        "derive_calculation_scope",
    ]:
        nodes = [
            next(n for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name == name)
            for t in trees
        ]
        check(
            "unchanged feature/clock/helper AST " + name, ast.dump(nodes[0]) == ast.dump(nodes[1])
        )
    for name in [
        "InputContract",
        "DecisionContract",
        "ExecutionPolicy",
        "MonitoringPolicy",
        "RequiredCapabilities",
    ]:
        nodes = [
            next(
                n
                for n in ast.walk(t)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
            )
            for t in trees
        ]
        check("unchanged economic contract AST " + name, ast.dump(nodes[0]) == ast.dump(nodes[1]))
    for invalid in [
        {"pause_profile": True},
        {"pause_profile": "x"},
        {"pause_profile": "BASE", "entry_guard": "BASE"},
    ]:
        try:
            code.PauseConfig.parse(invalid)
        except ValueError:
            check("invalid parameter rejected", True)
        else:
            raise AssertionError("invalid config accepted")
    check(
        "strict sign zero and tiny finite signs no epsilon",
        code.completed_sign(0.0) == 0
        and code.completed_sign(np.nextafter(0.0, 1.0)) == 1
        and code.completed_sign(np.nextafter(0.0, -1.0)) == -1,
    )
    for invalid in [np.nan, np.inf, -np.inf]:
        try:
            code.completed_sign(invalid)
        except ValueError:
            check("unknown outcome cannot masquerade completion", True)
        else:
            raise AssertionError("invalid completed sign accepted")
    # Fix old feature values to isolate the new lifecycle; real formulas are AST exact.
    original_features = code.causal_features

    def controlled(prices):
        out = original_features(prices)
        out["z5"], out["shock_known"] = 0.0, True
        out["atr20_prior"], out["atr_known"], out["atr_positive"] = 1.0, True, True
        return out

    code.causal_features = controlled
    old.causal_features = controlled
    findings = {}
    for kind in ["fee_loss", "profit", "blocked_sell", "failed_buy"]:
        frames = fixture(kind)
        histories = {}
        for profile in ["BASE", "AFTER_NET_LOSS_SKIP1", "AFTER_NET_PROFIT_SKIP1"]:
            cfg = code.PauseConfig.parse({"pause_profile": profile})
            history = code.history(**frames, config=cfg)
            histories[profile] = history
            oracle(history, frames, profile)
            strategy = code.CompletedPauseStrategy(ParameterSet({"pause_profile": profile}))
            materialized = strategy.calculate_history(frames, history.index)
            observed = materialized[list(strategy._observed)].to_numpy(dtype=float)
            check("finite numeric SRT observations synthetic", np.isfinite(observed).all())
            check(
                "raw unknown completed values not declared series",
                "completed_net_unit" not in strategy._observed
                and "last_completed_net_unit" not in strategy._observed,
            )
            for cutoff in [70, 81]:
                stop = frames["market"].Date.iloc[cutoff]
                prefix = {k: frame.loc[frame.Date <= stop].copy() for k, frame in frames.items()}
                actual = code.history(**prefix, config=cfg)
                pd.testing.assert_frame_equal(actual, history.loc[actual.index], check_exact=True)
                check("source complete newstate prefix exact", True)
            changed = {k: frame.copy() for k, frame in frames.items()}
            for name in ["market", "raw"]:
                changed[name].loc[82:, ["Open", "High", "Low", "Close"]] = 105.0
            perturbed = code.history(**changed, config=cfg)
            pd.testing.assert_frame_equal(perturbed.iloc[:82], history.iloc[:82], check_exact=True)
            check("future bar mutation no earlier newstate changes", True)
        baseline = old.history(
            **frames,
            config=old.ActionRoleConfig.parse(
                {"entry_guard": "BASE", "exit_domain": "POSITIVE_P", "cost_stop": "NET_LOSS_1ATR"}
            ),
        )
        pd.testing.assert_frame_equal(
            histories["BASE"][baseline.columns], baseline, check_exact=True
        )
        check("BASE all old columns exact cost comparator", True)
        if kind == "fee_loss":
            h = histories["AFTER_NET_LOSS_SKIP1"]
            check(
                "fee-only loss sameD consumes",
                h.iloc[70].sell_filled_today == 1
                and h.iloc[70].pause_slot_consumed == 1
                and h.iloc[70].reservation_index == 81,
            )
            check(
                "once consumed stale loss no rearm expiry",
                h.iloc[81].entry_signal == 1
                and h.iloc[81].last_completed_sign == -1
                and h.iloc[81].pause_slot_consumed == 0
                and h.iloc[82].buy_filled_today == 1,
            )
        if kind == "profit":
            h = histories["AFTER_NET_PROFIT_SKIP1"]
            check(
                "actual profit sameD consumes reversecontrol",
                h.iloc[70].sell_filled_today == 1
                and h.iloc[70].completed_profit_today == 1
                and h.iloc[70].pause_slot_consumed == 1,
            )
        if kind == "blocked_sell":
            h = histories["AFTER_NET_LOSS_SKIP1"]
            check(
                "unfilled suspended/lowerlimit SELL not completion",
                h.iloc[70:72].completed_cycle_today.eq(0).all()
                and h.iloc[70:72].completed_net_known.eq(0).all()
                and h.iloc[70:72].pause_slot_consumed.eq(0).all(),
            )
            check(
                "delayed actual SELL then sameD eligible consumes",
                h.iloc[72].completed_cycle_today == 1
                and h.iloc[72].pause_slot_consumed == 1
                and h.iloc[72].reservation_index == 83,
            )
        if kind == "failed_buy":
            for h in histories.values():
                check(
                    "failed BUY no closed history or pause",
                    h.iloc[60].failed_buy_reset == 1
                    and h.iloc[60].completed_cycle_today == 0
                    and h.iloc[60].completed_net_known == 0
                    and h.iloc[60].pause_slot_consumed == 0
                    and h.iloc[60].reservation_index == -1,
                )
        findings[kind] = (
            "Independent ownhistory oracle and prefix PASS; synthetic not market evidence"
        )
    check("zero network attempts", not ATTEMPTS)
    check("source remains stable bytes", digest(SOURCE) == expected)
    refs = [SOURCE, OLD, design, HERE / "locked_method_gate.json", Path(__file__)]
    result = dict(
        status="PASS",
        blocking_findings=[],
        reviewed_hashes={p.relative_to(ROOT).as_posix(): digest(p) for p in refs},
        checks=sum(COUNTS.values()),
        check_counts=dict(COUNTS),
        synthetic_findings=findings,
        new_accounts=0,
        prepared_fetches=0,
        new_market_calls=0,
        new_fits=0,
        new_labels=0,
        network_attempts=ATTEMPTS,
        limitations=[
            "Pure synthetic lifecycle oracle with controlled existing feature values; exact original feature AST, no repeated full real-price feature oracle.",
            "Fresh funded BASE must match EX044004 complete original economic/observed state fields before active2; local toy exactness is not funded control acceptance.",
            "A independently reconciles every actual policy ownrealfilled entry/exit/fees and strict sign; shadow100share source state cannot substitute account affordability audit.",
            "HistoricalA groups already weaken loss-persistence hypothesis; this PASS is technical/method gate, not signal or economic effectiveness.",
        ],
    )
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            dict(
                status=result["status"],
                checks=result["checks"],
                sha256=digest(destination),
                source_sha256=expected,
            )
        )
    )


if __name__ == "__main__":
    main()
