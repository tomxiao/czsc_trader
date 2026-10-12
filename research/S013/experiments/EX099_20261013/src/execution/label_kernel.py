"""S013 fixed independent H4 attempts through SRT planning and public TXE.

No data access, fitting, candidate registration, or continuous-account replay.
Frames must already be authenticated S013 normalized HFQ execution prices.
"""
from datetime import date, datetime, time
from decimal import Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from strategy_runtime import (
    ExecutionCapabilities, ExecutionPlan, ExecutionPolicy, ExecutionPriceBasis,
    ExecutionPricing, OrderSide, OrderType, PlannedOrder, PriceReference,
    StrategyIdentity, TradingPoint,
)
from strategy_runtime.contracts import plan_identity_for, signal_identity_for
from strategy_runtime.execution_planner import build_execution_plan
from trading_execution_engine import HistoricalExecutor

CASH = 1_000_000.0
FEE = 0.001
POLICY = ExecutionPolicy("FROZEN_RULE", {
    "instrument": {"lot_size": 100, "price_tick": .001,
                   "price_limit_ratio": .1, "maximum_order_quantity": 1_000_000},
    "capital": {"mode": "AVAILABLE_CASH", "allocation_fraction": 1.,
                "fee_rate": FEE, "target_scope": "STRATEGY"},
    "entry": {"order_type": "LIMIT", "limit_parameter": .01},
    "exit": {"order_type": "MARKET", "limit_ratio": .1},
})
PRICING = ExecutionPricing(ExecutionPriceBasis.HFQ_RESEARCH, date(2019, 12, 31), .2803)
ZONE = ZoneInfo("Asia/Shanghai")


def _indexed(frame):
    value = frame.copy()
    value.attrs = {}
    value["dt"] = pd.to_datetime(value["dt"], errors="raise").dt.as_unit("ns")
    value = value.set_index("dt").sort_index()
    if value.index.has_duplicates or value.index.tz is not None or value.index.hasnans:
        raise ValueError("unique local source dates required")
    return value


def validate_inputs(daily, intraday, raw_daily, pricing):
    if pricing != PRICING:
        raise ValueError("S013 fixed HFQ anchor required")
    d, bars, raw = map(_indexed, (daily, intraday, raw_daily))
    for frame in (d, bars, raw):
        if not {"open", "high", "low", "close"} <= set(frame.columns):
            raise ValueError("OHLC required")
        vals = frame[["open", "high", "low", "close"]].to_numpy(float)
        if not np.isfinite(vals).all() or (vals <= 0).any():
            raise ValueError("positive finite OHLC required")
        if (frame.high < frame.low).any():
            raise ValueError("invalid high/low")
    if not d.index.equals(d.index.normalize()) or not raw.index.equals(d.index):
        raise ValueError("raw/normalized unique daily session axes required")
    scales = d.close / raw.close
    ratios = d[["open", "high", "low", "close"]] / raw[["open", "high", "low", "close"]]
    if not ratios.div(scales, axis=0).sub(1).abs().le(1e-10).all().all():
        raise ValueError("daily single HFQ scale required")
    # Minute deviations from daily extrema are existing source facts, not repaired here.
    return d, bars, scales


