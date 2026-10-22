from __future__ import annotations

from datetime import date

import pytest
from dataflows import DataRequest, Dataset
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
    RuntimeContractError,
    TradableWindow,
    implementation_sha256,
)


def test_strategy_authoring_contracts_are_public() -> None:
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


def test_unknown_dataset_preserves_the_supported_contract() -> None:
    with pytest.raises(ValueError):
        DataRequest(
            dataset="market.trading_calendar",
            symbol="SSE",
            start="2026-09-01",
            end="2026-09-02",
            required_cutoff=None,
        )
    assert Dataset.TRADING_CALENDAR.value == "calendar.trading_sessions"


def test_calculation_scope_requires_complete_typed_requests() -> None:
    window = TradableWindow(date(2026, 9, 3), date(2026, 9, 3))
    signal = date(2026, 9, 2)
    request = DataRequest(Dataset.SHIBOR_DAILY, None, '2026-09-01', '2026-09-02', None)
    scope = CalculationScope(window, (window.start,), {window.start: signal}, (signal,), {'rates': request})
    assert scope.inputs['rates'] is request
    with pytest.raises(TypeError):
        scope.inputs['rates'] = request
    with pytest.raises(RuntimeContractError, match='named DataRequest'):
        CalculationScope(window, (window.start,), {window.start: signal}, (signal,), {'rates': (signal, signal)})
