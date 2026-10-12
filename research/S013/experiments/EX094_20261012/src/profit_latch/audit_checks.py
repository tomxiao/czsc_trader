"""Synthetic-only independent sigma/latch policy checks; no real-market reads."""

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
    name = "profit_audit_synthetic_runtime"
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(Path(__file__).parent / "strategy_runtime")]
    sys.modules[name] = pkg
    return tuple(importlib.import_module(name + ".strategies." + suffix) for suffix in (
        "policy_kernel", "locked_sigma", "profit_latch_range", "boundary_bear_recovery_range"
    ))


def parameters():
    rule = {"range_window": 60, "entry": .6, "exit": .9, "max_hold": 60,
            "acf_min": .1, "stop_loss": None, "trailing_stop": None,
            "cooldown": 0, "momentum_min": None, "limit_premium": .01}
    return {"bull": dict(rule, acf_min=None), "bear": rule,
            "regime_window": 20, "regime_threshold": 0.0, "exit_on_regime_change": True,
            "confirmation": {"enabled": True, "profile": "all", "threshold": -.2,
                             "orientation": 1, "scope": "both", "lookback": 120},
            "context": {"entry_gate": "all", "volume_basis": "ADJUSTED", "weighting": "EQUAL_BLOCKS"},
            "mechanism": "PROFIT_LATCH_SIGNAL_ANCHOR_ORIGINAL_BOUNDARY_RECOVERY",
            "profit_latch": {"enabled": True, "volatility_window": 20, "activation_multiple": 1.0}}


def fixture(close=(100, 102, 101, 100, 101, 102, 103, 104), sigma=None):
    axis = pd.bdate_range("2019-12-31", periods=len(close))
    close = pd.Series(close, index=axis, dtype=float)
    n = len(axis)
    momentum = pd.Series(np.full(n, -.01), index=axis)
    frames = {r: pd.DataFrame({"range_position": .5, "acf1": .2, "close": close,
                              "momentum20": momentum}, index=axis) for r in ("bull", "bear")}
    return axis, {
        "features": frames, "score": pd.Series(np.zeros(n), index=axis),
        "normalized": pd.DataFrame(np.zeros((n, 3)), index=axis, columns=["acf", "turnover", "volume"]),
        "signal_close": close, "signal_open": close-1, "previous_close": close,
        "momentum": momentum, "previous_momentum": momentum,
        "regimes": np.full(n, "bear", dtype=object), "previous_regimes": np.full(n, "bear", dtype=object),
        "raw_bear_acf": frames["bear"].acf1.copy(),
        "sigma_knowncurrent": pd.Series(np.full(n, .01) if sigma is None else sigma, index=axis),
    }


def sub(base, axis):
    return {k: {r: f.loc[axis].copy() for r, f in v.items()} if k == "features"
            else v.loc[axis].copy() if isinstance(v, (pd.Series, pd.DataFrame)) else v[:len(axis)].copy()
            for k, v in base.items()}


