"""Independent scalar market-episode and transaction-state reconstruction."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

OBSERVER_COLUMNS = (
    "episode_live", "episode_route", "episode_age", "episode_reason",
    "episode_expired", "episode_anchor", "episode_peak", "episode_id",
)


def _axis(sessions):
    if (
        not isinstance(sessions, pd.DatetimeIndex) or len(sessions) == 0
        or sessions.tz is not None or sessions.hasnans or sessions.has_duplicates
        or not sessions.is_monotonic_increasing or not sessions.equals(sessions.normalize())
    ):
        raise ValueError("complete nonempty ordered naive session dates required")


def observer(parameters, features, regimes, sessions):
    """Rebuild observer without primary imports, ACF, score or accepted trade.

    Signal start is cold FLAT, not prebuilt from warmup. Age starts0. The end
    priority is range,time,regime. End day never opens another episode.
    """
    _axis(sessions)
    if set(features) != {"bull", "bear"} or len(regimes) != len(sessions):
        raise ValueError("two aligned routes and one raw route per session required")
    if type(parameters["exit_on_regime_change"]) is not bool:
        raise ValueError("explicit regime exit boolean required")
    rows_by_route = {}
    for route in ("bull", "bear"):
        frame, rule = features[route], parameters[route]
        if (
            not isinstance(frame, pd.DataFrame) or not frame.index.equals(sessions)
            or frame.columns.has_duplicates
            or not {"range_position", "momentum20", "close"}.issubset(frame.columns)
        ):
            raise ValueError("route features must completely align with sessions")
        if type(rule["max_hold"]) is not int or not 1 <= rule["max_hold"] <= 60:
            raise ValueError("original H integer1..60 required")
        if not 0 <= rule["entry"] < rule["exit"] <= 1:
            raise ValueError("finite ordered entry/exit fractions required")
        if rule["momentum_min"] is not None and not math.isfinite(rule["momentum_min"]):
            raise ValueError("finite optional momentum threshold required")
        records = []
        for r, m, c in frame[["range_position", "momentum20", "close"]].itertuples(index=False, name=None):
            r, m, c = float(r), float(m), float(c)
            if not all(math.isfinite(v) for v in (r, m, c)) or c <= 0:
                raise ValueError("finite route values and positive close required")
            records.append((r, m, c))
        rows_by_route[route] = records
    episode = None
    next_identity = 0
    result = []
    for i, raw in enumerate(regimes):
        if raw not in ("bull", "bear"):
            raise ValueError("illegal raw route")
        if episode is None:
            r, m, c = rows_by_route[raw][i]
            rule = parameters[raw]
            if r <= rule["entry"] and (rule["momentum_min"] is None or m >= rule["momentum_min"]):
                next_identity += 1
                episode = {"route": raw, "age": 0, "anchor": c, "peak": c, "id": next_identity}
                result.append((True, raw, 0, "start", False, c, c, next_identity))
            else:
                result.append((False, None, None, "flat", False, None, None, None))
        else:
            route = episode["route"]
            r, _, c = rows_by_route[route][i]
            rule = parameters[route]
            episode["age"] += 1
            episode["peak"] = max(episode["peak"], c)
            ended = None
            if r >= rule["exit"]:
                ended = "range"
            elif episode["age"] >= rule["max_hold"]:
                ended = "time"
            elif parameters["exit_on_regime_change"] and raw != route:
                ended = "regime"
            result.append((
                ended is None, route, episode["age"], ended or "hold", ended == "time",
                episode["anchor"], episode["peak"], episode["id"],
            ))
            if ended is not None:
                episode = None
    return pd.DataFrame(result, index=sessions, columns=OBSERVER_COLUMNS)


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
            exact_state = name in {"target_position", "episode_age", "episode_id"} or pd.api.types.is_bool_dtype(wanted.dtype)
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
    OHLC. It separately reconstructs both state machines and all diagnostics.
    """
    _axis(sessions)
    if set(baseinputs) != BASE_KEYS:
        raise ValueError("exact causal base input fields required")
    if type(parameters.get("episode_enabled")) is not bool:
        raise ValueError("explicit episode_enabled required")
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
    observed = observer(parameters, features, routes, sessions)
    for route in ("bull", "bear"):
        if "acf1" not in features[route] or not np.isfinite(features[route].to_numpy(float)).all():
            raise ValueError("complete finite original route table required")
    p = parameters
    confirmation, context = p["confirmation"], p["context"]
    enabled = p["episode_enabled"]
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
                ("time", bool(observed.episode_expired.iloc[i]) if enabled else trade_age >= rule["max_hold"]),
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
            elif enabled and not (
                bool(observed.episode_live.iloc[i]) and observed.episode_route.iloc[i] == raw
            ):
                action = "episode_entry_rejected"
            elif score_ok:
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
    rebuilt = features["bull"].copy()
    state_frame = pd.DataFrame(outputs, index=sessions)
    for name in state_frame:
        rebuilt[name] = state_frame[name]
    return rebuilt.join(observed) if enabled else rebuilt


def verify(sessions, parameters, baseinputs, primarytable):
    expected = reconstruct(sessions, parameters, baseinputs)
    if set(primarytable.columns) != set(expected.columns):
        raise ValueError("complete policy/observer schema mismatch")
    compare_columns(primarytable, expected, expected.columns)
    return {
        "status": "PASS", "signal_rows": len(sessions),
        "policy_columns": len(expected.columns), "cells_checked": expected.size,
        "observer_columns": 8 if parameters["episode_enabled"] else 0,
        "scope": "independent observer and full policy conditional on authenticated original feature inputs",
        "initial_state": "cold flat at first FULL signal; no warmup episodes or annual reset",
        "state_equality": "targets, ages, episode ids and booleans exact; other authenticated floats atol1e-12",
    }
