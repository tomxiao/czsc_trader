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
    ExecutionPolicy,
    ExecutionState,
    ImplementationRef,
    PortfolioSnapshot,
    PriceReference,
    OrderType,
    ObservationDefinition,
    RuntimeCompatibilityError,
    RuntimeContractError,
    RuntimeExecutionError,
    SignalHistoryMode,
    StrategyInstance,
    StrategyIdentity,
    TradableWindow,
    TradingPoint,
)


def _instance(history):
    sessions = pd.DatetimeIndex(["2026-01-02", "2026-01-05"])
    window_sessions = sessions[1:]
    definition = SimpleNamespace(
        observation=ObservationDefinition((), ()),
        implementation=ImplementationRef("fixture", "History", 1, "a" * 64),
        decision=SimpleNamespace(minimum_target=0, maximum_target=1, output_kind="TARGET_POSITION"),
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
        execution_policy=ExecutionPolicy("FROZEN_RULE", {
            "capital": {"fee_rate": 0.001, "mode": "target_equity_fraction",
                        "target_scope": "decision", "allocation_fraction": 1.0},
            "entry": {"limit_parameter": 0.0, "order_type": "LIMIT"},
            "exit": {"limit_ratio": 0.1, "order_type": "MARKET"},
            "instrument": {"lot_size": 100, "maximum_order_quantity": 1_000_000,
                           "price_limit_ratio": 0.1, "price_tick": 0.001},
        }),
    )
    instance._prepared_data = SimpleNamespace(
        _inputs=SimpleNamespace(results={}, signal_dates={date(2026, 1, 6): date(2026, 1, 5)}),
        dataset_identity="test",
        calculation_dates=lambda: tuple(sessions.date),
        trading_dates=lambda: (date(2026, 1, 6),),
        signal_date_for=lambda day: date(2026, 1, 5),
    )
    return instance, sessions, window_sessions


def _plan(instance, mode):
    """Exercise the public planning chain with a prepared, fixed-price fixture."""
    instance._identity = StrategyIdentity("S900", "S900-C0001", "a" * 64, "b" * 64, "588080.SH")
    instance._prepared_data.price_reference = lambda *args: PriceReference(
        Decimal("10"), Decimal("10"), "hfq", "unadjusted",
    )
    instance._prepared_data.input_identities = {"fixture": "c" * 64}
    instance._prepared_data.price_identities = {"fixture": "d" * 64}
    now = datetime(2026, 1, 5, 22, tzinfo=timezone.utc)
    return instance.plan_at(
        point=TradingPoint(date(2026, 1, 6), now),
        portfolio=PortfolioSnapshot("fixture", "588080.SH", Decimal("10000"),
                                    Decimal("10000"), 0, 0, now),
        state=ExecutionState(0, now), history_mode=mode,
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 2, "bad"])
def test_invalid_history_targets_are_rejected_at_history_boundary(value):
    history = pd.DataFrame(
        {"target_position": [0, value]}, index=pd.to_datetime(["2026-01-02", "2026-01-05"])
    )
    instance, _, _ = _instance(history)
    with pytest.raises(RuntimeContractError, match="invalid target"):
        instance.inspect_signals()


@pytest.mark.parametrize("previous,current,continuous_action,window_action", [
    (0.0, 0.0, "HOLD", "HOLD"),
    (0.0, 0.5, "BUY", "BUY"),
    (0.5, 1.0, "BUY", "BUY"),
    (1.0, 0.5, "SELL", "BUY"),
    (0.5, 0.5, "HOLD", "BUY"),
    (0.5, 0.0, "SELL", "HOLD"),
])
def test_signal_action_uses_predecessor_with_mode_initialization(
    previous, current, continuous_action, window_action,
):
    history = pd.DataFrame({
        "target_position": [previous, current],
        "observation": [1, 2],
        "observed_at": pd.to_datetime(["2026-01-02", "2026-01-05"]),
        "missing": [float("nan"), float("nan")],
    }, index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
    instance, _, _ = _instance(history)
    for mode, action in (
        (SignalHistoryMode.CONTINUOUS, continuous_action),
        (SignalHistoryMode.WINDOW, window_action),
    ):
        signal = _plan(instance, mode)
        assert signal.target_position == current
        assert signal.evidence == {
            "signal_date": "2026-01-05", "action": action,
            "observation": 2, "observed_at": "2026-01-05",
        }
        assert signal.signal_date == date(2026, 1, 5)
        exported = instance.inspect_signals(history_mode=mode)
        exported.loc[:, "target_position"] = 99.0
        assert _plan(instance, mode) == signal


@pytest.mark.parametrize("extra,kind,action", [
    ({"action": "DECLARED_ACTION"}, "TARGET_POSITION", "DECLARED_ACTION"),
    ({"signal_active": True}, "TARGET_POSITION", "INTRADAY_LONG_OVERLAY"),
    ({"signal_active": False}, "INTRADAY_OVERLAY", "NO_EVENT"),
])
def test_signal_keeps_explicit_and_overlay_actions(extra, kind, action):
    history = pd.DataFrame({"target_position": [1.0, 0.0], **extra},
                           index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
    instance, _, _ = _instance(history)
    instance.definition.decision.output_kind = kind
    for mode in SignalHistoryMode:
        signal = _plan(instance, mode)
        assert signal.evidence["action"] == action


def test_signal_missing_date_preserves_contract_error():
    history = pd.DataFrame({"target_position": [0.0, 1.0]},
                           index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
    instance, _, _ = _instance(history)
    instance._prepared_data.signal_date_for = lambda day: date(2026, 1, 4)
    for mode in SignalHistoryMode:
        with pytest.raises(RuntimeContractError, match="does not reach the signal date: signal=2026-01-04"):
            _plan(instance, mode)




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
