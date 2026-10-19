"""Typed one-cycle exit component. No entry generation, accounts or re-entry."""
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
import math

import numpy as np
import pandas as pd
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill


class Action(str, Enum):
    ON = "ON"
    OFF_LOCAL_CYCLE = "OFF_LOCAL_CYCLE"


@dataclass(frozen=True)
class CycleSeed:
    event_id: str
    cycle_id: str
    entry_E: str
    first_shock_D: str
    entry_index: int
    deadline_index: int
    reservation_index: int
    quantity: int
    ledger_entry_price: float
    actual_buy_fee: float
    runtime_entry_price: float

    def __post_init__(self):
        if (type(self.quantity) is not int or self.quantity <= 0 or self.quantity % 100
                or self.deadline_index != self.entry_index + 9
                or self.reservation_index != self.entry_index + 10
                or self.entry_E > self.first_shock_D):
            raise ValueError("Original actual whole-lot funded entry and H10 anchors required")
        if not all(math.isfinite(v) and v > 0 for v in
                   (self.ledger_entry_price, self.actual_buy_fee, self.runtime_entry_price)):
            raise ValueError("Positive finite same-contract actual entry required")


@dataclass(frozen=True)
class PreparedInputs:
    source_market: pd.DataFrame
    source_raw: pd.DataFrame
    source_limits: pd.DataFrame
    source_status: pd.DataFrame
    source_features: pd.DataFrame
    projected_execution: pd.DataFrame
    raw_execution: pd.DataFrame
    price_limits: pd.DataFrame
    trading_status: pd.DataFrame
    clock: dict
    execution_dates: tuple
    cutoff: str = "2026-10-15"


def state_at_D(inputs, D):
    """Only declared runtime-HFQ source closes; no liquidation observations."""
    stamp = pd.Timestamp(D)
    market, feature = inputs.source_market, inputs.source_features.loc[stamp]
    i = market.index.get_loc(stamp)
    prior = float(market.Close.iloc[i - 1]) if i >= 1 else math.nan
    first = float(market.Close.iloc[i - 5]) if i >= 5 else math.nan
    close = float(market.Close.iloc[i])
    ma, lag = float(feature.ma20_prior), float(feature.ma20_prior_lag5)
    trend = bool(ma > lag and prior >= ma) if all(np.isfinite(v) for v in (ma, lag, prior)) else None
    r1 = float(np.log(close / prior)) if close > 0 and prior > 0 else None
    r4 = float(np.log(prior / first)) if prior > 0 and first > 0 else None
    spread = bool(r1 <= r4) if r1 is not None and r4 is not None else None
    return {"PRIOR_TREND_ESTABLISHED": trend, "NON_FINAL_DAY_DOMINATED": spread,
            "r1_log": r1, "r4_log": r4, "r1_positive": None if r1 is None else r1 > 0,
            "prior_close_RUNTIME_HFQ": prior if np.isfinite(prior) else None,
            "ma20_prior_RUNTIME_HFQ": ma if np.isfinite(ma) else None,
            "ma20_prior_lag5_RUNTIME_HFQ": lag if np.isfinite(lag) else None}


def public_sell(inputs, day, quantity):
    stamp = pd.Timestamp(day)
    status = inputs.trading_status.loc[stamp, "Status"]
    if status == "SUSPENDED":
        return {"filled": False, "price": None, "trigger": None, "reason": "SUSPENDED",
                "filled_at": None, "time_precision": None}
    if status != "TRADING":
        raise ValueError("Unknown original trading status")
    quote = inputs.projected_execution.loc[stamp]
    bounds = inputs.price_limits.loc[stamp]
    scale = float(quote.Close / inputs.raw_execution.loc[stamp, "Close"])
    limits = SessionPriceLimits(stamp.date(), float(bounds.DownLimit * scale),
                                float(bounds.UpLimit * scale), float(.01 * scale))
    fill = resolve_fill(OrderSpec("SELL", "MARKET", quantity), session_open=float(quote.Open),
                        session_time=datetime.combine(stamp.date(), time(9, 30)), intraday_touches=(),
                        daily_quote=DailyQuote(float(quote.Low), float(quote.High)), session_limits=limits)
    return {"filled": bool(fill.filled), "price": float(fill.price) if fill.filled else None,
            "trigger": fill.trigger, "reason": fill.reason,
            "filled_at": fill.filled_at.isoformat() if fill.filled_at is not None else None,
            "time_precision": fill.time_precision.value}


