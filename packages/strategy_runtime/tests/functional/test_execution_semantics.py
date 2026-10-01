from datetime import date, datetime, timezone
from types import SimpleNamespace
from pathlib import Path
from decimal import Decimal

import pandas as pd
import pytest
from strategy_runtime import (
    ExecutionCapabilities,
    ExecutionOutcome,
    ExecutionOutcomeStatus,
    ExecutionState,
    PortfolioSnapshot,
    OrderType,
    RuntimeCompatibilityError,
    RuntimeContractError,
    RuntimeExecutionError,
    SignalHistoryMode,
    StrategyInstance,
    TradableWindow,
    TradingPoint,
)


def _instance(history):
    sessions = pd.DatetimeIndex(["2026-01-02", "2026-01-05"])
    window_sessions = sessions[1:]
    definition = SimpleNamespace(
        decision=SimpleNamespace(minimum_target=0, maximum_target=1),
        capabilities=SimpleNamespace(order_types=("LIMIT",), checkpoints=()),
    )
    algorithm = SimpleNamespace(
        definition=definition,
        calculate_history=lambda frames, dates: history.reindex(dates),
        calculate_window_history=lambda frames, dates: history.reindex(dates),
    )
    instance = StrategyInstance(
        algorithm=algorithm,
        identity=None,
        tradable_window=TradableWindow(date(2026, 1, 6), date(2026, 1, 6)),
        data_dir=Path(".tmp"),
        execution_policy=None,
    )
    instance._prepared_data = SimpleNamespace(
        _inputs=SimpleNamespace(results={}, signal_dates={date(2026, 1, 6): date(2026, 1, 5)}),
        dataset_identity="test",
        calculation_dates=lambda: tuple(sessions.date),
        trading_dates=lambda: (date(2026, 1, 6),),
        signal_date_for=lambda day: date(2026, 1, 5),
    )
    return instance, sessions, window_sessions


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 2, "bad"])
def test_invalid_history_targets_are_rejected_at_history_boundary(value):
    history = pd.DataFrame(
        {"target_position": [0, value]}, index=pd.to_datetime(["2026-01-02", "2026-01-05"])
    )
    instance, _, _ = _instance(history)
    with pytest.raises(RuntimeContractError, match="invalid target"):
        instance.inspect_signals()


def test_history_modes_use_distinct_session_scopes_and_defensive_outputs():
    history = pd.DataFrame(
        {"target_position": [0.0, 1.0]}, index=pd.to_datetime(["2026-01-02", "2026-01-05"])
    )
    instance, continuous, window = _instance(history)
    assert instance.inspect_signals(history_mode=SignalHistoryMode.CONTINUOUS).index.equals(
        continuous
    )
    assert instance.inspect_signals(history_mode=SignalHistoryMode.WINDOW).index.equals(window)
    with pytest.raises(RuntimeContractError, match="SignalHistoryMode"):
        instance.inspect_signals(history_mode="WINDOW")


def test_missing_executor_capability_fails_before_snapshot_or_execute():
    instance, _, _ = _instance(pd.DataFrame())
    executor = SimpleNamespace(
        capabilities=ExecutionCapabilities(()),
        snapshot=lambda point: pytest.fail("must fail before snapshot"),
        execute=lambda plan: pytest.fail("must fail before execution"),
    )
    with pytest.raises(RuntimeCompatibilityError, match="before execution"):
        instance.run_window(executor=executor)


def test_failed_execution_outcome_does_not_finish_window(monkeypatch):
    instance, _, _ = _instance(pd.DataFrame())
    plan = SimpleNamespace(
        plan_identity="a" * 64, required_capabilities=ExecutionCapabilities((OrderType.LIMIT,))
    )
    monkeypatch.setattr(instance, "_plan_at", lambda **kwargs: plan)
    now = datetime.now(timezone.utc)
    portfolio = PortfolioSnapshot("test", "588080.SH", Decimal(100), Decimal(100), 0, 0, now)
    state = ExecutionState(0, now)
    executor = SimpleNamespace(
        capabilities=ExecutionCapabilities((OrderType.LIMIT,)),
        snapshot=lambda point: (None, None),
        execute=lambda plan: ExecutionOutcome(plan.plan_identity, portfolio, state, ExecutionOutcomeStatus.FAILED),
        finish=lambda: pytest.fail("failed execution must not finish successfully"),
    )
    with pytest.raises(RuntimeExecutionError, match="did not settle"):
        instance.run_window(executor=executor)


def test_execution_status_and_calendar_contracts_are_strict():
    with pytest.raises(RuntimeContractError, match="ExecutionOutcomeStatus"):
        ExecutionOutcome("a" * 64, None, None, "SETTLED")
    with pytest.raises(RuntimeContractError, match="OrderType"):
        ExecutionCapabilities(("LIMIT",))
    with pytest.raises(RuntimeContractError, match="date"):
        TradableWindow(datetime.now(), datetime.now())
    with pytest.raises(RuntimeContractError, match="date"):
        TradingPoint("2026-01-06", datetime.now(timezone.utc))
