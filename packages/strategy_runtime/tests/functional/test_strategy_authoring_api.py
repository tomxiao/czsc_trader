from __future__ import annotations

from datetime import date

import pytest
from dataflows import DataRequest, Dataset
from strategy_runtime import (
    CalculationScope,
    CalendarWindow,
    CutoffRule,
    DataPreparationResult,
    DecisionContract,
    ExecutionPolicy,
    HistoryPolicy,
    ImplementationRef,
    InputContract,
    InputRange,
    InputRequirement,
    MonitoringPolicy,
    ParameterSet,
    RequiredCapabilities,
    RuntimeDefinition,
    StrategyIdentity,
    TradableWindow,
    implementation_sha256,
    next_session_calculation_scope,
    next_session_calendar_window,
)


def test_strategy_authoring_contracts_are_public() -> None:
    import strategy_runtime

    expected = {
        "CalculationScope": CalculationScope,
        "CalendarWindow": CalendarWindow,
        "CutoffRule": CutoffRule,
        "DecisionContract": DecisionContract,
        "ExecutionPolicy": ExecutionPolicy,
        "HistoryPolicy": HistoryPolicy,
        "ImplementationRef": ImplementationRef,
        "InputContract": InputContract,
        "InputRange": InputRange,
        "InputRequirement": InputRequirement,
        "MonitoringPolicy": MonitoringPolicy,
        "ParameterSet": ParameterSet,
        "RequiredCapabilities": RequiredCapabilities,
        "RuntimeDefinition": RuntimeDefinition,
        "implementation_sha256": implementation_sha256,
        "next_session_calculation_scope": next_session_calculation_scope,
        "next_session_calendar_window": next_session_calendar_window,
    }

    assert set(expected) <= set(strategy_runtime.__all__)
    assert all(getattr(strategy_runtime, name) is value for name, value in expected.items())
    assert not hasattr(strategy_runtime, "StrategyLoader")


def test_unknown_dataset_preserves_the_supported_contract() -> None:
    with pytest.raises(ValueError):
        DataRequest(dataset="market.trading_calendar", symbol="SSE", start="2026-09-01",
                    end="2026-09-02", required_cutoff=None)
    assert Dataset.TRADING_CALENDAR.value == "calendar.trading_sessions"



def test_preparation_result_exposes_the_public_field_name() -> None:
    window = TradableWindow(date(2026, 9, 2), date(2026, 9, 3))
    result = DataPreparationResult(
        StrategyIdentity("S900", "S900-C0001", "a" * 64, "b" * 64, "518880.SH"),
        window,
        date(2026, 9, 2),
        "c" * 64,
    )

    assert result.data_identity == "c" * 64
    with pytest.raises(AttributeError):
        getattr(result, "dataset_identity")