def simulate(seed, inputs, action):
    if type(seed) is not CycleSeed or type(inputs) is not PreparedInputs or type(action) is not Action:
        raise ValueError("Typed CycleSeed, PreparedInputs and Action required")
    if inputs.source_market.index.get_loc(pd.Timestamp(seed.entry_E)) != seed.entry_index:
        raise ValueError("Original absolute entry index must not be rebased")
    pending = False
    pending_D = None
    latched = False
    first_shock_seen = False
    trace, attempts = [], []
    for day in inputs.execution_dates:
        if day < seed.entry_E or day > inputs.cutoff:
            continue
        if pending:
            if inputs.clock[pending_D] != day:
                raise ValueError("Original D intent must execute only its valid E")
            result = public_sell(inputs, day, seed.quantity)
            attempt = {"D": pending_D, "E": day, **result, "quantity": seed.quantity}
            attempts.append(attempt)
            if result["filled"]:
                fee = float(result["price"] * seed.quantity * .001)
                return {"event_id": seed.event_id, "cycle_id": seed.cycle_id, "action": action.value,
                        "status": "CLOSED", "exit_E": day, "exit_price_ledger": result["price"],
                        "exit_fee": fee, "quantity": seed.quantity, "exit_trigger": result["trigger"],
                        "exit_fill_time": result["filled_at"], "exit_time_precision": result["time_precision"],
                        "trace": trace, "attempts": attempts, "post_sale_close_evaluated": False}
        if day not in inputs.clock:
            if day != inputs.cutoff:
                raise ValueError("Missing original source-to-execution decision clock")
            continue
        stamp = pd.Timestamp(day)
        index = inputs.source_market.index.get_loc(stamp)
        f = inputs.source_features.loc[stamp]
        close = float(inputs.source_market.loc[stamp, "Close"])
        inherited = pending
        expired = bool(index >= seed.deadline_index)
        eligible = bool(not inherited and not expired)
        support = float(f.support_floor)
        support_break = bool(np.isfinite(support) and close < support)
        net = close * (1 - .001) / (seed.runtime_entry_price * (1 + .001)) - 1
        shock = bool(eligible and f.shock_known and net > 0 and f.z5 > 2)
        if shock and not first_shock_seen:
            if day != seed.first_shock_D:
                raise ValueError("First SHOCK must match original frozen event")
            first_shock_seen = True
            latched = action is Action.OFF_LOCAL_CYCLE
        cost_loss = seed.runtime_entry_price * (1 + .001) - close * (1 - .001)
        cost = bool(eligible and f.atr_positive and cost_loss >= f.atr20_prior)
        selected_shock = bool(shock and not latched)
        risk = bool(selected_shock or cost)
        grace_eligible = bool(eligible and day == seed.entry_E and support_break)
        ordinary_support = bool(eligible and support_break and not grace_eligible)
        pending = bool(inherited or expired or risk or ordinary_support)
        if pending:
            pending_D = day
        trace.append({"D": day, "valid_E": inputs.clock[day], "market_index": index,
                      "entry_index": seed.entry_index, "deadline_index": seed.deadline_index,
                      "reservation_index": seed.reservation_index, "holding_age": index - seed.entry_index,
                      "target_position": 0.0 if pending else 1.0, "held_at_close": True,
                      "pending_inherited": inherited, "deadline_exit": expired,
                      "profit_exit_eligible": eligible, "shock_condition": shock,
                      "selected_shock_exit": selected_shock, "selected_cost_exit": cost,
                      "selected_risk_exit": risk, "ordinary_support_exit": ordinary_support,
                      "entry_grace_eligible": grace_eligible, "entry_grace_applied": grace_eligible and not risk,
                      "support_exit_suppressed": bool(eligible and support_break and grace_eligible and not risk),
                      "support_break": support_break, "net_profit": net, "cost_loss_price": cost_loss,
                      "exit_pending": pending, "shock_disable_latched": latched})
    return {"event_id": seed.event_id, "cycle_id": seed.cycle_id, "action": action.value,
            "status": "CENSORED", "exit_E": None, "exit_price_ledger": None, "exit_fee": None,
            "quantity": seed.quantity, "exit_trigger": None, "exit_fill_time": None,
            "exit_time_precision": None, "trace": trace, "attempts": attempts,
            "post_sale_close_evaluated": False}


def label(seed, original_exit_price, original_exit_fee, alternative):
    if type(seed) is not CycleSeed or alternative["action"] != Action.OFF_LOCAL_CYCLE.value:
        raise ValueError("Fixed actual seed and OFF cycle required")
    if alternative["status"] == "CENSORED":
        return {"advantage": None, "sign": None, "delta_net_proceeds": None}
    if alternative["status"] != "CLOSED" or alternative["quantity"] != seed.quantity:
        raise ValueError("Unsupported or changed-quantity cycle")
    original = original_exit_price * seed.quantity - original_exit_fee
    other = alternative["exit_price_ledger"] * seed.quantity - alternative["exit_fee"]
    delta = other - original
    value = delta / (seed.ledger_entry_price * seed.quantity + seed.actual_buy_fee)
    return {"advantage": value, "sign": 1 if value > 0 else -1 if value < 0 else 0,
            "delta_net_proceeds": delta}
