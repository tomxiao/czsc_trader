from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time
from decimal import Decimal
from types import MappingProxyType
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from execution_channels.session_contracts import ExecutionCapabilities
from execution_channels.session_contracts import ExecutionPlan
from execution_channels.policy import ExecutionPolicy
from execution_channels.session_contracts import OrderSide
from execution_channels.session_contracts import OrderType
from execution_channels.session_contracts import PlanLeg
from execution_channels.session_contracts import PlannedOrder
from execution_channels.session_contracts import PriceReference
from execution_channels.errors import RuntimeContractError
from execution_channels.session_contracts import StrategyIdentity
from execution_channels.session_contracts import TradingPoint
from execution_channels.session_contracts import plan_identity_for
from execution_channels.session_contracts import signal_identity_for

from execution_channels.historical import HistoricalExecutor, MarketExecutionRules, SessionPriceLimits


def _market_executor_fixture(*, rules=None, policy_type="FROZEN_RULE", daily=None, intraday=None):
    dates = pd.bdate_range("2026-09-14", periods=5)
    if daily is None:
        daily = pd.DataFrame({"dt": dates, "open": [10., 11., 10., 9., 10.],
                              "close": [10., 10.5, 10., 9., 10.],
                              "high": [10., 11., 10., 9., 10.],
                              "low": [10., 10.5, 10., 9., 10.]})
    if rules is None:
        rules = MarketExecutionRules("600722.SH", tuple(SessionPriceLimits(day.date(), 9., 11.) for day in dates[1:]))
    policy = ExecutionPolicy(policy_type, {"capital": {"fee_rate": .001}, "one_way_cost": .001})
    if intraday is None:
        intraday = pd.DataFrame(columns=["dt", "high", "low"])
    return HistoricalExecutor(strategy_reference="S999-v1", symbol="600722.SH", execution_daily=daily,
                              execution_intraday=intraday,
                              evaluation_start=dates[1], evaluation_end=dates[-1], initial_cash=2000.,
                              execution_policy=policy, order_types=("MARKET",), market_rules=rules), dates


# Independent risk: EC08; responsibility-level assertions.
@pytest.mark.parametrize('fault', ['dates','symbol'], ids=['EC08-C04','EC08-C05'])
def test_market_rule_identity_and_complete_dates_are_required(fault):
    dates = pd.bdate_range('2026-09-14', periods=5)
    limits = tuple(SessionPriceLimits(day.date(), 9., 11.) for day in dates[1:])
    symbol = '510500.SH' if fault == 'symbol' else '600722.SH'
    selected = limits if fault == 'symbol' else limits[:-1]
    reason = 'another instrument' if fault == 'symbol' else 'do not cover'
    with pytest.raises(RuntimeContractError, match=reason):
        _market_executor_fixture(rules=MarketExecutionRules(symbol, selected))


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


# Independent risk: EC11; responsibility-level assertions.
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


# Independent risk: EC10; responsibility-level assertions.
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
