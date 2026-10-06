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
    evidence = {"ohlcv_quality_evidence": {"daily": [{"date": "2026-09-17", "valid": True}]}}
    daily.attrs = evidence
    intraday.attrs = evidence
    original_daily, original_intraday = daily.copy(), intraday.copy()
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
    # The admitted computation copies must not propagate evidence through each price lookup.
    assert channel._daily.attrs == channel._intraday.attrs == {}
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
    assert result.fills["quantity"].tolist() == [99_900, 99_900]
    assert result.fills["price"].tolist() == [1.0, 1.1]
    assert result.fills["fees"].tolist() == pytest.approx([99.9, 109.89])
    assert result.account_daily["cash"].tolist() == pytest.approx([0.1, 109_780.21])
    assert result.trades["status"].tolist() == ["CLOSED"]
    assert result.trades.iloc[0]["net_return"] == pytest.approx(109_780.11 / 99_999.9 - 1)
    pd.testing.assert_frame_equal(daily, original_daily)
    pd.testing.assert_frame_equal(intraday, original_intraday)
    assert daily.attrs == intraday.attrs == evidence


def _overlay_setup(fee_rate, *, missing_checkpoint=None):
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
    if missing_checkpoint is not None:
        missing = five["dt"].eq(pd.Timestamp(f"2026-09-18 {missing_checkpoint}"))
        five = five.loc[~missing].copy()
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
    return channel, core_plan, point, policy


def _rotation_plan(channel, fee_rate, *, buy_limit=Decimal("10.0")):
    zone = ZoneInfo("Asia/Shanghai")
    generated_at = datetime.fromisoformat("2026-09-17T20:30:00").replace(tzinfo=zone)
    point = TradingPoint(pd.Timestamp("2026-09-18").date(), generated_at)
    portfolio, state = channel.snapshot(point)
    buy = PlannedOrder(OrderSide.BUY, 4_600, OrderType.LIMIT, buy_limit)
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
    return plan, point


@pytest.mark.parametrize("fee_rate", [0.00012, 0.002])
def test_txe_historical_executor_executes_intraday_overlay_plan(fee_rate) -> None:
    channel, core_plan, point, policy = _overlay_setup(fee_rate)
    with pytest.raises(RuntimeContractError, match="fee rate differs"):
        channel.execute(replace(core_plan, fee_rate=Decimal("0.003")))
    assert channel.snapshot(point)[0].revision == 0
    core_outcome = channel.execute(core_plan)
    assert core_outcome.status == "SETTLED"
    assert core_outcome.portfolio.position_quantity == 4_900
    assert core_outcome.state.cycle_target_quantity == 4_900

    plan, point = _rotation_plan(channel, fee_rate)
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


def _confirmed_target_plan():
    daily = pd.DataFrame({
        "dt": pd.date_range("2026-09-16", periods=3),
        "open": [10.0, 10.0, 11.0], "close": [10.0, 10.0, 11.0],
    })
    intraday = pd.DataFrame({
        "dt": pd.to_datetime(["2026-09-17 10:00", "2026-09-18 10:00"]),
        "high": [10.0, 11.0], "low": [10.0, 11.0],
    })
    channel = HistoricalExecutor(
        strategy_reference="S999-v1", symbol="588080.SH",
        execution_daily=daily, execution_intraday=intraday,
        evaluation_start=pd.Timestamp("2026-09-17"),
        evaluation_end=pd.Timestamp("2026-09-18"), initial_cash=20_000,
        execution_policy=ExecutionPolicy("FROZEN_RULE", {"capital": {"fee_rate": 0.001}}),
        order_types=("LIMIT",),
    )
    zone = ZoneInfo("Asia/Shanghai")
    generated = datetime(2026, 9, 16, 20, 30, tzinfo=zone)
    point = TradingPoint(pd.Timestamp("2026-09-17").date(), generated)
    portfolio, state = channel.snapshot(point)
    entry = _execution_plan(
        reference="S999-v1", symbol="588080.SH", signal_date="2026-09-16",
        valid_date="2026-09-17", generated_at=generated, portfolio=portfolio, state=state,
        target_position=1.0, target_quantity=1000, cycle_target_quantity=1000,
        orders=(PlannedOrder(OrderSide.BUY, 1000, OrderType.LIMIT, Decimal("10")),),
    )
    outcome = channel.execute(entry)
    assert outcome.status == "SETTLED"
    assert outcome.portfolio.position_quantity == 1000
    assert outcome.portfolio.available_cash == Decimal("9990.0")
    assert outcome.portfolio.revision == outcome.state.revision == 1
    generated = datetime(2026, 9, 17, 20, 30, tzinfo=zone)
    point = TradingPoint(pd.Timestamp("2026-09-18").date(), generated)
    portfolio, state = channel.snapshot(point)
    exit_plan = _execution_plan(
        reference="S999-v1", symbol="588080.SH", signal_date="2026-09-17",
        valid_date="2026-09-18", generated_at=generated, portfolio=portfolio, state=state,
        target_position=0.0, target_quantity=0, cycle_target_quantity=1000,
        orders=(PlannedOrder(OrderSide.SELL, 1000, OrderType.LIMIT, Decimal("10")),),
    )
    return channel, exit_plan, point


