"""Synthetic-only complete observer/policy audit and parent-OFF equivalence."""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import sys
import types

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet

import audit_core as audit


def modules():
    root = Path(__file__).parent / "strategy_runtime"
    name = "episode_audit_synthetic_runtime"
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(root)]
    sys.modules[name] = pkg
    policy = importlib.import_module(name + ".strategies.policy_kernel")
    observer = importlib.import_module(name + ".strategies.pureobserver")
    adapter = importlib.import_module(name + ".strategies.episode_clock_range")
    parent = importlib.import_module(name + ".strategies.boundary_bear_recovery_range")
    return policy, observer, adapter, parent


def parameters():
    rule = {"range_window": 60, "entry": .6, "exit": .9, "max_hold": 4,
            "acf_min": .1, "stop_loss": None, "trailing_stop": None,
            "cooldown": 0, "momentum_min": None, "limit_premium": .01}
    return {
        "bull": dict(rule, max_hold=8, acf_min=None), "bear": rule,
        "regime_window": 20, "regime_threshold": 0.0, "exit_on_regime_change": True,
        "confirmation": {"enabled": True, "profile": "all", "threshold": -.2,
                         "orientation": 1, "scope": "both", "lookback": 120},
        "context": {"entry_gate": "all", "volume_basis": "ADJUSTED", "weighting": "EQUAL_BLOCKS"},
        "mechanism": "MARKET_EPISODE_TIME_ORIGINAL_BOUNDARY_RECOVERY", "episode_enabled": True,
    }


def fixture(n=16):
    axis = pd.bdate_range("2019-12-31", periods=n)
    close = pd.Series(np.full(n, 100.0), index=axis)
    momentum = pd.Series(np.full(n, -.01), index=axis)
    features = {
        route: pd.DataFrame({"range_position": .5, "acf1": .2,
                             "close": close, "momentum20": momentum}, index=axis)
        for route in ("bull", "bear")
    }
    base = {"features": features, "score": pd.Series(np.zeros(n), index=axis),
            "normalized": pd.DataFrame(np.zeros((n, 3)), index=axis, columns=["acf", "turnover", "volume"]),
            "signal_close": close, "signal_open": close - 1,
            "previous_close": close, "momentum": momentum, "previous_momentum": momentum,
            "regimes": np.full(n, "bear", dtype=object),
            "previous_regimes": np.full(n, "bear", dtype=object),
            "raw_bear_acf": features["bear"].acf1.copy()}
    return axis, base


def sub(base, axis):
    return {
        key: {r: f.loc[axis].copy() for r, f in value.items()}
        if key == "features" else value.loc[axis].copy()
        if isinstance(value, (pd.Series, pd.DataFrame)) else value[:len(axis)].copy()
        for key, value in base.items()
    }


