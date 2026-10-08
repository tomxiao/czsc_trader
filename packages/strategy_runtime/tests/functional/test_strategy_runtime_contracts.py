from __future__ import annotations

from dataclasses import fields

import pandas as pd
import pytest
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
    RuntimeContractError,
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


@pytest.mark.parametrize(
    "missing_method",
    [
        "from_parameters",
        "definition",
        "calendar_request",
        "derive_calculation_scope",
        "calculate_history",
    ],
)
def test_strategy_implementation_requires_every_strategy_owned_method(missing_method) -> None:
    parameters = ParameterSet({"entry_threshold": 0.1})
    complete = _author_type().from_parameters(parameters)
    assert isinstance(complete, StrategyImplementation)
    assert complete.definition.parameters == parameters

    incomplete = _author_type(missing_method=missing_method)
    with pytest.raises(TypeError, match=missing_method):
        incomplete(parameters)


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


def test_runtime_definition_is_family_version_scoped_and_immutable() -> None:
    definition = _definition()

    assert definition.strategy_family_id == "S007"
    assert definition.release_id == "S007-v1"
    assert definition.parameters.sha256
    with pytest.raises(TypeError):
        definition.parameters.values["entry_threshold"] = 0.2

    nested = ParameterSet({"weights": {"price": 0.5}, "windows": [20, 60]})
    with pytest.raises(TypeError):
        nested.values["weights"]["price"] = 0.7
    assert nested.values["windows"] == (20, 60)


def test_runtime_definition_binds_and_validates_tradable_symbol() -> None:
    definition = _definition()

    assert definition.tradable_symbol == "588080.SH"
    with pytest.raises(RuntimeContractError, match="tradable_symbol"):
        RuntimeDefinition(
            schema_version=3,
            observation=ObservationDefinition((), ()),
            strategy_family_id="S007",
            version="v1",
            release_id="S007-v1",
            release_hash=RELEASE_HASH,
            implementation=ImplementationRef("runtime", "Strategy", 1, "b" * 64),
            parameters=ParameterSet({}),
            inputs=InputContract((_requirement(),)),
            decision=DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION"),
            execution=ExecutionPolicy("LIMIT", {}),
            monitoring=MonitoringPolicy("ROLLING", {}),
            capabilities=RequiredCapabilities(("etf.ohlcv",), ("LIMIT",)),
            tradable_symbol="SPX",
        )


def test_runtime_definition_requires_input_capabilities() -> None:
    with pytest.raises(RuntimeContractError, match="input datasets"):
        RuntimeDefinition(
            schema_version=3,
            observation=ObservationDefinition((), ()),
            strategy_family_id="S007",
            version="v1",
            release_id="S007-v1",
            release_hash=RELEASE_HASH,
            implementation=ImplementationRef("runtime", "Strategy", 1, "b" * 64),
            parameters=ParameterSet({}),
            inputs=InputContract((_requirement(),)),
            decision=DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION"),
            execution=ExecutionPolicy("LIMIT", {}),
            monitoring=MonitoringPolicy("ROLLING", {}),
            capabilities=RequiredCapabilities(("macro.shibor_daily",), ("LIMIT",)),
            tradable_symbol="588080.SH",
        )


def test_business_definition_excludes_identity_and_enforces_typed_contracts():
    from dataclasses import fields, replace
    from strategy_runtime import StrategyDefinition

    runtime = _definition()
    business = StrategyDefinition(
        **{f.name: getattr(runtime, f.name) for f in fields(StrategyDefinition)}
    )
    assert not hasattr(business, "release_id")
    assert not hasattr(business, "implementation")
    with pytest.raises(RuntimeContractError, match="parameters"):
        replace(business, parameters={})
    with pytest.raises(RuntimeContractError, match="tradable_symbol"):
        replace(business, tradable_symbol="wrong")
    with pytest.raises(RuntimeContractError, match="input datasets"):
        replace(business, capabilities=RequiredCapabilities(("other",), ("LIMIT",)))
