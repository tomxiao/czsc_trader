"""H02: causally lagged ETF share expansion with bounded entry/exit timing."""

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


def target_history(
    inputs: Mapping[str, pd.DataFrame], sessions: pd.DatetimeIndex,
    share_threshold: float, pullback_ceiling: float, max_hold: int,
) -> pd.DataFrame:
    daily = inputs["adjusted_daily"].sort_values("Date")
    calendar = pd.DatetimeIndex(pd.to_datetime(daily["Date"]).dt.normalize())
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise RuntimeContractError("H02 ETF dates must be unique and increasing")
    close = pd.Series(pd.to_numeric(daily["Close"], errors="raise").to_numpy(dtype=float), index=calendar)
    if not np.isfinite(close).all() or close.le(0).any():
        raise RuntimeContractError("H02 ETF close must be positive and finite")
    shares = inputs["shares"].sort_values("Date")
    share_dates = pd.DatetimeIndex(pd.to_datetime(shares["Date"]).dt.normalize())
    if share_dates.has_duplicates:
        raise RuntimeContractError("H02 share dates must be unique")
    share_level = pd.Series(pd.to_numeric(shares["TotalShare"], errors="raise").to_numpy(dtype=float), index=share_dates)
    if not np.isfinite(share_level).all() or share_level.le(0).any():
        raise RuntimeContractError("H02 share count must be positive and finite")
    # T share count is published at T+1 08:30; T-close decisions use T-1 shares.
    known_shares = share_level.reindex(calendar).ffill().shift(1)
    flow = np.log(known_shares).diff(10)
    prior_three = np.log(close).diff(3)
    target = np.zeros(len(calendar), dtype=float)
    held = 0
    for i in range(len(calendar)):
        if not np.isfinite(flow.iloc[i]):
            continue
        active = bool(flow.iloc[i] > share_threshold)
        if held:
            held += 1
            if not active or held > max_hold:
                held = 0
            else:
                target[i] = 1.0
        elif active and np.isfinite(prior_three.iloc[i]) and prior_three.iloc[i] <= pullback_ceiling:
            held = 1
            target[i] = 1.0
    frame = pd.DataFrame({
        "share_growth_10": flow,
        "prior_price_return_3": prior_three,
        "target_position": target,
    }, index=calendar)
    requested = pd.DatetimeIndex(sessions).normalize()
    if not requested.isin(calendar).all():
        raise RuntimeContractError("H02 decision session has no ETF observation")
    return frame.reindex(requested)


class S011H02(StrategyImplementation):
    def __init__(self, candidate: StrategyCandidate) -> None:
        parameters = candidate.payload["parameters"]
        if set(parameters) != {"share_threshold", "pullback_ceiling", "max_hold"}:
            raise RuntimeContractError("H02 parameters are incomplete")
        self._share_threshold = float(parameters["share_threshold"])
        self._pullback_ceiling = float(parameters["pullback_ceiling"])
        self._max_hold = int(parameters["max_hold"])
        if (not np.isfinite(self._share_threshold) or not np.isfinite(self._pullback_ceiling)
                or self._max_hold < 1):
            raise RuntimeContractError("H02 parameters are invalid")
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
            monitoring=MonitoringPolicy("FORWARD_OBSERVATION", {"hypothesis": "H02"}),
            capabilities=RequiredCapabilities(tuple(sorted({r.dataset for r in requirements})), ("LIMIT", "MARKET")),
            tradable_symbol=SYMBOL, state_mode="STATELESS", identity_kind="CANDIDATE",
            candidate_id=candidate.candidate_id,
            history=HistoryPolicy("CANONICAL_REPLAY", START, START),
        )

    @classmethod
    def from_candidate(cls, candidate: StrategyCandidate) -> "S011H02":
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
        return target_history(inputs, sessions, self._share_threshold, self._pullback_ceiling, self._max_hold)
