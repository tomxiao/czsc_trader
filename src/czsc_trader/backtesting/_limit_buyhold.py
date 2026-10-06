"""Translate a fixed BuyHold target into public SRT plans and TXE ledgers."""

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
from strategy_runtime import (
    ExecutionCapabilities,
    ExecutionPlan,
    ExecutionPolicy,
    OrderSide,
    OrderType,
    PlannedOrder,
    PriceReference,
    StrategyIdentity,
    TradingPoint,
)
from strategy_runtime.contracts import plan_identity_for, signal_identity_for
from strategy_runtime.execution_planner import build_execution_plan
from trading_execution_engine import HistoricalExecutor


def replay_limit_buyhold(signals, data, initial_cash, benchmark, fee_rate):
    rule = benchmark.execution
    policy = ExecutionPolicy(
        "FROZEN_RULE",
        {
            "capital": {
                "fee_rate": fee_rate,
                "mode": "full_available_cash",
                "target_scope": "entry_cycle",
            },
            "entry": {"order_type": "LIMIT", "limit_parameter": rule.premium},
            "exit": {"order_type": "MARKET", "limit_ratio": rule.price_limit_ratio},
            "instrument": {
                "lot_size": rule.lot_size,
                "maximum_order_quantity": rule.maximum_order_quantity,
                "price_limit_ratio": rule.price_limit_ratio,
                "price_tick": rule.price_tick,
            },
        },
    )
    identity = StrategyIdentity(
        "BuyHold", "BuyHold", benchmark.fingerprint, benchmark.fingerprint, data.symbol
    )
    channel = HistoricalExecutor(
        strategy_reference=identity.reference_id,
        symbol=data.symbol,
        execution_daily=data.execution_daily,
        execution_intraday=data.execution_intraday,
        evaluation_start=signals.evaluation_start,
        evaluation_end=signals.evaluation_end,
        initial_cash=initial_cash,
        execution_policy=policy,
        order_types=("LIMIT",),
    )
    adjusted = pd.DataFrame(data.adjusted_daily, copy=False)
    adjusted = adjusted.set_index(pd.to_datetime(adjusted["dt"]).dt.normalize())
    prices = pd.DataFrame(data.execution_daily, copy=False)
    prices = prices.set_index(pd.to_datetime(prices["dt"]).dt.normalize())
    if adjusted.index.has_duplicates or prices.index.has_duplicates:
        raise ValueError("BuyHold prices require unique sessions")
    sessions = prices.index.sort_values()
    trading = sessions[
        (sessions >= signals.evaluation_start) & (sessions <= signals.evaluation_end)
    ]
    adjusted_close = dict(zip(adjusted.index, adjusted["close"].to_numpy(), strict=True))
    execution_close = dict(zip(prices.index, prices["close"].to_numpy(), strict=True))
    trading_locations = sessions.get_indexer(trading)
    identities = {"execution_data": data.fingerprint}
    for day, location in zip(trading, trading_locations, strict=True):
        if location == 0 or sessions[location - 1] not in adjusted_close:
            raise ValueError("BuyHold has no prior signal reference")
        signal_day = sessions[location - 1]
        point = TradingPoint(
            day.date(),
            datetime.combine(signal_day.date(), time(20, 31), tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        portfolio, state = channel.snapshot(point)
        references = PriceReference(
            Decimal(str(adjusted_close[signal_day])),
            Decimal(str(execution_close[signal_day])),
            "ADJUSTED_CLOSE",
            "UNADJUSTED_CLOSE",
        )
        raw = build_execution_plan(
            deployment_settings={"cycle_target_quantity": state.cycle_target_quantity},
            available_cash=float(portfolio.available_cash),
            position_quantity=portfolio.position_quantity,
            target_position=1.0,
            policy=policy,
            signal_reference_price=float(references.signal_price),
            execution_reference_price=float(references.execution_price),
        )
        orders = tuple(
            PlannedOrder(
                OrderSide(x["side"]),
                int(x["quantity"]),
                OrderType(x["order_type"]),
                Decimal(str(x["limit_price"])),
            )
            for x in raw["orders"]
        )
        signal_id = signal_identity_for(
            strategy=identity,
            signal_date=signal_day.date(),
            target_position=1.0,
            input_identities=identities,
            price_identities=identities,
        )
        terms = dict(
            actual_quantity=portfolio.position_quantity,
            target_quantity=int(raw["target_quantity"]),
            cycle_target_quantity=int(raw["cycle_target_quantity"]),
            plan_mode=str(raw.get("plan_mode", "NONE")),
            capital_mode=str(raw["capital_rule"]["mode"]),
            allocation_fraction=Decimal(str(raw["capital_rule"]["allocation_fraction"])),
            orders=orders,
            legs=(),
        )
        plan = ExecutionPlan(
            strategy=identity,
            signal_identity=signal_id,
            plan_identity=plan_identity_for(signal_identity=signal_id, **terms),
            symbol=data.symbol,
            signal_date=signal_day.date(),
            trading_date=day.date(),
            generated_at=point.calculation_time,
            expected_portfolio_revision=portfolio.revision,
            expected_state_revision=state.revision,
            target_position=1.0,
            action=str(raw["action"]),
            available_cash=portfolio.available_cash,
            fee_rate=Decimal(str(raw["fee_rate"])),
            estimated_order_cost=Decimal(str(raw["estimated_order_cost"])),
            unallocated_cash=Decimal(str(raw["unallocated_cash"])),
            references=references,
            required_capabilities=ExecutionCapabilities(tuple({x.order_type for x in orders}), ()),
            input_identities=identities,
            price_identities=identities,
            evidence={
                "signal_date": signal_day.date().isoformat(),
                "action": str(raw["action"]),
                "reason": "BUY_AND_HOLD",
            },
            **terms,
        )
        channel.execute(plan)
    return channel.finish()
