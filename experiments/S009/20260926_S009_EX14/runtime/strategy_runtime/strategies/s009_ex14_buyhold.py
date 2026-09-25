"""S009 same-execution BuyHold comparator for development evaluation."""

from __future__ import annotations

from datetime import date
from typing import Mapping

import pandas as pd
from dataflows import Dataset
from strategy_runtime import (
    CutoffRule, DecisionContract, ExecutionPolicy, HistoryPolicy, ImplementationRef,
    InputContract, InputRequirement, MonitoringPolicy, ParameterSet,
    RequiredCapabilities, RuntimeDefinition, StrategyCandidate, StrategyImplementation,
    TradableWindow, next_session_calculation_scope, next_session_calendar_window,
)


class S009BuyHold(StrategyImplementation):
    """Buy at the first evaluation opportunity and continuously target full exposure."""

    def __init__(self, candidate: StrategyCandidate) -> None:
        runtime = candidate.payload["runtime"]
        requirements = (
            InputRequirement("adjusted_daily", Dataset.ETF_OHLCV.value,
                             "518880.SH", "daily", 1, CutoffRule.SIGNAL_SESSION),
            InputRequirement("execution_daily", Dataset.ETF_UNADJUSTED_DAILY.value,
                             "518880.SH", "daily", 1, CutoffRule.SIGNAL_SESSION),
            InputRequirement("trading_calendar", Dataset.TRADING_CALENDAR.value,
                             "SSE", "daily", 0, CutoffRule.LATEST_AVAILABLE),
        )
        self._definition = RuntimeDefinition(
            schema_version=2,
            strategy_family_id="S009",
            version=None,
            release_id=candidate.reference_id,
            release_hash=candidate.runtime_identity_sha256,
            implementation=ImplementationRef(
                str(runtime["module"]), str(runtime["qualname"]),
                int(runtime["contract_version"]), str(runtime["source_sha256"]),
            ),
            parameters=ParameterSet({}),
            inputs=InputContract(requirements),
            decision=DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION_OPEN"),
            execution=ExecutionPolicy("FROZEN_RULE", {
                "capital": {"fee_rate": 0.001, "mode": "full_available_cash",
                            "target_scope": "entry_cycle"},
                "entry": {"order_type": "LIMIT", "limit_family": "previous_close_ratio",
                          "limit_parameter": 0.1},
                "exit": {"order_type": "MARKET", "limit_ratio": 0.1},
                "instrument": {"symbol": "518880.SH", "lot_size": 100,
                               "maximum_order_quantity": 100000000,
                               "price_limit_ratio": 0.1, "price_tick": 0.001},
            }),
            monitoring=MonitoringPolicy("FORWARD_OBSERVATION", {"comparator": "BUYHOLD"}),
            capabilities=RequiredCapabilities(
                tuple(sorted({item.dataset for item in requirements})),
                ("LIMIT", "MARKET"),
            ),
            tradable_symbol="518880.SH",
            state_mode="STATELESS",
            identity_kind="CANDIDATE",
            candidate_id=candidate.candidate_id,
            history=HistoryPolicy("CANONICAL_REPLAY", "2019-01-02", "2018-01-01"),
        )

    @classmethod
    def from_candidate(cls, candidate: StrategyCandidate) -> "S009BuyHold":
        return cls(candidate)

    @property
    def definition(self) -> RuntimeDefinition:
        return self._definition

    def calendar_window(self, tradable_window: TradableWindow):
        return next_session_calendar_window(self._definition, tradable_window)

    def derive_calculation_scope(self, tradable_window: TradableWindow,
                                 calendar_dates: tuple[date, ...]):
        return next_session_calculation_scope(self._definition, tradable_window, calendar_dates)

    def calculate_history(self, inputs: Mapping[str, pd.DataFrame],
                          sessions: pd.DatetimeIndex) -> pd.DataFrame:
        return pd.DataFrame({"target_position": 1.0}, index=sessions)
