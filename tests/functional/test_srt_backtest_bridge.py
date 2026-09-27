from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from strategy_runtime import (
    ExecutionCapabilities,
    ExecutionPlan,
    ExecutionPolicy,
    OrderSide,
    OrderType,
    PlanLeg,
    PlannedOrder,
    PriceReference,
    RuntimeContractError,
    StrategyIdentity,
    TradingPoint,
)
from strategy_runtime.contracts import plan_identity_for, signal_identity_for

from trading_execution_engine import HistoricalExecutor
from czsc_trader.backtesting.srt_bridge import _validate_historical_decisions


def _execution_plan(
    *,
    reference: str,
    symbol: str,
    signal_date: str,
    valid_date: str,
    generated_at: datetime,
    portfolio,
    state,
    target_position: float,
    target_quantity: int,
    cycle_target_quantity: int,
    orders: tuple[PlannedOrder, ...] = (),
    legs: tuple[PlanLeg, ...] = (),
    plan_mode: str = "TARGET_POSITION",
    fee_rate: float = 0.001,
) -> ExecutionPlan:
    strategy = StrategyIdentity(
        reference.split("-")[0], reference, "a" * 64, "b" * 64, symbol
    )
    inputs = MappingProxyType({"fixture": "c" * 64})
    prices = MappingProxyType({"execution_daily": "d" * 64})
    signal = signal_identity_for(
        strategy=strategy,
        signal_date=pd.Timestamp(signal_date).date(),
        target_position=target_position,
        input_identities=inputs,
        price_identities=prices,
    )
    identity = plan_identity_for(
        signal_identity=signal,
        actual_quantity=portfolio.position_quantity,
        target_quantity=target_quantity,
        cycle_target_quantity=cycle_target_quantity,
        plan_mode=plan_mode,
        capital_mode="full_available_cash",
        allocation_fraction=Decimal("1"),
        orders=orders,
        legs=legs,
    )
    return ExecutionPlan(
        strategy=strategy,
        signal_identity=signal,
        plan_identity=identity,
        symbol=symbol,
        signal_date=pd.Timestamp(signal_date).date(),
        trading_date=pd.Timestamp(valid_date).date(),
        generated_at=generated_at,
        expected_portfolio_revision=portfolio.revision,
        expected_state_revision=state.revision,
        actual_quantity=portfolio.position_quantity,
        target_quantity=target_quantity,
        cycle_target_quantity=cycle_target_quantity,
        target_position=target_position,
        action="PLAN",
        plan_mode=plan_mode,
        capital_mode="full_available_cash",
        allocation_fraction=Decimal("1"),
        orders=orders,
        legs=legs,
        available_cash=portfolio.available_cash,
        fee_rate=Decimal(str(fee_rate)),
        estimated_order_cost=Decimal("0"),
        unallocated_cash=Decimal("0"),
        references=PriceReference(Decimal("1"), Decimal("1"), "close", "open"),
        required_capabilities=ExecutionCapabilities(
            tuple(dict.fromkeys(order.order_type for order in orders + tuple(leg.order for leg in legs))),
            tuple(dict.fromkeys(leg.checkpoint for leg in legs)),
        ),
        input_identities=inputs,
        price_identities=prices,
        evidence=MappingProxyType({"signal_date": signal_date}),
    )


def test_srt_history_allows_unavailable_diagnostics_during_warmup() -> None:
    sessions = pd.DatetimeIndex(pd.to_datetime(["2026-09-16", "2026-09-17"]), name="dt")
    history = pd.DataFrame(
        {
            "base_score": [0.2, float("nan")],
            "confirmation_score": [0.1, 0.1],
            "target_position": [0.0, 0.0],
        },
        index=sessions,
    )

    _validate_historical_decisions(history, sessions)


def test_srt_history_rejects_unavailable_target_position() -> None:
    sessions = pd.DatetimeIndex(pd.to_datetime(["2026-09-16", "2026-09-17"]), name="dt")
    history = pd.DataFrame(
        {
            "base_score": [0.2, 0.3],
            "target_position": [0.0, float("nan")],
        },
        index=sessions,
    )

    with pytest.raises(RuntimeContractError, match="target_position"):
        _validate_historical_decisions(history, sessions)