def run():
    policy, sigma_module, adapter, parent = modules()
    p = parameters()
    checks, refused, certs = [], [], []

    def exercise(sessions, data, params=p):
        table = policy.decisions(params, sessions, data)
        certs.append(audit.verify(sessions, params, data, table))
        return table

    axis, base = fixture()
    table = exercise(axis, base)
    assert not table.profit_latch_after.iloc[0]
    assert table.profit_latch_activated.iloc[1]
    assert table.profit_latch_after.iloc[2]
    assert table.signal_reason.iloc[3] == "profit_floor" and table.profit_floor_triggered.iloc[3]
    assert table.target_position.iloc[3] == 0 and table.signal_reason.iloc[4] == "entry"
    assert table.last_exit_reason.iloc[4] == "profit_floor" and pd.isna(table.last_exit_category.iloc[4])
    assert pd.isna(table.profit_sigma_after.iloc[3]) and not table.profit_latch_after.iloc[3]
    checks.append("accepted entry locks sigma without activation; one-way gain latch then inclusive anchor floor; no same-T reentry")
    la, lb = fixture((100, 100.5, 101.1, 100, 101), (.01, .001, .03, .03, .1))
    locked = exercise(la, lb)
    assert not locked.profit_latch_activated.iloc[1] and locked.profit_latch_activated.iloc[2]
    assert locked.profit_sigma_before.iloc[2] == .01
    assert locked.signal_reason.iloc[3] == "profit_floor"
    delayed = copy.deepcopy(lb)
    delayed["score"].iloc[0] = -.5
    dt = exercise(la, delayed)
    assert dt.signal_reason.iloc[0] == "confirmation_rejected"
    assert dt.profit_sigma_after.iloc[1] == .001
    checks.append("sigma frozen at actual accepted signal; rejection does not lock; current rolling sigma cannot move activation")
    for values, label in (((100, 100, 100, 100), "equal"), ((100, 99, 99, 99), "negative")):
        za, zb = fixture(values, np.zeros(len(values)))
        z = exercise(za, zb)
        assert not z.profit_latch_activated.any()
        assert not z.profit_floor_triggered.any()
        assert z.profit_sigma_after.notna().all() and z.profit_sigma_after.eq(0).all()
        checks.append("zero sigma strict positive excursion excludes " + label)
    za, zb = fixture((100, 101, 100, 100), np.zeros(4))
    z = exercise(za, zb)
    assert z.profit_latch_activated.iloc[1] and z.signal_reason.iloc[2] == "profit_floor"
    checks.append("zero sigma retained and positive excursion activates without epsilon")
    ea, eb = fixture((100, 110, 100, 101), (.01, .01, .01, .01))
    # Exact comparison threshold is known log(110/100), not a rounded percentage.
    eb["sigma_knowncurrent"].iloc[0] = float(np.log(1.1))
    equality = exercise(ea, eb)
    assert equality.profit_latch_activated.iloc[1]
    checks.append("activation equality included while zero profit excluded")
    for reason in ("range", "time", "regime", "trailing", "loss"):
        params, data = copy.deepcopy(p), copy.deepcopy(base)
        if reason == "range":
            data["features"]["bear"].loc[axis[3], "range_position"] = .9
        elif reason == "time":
            params["bear"]["max_hold"] = 3
        elif reason == "regime":
            data["regimes"][3:] = "bull"
            data["previous_regimes"][4:] = "bull"
        elif reason == "trailing":
            params["bear"]["trailing_stop"] = .015
        else:
            params["bear"]["stop_loss"] = .005
            data["features"]["bear"].loc[axis[3], "close"] = 99
            data["signal_close"].loc[axis[3]] = 99
        t = exercise(axis, data, params)
        assert t.signal_reason.iloc[3] == reason and not t.profit_floor_triggered.iloc[3]
    exits_early = copy.deepcopy(base)
    exits_early["features"]["bear"].loc[axis[1], "range_position"] = .95
    early = exercise(axis, exits_early)
    assert early.signal_reason.iloc[1] == "range" and not early.profit_latch_activated.iloc[1]
    checks.append("all original exit reasons/categories outrank floor; exiting gain day cannot activate")
    recovery_p = copy.deepcopy(p)
    recovery_p["bear"]["max_hold"] = 3
    recovery_axis, recovery = fixture((100, 102, 101, 99, 100, 101))
    recovery["features"]["bear"].loc[recovery_axis[4], "acf1"] = -.4
    recovery["raw_bear_acf"] = recovery["features"]["bear"].acf1.copy()
    recovered = exercise(recovery_axis, recovery, recovery_p)
    assert recovered.signal_reason.iloc[3] == "time"
    assert recovered.last_exit_category.iloc[4] == "BELOW"
    assert recovered.entry_acf_recovery_applies.iloc[4] and recovered.signal_reason.iloc[4] == "entry"
    floor_no_recovery = copy.deepcopy(base)
    floor_no_recovery["features"]["bear"].loc[axis[4], "acf1"] = -.4
    floor_no_recovery["raw_bear_acf"] = floor_no_recovery["features"]["bear"].acf1.copy()
    denied = exercise(axis, floor_no_recovery)
    assert denied.last_exit_reason.iloc[4] == "profit_floor" and pd.isna(denied.last_exit_category.iloc[4])
    assert not denied.entry_acf_recovery_applies.iloc[4] and denied.target_position.iloc[4] == 0
    checks.append("original TIME-BELOW recovery survives; profit floor cannot impersonate TIME recovery category")
    pp = copy.deepcopy(p)
    pp["exit_on_regime_change"] = False
    cross = copy.deepcopy(base)
    cross["regimes"][2:] = "bull"
    cross["previous_regimes"][3:] = "bull"
    ct = exercise(axis, cross, pp)
    assert ct.profit_latch_before.iloc[3] and ct.signal_reason.iloc[3] == "profit_floor"
    checks.append("raw regime flip without real policy exit preserves locked sigma/anchor/latch")
    for n in (1, 2, 3, 4, len(axis)):
        pre = exercise(axis[:n], sub(base, axis[:n]))
        pd.testing.assert_frame_equal(pre, table.iloc[:n])
    future = copy.deepcopy(base)
    future["sigma_knowncurrent"].iloc[4:] = .5
    future["score"].iloc[4:] = -.5
    ft = exercise(axis, future)
    pd.testing.assert_frame_equal(ft.iloc[:4], table.iloc[:4])
    assert axis[0].year != axis[1].year and table.profit_anchor_before.iloc[1] == 100
    checks.append("complete prefix and future invariance; no year-end state reset")
    malformed = copy.deepcopy(base)
    malformed["regimes"][0] = "unknown"
    try:
        audit.reconstruct(axis, p, malformed)
    except ValueError:
        refused.append("illegal_raw_route")
    else:
        raise AssertionError("illegal route accepted")

    rng = np.random.default_rng(79)
    dates = pd.bdate_range("2018-01-02", periods=420)
    close = pd.Series(100*np.exp(np.cumsum(rng.normal(.0002, .008, len(dates)))), index=dates)
    sessions = dates[220:]
    sigma = sigma_module.sigma_known(close, sessions, 20)
    sigma_cert = audit.verify_sigma(close, sessions, 20, sigma)
    opening = close.to_numpy()*np.exp(rng.normal(0, .003, len(dates)))
    volume = 1e6*np.exp(rng.normal(0, .1, len(dates)))
    daily = pd.DataFrame({"Date": dates, "Open": opening, "Close": close.to_numpy(),
                          "High": np.maximum(opening, close.to_numpy())*1.02,
                          "Low": np.minimum(opening, close.to_numpy())*.98,
                          "Volume": volume, "Amount": volume*close.to_numpy()})
    native = {"daily": daily}
    off_p = copy.deepcopy(p)
    off_p["profit_latch"]["enabled"] = False
    parent_p = {k: v for k, v in off_p.items() if k != "profit_latch"}
    parent_p["mechanism"] = "RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY"
    old = parent.BoundaryBearRecoveryRange(ParameterSet(parent_p)).calculate_history(native, sessions)
    off = adapter.ProfitLatchRange(ParameterSet(off_p)).calculate_history(native, sessions)
    pd.testing.assert_frame_equal(off, old, check_exact=True)
    nb = policy.prepare(p, native, sessions)
    certs.append(audit.verify(sessions, off_p, nb, off))
    on = adapter.ProfitLatchRange(ParameterSet(p)).calculate_history(native, sessions)
    certs.append(audit.verify(sessions, p, nb, on))
    checks.append("parent OFF full exact including dtype; ON adapter and scalar sigma independently audited")
    sigma_results = [sigma_cert]
    for length in (10, 20, 60):
        for prices in (close, close*.2803, pd.Series(np.full(len(dates), 100.), index=dates)):
            reported = sigma_module.sigma_known(prices, sessions, length)
            sigma_results.append(audit.verify_sigma(prices, sessions, length, reported))
            short_sessions = sessions[:10]
            prefix = sigma_module.sigma_known(prices.iloc[:dates.get_loc(short_sessions[-1])+1], short_sessions, length)
            pd.testing.assert_series_equal(prefix, reported.iloc[:10])
    checks.append("sigma L endpoints/zero/scale/prefix and current-T L-change windows")
    mutations = []
    for name, field, value in (("sigma_negative", "sigma_knowncurrent", -.01),
                               ("sigma_unknown", "sigma_knowncurrent", np.nan),
                               ("price_zero", "signal_close", 0), ("score_nan", "score", np.nan)):
        bad = copy.deepcopy(base)
        bad[field].iloc[0] = value
        mutations.append((name, p, axis, bad))
    for name, key, value in (("L_float", "volatility_window", 20.), ("L_short", "volatility_window", 9),
                             ("L_long", "volatility_window", 61), ("multiple_low", "activation_multiple", .49),
                             ("multiple_high", "activation_multiple", 3.01),
                             ("multiple_integer", "activation_multiple", 1), ("enabled_nonbool", "enabled", 1)):
        bad_p = copy.deepcopy(p)
        bad_p["profit_latch"][key] = value
        mutations.append((name, bad_p, axis, base))
    for name, a in (("axis_duplicate", axis.insert(1, axis[0])), ("axis_unsorted", axis[::-1]),
                    ("axis_timezone", axis.tz_localize("Asia/Shanghai")), ("axis_intraday", axis+pd.Timedelta(hours=1))):
        mutations.append((name, p, a, base))
    for name, param, a, b in mutations:
        try:
            audit.reconstruct(a, param, b)
        except ValueError:
            refused.append(name)
        else:
            raise AssertionError("not rejected " + name)
    for column in ("target_position", "signal_reason", "profit_latch_before", "profit_latch_after",
                   "profit_sigma_before", "profit_anchor_before", "profit_latch_activated", "profit_floor_triggered"):
        bad = table.copy()
        replacement = "hold" if column == "signal_reason" else not bool(bad.loc[axis[3], column]) if pd.api.types.is_bool_dtype(bad[column].dtype) else 999
        bad.loc[axis[3], column] = replacement
        try:
            audit.verify(axis, p, base, bad)
        except ValueError:
            refused.append("fraud_" + column)
        else:
            raise AssertionError("reported fraud accepted " + column)
    for name, prices, a, length, reported in (
        ("sigma_insufficient", close.iloc[:21], dates[:21], 20, pd.Series(np.zeros(21), index=dates[:21])),
        ("sigma_gap", close, sessions.delete(3), 20, sigma.drop(index=sessions[3])),
        ("sigma_unordered_prices", close.iloc[::-1], sessions, 20, sigma),
        ("sigma_wrong_values", close, sessions, 20, sigma+.001),
        ("sigma_zero_close", close.mask(close.index == dates[221], 0), sessions, 20, sigma),
    ):
        try:
            audit.verify_sigma(prices, a, length, reported)
        except ValueError:
            refused.append(name)
        else:
            raise AssertionError("sigma input not rejected " + name)
    checks.append("known sigma/parameter/axis/report corruption and volatility windows rejected")
    return {"status": "PASS", "synthetic_only": True, "real_inputs_read": 0,
            "accounts": 0, "experiments_allocated": 0, "new_statistics": 0,
            "checks": checks, "rejections": refused, "certificates": certs,
            "scalar_sigma_certificates": sigma_results,
            "check_count": len(checks), "rejection_count": len(refused)}


if __name__ == "__main__":
    result = run()
    Path(__file__).with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "check_count", "rejection_count")}, ensure_ascii=False))
