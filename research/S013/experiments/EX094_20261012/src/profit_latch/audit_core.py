"""Independent scalar signal-profit latch and sigma audit; no market I/O."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _axis(index):
    if (
        not isinstance(index, pd.DatetimeIndex) or len(index) == 0
        or index.tz is not None or index.hasnans or index.has_duplicates
        or not index.is_monotonic_increasing or not index.equals(index.normalize())
    ):
        raise ValueError("finite unique ordered naive midnight dates required")


def verify_sigma(close_full, sessions, length, reported_sigma):
    """Rebuild exact L past daily log changes including T using scalar math.

    Each signal requires the real preceding Close at T-L. No zero-volatility
    exclusion, shortened window, annual reset, epsilon or replacement is used.
    """
    _axis(sessions)
    if not isinstance(close_full, pd.Series) or not isinstance(reported_sigma, pd.Series):
        raise ValueError("explicit close and reported sigma Series required")
    _axis(close_full.index)
    if type(length) is not int or not 10 <= length <= 60:
        raise ValueError("integer volatility length10..60 required")
    if not reported_sigma.index.equals(sessions):
        raise ValueError("reported sigma must exactly align signal dates")
    mapping = {day: i for i, day in enumerate(close_full.index)}
    if any(day not in mapping for day in sessions):
        raise ValueError("signal day absent from declared complete close axis")
    positions = [mapping[day] for day in sessions]
    if any(b != a + 1 for a, b in zip(positions, positions[1:])):
        raise ValueError("signal axis must traverse contiguous trading observations")
    logs = []
    for value in close_full:
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("finite positive full daily Close required")
        logs.append(math.log(value))
    maximum, zeros, windows = 0.0, 0, []
    for day, pos, sigma in zip(sessions, positions, reported_sigma):
        if pos < length:
            raise ValueError("unknown original full volatility window")
        changes = [logs[j] - logs[j-1] for j in range(pos-length+1, pos+1)]
        expected = math.sqrt(math.fsum(v*v for v in changes)/length)
        sigma = float(sigma)
        if not math.isfinite(sigma) or sigma < 0 or not math.isclose(expected, sigma, rel_tol=0, abs_tol=1e-12):
            raise ValueError("reported current sigma differs at " + day.isoformat())
        maximum = max(maximum, abs(expected-sigma))
        zeros += int(expected == 0)
        windows.append({"signal_date": day.isoformat(), "positions": list(range(pos-length+1, pos+1)),
                        "predecessor_position": pos-length, "last_observation_date": day.isoformat()})
    return {"status": "PASS", "rows": len(sessions), "length": length,
            "zero_sigma_rows": zeros, "maximum_difference": maximum,
            "all_scalar_sigma_windows": windows, "scope": "L real log changes including current T and actual predecessor"}


def compare_columns(reported, expected):
    if not isinstance(reported, pd.DataFrame) or not reported.index.equals(expected.index) or set(reported.columns) != set(expected.columns):
        raise ValueError("complete reported policy schema/axis mismatch")
    for name in expected:
        wanted, actual = expected[name], reported[name]
        if not actual.isna().equals(wanted.isna()):
            raise ValueError("missing-state mismatch: " + name)
        good = wanted.notna()
        if pd.api.types.is_numeric_dtype(wanted.dtype):
            ev, av = wanted[good].to_numpy(float), actual[good].to_numpy(float)
            exact = name == "target_position" or pd.api.types.is_bool_dtype(wanted.dtype)
            equal = np.array_equal(av, ev) if exact else np.allclose(av, ev, rtol=0, atol=1e-12)
            if not np.isfinite(av).all() or not equal:
                raise ValueError("numeric-state mismatch: " + name)
        elif actual[good].tolist() != wanted[good].tolist():
            raise ValueError("categorical-state mismatch: " + name)


BASE_KEYS = {
    "features", "score", "normalized", "signal_close", "signal_open",
    "previous_close", "momentum", "previous_momentum", "regimes",
    "previous_regimes", "raw_bear_acf", "sigma_knowncurrent",
}


def reconstruct(sessions, parameters, baseinputs):
    """Rebuild complete policy conditional on authenticated causal old features.

    Old range/ACF/confirmation inputs remain separately authenticated. Sigma
    must additionally pass verify_sigma on the full existing daily Close axis.
    """
    _axis(sessions)
    if set(baseinputs) != BASE_KEYS:
        raise ValueError("exact causal base input fields required")
    settings = parameters.get("profit_latch", {})
    if set(settings) != {"enabled", "volatility_window", "activation_multiple"} or type(settings["enabled"]) is not bool:
        raise ValueError("exact profit_latch fields and explicit enabled required")
    if type(settings["volatility_window"]) is not int or not 10 <= settings["volatility_window"] <= 60:
        raise ValueError("volatility length10..60 required")
    if type(settings["activation_multiple"]) is not float or not math.isfinite(settings["activation_multiple"]) or not .5 <= settings["activation_multiple"] <= 3:
        raise ValueError("activation multiple finite float.5..3 required")
    for key in BASE_KEYS - {"features", "regimes", "previous_regimes"}:
        obj = baseinputs[key]
        if not isinstance(obj, (pd.Series, pd.DataFrame)) or not obj.index.equals(sessions):
            raise ValueError("base input axis mismatch: " + key)
        arr = obj.to_numpy(float)
        if not np.isfinite(arr).all():
            raise ValueError("nonfinite base input: " + key)
    norms = baseinputs["normalized"]
    if set(norms.columns) != {"acf", "turnover", "volume"}:
        raise ValueError("three original normalized components required")
    for key in ("signal_close", "signal_open", "previous_close"):
        if (baseinputs[key] <= 0).any():
            raise ValueError("positive signal prices required")
    routes, old_routes = baseinputs["regimes"], baseinputs["previous_regimes"]
    if len(routes) != len(sessions) or any(v not in ("bull", "bear") for v in routes):
        raise ValueError("complete current raw regime required")
    if len(old_routes) != len(sessions) or any(v not in ("bull", "bear") for v in old_routes):
        raise ValueError("complete previous raw regime required")
    features = baseinputs["features"]
    if not isinstance(features, dict) or set(features) != {"bull", "bear"}:
        raise ValueError("two explicit route feature panels required")
    if (baseinputs["sigma_knowncurrent"] < 0).any():
        raise ValueError("current known sigma must be nonnegative")
    if type(parameters["exit_on_regime_change"]) is not bool:
        raise ValueError("explicit regime exit flag required")
    for route in ("bull", "bear"):
        if not isinstance(features[route], pd.DataFrame) or not features[route].index.equals(sessions) or not {"range_position", "acf1", "close", "momentum20"}.issubset(features[route].columns) or not np.isfinite(features[route].to_numpy(float)).all():
            raise ValueError("complete finite original route table required")
        rule = parameters[route]
        if type(rule["max_hold"]) is not int or not 1 <= rule["max_hold"] <= 60:
            raise ValueError("original integer H1..60 required")
        if not 0 <= rule["entry"] < rule["exit"] <= 1:
            raise ValueError("original ordered range thresholds required")
    p = parameters
    confirmation, context = p["confirmation"], p["context"]
    enabled = settings["enabled"]
    multiple = settings["activation_multiple"]
    latched, locked_sigma = False, None
    held, trade_age, entry_close, held_peak = None, 0, 0.0, 0.0
    memory_reason = memory_route = memory_category = None
    outputs = []
    for i, day in enumerate(sessions):
        before_latch = latched if held is not None else False
        before_sigma = locked_sigma if held is not None else None
        before_anchor = entry_close if held is not None else None
        activated = floor_triggered = False
        profit_log = np.nan
        raw = routes[i]
        route = held if held is not None else raw
        rule, row = p[route], features[route].iloc[i]
        previous_memory = (memory_reason, memory_route, memory_category)
        rising_body = bool(baseinputs["signal_close"].iloc[i] > baseinputs["signal_open"].iloc[i])
        acf_ok = rule["acf_min"] is None or float(row.acf1) >= rule["acf_min"]
        range_ok = float(row.range_position) <= rule["entry"]
        momentum_ok = rule["momentum_min"] is None or float(row.momentum20) >= rule["momentum_min"]
        recover_context = (
            held is None and raw == "bear" and memory_reason == "time"
            and memory_route == "bear" and memory_category == "BELOW" and rising_body
        )
        eligible = bool(range_ok and momentum_ok and (acf_ok or recover_context))
        score_applies = confirmation["scope"] in ("both", raw) and (
            context["entry_gate"] == "all" or memory_reason == "regime"
        )
        score_ok = not score_applies or float(baseinputs["score"].iloc[i]) >= confirmation["threshold"]
        boundary = raw == "bull" and old_routes[i] == "bear"
        opportunity = held is None and eligible
        memory_context = memory_reason or "initial"
        action = "flat"
        if held is not None:
            profit_log = math.log(float(row.close) / entry_close)
            trade_age += 1
            held_peak = max(held_peak, float(row.close))
            triggers = (
                ("loss", rule["stop_loss"] is not None and float(row.close)/entry_close-1 <= -rule["stop_loss"]),
                ("trailing", rule["trailing_stop"] is not None and float(row.close)/held_peak-1 <= -rule["trailing_stop"]),
                ("range", float(row.range_position) >= rule["exit"]),
                ("time", trade_age >= rule["max_hold"]),
                ("regime", p["exit_on_regime_change"] and raw != held),
            )
            triggered = [name for name, passes in triggers if passes]
            if not triggered and enabled and before_latch and float(row.close) <= entry_close:
                triggered = ["profit_floor"]
                floor_triggered = True
            if triggered:
                action = triggered[0]
                memory_reason, memory_route = action, held
                if action == "time" and held == "bear":
                    memory_category = "BELOW" if float(row.close) < entry_close else "ABOVE" if float(row.close) > entry_close else "EQUAL"
                else:
                    memory_category = None
                held = None
                latched, locked_sigma = False, None
            else:
                action = "hold"
                if enabled and not latched and profit_log > 0 and profit_log >= multiple * locked_sigma:
                    latched, activated = True, True
        elif eligible:
            if boundary and not rising_body:
                action = "entry_direction_rejected"
            elif score_ok:
                held, trade_age = raw, 0
                entry_close = held_peak = float(row.close)
                latched, locked_sigma = False, float(baseinputs["sigma_knowncurrent"].iloc[i]) if enabled else None
                memory_reason = memory_route = memory_category = None
                action = "entry"
            else:
                action = "confirmation_rejected"
        outputs.append({
            "range_position": float(row.range_position),
            "target_position": float(held is not None), "signal_reason": action,
            "regime": raw, "regime_momentum": float(baseinputs["momentum"].iloc[i]),
            "previous_regime": old_routes[i],
            "previous_regime_momentum": float(baseinputs["previous_momentum"].iloc[i]),
            "entry_direction_gate_applies": bool(boundary), "entry_direction_up": rising_body,
            "previous_signal_close": float(baseinputs["previous_close"].iloc[i]),
            "entry_signal_close": float(baseinputs["signal_close"].iloc[i]),
            "entry_signal_open": float(baseinputs["signal_open"].iloc[i]),
            "bull_range_position": float(features["bull"].range_position.iloc[i]),
            "bear_range_position": float(features["bear"].range_position.iloc[i]),
            "confirmation_score": float(baseinputs["score"].iloc[i]),
            "confirmation_acf": float(norms.acf.iloc[i]),
            "confirmation_turnover": float(norms.turnover.iloc[i]),
            "confirmation_volume": float(norms.volume.iloc[i]),
            "confirmation_opportunity": bool(opportunity), "confirmation_pass": bool(score_ok),
            "confirmation_exit_context": memory_context,
            "last_exit_reason": previous_memory[0], "last_exit_route": previous_memory[1],
            "last_exit_category": previous_memory[2],
            "bear_acf_raw": float(baseinputs["raw_bear_acf"].iloc[i]),
            "entry_acf_value": float(row.acf1), "entry_acf_pass": bool(acf_ok),
            "entry_acf_recovery_applies": bool(range_ok and momentum_ok and not acf_ok and recover_context),
            "entry_eligible": eligible,
        })
        if enabled:
            outputs[-1].update({
                "profit_latch_before": bool(before_latch), "profit_latch_after": bool(latched),
                "profit_sigma_before": before_sigma, "profit_sigma_after": locked_sigma,
                "profit_anchor_before": before_anchor, "profit_anchor_after": entry_close if held is not None else None,
                "profit_latch_activated": bool(activated), "profit_floor_triggered": bool(floor_triggered),
                "profit_sigma_current": float(baseinputs["sigma_knowncurrent"].iloc[i]),
                "profit_latch_profit_log": profit_log,
            })
    rebuilt = features["bull"].copy()
    state_frame = pd.DataFrame(outputs, index=sessions)
    for name in state_frame:
        rebuilt[name] = state_frame[name]
    return rebuilt



def verify(sessions, parameters, baseinputs, primarytable):
    expected = reconstruct(sessions, parameters, baseinputs)
    compare_columns(primarytable, expected)
    return {"status": "PASS", "signal_rows": len(sessions),
            "policy_columns": len(expected.columns), "cells_checked": expected.size,
            "new_latch_columns": 10 if parameters["profit_latch"]["enabled"] else 0,
            "scope": "independent complete transaction/latch state conditional on original causal inputs; sigma separately verified",
            "semantics": "signal-reference floor only, no actual filled-cost breakeven or guaranteed exit price"}
