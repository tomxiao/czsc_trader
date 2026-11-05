"""Frozen financial signal mathematics, copied without runtime adapters.

The source is the authenticated pre-upgrade release. Execution and loading use
the native account contract; historical signal definitions remain unchanged.
"""
from __future__ import annotations
from typing import Any, Mapping
import czsc
import pandas as pd
from strategy_runtime import RuntimeContractError

_INPUT_DAILY = "adjusted_daily"

_INPUT_EXECUTION = "execution_daily"

_INPUT_CALENDAR = "trading_calendar"

def _object(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeContractError(f"{field_name} must be an object")
    return value

def _primary_value(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value).split("_", 1)[0]

def _target_history(states: pd.Series, entry_state: str, holding_sessions: int) -> pd.DataFrame:
    active = states.eq(entry_state).fillna(False)
    entries = active & ~active.shift(1, fill_value=False)
    in_position = False
    entry_offset: int | None = None
    rows: list[dict[str, object]] = []
    for offset, session in enumerate(states.index):
        entry = bool(entries.iloc[offset])
        held = 0 if entry_offset is None else max(0, offset - entry_offset)
        action = "HOLD_POSITION" if in_position else "HOLD_CASH"
        if in_position and held >= holding_sessions:
            in_position = False
            entry_offset = None
            action = "EXIT_TIME"
        elif in_position and entry:
            action = "IGNORE_ENTRY_WHILE_HOLDING"
        elif not in_position and entry:
            in_position = True
            entry_offset = offset
            action = "ENTER"
        rows.append(
            {
                "date": session,
                "signal_state": None if pd.isna(states.iloc[offset]) else str(states.iloc[offset]),
                "entry_transition": entry,
                "held_sessions": held,
                "action": action,
                "target_position": 1.0 if in_position else 0.0,
            }
        )
    return pd.DataFrame(rows).set_index("date")

def _calculate_signal_states(
    daily: pd.DataFrame,
    *,
    symbol: str,
    signal: Mapping[str, Any],
) -> pd.Series:
    frame = daily.rename(
        columns={
            "Date": "dt",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "vol",
            "Amount": "amount",
        }
    ).copy()
    frame["dt"] = pd.to_datetime(frame["dt"])
    frame.insert(1, "symbol", symbol)
    bars = czsc.format_standard_kline(
        frame[["dt", "symbol", "open", "close", "high", "low", "vol", "amount"]],
        freq="日线",
    )
    config = dict(_object(signal.get("config"), "S002-v1 signal config"))
    output = czsc.generate_czsc_signals(
        bars,
        [config],
        sdt=str(frame["dt"].min().date()),
        init_n=int(signal.get("warmup_bars", 250)),
        df=True,
    )
    output_key = str(signal.get("output_key", ""))
    if output_key not in output.columns:
        raise RuntimeContractError(f"S002-v1 signal output is missing: {output_key}")
    sessions = pd.DatetimeIndex(pd.to_datetime(output["dt"])).tz_localize(None).normalize()
    states = pd.Series(
        output[output_key].map(_primary_value).astype("string").to_numpy(),
        index=sessions,
    )
    return states

def _calculate_target_history(
    daily: pd.DataFrame,
    *,
    symbol: str,
    signal: Mapping[str, Any],
    portfolio: Mapping[str, Any],
) -> pd.DataFrame:
    """Calculate the complete S002 target-position history from published daily bars."""

    states = _calculate_signal_states(daily, symbol=symbol, signal=signal)
    history = _target_history(
        states,
        str(signal.get("entry_state", "")),
        int(portfolio.get("holding_sessions", 0)),
    )
    history["factor_score"] = (
        history["signal_state"].eq(str(signal.get("entry_state", ""))).astype(float)
    )
    return history