def test_txe_historical_executor_refuses_to_finish_with_missing_session_plan() -> None:
    daily = pd.DataFrame(
        [{"dt": pd.Timestamp("2026-09-18"), "open": 1.0, "close": 1.0}]
    )
    channel = HistoricalExecutor(
        strategy_reference="S001-v1",
        symbol="588080.SH",
        execution_daily=daily,
        execution_intraday=pd.DataFrame(columns=["dt", "open", "high", "low", "close"]),
        evaluation_start=pd.Timestamp("2026-09-18"),
        evaluation_end=pd.Timestamp("2026-09-18"),
        initial_cash=100_000,
        execution_policy=ExecutionPolicy(
            "FROZEN_RULE",
            {
                "capital": {"fee_rate": 0.001, "mode": "full_available_cash"},
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
        order_types=("LIMIT",),
    )

    with pytest.raises(RuntimeContractError, match="incomplete target-position plans"):
        channel.finish()


@pytest.mark.parametrize("fee_rate", [-0.01, 1.0, "invalid"])
def test_txe_historical_executor_rejects_invalid_policy_fee_rate(fee_rate) -> None:
    daily = pd.DataFrame(
        [{"dt": pd.Timestamp("2026-09-18"), "open": 1.0, "close": 1.0}]
    )
    policy = ExecutionPolicy("FROZEN_RULE", {"capital": {"fee_rate": fee_rate}})
    with pytest.raises(RuntimeContractError, match="policy .*fee rate"):
        HistoricalExecutor(
            strategy_reference="S001-v1",
            symbol="588080.SH",
            execution_daily=daily,
            execution_intraday=pd.DataFrame(columns=["dt", "high", "low"]),
            evaluation_start=pd.Timestamp("2026-09-18"),
            evaluation_end=pd.Timestamp("2026-09-18"),
            initial_cash=100_000,
            execution_policy=policy,
            order_types=("LIMIT",),
        )


def test_txe_historical_executor_executes_requests_against_its_confirmed_ledger() -> None:
    daily = pd.DataFrame(
        [
            {"dt": pd.Timestamp("2026-09-16"), "open": 1.0, "close": 1.0},
            {"dt": pd.Timestamp("2026-09-17"), "open": 1.0, "close": 1.1},
            {"dt": pd.Timestamp("2026-09-18"), "open": 1.1, "close": 1.1},
        ]
    )
    intraday = pd.DataFrame(
        [
            {
                "dt": pd.Timestamp("2026-09-17 10:00"),
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
            },
            {
                "dt": pd.Timestamp("2026-09-18 10:00"),
                "open": 1.1,
                "high": 1.1,
                "low": 1.1,
                "close": 1.1,
            },
        ]
    )
    replay_data = SimpleNamespace(
        execution_daily=daily,
        execution_intraday=intraday,
        adjusted=SimpleNamespace(daily=daily),
    )
    policy = ExecutionPolicy(
        "FROZEN_RULE",
        {
            "capital": {
                "allocation_fraction": 1.0,
                "fee_rate": 0.001,
                "mode": "full_available_cash",
                "target_scope": "entry_cycle",
            },
            "entry": {"limit_parameter": 0.0, "order_type": "LIMIT"},
            "exit": {"limit_ratio": 0.1, "order_type": "LIMIT"},
            "instrument": {
                "lot_size": 100,
                "maximum_order_quantity": 1_000_000,
                "price_limit_ratio": 0.1,
                "price_tick": 0.001,
            },
        },
    )
    channel = HistoricalExecutor(
        strategy_reference="S999-v1",
        symbol="588080.SH",
        execution_daily=replay_data.execution_daily,
        execution_intraday=replay_data.execution_intraday,
        evaluation_start=pd.Timestamp("2026-09-17"),
        evaluation_end=pd.Timestamp("2026-09-18"),
        initial_cash=100_000,
        execution_policy=policy,
        order_types=("LIMIT",),
    )
    zone = ZoneInfo("Asia/Shanghai")
    outcomes = []
    for revision, (signal_date, valid_date, target, target_quantity, order) in enumerate(
        (
            (
                "2026-09-16",
                "2026-09-17",
                1.0,
                99_900,
                PlannedOrder(OrderSide.BUY, 99_900, OrderType.LIMIT, Decimal("1.0")),
            ),
            (
                "2026-09-17",
                "2026-09-18",
                0.0,
                0,
                PlannedOrder(OrderSide.SELL, 99_900, OrderType.LIMIT, Decimal("0.99")),
            ),
        )
    ):
        generated_at = datetime.fromisoformat(f"{signal_date}T20:30:00").replace(tzinfo=zone)
        point = TradingPoint(pd.Timestamp(valid_date).date(), generated_at)
        portfolio, state = channel.snapshot(point)
        assert portfolio.revision == state.revision == revision
        plan = _execution_plan(
            reference="S999-v1",
            symbol="588080.SH",
            signal_date=signal_date,
            valid_date=valid_date,
            generated_at=generated_at,
            portfolio=portfolio,
            state=state,
            target_position=target,
            target_quantity=target_quantity,
            cycle_target_quantity=99_900,
            orders=(order,),
        )
        if revision == 0:
            with pytest.raises(RuntimeContractError, match="fee rate differs"):
                channel.execute(replace(plan, fee_rate=Decimal("0.003")))
            assert channel.snapshot(point)[0].revision == 0
        outcomes.append(channel.execute(plan))

    result = channel.finish()
    assert [outcome.status for outcome in outcomes] == ["SETTLED", "SETTLED"]
    assert result.orders["side"].tolist() == ["BUY", "SELL"]
    assert result.fills["side"].tolist() == ["BUY", "SELL"]
    assert result.account_daily["quantity"].tolist() == [99_900, 0]
    assert result.account_daily.iloc[-1]["cash"] > 109_000


@pytest.mark.parametrize("fee_rate", [0.00012, 0.002])
def test_txe_historical_executor_executes_intraday_overlay_plan(fee_rate) -> None:
    daily = pd.DataFrame(
        [
            {"dt": pd.Timestamp("2026-09-16"), "open": 10.0, "close": 10.0},
            {"dt": pd.Timestamp("2026-09-17"), "open": 10.0, "close": 10.1},
            {"dt": pd.Timestamp("2026-09-18"), "open": 10.0, "close": 10.2},
        ]
    )
    five = pd.DataFrame(
        [
            {
                "dt": pd.Timestamp("2026-09-17 09:35"),
                "open": 10.0,
                "high": 10.1,
                "low": 9.9,
                "close": 10.0,
            },
            {
                "dt": pd.Timestamp("2026-09-17 11:30"),
                "open": 10.1,
                "high": 10.3,
                "low": 10.0,
                "close": 10.2,
            },
            {
                "dt": pd.Timestamp("2026-09-18 09:35"),
                "open": 10.0,
                "high": 10.1,
                "low": 9.9,
                "close": 10.0,
            },
            {
                "dt": pd.Timestamp("2026-09-18 11:30"),
                "open": 10.1,
                "high": 10.3,
                "low": 10.0,
                "close": 10.2,
            },
        ]
    )
    replay_data = SimpleNamespace(
        execution_daily=daily,
        execution_intraday=pd.DataFrame(
            columns=["dt", "open", "high", "low", "close"]
        ),
        execution_five_minute=five,
        adjusted=SimpleNamespace(daily=daily),
    )
    policy = ExecutionPolicy(
        "INTRADAY_OVERLAY",
        {
            "core_fraction": 0.5,
            "event_fraction": 0.5,
            "lot_size": 100,
            "one_way_cost": fee_rate,
        },
    )
    channel = HistoricalExecutor(
        strategy_reference="S003-v1",
        symbol="510500.SH",
        execution_five_minute=five,
        execution_daily=replay_data.execution_daily,
        execution_intraday=replay_data.execution_intraday,
        evaluation_start=pd.Timestamp("2026-09-17"),
        evaluation_end=pd.Timestamp("2026-09-18"),
        initial_cash=100_000,
        execution_policy=policy,
        order_types=("LIMIT", "MARKET"),
        checkpoints=("OPEN", "11:30_CLOSE"),
    )
    zone = ZoneInfo("Asia/Shanghai")
    generated_at = datetime.fromisoformat("2026-09-16T20:30:00").replace(tzinfo=zone)
    point = TradingPoint(pd.Timestamp("2026-09-17").date(), generated_at)
    portfolio, state = channel.snapshot(point)
    assert portfolio.position_quantity == 0
    assert portfolio.available_cash == Decimal("100000.0")
    core = PlannedOrder(OrderSide.BUY, 4_900, OrderType.LIMIT, Decimal("10.0"))
    core_plan = _execution_plan(
        reference="S003-v1",
        symbol="510500.SH",
        signal_date="2026-09-16",
        valid_date="2026-09-17",
        generated_at=generated_at,
        portfolio=portfolio,
        state=state,
        target_position=0.5,
        target_quantity=4_900,
        cycle_target_quantity=4_900,
        plan_mode="CORE_SETUP",
        fee_rate=fee_rate,
        legs=(PlanLeg(0, "CORE_SETUP", "OPEN", time(9, 30), time(9, 35), core),),
    )
    with pytest.raises(RuntimeContractError, match="fee rate differs"):
        channel.execute(replace(core_plan, fee_rate=Decimal("0.003")))
    assert channel.snapshot(point)[0].revision == 0
    core_outcome = channel.execute(core_plan)
    assert core_outcome.status == "SETTLED"
    assert core_outcome.portfolio.position_quantity == 4_900
    assert core_outcome.state.cycle_target_quantity == 4_900

    generated_at = datetime.fromisoformat("2026-09-17T20:30:00").replace(tzinfo=zone)
    point = TradingPoint(pd.Timestamp("2026-09-18").date(), generated_at)
    portfolio, state = channel.snapshot(point)
    buy = PlannedOrder(OrderSide.BUY, 4_600, OrderType.LIMIT, Decimal("10.0"))
    sell = PlannedOrder(OrderSide.SELL, 4_600, OrderType.MARKET, Decimal("10.2"))
    plan = _execution_plan(
        reference="S003-v1",
        symbol="510500.SH",
        signal_date="2026-09-17",
        valid_date="2026-09-18",
        generated_at=generated_at,
        portfolio=portfolio,
        state=state,
        target_position=1.0,
        target_quantity=4_900,
        cycle_target_quantity=4_900,
        plan_mode="CORE_EVENT_INTRADAY_ROTATION",
        fee_rate=fee_rate,
        legs=(
            PlanLeg(1, "OPEN_ROTATION_BUY", "OPEN", time(9, 15), time(10), buy),
            PlanLeg(
                2,
                "MIDDAY_ROTATION_SELL",
                "11:30_CLOSE",
                time(11, 25),
                time(11, 35),
                sell,
                dependency_sequence=1,
                dependency_required_status="FILLED_ALL",
            ),
        ),
    )
    outcome = channel.execute(plan)
    assert outcome.status == "SETTLED"

    result = channel.finish()
    assert result.decisions["plan_mode"].tolist() == [
        "CORE_SETUP",
        "CORE_EVENT_INTRADAY_ROTATION",
    ]
    assert result.orders["side"].tolist() == ["BUY", "BUY", "SELL"]
    assert result.orders["role"].tolist() == [
        "CORE_SETUP",
        "OPEN_ROTATION_BUY",
        "MIDDAY_ROTATION_SELL",
    ]
    assert result.orders["order_type"].tolist() == ["LIMIT", "LIMIT", "MARKET"]
    assert result.fills["price"].tolist() == [10.0, 10.0, 10.2]
    assert result.account_daily["quantity"].tolist() == [4_900, 4_900]
    assert result.trades["status"].tolist() == ["CLOSED"]
    assert policy.settings["one_way_cost"] == fee_rate
    assert result.account_daily.iloc[0]["cash_before"] == pytest.approx(100_000)
    assert result.account_daily.iloc[0]["quantity_before"] == 0
    assert result.account_daily.iloc[1]["cash_before"] == pytest.approx(
        100_000 - 49_000 * (1 + fee_rate)
    )
    assert result.account_daily.iloc[1]["quantity_before"] == 4_900
    # Event sizing reserves cash against its limit price; it need not equal the core lot.
    assert result.fills["quantity"].tolist() == [4_900, 4_600, 4_600]
    assert result.fills["fees"].tolist() == pytest.approx(
        [49_000 * fee_rate, 46_000 * fee_rate, 46_920 * fee_rate]
    )
    assert result.account_daily.iloc[-1]["cash"] == pytest.approx(
        100_000 - 49_000 * (1 + fee_rate) - 46_000 * (1 + fee_rate)
        + 46_920 * (1 - fee_rate)
    )
