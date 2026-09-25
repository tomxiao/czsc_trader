"""Acceptance-only parameterized SRT using a non-OHLCV input.

Tests install this source in an isolated SRT package path. It is never a
production strategy or registered frozen release.
"""

from datetime import date

import pandas as pd
from dataflows import Dataset
from strategy_runtime import (
    CalculationScope,
    CalendarWindow,
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
    StrategyCandidate,
    StrategyImplementation,
    TradableWindow,
    next_session_calculation_scope,
    next_session_calendar_window,
)


class CandidateFixture(StrategyImplementation):
    def __init__(self, identity):
        candidate = isinstance(identity, StrategyCandidate)
        payload = identity.payload
        ref = payload["runtime"]
        reference_symbols = tuple(payload["parameters"].get("reference_symbols", ()))
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
        self._definition = RuntimeDefinition(
            schema_version=2,
            strategy_family_id=identity.strategy_family_id,
            version=None if candidate else identity.version,
            release_id=identity.reference_id if candidate else identity.release_id,
            release_hash=identity.runtime_identity_sha256 if candidate else identity.release_hash,
            implementation=ImplementationRef(
                ref["module"],
                ref["qualname"],
                ref["contract_version"],
                ref["source_sha256"],
            ),
            parameters=ParameterSet(payload["parameters"]),
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
                        "limit_parameter": payload["parameters"].get("entry_premium", 0.0),
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
            identity_kind="CANDIDATE" if candidate else "RELEASE",
            candidate_id=identity.candidate_id if candidate else None,
        )

    @classmethod
    def from_candidate(cls, candidate):
        return cls(candidate)

    @classmethod
    def from_release(cls, release):
        return cls(release)

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
        return pd.DataFrame({"target_position": target}, index=sessions)
