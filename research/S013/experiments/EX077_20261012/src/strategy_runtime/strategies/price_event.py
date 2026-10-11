"""SOURCE ONLY: native SRT adapter; no execution or data access on import.

Future materialization: strategies/price_event.py beside exact frozen policy.py.
"""

from datetime import timedelta

import pandas as pd
from dataflows import DataCoverageRequirement, DataRequest, Dataset
from strategy_runtime import (
    CalculationScope,
    CutoffRule,
    DecisionContract,
    ExecutionPolicy,
    InputContract,
    InputRequirement,
    MonitoringPolicy,
    ObservationDefinition,
    RequiredCapabilities,
    StrategyDefinition,
    StrategyImplementation,
)

from .policy import decisions


class PriceEvent(StrategyImplementation):
    def __init__(self, parameters):
        if set(parameters.values) != {"lookback", "distance"}:
            raise ValueError("exact two-parameter contract required")
        # Validate full domain using artificial input only; no real signal generation.
        axis = pd.date_range("2000-01-03", periods=2, freq="B")
        decisions(pd.Series([1.0, 1.1], index=axis), axis, **parameters.values)
        self._parameters = parameters

    @classmethod
    def from_parameters(cls, parameters):
        return cls(parameters)

    @property
    def definition(self):
        # Fixed121 Close observations support the entire L<=120 domain.
        # Warmup depth is a data contract, never an additional searched parameter.
        return StrategyDefinition(
            parameters=self._parameters,
            inputs=InputContract(
                (
                    InputRequirement(
                        "daily", "etf.ohlcv", "510500.SH", "daily", 121, CutoffRule.SIGNAL_SESSION
                    ),
                    InputRequirement(
                        "execution",
                        "etf.unadjusted_daily",
                        "510500.SH",
                        "daily",
                        1,
                        CutoffRule.SIGNAL_SESSION,
                    ),
                    InputRequirement(
                        "calendar",
                        "calendar.trading_sessions",
                        "SSE",
                        "daily",
                        0,
                        CutoffRule.SIGNAL_SESSION,
                    ),
                )
            ),
            decision=DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION"),
            execution=ExecutionPolicy(
                "FROZEN_RULE",
                {
                    "instrument": {
                        "lot_size": 100,
                        "price_tick": 0.001,
                        "price_limit_ratio": 0.1,
                        "maximum_order_quantity": 1_000_000,
                    },
                    "capital": {
                        "mode": "AVAILABLE_CASH",
                        "allocation_fraction": 1.0,
                        "fee_rate": 0.001,
                        "target_scope": "STRATEGY",
                    },
                    "entry": {"order_type": "LIMIT", "limit_parameter": 0.01},
                    "exit": {"order_type": "MARKET", "limit_ratio": 0.1},
                },
            ),
            monitoring=MonitoringPolicy("RESEARCH", {"frequency_window_sessions": 60}),
            capabilities=RequiredCapabilities(
                ("etf.ohlcv", "etf.unadjusted_daily", "calendar.trading_sessions"),
                ("LIMIT", "MARKET"),
                ("OPEN",),
            ),
            tradable_symbol="510500.SH",
            observation=ObservationDefinition((), ()),
        )

    def calendar_request(self, window):
        start = window.start - timedelta(days=242)
        return DataRequest(
            Dataset.TRADING_CALENDAR,
            "SSE",
            start.isoformat(),
            window.end.isoformat(),
            window.end.isoformat(),
        )

    def derive_calculation_scope(self, window, calendar_dates):
        trading = tuple(day for day in calendar_dates if window.contains(day))
        if not trading or trading[0] != window.start or trading[-1] != window.end:
            raise ValueError("original open-session endpoints required")
        signals = {}
        for day in trading:
            previous = tuple(item for item in calendar_dates if item < day)
            if not previous:
                raise ValueError("preceding signal session missing")
            signals[day] = previous[-1]
        first, last = signals[trading[0]], signals[trading[-1]]
        available = tuple(day for day in calendar_dates if day <= first)
        requests = {}
        for item in self.definition.inputs.requirements:
            if item.dataset == Dataset.TRADING_CALENDAR.value:
                continue
            depth = max(1, item.lookback_sessions)
            if len(available) < depth:
                raise ValueError("existing original calendar cannot satisfy history")
            coverage = DataCoverageRequirement(
                maximum_start_lag_days=None,
                minimum_observations=depth,
                minimum_sessions=depth,
                observations_through=first.isoformat(),
            )
            requests[item.name] = DataRequest(
                item.dataset,
                item.subject,
                available[-depth].isoformat(),
                last.isoformat(),
                last.isoformat(),
                item.frequency,
                coverage=coverage,
            )
        calculation = tuple(day for day in calendar_dates if first <= day <= last)
        return CalculationScope(window, trading, signals, calculation, requests)

    def calculate_history(self, inputs, sessions):
        daily = inputs["daily"]
        close = pd.Series(
            daily.Close.to_numpy(), index=pd.DatetimeIndex(pd.to_datetime(daily.Date)).normalize()
        )
        history = decisions(close, sessions, **self._parameters.values)
        return history.rename(columns={"reason": "signal_reason"})
