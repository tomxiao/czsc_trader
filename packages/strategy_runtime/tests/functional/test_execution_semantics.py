from datetime import date, datetime, timezone
from types import SimpleNamespace
from pathlib import Path
from decimal import Decimal

import pandas as pd
import pytest
from czsc_trader.application.ec_boundary import session_execution_plan
from execution_channels.serialization import from_record, to_record
from execution_channels.session_contracts import (
    PortfolioSnapshot as ChannelPortfolio,
    ExecutionState as ChannelState,
)
from strategy_runtime import (
    ExecutionPolicy,
    ExecutionState,
    ImplementationRef,
    PortfolioSnapshot,
    PriceReference,
    ObservationDefinition,
    RuntimeContractError,
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
        execution_policy=ExecutionPolicy(
            "FROZEN_RULE",
            {
                "capital": {
                    "fee_rate": 0.001,
                    "mode": "target_equity_fraction",
                    "target_scope": "decision",
                    "allocation_fraction": 1.0,
                },
                "entry": {"limit_parameter": 0.0, "order_type": "LIMIT"},
                "exit": {"limit_ratio": 0.1, "order_type": "MARKET"},
                "instrument": {
                    "lot_size": 100,
                    "maximum_order_quantity": 1_000_000,
                    "price_limit_ratio": 0.1,
                    "price_tick": 0.001,
                },
            },
        ),
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
        Decimal("10"),
        Decimal("10"),
        "hfq",
        "unadjusted",
    )
    instance._prepared_data.input_identities = {"fixture": "c" * 64}
    instance._prepared_data.price_identities = {"fixture": "d" * 64}
    now = datetime(2026, 1, 5, 22, tzinfo=timezone.utc)
    return session_execution_plan(
        instance.propose_at(point=TradingPoint(date(2026, 1, 6), now), history_mode=mode),
        from_record(
            ChannelPortfolio,
            to_record(
                PortfolioSnapshot(
                    "fixture", "588080.SH", Decimal("10000"), Decimal("10000"), 0, 0, now
                )
            ),
        ),
        from_record(ChannelState, to_record(ExecutionState(0, now))),
    )


@pytest.mark.parametrize(
    "extra,kind,action",
    [
        ({"signal_active": True}, "TARGET_POSITION", "INTRADAY_LONG_OVERLAY"),
    ],
    ids=["SRT-30-C03"],
)
def test_signal_keeps_explicit_and_overlay_actions(extra, kind, action):
    history = pd.DataFrame(
        {"target_position": [1.0, 0.0], **extra}, index=pd.to_datetime(["2026-01-02", "2026-01-05"])
    )
    instance, _, _ = _instance(history)
    instance.definition.decision.output_kind = kind
    for mode in SignalHistoryMode:
        signal = _plan(instance, mode)
        assert signal.evidence["action"] == action


def test_SRT_30_C04_signal_missing_date_preserves_contract_error():
    history = pd.DataFrame(
        {"target_position": [0.0, 1.0]}, index=pd.to_datetime(["2026-01-02", "2026-01-05"])
    )
    instance, _, _ = _instance(history)
    instance._prepared_data.signal_date_for = lambda day: date(2026, 1, 4)
    for mode in SignalHistoryMode:
        with pytest.raises(
            RuntimeContractError, match="does not reach the signal date: signal=2026-01-04"
        ):
            _plan(instance, mode)


@pytest.mark.parametrize(
    "previous,mode",
    [(0.0, SignalHistoryMode.CONTINUOUS), (1.0, SignalHistoryMode.WINDOW)],
    ids=["SRT-30-C01", "SRT-30-C02"],
)
def test_signal_uses_the_selected_mode_initial_state(previous, mode):
    history = pd.DataFrame(
        {"target_position": [previous, 1.0]}, index=pd.to_datetime(["2026-01-02", "2026-01-05"])
    )
    instance, _, _ = _instance(history)
    signal = _plan(instance, mode)
    assert signal.target_position == 1.0
    assert signal.evidence["action"] == "BUY" and signal.signal_date == date(2026, 1, 5)
