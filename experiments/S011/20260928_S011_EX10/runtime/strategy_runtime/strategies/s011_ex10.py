"""H06 strict underreaction with an observable relative-catch-up failure exit."""

from __future__ import annotations

from datetime import date
from typing import Mapping

import numpy as np
import pandas as pd
from dataflows import Dataset
from strategy_runtime import (
    CalendarWindow, CutoffRule, DecisionContract, ExecutionPolicy, HistoryPolicy,
    ImplementationRef, InputContract, InputRequirement, MonitoringPolicy,
    ParameterSet, RequiredCapabilities, RuntimeDefinition, StrategyCandidate,
    StrategyImplementation, TradableWindow, next_session_calculation_scope,
    next_session_calendar_window,
)
from strategy_runtime.errors import RuntimeContractError


SYMBOL = "159326.SZ"
MARKET = "000300.SH"
START = "2024-09-10"
LOOKBACK = 60


def _close(frame: pd.DataFrame, label: str) -> pd.Series:
    ordered = frame.sort_values("Date")
    dates = pd.DatetimeIndex(pd.to_datetime(ordered["Date"]).dt.normalize())
    if dates.has_duplicates or not dates.is_monotonic_increasing:
        raise RuntimeContractError(f"H06 {label} dates must be unique and increasing")
    values = pd.to_numeric(ordered["Close"], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise RuntimeContractError(f"H06 {label} close must be positive and finite")
    return pd.Series(values, index=dates)


def target_history(
    inputs: Mapping[str, pd.DataFrame], sessions: pd.DatetimeIndex,
    max_shock_age: int, max_hold: int, relative_failure_floor: float,
) -> pd.DataFrame:
    etf_close = _close(inputs["adjusted_daily"], "ETF")
    market_close = _close(inputs["market_daily"], "market")
    if not etf_close.index.isin(market_close.index).all():
        raise RuntimeContractError("H06 market does not cover each ETF session")
    market_close = market_close.reindex(etf_close.index)
    etf_return = np.log(etf_close).diff()
    market_return = np.log(market_close).diff()
    relative_return = etf_return - market_return
    age = np.full(len(etf_close), np.nan)
    market_values = market_return.to_numpy(dtype=float)
    for i in range(LOOKBACK, len(etf_close)):
        window = market_values[i - LOOKBACK + 1 : i + 1]
        if np.isfinite(window).all():
            age[i] = LOOKBACK - 1 - int(np.argmax(window))
    opportunity = np.isfinite(age) & (age <= max_shock_age)
    relative_values = relative_return.to_numpy(dtype=float)
    underreaction = np.isfinite(relative_values) & (relative_values <= 0)
    target = np.zeros(len(etf_close), dtype=float)
    relative_since_signal = np.full(len(etf_close), np.nan)
    held = 0
    cumulative_relative = 0.0
    for i in range(len(etf_close)):
        if held:
            held += 1
            if not np.isfinite(relative_values[i]):
                raise RuntimeContractError("H06 held session lacks relative return")
            cumulative_relative += relative_values[i]
            relative_since_signal[i] = cumulative_relative
            if (not opportunity[i] or held > max_hold
                    or cumulative_relative <= relative_failure_floor):
                held = 0
                cumulative_relative = 0.0
            else:
                target[i] = 1.0
        elif opportunity[i] and underreaction[i]:
            held = 1
            cumulative_relative = 0.0
            relative_since_signal[i] = 0.0
            target[i] = 1.0
    result = pd.DataFrame({
        "market_shock_age": age,
        "relative_return_1": relative_values,
        "relative_since_signal": relative_since_signal,
        "opportunity": opportunity,
        "underreaction": underreaction,
        "target_position": target,
    }, index=etf_close.index)
    requested = pd.DatetimeIndex(sessions).normalize()
    if not requested.isin(etf_close.index).all():
        raise RuntimeContractError("H06 decision session has no ETF observation")
    return result.reindex(requested)


class S011H06FailureExit(StrategyImplementation):
    def __init__(self, candidate: StrategyCandidate) -> None:
        parameters = candidate.payload["parameters"]
        if set(parameters) != {"max_shock_age", "max_hold", "relative_failure_floor"}:
            raise RuntimeContractError("H06 failure-exit parameters are incomplete")
        self._max_shock_age = int(parameters["max_shock_age"])
        self._max_hold = int(parameters["max_hold"])
        self._relative_failure_floor = float(parameters["relative_failure_floor"])
        if (not 0 <= self._max_shock_age < LOOKBACK or not 1 <= self._max_hold <= LOOKBACK
                or not np.isfinite(self._relative_failure_floor)
                or not -1.0 <= self._relative_failure_floor < 0):
            raise RuntimeContractError("H06 failure-exit parameters are invalid")
        runtime = candidate.payload["runtime"]
        requirements = (
            InputRequirement("adjusted_daily", Dataset.ETF_OHLCV.value, SYMBOL, "daily", 1,
                             CutoffRule.SIGNAL_SESSION),
            InputRequirement("market_daily", Dataset.DOMESTIC_INDEX_DAILY.value, MARKET, "daily", LOOKBACK,
                             CutoffRule.SIGNAL_SESSION),
            InputRequirement("execution_daily", Dataset.ETF_UNADJUSTED_DAILY.value, SYMBOL, "daily", 1,
                             CutoffRule.SIGNAL_SESSION),
            InputRequirement("trading_calendar", Dataset.TRADING_CALENDAR.value, "SSE", "daily", 0,
                             CutoffRule.LATEST_AVAILABLE),
        )
        self._definition = RuntimeDefinition(
            schema_version=2, strategy_family_id="S011", version=None,
            release_id=candidate.reference_id, release_hash=candidate.runtime_identity_sha256,
            implementation=ImplementationRef(str(runtime["module"]), str(runtime["qualname"]),
                                             int(runtime["contract_version"]), str(runtime["source_sha256"])),
            parameters=ParameterSet(parameters), inputs=InputContract(requirements),
            decision=DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION_OPEN"),
            execution=ExecutionPolicy("FROZEN_RULE", {
                "capital": {"fee_rate": 0.001, "mode": "full_available_cash", "target_scope": "entry_cycle"},
                "entry": {"order_type": "LIMIT", "limit_family": "previous_close_ratio", "limit_parameter": 0.005},
                "exit": {"order_type": "MARKET", "limit_ratio": 0.1},
                "instrument": {"symbol": SYMBOL, "lot_size": 100, "maximum_order_quantity": 100000000,
                               "price_limit_ratio": 0.1, "price_tick": 0.001},
            }),
            monitoring=MonitoringPolicy("FORWARD_OBSERVATION", {"hypothesis": "H06"}),
            capabilities=RequiredCapabilities(tuple(sorted({r.dataset for r in requirements})), ("LIMIT", "MARKET")),
            tradable_symbol=SYMBOL, state_mode="STATELESS", identity_kind="CANDIDATE",
            candidate_id=candidate.candidate_id,
            history=HistoryPolicy("CANONICAL_REPLAY", START, START),
        )

    @classmethod
    def from_candidate(cls, candidate: StrategyCandidate) -> "S011H06FailureExit":
        return cls(candidate)

    @property
    def definition(self) -> RuntimeDefinition:
        return self._definition

    def calendar_window(self, tradable_window: TradableWindow):
        window = next_session_calendar_window(self._definition, tradable_window)
        return CalendarWindow(window.start, tradable_window.end)

    def derive_calculation_scope(self, tradable_window: TradableWindow, calendar_dates: tuple[date, ...]):
        return next_session_calculation_scope(self._definition, tradable_window, calendar_dates)

    def calculate_history(self, inputs: Mapping[str, pd.DataFrame], sessions: pd.DatetimeIndex) -> pd.DataFrame:
        return target_history(inputs, sessions, self._max_shock_age, self._max_hold, self._relative_failure_floor)
