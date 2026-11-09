from __future__ import annotations


from dataclasses import fields


import pandas as pd




from dataflows import DataRequest, Dataset


from strategy_runtime import (
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
    ObservationDefinition,
    StrategyDefinition,
    StrategyImplementation,
    CalculationScope,
)


RELEASE_HASH = "a" * 64


def _author_type(*, missing_method=None):
    def initialize(self, parameters):
        self._parameters = parameters

    def from_parameters(cls, parameters):
        return cls(parameters)

    def definition(self):
        runtime = _definition()
        return StrategyDefinition(
            **{
                field.name: self._parameters
                if field.name == "parameters"
                else getattr(runtime, field.name)
                for field in fields(StrategyDefinition)
            }
        )

    def calendar_request(self, window):
        return DataRequest(
            Dataset.TRADING_CALENDAR, "SSE", window.start.isoformat(), window.end.isoformat(), None
        )

    def derive_calculation_scope(self, window, calendar_dates):
        first = calendar_dates[0]
        return CalculationScope(window, (window.start,), {window.start: first}, (first,), {})

    def calculate_history(self, inputs, sessions):
        return pd.DataFrame({"target_position": 0.0}, index=sessions)

    methods = {
        "__init__": initialize,
        "from_parameters": classmethod(from_parameters),
        "definition": property(definition),
        "calendar_request": calendar_request,
        "derive_calculation_scope": derive_calculation_scope,
        "calculate_history": calculate_history,
    }
    if missing_method is not None:
        del methods[missing_method]
    return type("ContractAuthor", (StrategyImplementation,), methods)


def _requirement() -> InputRequirement:
    return InputRequirement(
        name="daily_bars",
        dataset="etf.ohlcv",
        subject="588080.SH",
        frequency="daily",
        lookback_sessions=252,
        cutoff_rule=CutoffRule.SIGNAL_SESSION,
    )


def _definition() -> RuntimeDefinition:
    return RuntimeDefinition(
        schema_version=3,
        observation=ObservationDefinition((), ()),
        strategy_family_id="S007",
        version="v1",
        release_id="S007-v1",
        release_hash=RELEASE_HASH,
        implementation=ImplementationRef(
            "strategy_runtime.strategies.s007_v1",
            "S007V1",
            1,
            "b" * 64,
        ),
        parameters=ParameterSet({"entry_threshold": 0.1}),
        inputs=InputContract((_requirement(),)),
        decision=DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION"),
        execution=ExecutionPolicy("MARKETABLE_LIMIT", {"limit_ratio": 0.2}),
        monitoring=MonitoringPolicy("ROLLING", {"window_sessions": 60}),
        capabilities=RequiredCapabilities(("etf.ohlcv",), ("LIMIT",)),
        tradable_symbol="588080.SH",
    )