def _plan(channel, identity, signal, execution, target, d, scales, source_hash):
    point = TradingPoint(execution.date(), datetime.combine(signal.date(), time(17), tzinfo=ZONE))
    portfolio, state = channel.snapshot(point)
    ref = PriceReference(Decimal(str(d.loc[signal, "close"])),
                         Decimal(str(d.loc[signal, "close"])),
                         "NORMALIZED_HFQ_CLOSE", "NORMALIZED_HFQ_CLOSE",
                         pricing=PRICING, price_scale=Decimal(str(scales.loc[signal])))
    raw = build_execution_plan(
        deployment_settings={"cycle_target_quantity": state.cycle_target_quantity},
        available_cash=float(portfolio.available_cash), position_quantity=portfolio.position_quantity,
        target_position=target, policy=POLICY, signal_reference_price=float(ref.signal_price),
        execution_reference_price=float(ref.execution_price), price_scale=float(ref.price_scale),
        unadjusted_reference_price=float(ref.execution_price / ref.price_scale))
    orders = tuple(PlannedOrder(OrderSide(x["side"]), int(x["quantity"]),
                                OrderType(x["order_type"]), Decimal(str(x["limit_price"])))
                   for x in raw["orders"])
    ids = {"execution_data": source_hash}
    sid = signal_identity_for(strategy=identity, signal_date=signal.date(),
                             target_position=target, input_identities=ids, price_identities=ids)
    terms = dict(actual_quantity=portfolio.position_quantity, target_quantity=int(raw["target_quantity"]),
                 cycle_target_quantity=int(raw["cycle_target_quantity"]),
                 plan_mode=str(raw.get("plan_mode", "NONE")),
                 capital_mode=str(raw["capital_rule"]["mode"]),
                 allocation_fraction=Decimal(str(raw["capital_rule"]["allocation_fraction"])),
                 orders=orders, legs=())
    return ExecutionPlan(
        strategy=identity, signal_identity=sid,
        plan_identity=plan_identity_for(signal_identity=sid, **terms), symbol="510500.SH",
        signal_date=signal.date(), trading_date=execution.date(), generated_at=point.calculation_time,
        expected_portfolio_revision=portfolio.revision, expected_state_revision=state.revision,
        target_position=target, action=str(raw["action"]), available_cash=portfolio.available_cash,
        fee_rate=Decimal(str(raw["fee_rate"])), estimated_order_cost=Decimal(str(raw["estimated_order_cost"])),
        unallocated_cash=Decimal(str(raw["unallocated_cash"])), references=ref,
        required_capabilities=ExecutionCapabilities(tuple(dict.fromkeys(x.order_type for x in orders))),
        input_identities=ids, price_identities=ids,
        evidence={"signal_date": signal.date().isoformat(), "reason": "FIXED_SINGLE_H4_ATTEMPT"}, **terms)


