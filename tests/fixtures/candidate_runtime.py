"""Acceptance-only parameterized SRT using a non-OHLCV input.

Tests install and freeze this source only in isolated test repositories.
"""

from datetime import date

import pandas as pd
from dataflows import Dataset
from strategy_runtime import (
    ObservationDefinition, ObservationSeries,
    CalculationScope,
    CalendarWindow,
    CutoffRule,
    DecisionContract,
    ExecutionPolicy,
    InputContract,
    InputRequirement,
    MonitoringPolicy,
    ParameterSet,
    RequiredCapabilities,
    StrategyDefinition,
    StrategyImplementation,
    TradableWindow,
    next_session_calculation_scope,
    next_session_calendar_window,
)


class CandidateFixture(StrategyImplementation):
    def __init__(self, parameters: ParameterSet):
        reference_symbols = tuple(parameters.values.get("reference_symbols", ()))
        requirements = [
            InputRequirement(
                "flow",
                "etf.share",
                "588080.SH",
                "daily",
                1,
                CutoffRule.SIGNAL_SESSION,
            ),
            InputRequirement(
                "market",
                Dataset.ETF_OHLCV.value,
                "588080.SH",
                "daily",
                1,
                CutoffRule.SIGNAL_SESSION,
            ),
            InputRequirement(
                "execution",
                Dataset.ETF_UNADJUSTED_DAILY.value,
                "588080.SH",
                "daily",
                1,
                CutoffRule.SIGNAL_SESSION,
            ),
            InputRequirement(
                "calendar",
                Dataset.TRADING_CALENDAR.value,
                "SSE",
                "daily",
                0,
                CutoffRule.LATEST_AVAILABLE,
            ),
        ]
        requirements.extend(
            InputRequirement(
                f"reference_{index}",
                Dataset.ETF_SHARE_SIZE.value,
                symbol,
                "daily",
                1,
                CutoffRule.SIGNAL_SESSION,
            )
            for index, symbol in enumerate(reference_symbols, start=1)
        )
        self._definition = StrategyDefinition(
            observation=ObservationDefinition((ObservationSeries("fixture", "合成信号", "fixture_signal"),), ()),
            parameters=parameters,
            inputs=InputContract(tuple(requirements)),
            decision=DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION"),
            execution=ExecutionPolicy(
                "FROZEN_RULE",
                {
                    "capital": {
                        "fee_rate": 0.001,
                        "mode": "full_available_cash",
                        "target_scope": "entry_cycle",
                    },
                    "entry": {
                        "limit_parameter": parameters.values.get("entry_premium", 0.0),
                        "order_type": "LIMIT",
                    },
                    "exit": {"limit_ratio": 0.1, "order_type": "MARKET"},
                    "instrument": {
                        "lot_size": 100,
                        "maximum_order_quantity": 1_000_000,
                        "price_limit_ratio": 0.1,
                        "price_tick": 0.001,
                    },
                },
            ),
            monitoring=MonitoringPolicy("OBSERVE", {}),
            capabilities=RequiredCapabilities(
                (
                    "etf.share",
                    Dataset.ETF_SHARE_SIZE.value,
                    Dataset.ETF_OHLCV.value,
                    Dataset.ETF_UNADJUSTED_DAILY.value,
                    Dataset.TRADING_CALENDAR.value,
                ),
                ("LIMIT", "MARKET"),
            ),
            tradable_symbol="588080.SH",
        )

    @classmethod
    def from_parameters(cls, parameters: ParameterSet):
        return cls(parameters)

    @property
    def definition(self):
        return self._definition

    @definition.setter
    def definition(self, value):
        self._definition = value

    def calendar_window(self, tradable_window: TradableWindow) -> CalendarWindow:
        return next_session_calendar_window(self.definition, tradable_window)

    def derive_calculation_scope(
        self,
        tradable_window: TradableWindow,
        calendar_dates: tuple[date, ...],
    ) -> CalculationScope:
        return next_session_calculation_scope(
            self.definition,
            tradable_window,
            calendar_dates,
        )

    def calculate_history(self, inputs, sessions):
        threshold = float(self.definition.parameters.values["threshold"])
        flow = inputs["flow"].copy()
        flow["Date"] = pd.to_datetime(flow["Date"])
        values = flow.set_index("Date").reindex(sessions)["Flow"].astype(float)
        if values.isna().any():
            raise ValueError("fixture flow does not cover the calculation sessions")
        target = (values > threshold).astype(float)
        if self.definition.parameters.values.get("invert", False):
            target = 1.0 - target
        return pd.DataFrame({"target_position": target, "fixture_signal": target}, index=sessions)
