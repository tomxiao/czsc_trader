"""S012 research screening ledger; require FULL equivalence before activation.

Only public StrategyImplementation and TXE fill APIs are called. Inputs must be
already authenticated managed market frames. This module never fetches data.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from math import isfinite

import pandas as pd
from trading_execution_engine import OrderSpec, resolve_fill


def tick(value, rounding):
    modes = {"floor": ROUND_FLOOR, "ceil": ROUND_CEILING, "half_up": ROUND_HALF_UP}
    quantum = Decimal("0.001")
    return float((Decimal(str(value)) / quantum).to_integral_value(rounding=modes[rounding]) * quantum)


def prices(frame):
    """Create an owned numeric projection without copying pandas attrs."""
    names = {"Date": "dt", "Open": "open", "High": "high", "Low": "low", "Close": "close"}
    value = {}
    for original in frame.columns:
        name = names.get(original, original)
        if name in {"dt", "open", "high", "low", "close"}:
            value[name] = frame[original].to_numpy(copy=True)
    result = pd.DataFrame(value)
    result["dt"] = pd.to_datetime(result["dt"], errors="raise")
    if result.dt.duplicated().any() or result.dt.isna().any() or result.dt.dt.tz is not None:
        raise ValueError("market requires unique naive local timestamps")
    for name in set(result.columns) - {"dt"}:
        result[name] = pd.to_numeric(result[name], errors="raise")
        if not result[name].map(lambda x: isfinite(x) and x > 0).all():
            raise ValueError("market prices must be positive and finite")
    return result.sort_values("dt").reset_index(drop=True)


def simulate(strategy, features, daily, intraday, *, start="2020-06-08", end="2026-09-30",
             initial_cash=100000.0, fee_rate=0.001):
    """Replay complete account economics with the exact current FROZEN_RULE subset.

    The output is research acceleration evidence, never a platform FULL result.
    There is no slippage, partial fill, intraday stop, or dynamic position fraction.
    """
    policy = strategy.definition.execution
    settings = policy.settings
    instrument, capital = settings["instrument"], settings["capital"]
    if (policy.policy_type != "FROZEN_RULE" or instrument["lot_size"] != 100
            or instrument["price_tick"] != .001 or instrument["price_limit_ratio"] != .1
            or settings["entry"]["order_type"] != "LIMIT"
            or settings["exit"]["order_type"] != "MARKET"
            or settings.get("virtual_fill") or capital["target_scope"] != "entry_cycle"):
        raise ValueError("unsupported execution policy; accelerator cannot approximate it")
    if initial_cash != 100000.0 or fee_rate != .001 or capital["fee_rate"] != fee_rate:
        raise ValueError("accelerator is pinned to the approved 100000 cash /10bp mandate")
    daily = prices(daily)
    bars = prices(intraday)
    if not {"open", "close"} <= set(daily) or not {"low", "high"} <= set(bars):
        raise ValueError("execution frames are incomplete")
    dates = pd.DatetimeIndex(daily.dt, name="dt")
    if not dates.equals(dates.normalize()):
        raise ValueError("daily dates must be normalized")
    evaluation = dates[(dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))]
    if evaluation.empty or evaluation[0] != pd.Timestamp(start) or evaluation[-1] != pd.Timestamp(end):
        raise ValueError("execution endpoints must be available sessions")
    positions = dates.get_indexer(evaluation)
    if (positions <= 0).any():
        raise ValueError("each execution session requires a real predecessor close")
    signals = dates[positions - 1]
    execution_input = pd.DataFrame({"Date": daily.dt.to_numpy(copy=True),
                                    "Close": daily.close.to_numpy(copy=True)})
    history = strategy.calculate_window_history({"features": features, "execution": execution_input}, signals)
    if not history.index.equals(signals) or not history.target_position.isin([0., 1.]).all():
        raise ValueError("strategy returned unsupported history")
    grouped = {pd.Timestamp(key): [(row.dt.to_pydatetime(), float(row.low), float(row.high))
                                  for row in group.itertuples(index=False)]
               for key, group in bars.groupby(bars.dt.dt.normalize(), sort=False)}
    if not set(evaluation) <= set(grouped):
        raise ValueError("30-minute execution bars must cover every evaluation session")
    allocation = Decimal(str(capital.get("allocation_fraction", 1.0)))
    fee = Decimal(str(fee_rate))
    maximum = int(instrument["maximum_order_quantity"])
    if maximum <= 0 or maximum % 100:
        raise ValueError("maximum quantity must use 100-share lots")
    cash, quantity, cycle_target, cycle_id, cycle_number = initial_cash, 0, None, None, 0
    open_trade = None
    accounts, orders, fills, trades, decisions = [], [], [], [], []
    for number, (execution_date, signal_date, location) in enumerate(zip(evaluation, signals, positions)):
        target = int(history.target_position.iloc[number])
        before_cash, before_quantity = cash, quantity
        reference = float(daily.close.iloc[location - 1])
        if target:
            requested = tick(reference * (1 + float(settings["entry"]["limit_parameter"])), "floor")
            guard = tick(tick(reference * (1 + float(instrument["price_limit_ratio"])), "floor") - .001, "half_up")
            limit = min(requested, guard)
            unit_cost = Decimal(str(limit)) * (1 + fee)
            affordable = quantity + int((Decimal(str(cash)) * allocation / (unit_cost * 100))
                                       .to_integral_value(rounding=ROUND_FLOOR)) * 100
            planned_cycle = affordable if cycle_target is None else cycle_target
            target_quantity = min(planned_cycle, affordable)
            delta = max(0, target_quantity - quantity)
            side, order_type = "BUY", "LIMIT"
            if quantity == 0 and cycle_id is None:
                cycle_number += 1
                cycle_id = cycle_number
        else:
            limit = tick(reference, "half_up")
            planned_cycle = 0 if not quantity else int(cycle_target or quantity)
            target_quantity, delta, side, order_type = 0, -quantity, "SELL", "MARKET"
        remaining = abs(delta)
        while remaining:
            size = min(remaining, maximum)
            remaining -= size
            touches = [(timestamp, low if side == "BUY" else high)
                       for timestamp, low, high in grouped[execution_date]]
            resolved = resolve_fill(OrderSpec(side, order_type, size, limit),
                                    session_open=float(daily.open.iloc[location]),
                                    session_time=execution_date.to_pydatetime(),
                                    intraday_touches=touches)
            filled = resolved.filled
            if side == "BUY" and filled and size * resolved.price * (1 + fee_rate) > cash + 1e-8:
                filled = False
            orders.append({"cycle_id": cycle_id, "signal_date": signal_date,
                           "execution_date": execution_date, "side": side, "quantity": size,
                           "order_type": order_type, "limit_price": limit,
                           "status": "FILLED" if filled else "UNFILLED"})
            if not filled:
                continue
            price = resolved.price
            gross, cost = size * price, size * price * fee_rate
            if side == "BUY":
                cash -= gross + cost
                quantity += size
                if open_trade is None:
                    open_trade = {"cycle_id": cycle_id, "entry_date": pd.Timestamp(resolved.filled_at),
                                  "quantity": 0, "gross": 0., "fees": 0., "exit_proceeds": 0.,
                                  "exit_fees": 0., "exit_quantity": 0}
                open_trade["quantity"] += size
                open_trade["gross"] += gross
                open_trade["fees"] += cost
            else:
                cash += gross - cost
                quantity -= size
                if open_trade is None:
                    raise ValueError("sell lacks an open actual trade")
                open_trade["exit_proceeds"] += gross - cost
                open_trade["exit_fees"] += cost
                open_trade["exit_quantity"] += size
                if quantity == 0:
                    trades.append({"cycle_id": cycle_id, "status": "CLOSED",
                                   "entry_date": open_trade["entry_date"],
                                   "exit_date": pd.Timestamp(resolved.filled_at),
                                   "quantity": open_trade["quantity"],
                                   "entry_price": open_trade["gross"] / open_trade["quantity"],
                                   "exit_price": (open_trade["exit_proceeds"] + open_trade["exit_fees"])
                                   / open_trade["exit_quantity"],
                                   "net_return": open_trade["exit_proceeds"]
                                   / (open_trade["gross"] + open_trade["fees"]) - 1})
                    open_trade = None
            fills.append({"cycle_id": cycle_id, "signal_date": signal_date,
                          "fill_time": pd.Timestamp(resolved.filled_at), "side": side,
                          "quantity": size, "price": price, "fees": cost, "trigger": resolved.trigger})
        cycle_target = planned_cycle
        if not target and not quantity:
            cycle_target, cycle_id = None, None
        close = float(daily.close.iloc[location])
        accounts.append({"date": execution_date, "signal_date": signal_date,
                         "target_position": target, "cash_before": before_cash,
                         "quantity_before": before_quantity, "cash": cash, "quantity": quantity,
                         "close": close, "equity": cash + quantity * close})
        decisions.append({"signal_date": signal_date, "execution_date": execution_date,
                          "target_position": target, "target_quantity": target_quantity,
                          "cycle_target_quantity": planned_cycle})
    if open_trade is not None:
        trades.append({"cycle_id": open_trade["cycle_id"], "status": "OPEN",
                       "entry_date": open_trade["entry_date"], "exit_date": pd.NaT,
                       "quantity": open_trade["quantity"],
                       "entry_price": open_trade["gross"] / open_trade["quantity"],
                       "exit_price": float("nan"), "net_return": float("nan")})
    return {"mode": "RESEARCH_ACCELERATED_UNAPPROVED_UNTIL_EQUIVALENCE",
            "signals": history, "decisions": pd.DataFrame(decisions),
            "account_daily": pd.DataFrame(accounts),
            "orders": pd.DataFrame(orders, columns=["cycle_id", "signal_date", "execution_date", "side",
                                                  "quantity", "order_type", "limit_price", "status"]),
            "fills": pd.DataFrame(fills, columns=["cycle_id", "signal_date", "fill_time", "side",
                                                 "quantity", "price", "fees", "trigger"]),
            "trades": pd.DataFrame(trades, columns=["cycle_id", "status", "entry_date", "exit_date",
                                                   "quantity", "entry_price", "exit_price", "net_return"])}


def compare_economics(accelerated, full):
    """Compare all semantic economic rows; ignore channel-generated identity IDs."""
    checks = {}
    columns = {
        "account_daily": ["date", "signal_date", "target_position", "cash_before", "quantity_before",
                          "cash", "quantity", "close", "equity"],
        "orders": ["signal_date", "execution_date", "side", "quantity", "order_type", "limit_price", "status"],
        "fills": ["signal_date", "fill_time", "side", "quantity", "price", "fees", "trigger"],
        "trades": ["status", "entry_date", "exit_date", "quantity", "entry_price", "exit_price", "net_return"],
    }
    for name, fields in columns.items():
        left = accelerated[name][fields].reset_index(drop=True).copy()
        right = full[name][fields].reset_index(drop=True).copy()
        for field in fields:
            if field.endswith("date") or field == "fill_time":
                left[field] = pd.to_datetime(left[field]).astype("datetime64[ns]")
                right[field] = pd.to_datetime(right[field]).astype("datetime64[ns]")
        pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=False,
                                      atol=1e-8, rtol=1e-12)
        checks[name] = {"rows": len(left), "columns": fields, "status": "PASS"}
    return {"status": "PASS", "checks": checks,
            "scope": "entire semantic account/order/fill/trade ledger; identity strings excluded"}
