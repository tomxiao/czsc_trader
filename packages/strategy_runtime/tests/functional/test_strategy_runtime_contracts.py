from __future__ import annotations
import pytest
from strategy_runtime import (
    DecisionContract,
    ExecutionPolicy,
    ImplementationRef,
    InputContract,
    MonitoringPolicy,
    ParameterSet,
    RequiredCapabilities,
    RuntimeDefinition,
    ObservationDefinition,
    RuntimeContractError,
    StrategyImplementation,
)
from packages.strategy_runtime.tests.authoring_fixture_support import (
    _author_type,
    _requirement,
)

RELEASE_HASH = "a" * 64


@pytest.mark.parametrize(
    "missing_method",
    [
        "from_parameters",
    ],
    ids=["SRT-03-C12"],
)
def test_strategy_implementation_requires_every_strategy_owned_method(missing_method) -> None:
    parameters = ParameterSet({"entry_threshold": 0.1})
    complete = _author_type().from_parameters(parameters)
    assert isinstance(complete, StrategyImplementation)
    assert complete.definition.parameters == parameters

    incomplete = _author_type(missing_method=missing_method)
    with pytest.raises(TypeError, match=missing_method):
        incomplete(parameters)


def test_SRT_03_C13_runtime_definition_requires_input_capabilities() -> None:
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
