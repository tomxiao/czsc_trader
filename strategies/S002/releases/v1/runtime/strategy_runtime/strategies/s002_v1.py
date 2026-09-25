"""Frozen S002-v1 three-down-bars, five-session repair strategy."""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Mapping

import czsc
import pandas as pd
from dataflows import Dataset

from ..algorithm import StrategyImplementation
from ..calculation import (
    CalculationScope,
    CalendarWindow,
    next_session_calculation_scope,
    next_session_calendar_window,
)
from ..contracts import TradableWindow
from ..errors import RuntimeContractError
from ..execution_rules import effective_target_order_type
from ..implementation_identity import implementation_sha256
from ..models import (
    CutoffRule,
    DecisionContract,
    ExecutionPolicy,
    ImplementationRef,
    InputContract,
    InputRequirement,
    MonitoringPolicy,
    ParameterSet,
    RequiredCapabilities,
    RuntimeDefinition,
    StrategyRelease,
)


_INPUT_DAILY = "adjusted_daily"
_INPUT_EXECUTION = "execution_daily"
_INPUT_CALENDAR = "trading_calendar"


def _source_sha256() -> str:
    return implementation_sha256(
        ("strategies/s002_v1.py", "calculation.py", "execution_rules.py")
    )


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


class S002V1(StrategyImplementation):
    """Executable S002-v1 implementation with no TDR dependency."""

    def __init__(self, release: StrategyRelease, deployment_symbol: str | None = None) -> None:
        payload = _object(release.payload, "strategy payload")
        if payload.get("strategy_kind") != "czsc_event_hold":
            raise RuntimeContractError("S002-v1 strategy_kind must be czsc_event_hold")
        rule = _object(payload.get("rule"), "S002-v1 rule")
        signal = _object(rule.get("signal"), "S002-v1 signal")
        portfolio = _object(rule.get("portfolio_rule"), "S002-v1 portfolio rule")
        execution = _object(rule.get("execution"), "S002-v1 execution")
        instrument = _object(execution.get("instrument"), "S002-v1 instrument")
        frozen_symbol = str(rule.get("symbol", "")).upper()
        if (
            frozen_symbol != "510500.SH"
            or str(instrument.get("symbol", "")).upper() != frozen_symbol
        ):
            raise RuntimeContractError("S002-v1 frozen symbol must be 510500.SH")
        symbol = (deployment_symbol or frozen_symbol).upper()
        if not re.fullmatch(r"\d{6}\.(?:SH|SZ)", symbol):
            raise RuntimeContractError("S002-v1 deployment symbol must be an A-share instrument")
        if signal.get("trigger") != "fresh_transition":
            raise RuntimeContractError("S002-v1 requires fresh_transition")
        if portfolio.get("ignore_entries_while_holding") is not True:
            raise RuntimeContractError("S002-v1 must ignore entries while holding")
        if portfolio.get("require_fresh_transition_after_exit") is not True:
            raise RuntimeContractError("S002-v1 must require a fresh transition after exit")
        self._release = release
        self._rule = rule
        self._signal = signal
        self._portfolio = portfolio
        self._symbol = symbol
        order_types = tuple(
            sorted(
                {
                    effective_target_order_type(execution, "BUY"),
                    effective_target_order_type(execution, "SELL"),
                }
            )
        )
        self._definition = RuntimeDefinition(
            schema_version=1,
            strategy_family_id=release.strategy_family_id,
            version=release.version,
            release_id=release.release_id,
            release_hash=release.release_hash,
            implementation=ImplementationRef(
                __name__, self.__class__.__name__, 1, _source_sha256()
            ),
            parameters=ParameterSet(release.payload),
            inputs=InputContract(
                (
                    InputRequirement(
                        _INPUT_DAILY,
                        Dataset.ETF_OHLCV.value,
                        symbol,
                        "daily",
                        300,
                        CutoffRule.SIGNAL_SESSION,
                    ),
                    InputRequirement(
                        _INPUT_EXECUTION,
                        Dataset.ETF_UNADJUSTED_DAILY.value,
                        symbol,
                        "daily",
                        1,
                        CutoffRule.SIGNAL_SESSION,
                    ),
                    InputRequirement(
                        _INPUT_CALENDAR,
                        Dataset.TRADING_CALENDAR.value,
                        "SSE",
                        "daily",
                        0,
                        CutoffRule.LATEST_AVAILABLE,
                    ),
                )
            ),
            decision=DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION_OPEN"),
            execution=ExecutionPolicy("FROZEN_RULE", execution),
            monitoring=MonitoringPolicy("FORWARD_OBSERVATION", {"frozen": True}),
            capabilities=RequiredCapabilities(
                (
                    Dataset.ETF_OHLCV.value,
                    Dataset.ETF_UNADJUSTED_DAILY.value,
                    Dataset.TRADING_CALENDAR.value,
                ),
                order_types,
            ),
            tradable_symbol=symbol,
        )

    @classmethod
    def from_release(cls, release: StrategyRelease) -> "S002V1":
        if release.release_id != "S002-v1":
            raise RuntimeContractError("S002V1 can only load S002-v1")
        return cls(release)

    @classmethod
    def from_release_for_symbol(cls, release: StrategyRelease, symbol: str) -> "S002V1":
        if release.release_id != "S002-v1":
            raise RuntimeContractError("S002V1 can only load S002-v1")
        return cls(release, symbol)

    @property
    def definition(self) -> RuntimeDefinition:
        return self._definition

    def calendar_window(self, tradable_window: TradableWindow) -> CalendarWindow:
        return next_session_calendar_window(self._definition, tradable_window)

    def derive_calculation_scope(
        self,
        tradable_window: TradableWindow,
        calendar_dates: tuple[date, ...],
    ) -> CalculationScope:
        return next_session_calculation_scope(
            self._definition,
            tradable_window,
            calendar_dates,
        )

    def calculate_history(
        self,
        inputs: Mapping[str, pd.DataFrame],
        sessions: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        del sessions
        return _calculate_target_history(
            inputs[_INPUT_DAILY],
            symbol=self._symbol,
            signal=self._signal,
            portfolio=self._portfolio,
        )

    def calculate_window_history(
        self,
        inputs: Mapping[str, pd.DataFrame],
        sessions: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        states = _calculate_signal_states(
            inputs[_INPUT_DAILY], symbol=self._symbol, signal=self._signal,
        )
        requested = pd.DatetimeIndex(sessions).tz_localize(None).normalize()
        missing = requested.difference(states.index)
        if not missing.empty:
            raise RuntimeContractError(
                "S002-v1 prepared history misses evaluation sessions"
            )
        history = _target_history(
            states.reindex(requested),
            str(self._signal.get("entry_state", "")),
            int(self._portfolio.get("holding_sessions", 0)),
        )
        history["factor_score"] = (
            history["signal_state"]
            .eq(str(self._signal.get("entry_state", "")))
            .astype(float)
        )
        return history
