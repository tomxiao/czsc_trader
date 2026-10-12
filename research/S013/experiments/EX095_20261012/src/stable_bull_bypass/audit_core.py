"""Independent scalar stable-bull score bypass and full transaction state."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

def _axis(sessions):
    if (
        not isinstance(sessions, pd.DatetimeIndex) or len(sessions) == 0
        or sessions.tz is not None or sessions.hasnans or sessions.has_duplicates
        or not sessions.is_monotonic_increasing or not sessions.equals(sessions.normalize())
    ):
        raise ValueError("complete nonempty ordered naive session dates required")


def compare_columns(reported, expected, columns):
    if not reported.index.equals(expected.index) or any(name not in reported for name in columns):
        raise ValueError("reported table axis/fields mismatch")
    for name in columns:
        actual, wanted = reported[name], expected[name]
        if not actual.isna().equals(wanted.isna()):
            raise ValueError("missing-state mismatch: " + name)
        good = wanted.notna()
        if pd.api.types.is_numeric_dtype(wanted.dtype):
            av, ev = actual[good].to_numpy(float), wanted[good].to_numpy(float)
            exact_state = name == "target_position" or pd.api.types.is_bool_dtype(wanted.dtype)
            matches = np.array_equal(av, ev) if exact_state else np.allclose(av, ev, rtol=0, atol=1e-12)
            if not np.isfinite(av).all() or not matches:
                raise ValueError("numeric-state mismatch: " + name)
        elif actual[good].tolist() != wanted[good].tolist():
            raise ValueError("categorical-state mismatch: " + name)


BASE_KEYS = {
    "features", "score", "normalized", "signal_close", "signal_open",
    "previous_close", "momentum", "previous_momentum", "regimes",
    "previous_regimes", "raw_bear_acf",
}


def reconstruct(sessions, parameters, baseinputs):
    """Rebuild complete policy conditional on authenticated causal old features.

    This audit does not independently derive old range/ACF/confirmation from
    OHLC. It reconstructs all transaction state and the narrow bypass predicate.
    """
    _axis(sessions)
    if set(baseinputs) != BASE_KEYS:
        raise ValueError("exact causal base input fields required")
    if type(parameters.get("bypass_enabled")) is not bool:
        raise ValueError("explicit bypass_enabled required")
    keys = {"bull", "bear", "regime_window", "regime_threshold", "exit_on_regime_change",
            "confirmation", "context", "mechanism", "bypass_enabled"}
    if set(parameters) != keys or parameters["mechanism"] != "STABLE_RAW_BULL_BODY_CONFIRMATION_BYPASS":
        raise ValueError("exact stable-bull mechanism and fields required")
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
    if len(old_routes) != len(sessions) or any(v not in ("bull", "bear") for v in old_routes):
        raise ValueError("complete previous raw regime required")
    features = baseinputs["features"]
    if len(routes) != len(sessions) or any(v not in ("bull", "bear") for v in routes):
        raise ValueError("complete current raw regime required")
    if not isinstance(features, dict) or set(features) != {"bull", "bear"}:
        raise ValueError("two explicit route feature panels required")
    if type(parameters["exit_on_regime_change"]) is not bool:
        raise ValueError("explicit regime exit boolean required")
    for route in ("bull", "bear"):
        if not isinstance(features[route], pd.DataFrame) or not features[route].index.equals(sessions) or features[route].columns.has_duplicates or not {"range_position", "acf1", "close", "momentum20"}.issubset(features[route].columns) or not np.isfinite(features[route].to_numpy(float)).all() or (features[route]["close"] <= 0).any():
            raise ValueError("complete finite original route table required")
        rule = parameters[route]
        if type(rule["max_hold"]) is not int or not 1 <= rule["max_hold"] <= 60:
            raise ValueError("original H integer1..60 required")
        if not 0 <= rule["entry"] < rule["exit"] <= 1:
            raise ValueError("original ordered range thresholds required")
        for name in ("acf_min", "momentum_min"):
            if rule[name] is not None and not math.isfinite(rule[name]):
                raise ValueError("finite optional original entry threshold required")
    p = parameters
    confirmation, context = p["confirmation"], p["context"]
    enabled = p["bypass_enabled"]
    held, trade_age, entry_close, held_peak = None, 0, 0.0, 0.0
    memory_reason = memory_route = memory_category = None
    outputs = []
    for i, day in enumerate(sessions):
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
        bypass_scope = bool(raw == "bull" and old_routes[i] == "bull" and rising_body)
        effective_pass = bool(score_ok or (enabled and bypass_scope))
        opportunity = held is None and eligible
        memory_context = memory_reason or "initial"
        action = "flat"
        if held is not None:
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
            if triggered:
                action = triggered[0]
                memory_reason, memory_route = action, held
                if action == "time" and held == "bear":
                    memory_category = "BELOW" if float(row.close) < entry_close else "ABOVE" if float(row.close) > entry_close else "EQUAL"
                else:
                    memory_category = None
                held = None
            else:
                action = "hold"
        elif eligible:
            if boundary and not rising_body:
                action = "entry_direction_rejected"
            elif effective_pass:
                held, trade_age = raw, 0
                entry_close = held_peak = float(row.close)
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
            outputs[-1].update({"bypass_applies": bypass_scope,
                               "effective_confirmation_pass": effective_pass,
                               "actually_bypassed": bool(action == "entry" and bypass_scope and not score_ok)})
    rebuilt = features["bull"].copy()
    state_frame = pd.DataFrame(outputs, index=sessions)
    for name in state_frame:
        rebuilt[name] = state_frame[name]
    return rebuilt



def verify(sessions, parameters, baseinputs, primarytable):
    expected = reconstruct(sessions, parameters, baseinputs)
    if set(primarytable.columns) != set(expected.columns):
        raise ValueError("complete policy/bypass schema mismatch")
    compare_columns(primarytable, expected, expected.columns)
    return {"status": "PASS", "signal_rows": len(sessions),
            "policy_columns": len(expected.columns), "cells_checked": expected.size,
            "scope": "independent whole transaction state conditional on authenticated original features and known raw current/previous regime",
            "new_numeric_coordinates": 0, "annual_oracle_used": False,
            "off": "no new diagnostics; original full policy reconstructed" if not parameters["bypass_enabled"] else None}