def construct_labels(daily, intraday, raw_daily, signal_dates, *, pricing=PRICING,
                     source_hash, emit_ledgers=False):
    """Return rows indexed by T and actual independent attempt ledgers.

    Exactly one BUY DAY attempt, never retry an unfilled entry. Filled positions
    receive HOLD plans through T+4 and MARKET exit T+5. Missing exit stays OPEN.
    L0 matures T+5; L1 matures end of actual fill/cancel/exit session.
    """
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        raise ValueError("authenticated source SHA256 required")
    d, bars, scales = validate_inputs(daily, intraday, raw_daily, pricing)
    axis = pd.DatetimeIndex(signal_dates).as_unit("ns")
    if axis.has_duplicates or axis.hasnans or axis.tz is not None or not axis.is_monotonic_increasing:
        raise ValueError("ordered unique signal axis required")
    if len(axis) > 1636 or not axis.isin(d.index).all():
        raise ValueError("authorized maximum1636 source-known signal dates required")
    rows, ledgers = [], {key: [] for key in ("decisions", "orders", "fills", "trades", "account_daily")}
    for ordinal, signal in enumerate(axis):
        location = d.index.get_loc(signal)
        available = d.index[location + 1:location + 6]
        complete = len(available) == 5
        row = dict(signal_date=signal, l0=np.nan, l0_maturity=pd.NaT,
                   l1=np.nan, l1_maturity=pd.NaT, attempted=False, entry_filled=False,
                   closed=False, exit_date=pd.NaT, release_date=pd.NaT,
                   occupation_sessions=0, occupied_at_end=False, quantity=0,
                   entry_price=np.nan, exit_price=np.nan, fees=0., cash_end=CASH,
                   pnl=np.nan, adverse_price_excursion=np.nan, termination="NO_NEXT_SESSION")
        if complete:
            row.update(l0=float(d.loc[available[-1], "open"] / d.loc[available[0], "open"]
                                * (.999 / 1.001) - 1), l0_maturity=available[-1])
        if not len(available):
            rows.append(row)
            continue
        # No future price controls identity or entry reference/quantity.
        identity_hash = sha256(f"S013-independent-h4-{source_hash}".encode()).hexdigest()
        # Synthetic episode transport only, not a registered candidate or frozen release.
        # The public typed contract requires S013-Cdddd or S013-vN syntax.
        identity = StrategyIdentity("S013", "S013-C0000", identity_hash, identity_hash, "510500.SH")
        channel = HistoricalExecutor(
            strategy_reference=identity.reference_id, symbol="510500.SH",
            execution_daily=d.loc[:available[-1]].reset_index(),
            execution_intraday=bars.loc[(bars.index.normalize() >= available[0]) &
                                        (bars.index.normalize() <= available[-1])].reset_index(),
            evaluation_start=available[0], evaluation_end=available[-1], initial_cash=CASH,
            execution_policy=POLICY, order_types=("LIMIT", "MARKET"),
            pricing=PRICING, account_id=f"S013-H4-{ordinal:04}" )
        buy_outcome = channel.execute(_plan(channel, identity, signal, available[0], 1., d, scales, source_hash))
        filled = buy_outcome.portfolio.position_quantity > 0
        row["attempted"] = True
        # Additional days are bookkeeping WAIT when first DAY entry unfilled.
        for j, execution in enumerate(available[1:], start=1):
            target = 1. if filled and j < 4 else 0.
            channel.execute(_plan(channel, identity, d.index[location + j], execution,
                                  target, d, scales, source_hash))
        result = channel.finish()
        final = result.account_daily.iloc[-1]
        fills = result.fills
        buy = fills.loc[fills.side.eq("BUY")]
        sell = fills.loc[fills.side.eq("SELL")]
        closed = filled and int(final.quantity) == 0 and len(sell) > 0
        row.update(entry_filled=filled, closed=closed, occupied_at_end=int(final.quantity) > 0,
                   fees=float(fills.fees.sum()), cash_end=float(final.cash))
        if filled:
            qty = int(buy.quantity.sum())
            entry = float((buy.price * buy.quantity).sum() / qty)
            row.update(quantity=qty, entry_price=entry,
                       occupation_sessions=len(available),
                       adverse_price_excursion=float(d.loc[available, "low"].min() / entry - 1))
        if closed:
            end = pd.Timestamp(sell.fill_time.max()).normalize()
            row.update(l1=float(final.cash / CASH - 1), l1_maturity=end, release_date=end,
                       exit_date=end, pnl=float(final.cash - CASH),
                       exit_price=float((sell.price * sell.quantity).sum() / sell.quantity.sum()),
                       termination="CLOSED_H4")
        elif not filled:
            row.update(l1=0., l1_maturity=available[0], release_date=available[0], pnl=0.,
                       occupation_sessions=1, termination="ENTRY_DAY_UNFILLED_OR_NO_LOT")
        else:
            row["termination"] = "TAIL_OPEN_NO_EXIT" if not complete else "EXIT_UNFILLED"
        if float(result.account_daily.cash.min()) < -1e-8:
            raise AssertionError("public ledger cash negative")
        if emit_ledgers:
            for key in ledgers:
                frame = getattr(result, key).copy()
                frame.insert(0, "attempt_signal_date", signal)
                ledgers[key].append(frame)
        rows.append(row)
    labels = pd.DataFrame(rows).set_index("signal_date")
    labels.index = pd.DatetimeIndex(labels.index).as_unit("ns")
    return labels, {key: pd.concat(value, ignore_index=True) if value else pd.DataFrame()
                    for key, value in ledgers.items()}
