"""Focused return-first H02 successor: broader flow and shorter entry/exit horizons."""

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
START = "2024-09-10"
SHARE_WINDOWS = (15, 20, 25, 30)
MOMENTUM_WINDOWS = (1, 2, 3, 5)
MAX_HOLDS = (5, 7, 10, 14)


def target_history(inputs: Mapping[str, pd.DataFrame], sessions: pd.DatetimeIndex,
                   share_window: int, momentum_window: int, max_hold: int) -> pd.DataFrame:
    if (share_window not in SHARE_WINDOWS or momentum_window not in MOMENTUM_WINDOWS
            or max_hold not in MAX_HOLDS):
        raise RuntimeContractError("EX07 parameters are outside the frozen grid")
    daily = inputs["adjusted_daily"].sort_values("Date")
    calendar = pd.DatetimeIndex(pd.to_datetime(daily["Date"]).dt.normalize())
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise RuntimeContractError("EX07 ETF dates must be unique and increasing")
    close = pd.Series(pd.to_numeric(daily["Close"], errors="raise").to_numpy(dtype=float), index=calendar)
    if not np.isfinite(close).all() or close.le(0).any():
        raise RuntimeContractError("EX07 ETF close must be positive and finite")
    shares = inputs["shares"].sort_values("Date")
    share_dates = pd.DatetimeIndex(pd.to_datetime(shares["Date"]).dt.normalize())
    if share_dates.has_duplicates:
        raise RuntimeContractError("EX07 share dates must be unique")
    share_level = pd.Series(pd.to_numeric(shares["TotalShare"], errors="raise").to_numpy(dtype=float), index=share_dates)
    if not np.isfinite(share_level).all() or share_level.le(0).any():
        raise RuntimeContractError("EX07 share count must be positive and finite")
    # T-close decisions use T-1 share count, first published T morning.
    known_shares = share_level.reindex(calendar).ffill().shift(1)
    flow = np.log(known_shares).diff(share_window)
    momentum = np.log(close).diff(momentum_window)
    target = np.zeros(len(calendar), dtype=float)
    held = 0
    for i in range(len(calendar)):
        if not np.isfinite(flow.iloc[i]):
            continue
        active = bool(flow.iloc[i] > 0)
        if held:
            held += 1
            if not active or held > max_hold:
                held = 0
            else:
                target[i] = 1.0
        elif active and np.isfinite(momentum.iloc[i]) and momentum.iloc[i] > 0:
            held = 1
            target[i] = 1.0
    frame = pd.DataFrame({"share_growth": flow, "prior_price_momentum": momentum,
                          "target_position": target}, index=calendar)
    requested = pd.DatetimeIndex(sessions).normalize()
    if not requested.isin(calendar).all():
        raise RuntimeContractError("EX07 decision session has no ETF observation")
    return frame.reindex(requested)


class S011H02Focused(StrategyImplementation):
    def __init__(self, candidate: StrategyCandidate) -> None:
        parameters = candidate.payload["parameters"]
        if set(parameters) != {"share_window", "momentum_window", "max_hold"}:
            raise RuntimeContractError("EX07 parameters are incomplete")
        self._share_window = int(parameters["share_window"])
        self._momentum_window = int(parameters["momentum_window"])
        self._max_hold = int(parameters["max_hold"])
        if (self._share_window not in SHARE_WINDOWS or self._momentum_window not in MOMENTUM_WINDOWS
                or self._max_hold not in MAX_HOLDS):
            raise RuntimeContractError("EX07 parameters are outside the frozen grid")
        runtime = candidate.payload["runtime"]
        requirements = (
            InputRequirement("adjusted_daily", Dataset.ETF_OHLCV.value, SYMBOL, "daily", 1, CutoffRule.SIGNAL_SESSION),
            InputRequirement("execution_daily", Dataset.ETF_UNADJUSTED_DAILY.value, SYMBOL, "daily", 1, CutoffRule.SIGNAL_SESSION),
            InputRequirement("shares", Dataset.ETF_SHARE_SIZE.value, SYMBOL, "daily", 1, CutoffRule.PREVIOUS_SESSION),
            InputRequirement("trading_calendar", Dataset.TRADING_CALENDAR.value, "SSE", "daily", 0, CutoffRule.LATEST_AVAILABLE),
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
            monitoring=MonitoringPolicy("FORWARD_OBSERVATION", {"hypothesis": "H02", "experiment": "EX07"}),
            capabilities=RequiredCapabilities(tuple(sorted({r.dataset for r in requirements})), ("LIMIT", "MARKET")),
            tradable_symbol=SYMBOL, state_mode="STATELESS", identity_kind="CANDIDATE",
            candidate_id=candidate.candidate_id,
            history=HistoryPolicy("CANONICAL_REPLAY", START, START),
        )

    @classmethod
    def from_candidate(cls, candidate: StrategyCandidate) -> "S011H02Focused":
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
        return target_history(inputs, sessions, self._share_window, self._momentum_window, self._max_hold)
