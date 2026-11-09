from __future__ import annotations


from strategy_runtime import (
    CalculationScope,
    CutoffRule,
    DecisionContract,
    ExecutionPolicy,
    HistoryPolicy,
    ImplementationRef,
    InputContract,
    InputRequirement,
    MonitoringPolicy,
    ParameterSet,
    RequiredCapabilities,
    RuntimeDefinition,
    implementation_sha256,
)


def test_SRT_28_C07_strategy_authoring_contracts_are_public() -> None:
    import strategy_runtime

    expected = {
        "CalculationScope": CalculationScope,
        "CutoffRule": CutoffRule,
        "DecisionContract": DecisionContract,
        "ExecutionPolicy": ExecutionPolicy,
        "HistoryPolicy": HistoryPolicy,
        "ImplementationRef": ImplementationRef,
        "InputContract": InputContract,
        "InputRequirement": InputRequirement,
        "MonitoringPolicy": MonitoringPolicy,
        "ParameterSet": ParameterSet,
        "RequiredCapabilities": RequiredCapabilities,
        "RuntimeDefinition": RuntimeDefinition,
        "implementation_sha256": implementation_sha256,
    }

    assert set(expected) <= set(strategy_runtime.__all__)
    assert all(getattr(strategy_runtime, name) is value for name, value in expected.items())