@pytest.mark.parametrize("fact,expected_error", [
    ("strategy", "plan belongs to another strategy"),
    ("symbol", "plan belongs to another instrument"),
    ("state_revision", "historical plan execution state is stale"),
    ("portfolio_revision", "historical plan portfolio revision is stale"),
    ("cash", "historical plan cash differs from ledger"),
    ("quantity", "historical plan position differs from ledger"),
], ids=["strategy", "instrument", "state-revision", "portfolio-revision", "cash", "quantity"])
def test_historical_execute_rejects_plan_facts_that_differ_from_confirmed_ledger(fact, expected_error):
    channel, plan, point = _confirmed_target_plan()
    before = channel.snapshot(point)
    if fact in {"strategy", "symbol"}:
        strategy = replace(plan.strategy, **(
            {"reference_id": "S999-v2"} if fact == "strategy" else {"symbol": "510500.SH"}
        ))
        signal = signal_identity_for(
            strategy=strategy, signal_date=plan.signal_date, target_position=plan.target_position,
            input_identities=plan.input_identities, price_identities=plan.price_identities,
        )
        plan_identity = plan_identity_for(
            signal_identity=signal, actual_quantity=plan.actual_quantity,
            target_quantity=plan.target_quantity, cycle_target_quantity=plan.cycle_target_quantity,
            plan_mode=plan.plan_mode, capital_mode=plan.capital_mode,
            allocation_fraction=plan.allocation_fraction, orders=plan.orders, legs=plan.legs,
        )
        forged = replace(plan, strategy=strategy, symbol=strategy.symbol,
                         signal_identity=signal, plan_identity=plan_identity)
    elif fact == "quantity":
        plan_identity = plan_identity_for(
            signal_identity=plan.signal_identity, actual_quantity=900,
            target_quantity=plan.target_quantity, cycle_target_quantity=plan.cycle_target_quantity,
            plan_mode=plan.plan_mode, capital_mode=plan.capital_mode,
            allocation_fraction=plan.allocation_fraction, orders=plan.orders, legs=plan.legs,
        )
        forged = replace(plan, actual_quantity=900, plan_identity=plan_identity)
    else:
        field, value = {
            "state_revision": ("expected_state_revision", 0),
            "portfolio_revision": ("expected_portfolio_revision", 0),
            "cash": ("available_cash", plan.available_cash + Decimal("1")),
        }[fact]
        forged = replace(plan, **{field: value})
    # Each forged plan is typed and internally authenticated; TXE must compare
    # its one changed fact with the real ledger rather than rely on DTO rejection.
    with pytest.raises(RuntimeContractError, match=expected_error):
        channel.execute(forged)
    assert channel.snapshot(point) == before
    settled = channel.execute(plan)
    assert settled.status == "SETTLED"
    assert settled.portfolio.position_quantity == 0
    assert settled.portfolio.available_cash == Decimal("20979.0")
    assert settled.portfolio.revision == settled.state.revision == 2
    result = channel.finish()
    assert result.orders["status"].tolist() == ["FILLED", "FILLED"]
    assert result.fills["quantity"].tolist() == [1000, 1000]
    assert result.fills["price"].tolist() == [10.0, 11.0]
    assert result.fills["fees"].tolist() == pytest.approx([10.0, 11.0])
    assert result.account_daily["cash"].tolist() == pytest.approx([9990, 20979])
    assert result.account_daily["quantity"].tolist() == [1000, 0]


