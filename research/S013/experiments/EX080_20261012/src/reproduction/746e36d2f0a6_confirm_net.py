"""SOURCE ONLY: native SRT adapter; no execution or data access on import.

Future materialization: strategies/confirm_net.py beside exact frozen confirm_kernel.py.
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

from .confirm_kernel import parameters, rebuild, annual_forecasts, episode_history
from strategy_runtime.pricing import ExecutionPricing, ExecutionPriceBasis
from datetime import date


class ConfirmNet(StrategyImplementation):
    def __init__(self, parameters_value):
        if set(parameters_value.values) != {
            "confirmation_lookback",
            "holding_sessions",
            "ridge_alpha",
        }:
            raise ValueError("exact three effective parameter contract")
        parameters(**parameters_value.values)
        self._parameters = parameters_value

    @classmethod
    def from_parameters(cls, parameters):
        return cls(parameters)

    @property
    def definition(self):
        # Exact original180 daily request supports normalization120 plus raw20.
        # Warmup depth is a data contract, never an additional searched parameter.
        return StrategyDefinition(
            parameters=self._parameters,
            inputs=InputContract(
                (
                    InputRequirement(
                        "daily", "etf.ohlcv", "510500.SH", "daily", 180, CutoffRule.SIGNAL_SESSION
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
                        "native_daily",
                        "etf.unadjusted_daily",
                        "510500.SH",
                        "daily",
                        1,
                        CutoffRule.SIGNAL_SESSION,
                    ),
                    InputRequirement(
                        "intraday",
                        "etf.unadjusted_intraday",
                        "510500.SH",
                        "30m",
                        0,
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
                (
                    "etf.ohlcv",
                    "etf.unadjusted_daily",
                    "etf.unadjusted_intraday",
                    "calendar.trading_sessions",
                ),
                ("LIMIT", "MARKET"),
                ("OPEN",),
            ),
            tradable_symbol="510500.SH",
            observation=ObservationDefinition((), ()),
        )

    def calendar_request(self, window):
        start = window.start - timedelta(days=360)
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
            if item.name in ("native_daily", "intraday"):
                requests[item.name] = DataRequest(
                    item.dataset,
                    item.subject,
                    (first if item.name == "native_daily" else window.start).isoformat(),
                    window.end.isoformat(),
                    window.end.isoformat(),
                    item.frequency,
                )
                continue
            depth = 180 if item.name == "daily" else max(1, item.lookback_sessions)
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
        p = self._parameters.values
        rename = {
            "Date": "dt",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "vol",
            "Amount": "amount",
        }

        def numerical(f):
            out = f.loc[:, list(rename)].rename(columns=rename).copy()
            out.dt = pd.to_datetime(out.dt).dt.as_unit("ns")
            return out

        adjusted = numerical(inputs["daily"])
        raw = numerical(inputs["native_daily"])
        intra = numerical(inputs["intraday"])
        last = pd.Timestamp(sessions[-1])
        raw = raw.loc[raw.dt <= last].copy()
        intra = intra.loc[intra.dt.dt.normalize() <= last].copy()
        pricing = ExecutionPricing(ExecutionPriceBasis.HFQ_RESEARCH, date(2019, 12, 31), 0.2803)
        native = pricing.apply(raw, raw_daily=raw, adjusted_daily=adjusted).rename(
            columns={v: k for k, v in rename.items()}
        )
        bars = pricing.apply(intra, raw_daily=raw, adjusted_daily=adjusted).rename(
            columns={v: k for k, v in rename.items()}
        )
        feature = rebuild(inputs["daily"], native, bars, sessions, p["confirmation_lookback"])
        prices = native.set_index("Date")
        prices.index = pd.DatetimeIndex(prices.index).as_unit("ns")
        scores, proof = annual_forecasts(
            feature, prices, sessions, p["holding_sessions"], p["ridge_alpha"]
        )
        history = episode_history(scores, sessions, p["holding_sessions"])
        # JSON-safe known-time audit metadata only, never file/model IO.
        history["common14_available"] = feature.notna().all(axis=1)
        history["confirmation_score"] = feature.confirmation_score
        history["train_n"] = [proof.get(str(t.year), {}).get("train_n", 0) for t in history.index]
        history["train_max_maturity"] = [
            proof.get(str(t.year), {}).get("max_maturity") for t in history.index
        ]
        history["close"] = (
            inputs["daily"]
            .set_index(pd.DatetimeIndex(pd.to_datetime(inputs["daily"].Date)).as_unit("ns"))
            .Close.reindex(history.index)
        )
        return history
