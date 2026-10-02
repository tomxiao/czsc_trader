from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest
from dataflows import DataRequest, DataStatus, Dataflows, Dataset
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


ROOT = Path(__file__).resolve().parents[4]
CASES = json.loads(
    (ROOT / "tests/fixtures/s008_research_cases/public_contract_cases.json").read_text(
        encoding="utf-8"
    )
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


def test_c01_unknown_dataset_fixture_preserves_the_supported_contract() -> None:
    case = CASES["c01_unknown_dataset"]
    request = DataRequest(
        dataset=case["invalid_dataset"],
        symbol="SSE",
        start="2026-09-01",
        end="2026-09-02",
        required_cutoff=None,
    )

    result = Dataflows({}).fetch(request)

    assert case["valid_dataset"] == Dataset.TRADING_CALENDAR.value
    assert result.status is DataStatus.FAILED
    assert result.error is not None
    assert result.error.code == case["expected_error_code"]
    assert result.error.context["dataset"] == case["invalid_dataset"]


def test_c02_preparation_result_fixture_pins_the_public_field_name() -> None:
    case = CASES["c02_preparation_result_field"]
    window = TradableWindow(date(2026, 9, 2), date(2026, 9, 3))
    result = DataPreparationResult(
        StrategyIdentity("S008", "S008-C0001", "a" * 64, "b" * 64, "518880.SH"),
        window,
        date(2026, 9, 2),
        "c" * 64,
    )

    assert getattr(result, case["valid_field"]) == "c" * 64
    with pytest.raises(AttributeError):
        getattr(result, case["invalid_field"])
