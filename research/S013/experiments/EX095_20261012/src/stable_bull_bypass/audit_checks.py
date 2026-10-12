"""Synthetic whole-policy, truth-table, and parent-OFF equivalence checks."""

from __future__ import annotations

import copy
import importlib
import itertools
import json
from pathlib import Path
import sys
import types

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet

import audit_core as audit


def modules():
    name = "bypass_audit_synthetic_runtime"
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(Path(__file__).parent / "strategy_runtime")]
    sys.modules[name] = pkg
    return tuple(importlib.import_module(name + ".strategies." + suffix) for suffix in (
        "policy_kernel", "stable_bull_bypass_range", "boundary_bear_recovery_range"
    ))


def parameters():
    rule = {"range_window": 60, "entry": .6, "exit": .9, "max_hold": 4,
            "acf_min": .1, "stop_loss": None, "trailing_stop": None,
            "cooldown": 0, "momentum_min": None, "limit_premium": .01}
    return {"bull": dict(rule, max_hold=8, acf_min=None), "bear": rule,
            "regime_window": 20, "regime_threshold": 0.0, "exit_on_regime_change": True,
            "confirmation": {"enabled": True, "profile": "all", "threshold": -.2,
                             "orientation": 1, "scope": "both", "lookback": 120},
            "context": {"entry_gate": "all", "volume_basis": "ADJUSTED", "weighting": "EQUAL_BLOCKS"},
            "mechanism": "STABLE_RAW_BULL_BODY_CONFIRMATION_BYPASS", "bypass_enabled": True}


def fixture(n=16, route="bull", previous="bull", body=1., score=-.5, eligible=True):
    axis = pd.bdate_range("2019-12-31", periods=n)
    close = pd.Series(np.full(n, 100.), index=axis)
    momentum = pd.Series(np.full(n, .01 if route == "bull" else -.01), index=axis)
    frames = {r: pd.DataFrame({"range_position": .5 if eligible else .7, "acf1": .2,
                              "close": close, "momentum20": momentum}, index=axis)
              for r in ("bull", "bear")}
    return axis, {
        "features": frames, "score": pd.Series(np.full(n, score), index=axis),
        "normalized": pd.DataFrame(np.zeros((n, 3)), index=axis, columns=["acf", "turnover", "volume"]),
        "signal_close": close, "signal_open": close-body, "previous_close": close,
        "momentum": momentum, "previous_momentum": momentum,
        "regimes": np.full(n, route, dtype=object), "previous_regimes": np.full(n, previous, dtype=object),
        "raw_bear_acf": frames["bear"].acf1.copy(),
    }


def sub(base, axis):
    return {k: {r: f.loc[axis].copy() for r, f in v.items()} if k == "features"
            else v.loc[axis].copy() if isinstance(v, (pd.Series, pd.DataFrame)) else v[:len(axis)].copy()
            for k, v in base.items()}


