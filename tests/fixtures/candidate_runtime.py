"""Acceptance-only parameterized SRT using a non-OHLCV input.

Tests install and freeze this source only in isolated test repositories.
"""

from datetime import date, timedelta

import pandas as pd
from dataflows import Dataset, DataRequest, DataCoverageRequirement
from strategy_runtime import (
    ObservationDefinition,
    ObservationSeries,
    CalculationScope,
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
)


class CandidateFixture(StrategyImplementation):
    def __init__(self, parameters: ParameterSet):
        reference_symbols = tuple(parameters.values.get("reference_symbols", ()))
        requirements = [
            InputRequirement(
                "flow",
                Dataset.ETF_SHARE_SIZE.value,
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
            observation=ObservationDefinition(
                (ObservationSeries("fixture", "鍚堟垚淇″彿", "fixture_signal"),), ()
            ),
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
                        "order_type": parameters.values.get("entry_order_type", "LIMIT"),
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

    def calendar_request(self, tradable_window: TradableWindow) -> DataRequest:
        start = tradable_window.start - timedelta(days=31)
        end = tradable_window.end + timedelta(days=20)
        return DataRequest(
            Dataset.TRADING_CALENDAR, "SSE", start.isoformat(), end.isoformat(), end.isoformat()
        )

    def derive_calculation_scope(
        self,
        tradable_window: TradableWindow,
        calendar_dates: tuple[date, ...],
    ) -> CalculationScope:
        trading_dates = tuple(day for day in calendar_dates if tradable_window.contains(day))
        signal_dates = {
            day: max(prior for prior in calendar_dates if prior < day) for day in trading_dates
        }
        first_signal, last_signal = min(signal_dates.values()), max(signal_dates.values())
        requests = {}
        for requirement in self.definition.inputs.requirements:
            if requirement.dataset == Dataset.TRADING_CALENDAR.value:
                continue
            previous = tuple(day for day in calendar_dates if day <= first_signal)
            start = previous[-max(1, requirement.lookback_sessions)]
            end = last_signal
            cutoff = last_signal
            if requirement.cutoff_rule is CutoffRule.PREVIOUS_SESSION:
                end = cutoff = max(day for day in calendar_dates if day < last_signal)
            elif requirement.cutoff_rule is CutoffRule.LATEST_AVAILABLE:
                start -= timedelta(days=requirement.maximum_staleness_days)
                cutoff = max(
                    start, last_signal - timedelta(days=requirement.maximum_staleness_days)
                )
            coverage = (
                DataCoverageRequirement(
                    maximum_start_lag_days=None,
                    minimum_observations=requirement.lookback_sessions,
                    minimum_sessions=requirement.lookback_sessions,
                    observations_through=min(first_signal, end).isoformat(),
                )
                if requirement.lookback_sessions
                else None
            )
            requests[requirement.name] = DataRequest(
                requirement.dataset,
                requirement.subject,
                start.isoformat(),
                end.isoformat(),
                cutoff.isoformat(),
                requirement.frequency,
                coverage=coverage,
            )
        calculation_dates = tuple(
            day for day in calendar_dates if first_signal <= day <= last_signal
        )
        return CalculationScope(
            tradable_window, trading_dates, signal_dates, calculation_dates, requests
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