def run():
    policy, primary_observer, adapter, parent = modules()
    checks, rejections, certificates = [], [], []
    p, (axis, base) = parameters(), fixture()

    def exercise(param, data, sessions=axis):
        table = policy.decisions(param, sessions, data)
        certificates.append(audit.verify(sessions, param, data, table))
        return table

    original = exercise(p, base)
    assert original.episode_age.iloc[:5].tolist() == [0, 1, 2, 3, 4]
    assert original.signal_reason.iloc[4] == "time"
    assert not original.episode_live.iloc[4] and original.episode_reason.iloc[5] == "start"
    assert original.signal_reason.iloc[5] == "entry"
    assert original.last_exit_category.iloc[5] == "EQUAL"
    checks.append("cold first FULL signal age0; inclusive H4 boundary; no end-day restart/reentry")
    delayed = copy.deepcopy(base)
    delayed["score"].iloc[:2] = -.5
    late = exercise(p, delayed)
    assert late.signal_reason.iloc[:5].tolist() == ["confirmation_rejected", "confirmation_rejected", "entry", "hold", "time"]
    pd.testing.assert_frame_equal(late[list(audit.OBSERVER_COLUMNS)], original[list(audit.OBSERVER_COLUMNS)])
    blocked = copy.deepcopy(base)
    blocked["features"]["bear"].acf1 = -.5
    blocked["raw_bear_acf"] = blocked["features"]["bear"].acf1.copy()
    bt = exercise(p, blocked)
    assert bt.target_position.eq(0).all()
    pd.testing.assert_frame_equal(bt[list(audit.OBSERVER_COLUMNS)], original[list(audit.OBSERVER_COLUMNS)])
    checks.append("observer unaffected by score/ACF acceptance; late actual entry uses remaining episode age")
    rp = copy.deepcopy(base)
    rp["features"]["bear"].loc[axis[4], "range_position"] = .9
    rt = exercise(p, rp)
    assert rt.episode_reason.iloc[4] == "range" and not rt.episode_expired.iloc[4]
    assert rt.signal_reason.iloc[4] == "range"
    switches = copy.deepcopy(base)
    switches["regimes"][1:] = "bull"
    switches["previous_regimes"][2:] = "bull"
    st = exercise(p, switches)
    assert st.episode_reason.iloc[1] == "regime" and not st.episode_live.iloc[1]
    assert st.episode_route.iloc[1] == "bear" and st.episode_route.iloc[2] == "bull"
    kept_p = copy.deepcopy(p)
    kept_p["exit_on_regime_change"] = False
    kept = exercise(kept_p, switches)
    assert kept.episode_route.iloc[:5].eq("bear").all()
    assert kept.episode_reason.iloc[1] == "hold" and kept.episode_reason.iloc[4] == "time"
    checks.append("range>TIME>regime priority; route lock; raw switch end has no same-day restart")
    tied = copy.deepcopy(base)
    tied["regimes"][4:] = "bull"
    tied["previous_regimes"][5:] = "bull"
    tt = exercise(p, tied)
    assert tt.episode_reason.iloc[4] == "time" and tt.signal_reason.iloc[4] == "time"
    risk_p = copy.deepcopy(p)
    risk_p["bear"]["stop_loss"] = .01
    drops = copy.deepcopy(base)
    for r in ("bull", "bear"):
        drops["features"][r].loc[axis[1], "close"] = 98
    drops["signal_close"].loc[axis[1]] = 98
    drops["signal_open"].loc[axis[1]] = 97
    risk = exercise(risk_p, drops)
    assert risk.signal_reason.iloc[1] == "loss" and risk.episode_live.iloc[1]
    assert risk.signal_reason.iloc[2] == "entry" and risk.episode_id.iloc[2] == risk.episode_id.iloc[0]
    assert risk.signal_reason.iloc[4] == "time"
    trail_p = copy.deepcopy(p)
    trail_p["bear"]["trailing_stop"] = .01
    trail = exercise(trail_p, drops)
    assert trail.signal_reason.iloc[1] == "trailing"
    checks.append("risk/trailing original priorities; multiple trades same observer episode allowed")
    below = copy.deepcopy(base)
    for r in ("bull", "bear"):
        below["features"][r].loc[axis[4], "close"] = 99
        below["features"][r].loc[axis[5], "acf1"] = -.4
    below["signal_close"].loc[axis[4]] = 99
    below["signal_open"].loc[axis[4]] = 98
    below["raw_bear_acf"] = below["features"]["bear"].acf1.copy()
    br = exercise(p, below)
    assert br.last_exit_category.iloc[5] == "BELOW"
    assert br.entry_acf_recovery_applies.iloc[5] and br.signal_reason.iloc[5] == "entry"
    above = copy.deepcopy(base)
    for r in ("bull", "bear"):
        above["features"][r].loc[axis[4], "close"] = 101
    above["signal_close"].loc[axis[4]] = 101
    above["signal_open"].loc[axis[4]] = 100
    ar = exercise(p, above)
    assert ar.last_exit_category.iloc[5] == "ABOVE"
    bodyno = copy.deepcopy(switches)
    bodyno["signal_open"].loc[axis[2]] = 101
    bodyno["previous_regimes"][2] = "bear"
    body = exercise(p, bodyno)
    assert body.signal_reason.iloc[2] == "entry_direction_rejected"
    checks.append("BELOW TIME category/recovery and raw-bull boundary BODY unchanged")
    guard_p = copy.deepcopy(p)
    guard_p["bear"]["momentum_min"] = .05
    guard = exercise(guard_p, base)
    assert guard.episode_reason.eq("flat").all()
    equality = copy.deepcopy(base)
    equality["features"]["bear"].range_position = .6
    equality["features"]["bear"].momentum20 = .05
    equality["features"]["bear"].acf1 = .1
    eq = exercise(guard_p, equality)
    assert eq.episode_reason.iloc[0] == "start" and eq.signal_reason.iloc[0] == "entry"
    checks.append("original range/momentum/ACF equality semantics; no short/missing-history fallback")
    for n in (1, 4, 5, 9, len(axis)):
        a = axis[:n]
        prefix = exercise(p, sub(base, a), a)
        pd.testing.assert_frame_equal(prefix, original.iloc[:n])
    future = copy.deepcopy(base)
    future["score"].iloc[9:] = -.5
    future["features"]["bear"].iloc[9:, 0] = .95
    future_table = exercise(p, future)
    pd.testing.assert_frame_equal(future_table.iloc[:9], original.iloc[:9])
    assert original.episode_age.iloc[1] == 1 and axis[0].year != axis[1].year
    checks.append("prefix/future invariance and annual transition without resetting observer")

    # Adapter-OFF compared to exact frozen parent on artificial OHLC only.
    rng = np.random.default_rng(73)
    daily_axis = pd.bdate_range("2018-01-02", periods=420)
    prices = 100 * np.exp(np.cumsum(rng.normal(.0002, .008, len(daily_axis))))
    openings = prices * np.exp(rng.normal(0, .003, len(prices)))
    volumes = 1e6 * np.exp(rng.normal(0, .1, len(prices)))
    daily = pd.DataFrame({"Date": daily_axis, "Open": openings, "Close": prices,
                          "High": np.maximum(openings, prices)*1.02,
                          "Low": np.minimum(openings, prices)*.98,
                          "Volume": volumes, "Amount": volumes*prices})
    sessions = daily_axis[220:]
    native_inputs = {"daily": daily}
    off_p = copy.deepcopy(p)
    off_p["episode_enabled"] = False
    parent_p = {k: v for k, v in off_p.items() if k != "episode_enabled"}
    parent_p["mechanism"] = "RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY"
    old = parent.BoundaryBearRecoveryRange(ParameterSet(parent_p)).calculate_history(native_inputs, sessions)
    off = adapter.EpisodeClockRange(ParameterSet(off_p)).calculate_history(native_inputs, sessions)
    pd.testing.assert_frame_equal(off, old, check_exact=True)
    off_base = policy.prepare(p, native_inputs, sessions)
    certificates.append(audit.verify(sessions, off_p, off_base, off))
    on = adapter.EpisodeClockRange(ParameterSet(p)).calculate_history(native_inputs, sessions)
    certificates.append(audit.verify(sessions, p, off_base, on))
    checks.append("enabledFalse exact full parent table; ON/native adapter synthetic independently audited")
    mutations = []
    bad = copy.deepcopy(base)
    bad["features"]["bear"].loc[axis[0], "close"] = 0
    mutations.append(("zero_feature_close", p, axis, bad))
    bad = copy.deepcopy(base)
    bad["score"].iloc[0] = np.nan
    mutations.append(("missing_score", p, axis, bad))
    bad = copy.deepcopy(base)
    bad["signal_open"].iloc[0] = 0
    mutations.append(("zero_signal_open", p, axis, bad))
    bad = copy.deepcopy(base)
    bad["regimes"][0] = "unknown"
    mutations.append(("illegal_rawroute", p, axis, bad))
    bad = copy.deepcopy(base)
    bad["previous_regimes"] = bad["previous_regimes"][:-1]
    mutations.append(("missing_previous_rawroute", p, axis, bad))
    bad = copy.deepcopy(base)
    bad["features"]["bear"] = bad["features"]["bear"].iloc[1:]
    mutations.append(("feature_missing_date", p, axis, bad))
    for name, value in (("H_noninteger", 4.0), ("H_zero", 0), ("H_over60", 61)):
        bad_p = copy.deepcopy(p)
        bad_p["bear"]["max_hold"] = value
        mutations.append((name, bad_p, axis, base))
    bad_p = copy.deepcopy(p)
    bad_p["bear"]["entry"] = .95
    mutations.append(("threshold_order", bad_p, axis, base))
    bad_p = copy.deepcopy(p)
    bad_p["exit_on_regime_change"] = None
    mutations.append(("nonbool_exitflag", bad_p, axis, base))
    for name, a in (("axis_duplicate", axis.insert(1, axis[0])),
                    ("axis_unordered", axis[::-1]), ("axis_timezone", axis.tz_localize("Asia/Shanghai")),
                    ("axis_notmidnight", axis + pd.Timedelta(hours=1))):
        mutations.append((name, p, a, base))
    for name, param, a, b in mutations:
        try:
            audit.reconstruct(a, param, b)
        except ValueError:
            rejections.append(name)
        else:
            raise AssertionError("not rejected: " + name)
    for name, column in (("false_time", "signal_reason"), ("false_observer_age", "episode_age"),
                          ("false_target", "target_position"), ("false_last_category", "last_exit_category")):
        corrupted = original.copy()
        corrupted.loc[axis[4], column] = "hold" if column == "signal_reason" else "BELOW" if column == "last_exit_category" else 999
        try:
            audit.verify(axis, p, base, corrupted)
        except ValueError:
            rejections.append(name)
        else:
            raise AssertionError("corrupted policy not rejected: " + name)
    checks.append("invalid inputs/parameters and corrupted complete-state decisions rejected")
    # Primary observer itself is checked independently on the full fake input.
    obs = primary_observer.observe(p, base["features"], base["regimes"], axis)
    audit.compare_columns(obs, audit.observer(p, base["features"], base["regimes"], axis), audit.OBSERVER_COLUMNS)
    checks.append("scalar observer independently matches primary eight fields")
    return {"status": "PASS", "synthetic_only": True, "real_inputs_read": 0,
            "new_statistics": 0, "accounts": 0, "experiments_allocated": 0,
            "checks": checks, "rejections": rejections, "certificates": certificates,
            "prefix_storage_scope": "Primary prefix/future checks include storage dtype. Initial audit found age/id dtype depended on future flat rows; primary fixed explicit observer storage types before this final test, without state-rule changes. OFF-parent exact comparison includes dtype.",
            "check_count": len(checks), "rejection_count": len(rejections)}


if __name__ == "__main__":
    result = run()
    Path(__file__).with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "check_count", "rejection_count")}, ensure_ascii=False))