def run():
    primary, adapter, parent = modules()
    p = parameters()
    checks, refused, certs, truth = [], [], [], []

    def exercise(axis, base, parameters=p):
        table = primary.decisions(parameters, axis, base)
        certs.append(audit.verify(axis, parameters, base, table))
        return table

    for raw, prev, body, eligible, oldpass in itertools.product(
        ("bull", "bear"), ("bull", "bear"), (-1., 0., 1.), (False, True), (False, True)
    ):
        axis, data = fixture(1, raw, prev, body, -.2 if oldpass else -.5, eligible)
        table = exercise(axis, data)
        scope = raw == "bull" and prev == "bull" and body > 0
        expect_entry = eligible and (oldpass or scope) and not (raw == "bull" and prev == "bear" and body <= 0)
        row = table.iloc[0]
        assert bool(row.bypass_applies) == scope
        assert bool(row.effective_confirmation_pass) == (oldpass or scope)
        assert bool(row.confirmation_pass) == oldpass
        assert row.target_position == int(expect_entry)
        assert bool(row.actually_bypassed) == (expect_entry and scope and not oldpass)
        truth.append({"raw": raw, "previous": prev, "body": body, "eligible": eligible,
                      "oldpass": oldpass, "scope": scope, "entry": expect_entry})
    checks.append("48 complete scope/eligibility/old-score truth cells; strict positive body and score equality")
    assert len(truth) == 48
    for route, prev, body in (("bear", "bear", 1.), ("bull", "bear", 1.),
                              ("bull", "bull", -1.), ("bull", "bull", 0.)):
        a, b = fixture(3, route, prev, body, -.5)
        t = exercise(a, b)
        assert t.target_position.eq(0).all()
    checks.append("not full confirmation-OFF or all-bull-OFF; bear/transitions/nonpositive-body retain score")
    axis, base = fixture()
    original = exercise(axis, base)
    assert original.signal_reason.iloc[0] == "entry"
    assert original.signal_reason.iloc[8] == "time" and not original.actually_bypassed.iloc[8]
    assert original.signal_reason.iloc[9] == "entry"
    for reason in ("loss", "trailing", "range", "time", "regime"):
        param, data = copy.deepcopy(p), copy.deepcopy(base)
        if reason == "loss":
            param["bull"]["stop_loss"] = .01
            data["features"]["bull"].loc[axis[1], "close"] = 98
        elif reason == "trailing":
            param["bull"]["trailing_stop"] = .01
            data["features"]["bull"].loc[axis[1], "close"] = 98
        elif reason == "range":
            data["features"]["bull"].loc[axis[1], "range_position"] = .9
        elif reason == "time":
            param["bull"]["max_hold"] = 1
        else:
            data["regimes"][1:] = "bear"
            data["previous_regimes"][2:] = "bear"
        t = exercise(axis, data, param)
        assert t.signal_reason.iloc[1] == reason and not t.actually_bypassed.iloc[1]
        assert t.target_position.iloc[1] == 0
    overlap = copy.deepcopy(base)
    overlap["features"]["bull"].loc[axis[1], "range_position"] = .9
    hp = copy.deepcopy(p)
    hp["bull"]["max_hold"] = 1
    ot = exercise(axis, overlap, hp)
    assert ot.signal_reason.iloc[1] == "range"
    checks.append("held original five-exit priorities; TIME no same-day bypass entry; range outranks TIME")
    for category, final_close in (("BELOW", 99.), ("EQUAL", 100.), ("ABOVE", 101.)):
        a, b = fixture(7, "bear", "bear", 1., 0.)
        for r in ("bull", "bear"):
            b["features"][r].loc[a[4], "close"] = final_close
        b["signal_close"].loc[a[4]] = final_close
        b["signal_open"].loc[a[4]] = final_close-1
        b["features"]["bear"].loc[a[5], "acf1"] = -.4
        b["raw_bear_acf"] = b["features"]["bear"].acf1.copy()
        t = exercise(a, b)
        assert t.last_exit_category.iloc[5] == category
        assert bool(t.entry_acf_recovery_applies.iloc[5]) == (category == "BELOW")
        assert (t.signal_reason.iloc[5] == "entry") == (category == "BELOW")
        assert not t.bypass_applies.any()
    checks.append("original TIME-BELOW/ABOVE/EQUAL contexts unchanged; bear recovery still needs original confirmation")
    for n in (1, 2, 8, 9, len(axis)):
        pre = exercise(axis[:n], sub(base, axis[:n]))
        pd.testing.assert_frame_equal(pre, original.iloc[:n])
    changed = copy.deepcopy(base)
    changed["score"].iloc[10:] = .2
    changed["features"]["bull"].iloc[10:, 0] = .95
    future = exercise(axis, changed)
    pd.testing.assert_frame_equal(future.iloc[:10], original.iloc[:10])
    assert axis[0].year != axis[1].year and original.signal_reason.iloc[1] == "hold"
    checks.append("cold first signal, business/dtype prefix and future invariance, no annual reset or final-year input")
    # Whole original native adapter comparison uses artificial OHLC only.
    rng = np.random.default_rng(83)
    dates = pd.bdate_range("2018-01-02", periods=420)
    close = 100*np.exp(np.cumsum(rng.normal(.0002, .008, len(dates))))
    opening = close*np.exp(rng.normal(0, .003, len(dates)))
    volume = 1e6*np.exp(rng.normal(0, .1, len(dates)))
    daily = pd.DataFrame({"Date": dates, "Open": opening, "Close": close,
                          "High": np.maximum(opening, close)*1.02, "Low": np.minimum(opening, close)*.98,
                          "Volume": volume, "Amount": volume*close})
    sessions, native = dates[220:], {"daily": daily}
    off_p = copy.deepcopy(p)
    off_p["bypass_enabled"] = False
    parent_p = {k: v for k, v in off_p.items() if k != "bypass_enabled"}
    parent_p["mechanism"] = "RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY"
    old = parent.BoundaryBearRecoveryRange(ParameterSet(parent_p)).calculate_history(native, sessions)
    off = adapter.StableBullBypassRange(ParameterSet(off_p)).calculate_history(native, sessions)
    pd.testing.assert_frame_equal(off, old, check_exact=True)
    prepared = primary.prepare(p, native, sessions)
    certs.append(audit.verify(sessions, off_p, prepared, off))
    on = adapter.StableBullBypassRange(ParameterSet(p)).calculate_history(native, sessions)
    certs.append(audit.verify(sessions, p, prepared, on))
    checks.append("enabledFalse full parent exact including dtype; ON native adapter synthetic full independent audit")
    for name, field, value in (("missing_score", "score", np.nan), ("zero_open", "signal_open", 0),
                               ("nonfinite_momentum", "momentum", np.inf)):
        data = copy.deepcopy(base)
        data[field].iloc[0] = value
        try:
            audit.reconstruct(axis, p, data)
        except ValueError:
            refused.append(name)
        else:
            raise AssertionError("invalid input accepted " + name)
    bads = []
    bad = copy.deepcopy(base)
    bad["regimes"][0] = "positive_year"
    bads.append(("oracle_rawroute", p, axis, bad))
    bad = copy.deepcopy(base)
    bad["future_year_profit"] = np.ones(len(axis))
    bads.append(("extra_future_year_field", p, axis, bad))
    bad = copy.deepcopy(base)
    bad["features"]["bull"] = bad["features"]["bull"].iloc[1:]
    bads.append(("incomplete_feature_axis", p, axis, bad))
    for name, flag in (("switch_integer", 1), ("switch_missing", None)):
        param = copy.deepcopy(p)
        param["bypass_enabled"] = flag
        bads.append((name, param, axis, base))
    bad_p = copy.deepcopy(p)
    bad_p["bull"]["max_hold"] = 8.
    bads.append(("H_noninteger", bad_p, axis, base))
    for name, a in (("duplicate_axis", axis.insert(1, axis[0])), ("unordered_axis", axis[::-1]),
                    ("timezone_axis", axis.tz_localize("Asia/Shanghai")), ("intraday_axis", axis+pd.Timedelta(hours=1))):
        bads.append((name, p, a, base))
    for name, param, a, b in bads:
        try:
            audit.reconstruct(a, param, b)
        except ValueError:
            refused.append(name)
        else:
            raise AssertionError("not rejected " + name)
    for column in ("target_position", "signal_reason", "bypass_applies", "effective_confirmation_pass",
                   "actually_bypassed", "last_exit_category"):
        bad = original.copy()
        value = "BELOW" if column == "last_exit_category" else "entry" if column == "signal_reason" else not bool(bad.loc[axis[8], column]) if pd.api.types.is_bool_dtype(bad[column].dtype) else 999
        bad.loc[axis[8], column] = value
        try:
            audit.verify(axis, p, base, bad)
        except ValueError:
            refused.append("fraud_"+column)
        else:
            raise AssertionError("reported mutation accepted " + column)
    checks.append("NA/type/axis/oracle-field and complete decision/diagnostic corruption refused")
    return {"status": "PASS", "synthetic_only": True, "real_inputs_read": 0,
            "accounts": 0, "new_statistics": 0, "experiments_allocated": 0,
            "checks": checks, "rejections": refused, "certificates": certs, "truth_table": truth,
            "check_count": len(checks), "rejection_count": len(refused)}


if __name__ == "__main__":
    result = run()
    Path(__file__).with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "check_count", "rejection_count")}, ensure_ascii=False))