def test_historical_execute_rejects_different_payload_for_settled_plan_identity():
    channel, plan, point = _confirmed_target_plan()
    settled = channel.execute(plan)
    before = channel.snapshot(point)
    changed_payload = replace(plan, evidence={**plan.evidence, "note": "different payload"})
    assert changed_payload.plan_identity == plan.plan_identity
    assert changed_payload != plan
    with pytest.raises(RuntimeContractError, match="plan identity was reused for another plan"):
        channel.execute(changed_payload)
    assert channel.snapshot(point) == before
    assert channel.execute(plan) is settled
    result = channel.finish()
    assert len(result.decisions) == len(result.orders) == len(result.fills) == 2
    assert result.fills["fees"].tolist() == pytest.approx([10.0, 11.0])
    assert result.account_daily.iloc[-1]["cash"] == pytest.approx(20979)
    assert result.account_daily.iloc[-1]["quantity"] == 0


def test_intraday_rotation_does_not_sell_core_when_dependency_buy_is_unfilled():
    fee_rate = 0.001
    channel, core_plan, _, _ = _overlay_setup(fee_rate)
    core = channel.execute(core_plan)
    assert core.portfolio.available_cash == Decimal("50951.0")
    plan, point = _rotation_plan(channel, fee_rate, buy_limit=Decimal("9.9"))
    before_portfolio, before_state = channel.snapshot(point)
    settled = channel.execute(plan)
    assert settled.status == "SETTLED"
    assert settled.portfolio.position_quantity == before_portfolio.position_quantity == 4900
    assert settled.portfolio.available_cash == before_portfolio.available_cash == Decimal("50951.0")
    assert settled.state.cycle_target_quantity == before_state.cycle_target_quantity == 4900
    assert settled.portfolio.revision == settled.state.revision == 2
    result = channel.finish()
    assert result.decisions["plan_mode"].tolist() == ["CORE_SETUP", "CORE_EVENT_INTRADAY_ROTATION"]
    assert result.orders["role"].tolist() == ["CORE_SETUP", "OPEN_ROTATION_BUY"]
    assert result.orders["status"].tolist() == ["FILLED", "UNFILLED"]
    assert result.fills["side"].tolist() == ["BUY"]
    assert result.fills["quantity"].tolist() == [4900]
    assert result.fills["price"].tolist() == [10.0]
    assert result.fills["fees"].tolist() == pytest.approx([49.0])
    assert result.account_daily["quantity"].tolist() == [4900, 4900]
    assert result.account_daily["cash"].tolist() == pytest.approx([50951, 50951])
    assert result.trades.empty


@pytest.mark.parametrize("checkpoint", ["09:35", "11:30"], ids=["opening", "midday"])
def test_intraday_rotation_rejects_missing_checkpoint_without_changing_core(checkpoint):
    fee_rate = 0.001
    channel, core_plan, _, _ = _overlay_setup(fee_rate, missing_checkpoint=checkpoint)
    channel.execute(core_plan)
    plan, point = _rotation_plan(channel, fee_rate)
    before = channel.snapshot(point)
    with pytest.raises(RuntimeContractError, match="incomplete execution checkpoints"):
        channel.execute(plan)
    assert channel.snapshot(point) == before
    result = channel.finish()
    assert result.decisions["plan_mode"].tolist() == ["CORE_SETUP"]
    assert result.orders["role"].tolist() == ["CORE_SETUP"]
    assert result.fills["quantity"].tolist() == [4900]
    assert result.fills["fees"].tolist() == pytest.approx([49.0])
    assert result.account_daily["quantity"].tolist() == [4900, 4900]
    assert result.account_daily["cash"].tolist() == pytest.approx([50951, 50951])
    assert result.trades.empty
