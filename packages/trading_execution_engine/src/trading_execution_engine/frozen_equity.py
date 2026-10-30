"""Private executor for exact V2 frozen-strategy technical replay.

New research uses PortfolioHistoricalExecutor. This adapter preserves only the
execution contract required to inspect already-frozen V2 implementations.
"""
from datetime import datetime
from collections.abc import Mapping
import math

import numpy as np
import pandas as pd
from dataflows import MarketId
from strategy_runtime.equity import (CashAvailabilityPolicy, EquityClosedCycle,
    EquityClosedCycleFeedback, EquityPlan, equity_hash)
from .equity import _EquityAccount, _timestamp, _bar_identity_value, _SESSION_ZONES
from .fills import OrderSpec, resolve_fill
from .accounting import _post_confirmed_fill

EquityRow = pd.Series | Mapping[str, object]


class _FrozenEquityExecutor(_EquityAccount):
    """Execution adapter used only by the V2 frozen technical inspection."""

    def execute(self, plan: EquityPlan, bar: EquityRow, *, constraint: EquityRow):
        """Execute a Series or immutable mapping row through the same fill kernel."""
        if not isinstance(bar, (pd.Series, Mapping)) or not isinstance(constraint, (pd.Series, Mapping)):
            raise TypeError("execution bar and constraint must be Series or Mapping rows")
        with self.transaction():
            return self._execute(plan, bar, constraint=constraint)

    def _execute(self, plan: EquityPlan, bar: EquityRow, *, constraint: EquityRow):
        if type(plan) is not EquityPlan or plan.specification_hash != self.spec.fingerprint:
            raise ValueError("MARKET_CONTRACT_MISMATCH: execution plan")
        interval = plan.point.execution_interval
        status = bar.get("BarStatus", "OBSERVED")
        if status not in {"OBSERVED", "MISSING", "ZERO_VOLUME"}:
            raise ValueError("invalid execution bar status")
        blocked = bar.get("ExecutionBlocked", False)
        if type(blocked) not in (bool, np.bool_):
            raise ValueError("invalid execution block flag")
        stale = status != "OBSERVED"
        if status == "MISSING":
            if not all(pd.isna(bar[name]) for name in ("Open", "High", "Low", "Close", "Volume", "Amount")):
                raise ValueError("missing bar must not contain fabricated prices or volume")
        else:
            prices = [float(bar[name]) for name in ("Open", "High", "Low", "Close")]
            opening, high, low, close = prices
            if (any(not math.isfinite(value) or value <= 0 for value in prices)
                or not low <= min(opening, close) or not high >= max(opening, close)):
                raise ValueError("invalid execution OHLCV")
            volume = float(bar['Volume'])
            if not math.isfinite(volume) or volume < 0:
                raise ValueError("invalid execution OHLCV")
            if "BarStatus" in bar and ((status == "ZERO_VOLUME") != (volume == 0)):
                raise ValueError("bar status differs from observed volume")
        bar_hash = equity_hash({"bar": {k: _bar_identity_value(v) for k, v in bar.items()},
                                "constraints": {k: (v.isoformat() if isinstance(v, (datetime, pd.Timestamp)) else v)
                                                for k, v in constraint.items()}})
        if plan.plan_id in self.completed:
            if self.completed[plan.plan_id] != bar_hash:
                raise ValueError("same plan was resubmitted with different execution facts")
            return self.snapshot()
        if plan.portfolio_revision != self.revision or (self.last_end is not None and interval.start < self.last_end):
            raise ValueError("stale portfolio revision or unordered execution")
        if _timestamp(bar["BarStart"]) != interval.start or _timestamp(bar["Date"]) != interval.end:
            raise ValueError("execution bar does not match plan interval")
        if (int(constraint["QuantityStep"]), float(constraint["PriceTick"])) != (self.spec.quantity_step, self.spec.price_tick):
            raise ValueError("dated quantity/price rules differ from declared execution specification")
        if _timestamp(constraint["Date"]) != interval.start or _timestamp(constraint["AvailableDate"]) > interval.start:
            raise ValueError("CAUSAL_TIME_VIOLATION: constraints must belong to this execution interval")
        if self.spec.market_id is MarketId.CN:
            # Existing CN engine owns exchange-bound execution. Do not execute CN
            # bars without its price limits and sellability semantics.
            raise ValueError("UNSUPPORTED_EXECUTION_COMBINATION: CN bar execution is not admitted")
        for event in self._action_events:
            if event.Kind != "NONE" and interval.start < _timestamp(event.Date) < interval.end:
                raise ValueError("CORPORATE_ACTION_UNSUPPORTED: event inside execution bar")
        quantity, limit = self._events(interval.start, after=plan.point.decision_at,
                                       plan_quantity=plan.quantity, limit_price=plan.limit_price)
        decision = {"decision_id": plan.plan_id, "observed_through": plan.point.observed_through,
                    "decision_at": plan.point.decision_at, "execution_start": interval.start,
                    "execution_end": interval.end, "target": plan.target, "reference_price": plan.reference_price,
                    "quantity": plan.quantity, "side": plan.side, "limit_price": plan.limit_price,
                    "portfolio_revision": plan.portfolio_revision, "signal_status": plan.signal_status}
        self.rows["decisions"].append(decision)
        if plan.explanation is not None:
            decision["explanation"] = plan.explanation
        if quantity:
            reason, fill_price, precision = "NOT_TRADABLE", None, None
            if status == "MISSING":
                reason = "MISSING_BAR"
            elif status == "ZERO_VOLUME":
                reason = "ZERO_VOLUME"
            elif blocked:
                reason = "KNOWN_INTERRUPTION"
            elif bool(constraint["Tradable"]) and (volume <= 0 or quantity > volume):
                reason = "INSUFFICIENT_BAR_VOLUME"
            elif bool(constraint["Tradable"]):
                fill = resolve_fill(OrderSpec(plan.side, "LIMIT" if plan.side == "BUY" else "MARKET",
                                               quantity, limit),
                                    session_open=opening, session_time=interval.start,
                                    intraday_touches=((interval.end, low if plan.side == "BUY" else high),),
                                    slippage_bp=self.spec.slippage_bp, inclusive_touch=self.spec.inclusive_touch)
                reason = fill.reason or "FILLED"
                if fill.filled:
                    price = float(fill.price)
                    if plan.side == "BUY" and price > limit:
                        reason = "SLIPPAGE_EXCEEDS_LIMIT"
                    elif plan.side == "BUY" and quantity * price * (1 + self.fee_rate) > self.cash + 1e-9:
                        reason = "INSUFFICIENT_CASH"
                    elif plan.side == "SELL" and quantity > self.quantity:
                        raise ValueError("sell quantity exceeds holdings")
                    else:
                        fill_price = price
                        precision = "BAR_INTERVAL" if fill.trigger == "INTRADAY_LIMIT" else "MODEL_BAR_OPEN"
            order = {"order_id": plan.plan_id, "decision_id": plan.plan_id,
                     "side": plan.side, "quantity": quantity, "limit_price": limit,
                     "valid_start": interval.start, "valid_end": interval.end,
                     "status": "FILLED" if fill_price is not None else "EXPIRED", "reason": reason}
            self.rows["orders"].append(order)
            if fill_price is not None:
                deferred = (plan.side == "SELL"
                    and self.spec.account.cash_availability is CashAvailabilityPolicy.SETTLED_ONLY)
                self.cash, self.quantity, self.receivable, gross, fees, _ = _post_confirmed_fill(
                    self.cash, self.quantity, self.receivable, plan.side == "BUY", quantity,
                    fill_price, self.fee_rate, deferred)
                if plan.side == "BUY":
                    if self.cycle is None:
                        self.cycle = plan.plan_id
                        self.cycle_entry = interval.start
                        self.cycle_cost = self.cycle_income = 0.
                        self._cycle_entry_interval = interval
                        self._cycle_entry_quantity = quantity
                        self._cycle_feedback_supported = True
                    else:
                        self._cycle_feedback_supported = False
                        self._closed_cycle_feedback = None
                    self.cycle_cost += gross + fees
                else:
                    if self.quantity:
                        self._cycle_feedback_supported = False
                        self._closed_cycle_feedback = None
                    proceeds = gross - fees
                    self.cycle_income += proceeds
                    if deferred:
                        settle = _timestamp(constraint["SettlementAt"])
                        if pd.isna(settle) or settle.tzinfo is None or settle < interval.end:
                            raise ValueError("missing or invalid settlement time")
                        self.pending.append((settle, proceeds, plan.plan_id, "SALE_SETTLEMENT"))
                self.rows["fills"].append({"fill_id": plan.plan_id, "order_id": plan.plan_id,
                                           "account_revision": self.revision,
                                           "cycle_id": self.cycle, "side": plan.side,
                                           "quantity": quantity, "price": fill_price, "fees": fees,
                                           "interval_start": interval.start, "interval_end": interval.end,
                                           "time_precision": precision})
                if self.quantity == 0 and self.cycle is not None:
                    # Preserve the old execution path even for manually supplied
                    # plans whose observation boundary cannot express this contract.
                    if (self._cycle_feedback_supported
                        and self._cycle_entry_interval.end <= plan.point.observed_through):
                        self._closed_cycle_feedback = EquityClosedCycleFeedback(EquityClosedCycle(
                            self.cycle, self._cycle_entry_interval, interval,
                            self._cycle_entry_quantity, self.cycle_cost, plan.point.observed_through))
                    else:
                        self._closed_cycle_feedback = None
                    self.rows["trades"].append({"cycle_id": self.cycle, "entry_at": self.cycle_entry,
                                               "exit_at": interval.end, "cost": self.cycle_cost,
                                               "income": self.cycle_income, "net_pnl": self.cycle_income - self.cycle_cost,
                                               "net_return": self.cycle_income / self.cycle_cost - 1,
                                               "status": "CLOSED"})
                    self.cycle = None
        self._events(interval.end, after=interval.start, plan_quantity=0, limit_price=None, include_actions=False)
        if self.cash < -1e-8 or self.quantity < 0:
            raise ValueError("unlevered long-only account invariant violated")
        self.revision += 1
        self.last_end = interval.end
        if not stale:
            self.last_mark_price, self.last_mark_time = close, interval.end
        elif self.last_mark_price is None:
            self.last_mark_price, self.last_mark_time = plan.reference_price, plan.point.observed_through
        self.rows["points"].append({"time": interval.end,
                                    "account_revision": self.revision - 1,
                                    "session": interval.end.astimezone(_SESSION_ZONES[self.spec.market_id]).date().isoformat(),
                                    "cash": self.cash, "quantity": self.quantity, "receivable": self.receivable,
                                    "close": self.last_mark_price,
                                    "equity": self.cash + self.receivable + self.quantity * self.last_mark_price,
                                    "bar_status": status, "valuation_stale": stale,
                                    "valuation_price_at": self.last_mark_time, "execution_blocked": bool(blocked),
                                    "cycle_id": self.cycle, "decision_id": plan.plan_id})
        for checkpoint in self._transactions:
            checkpoint.completed_added.append(plan.plan_id)
        self.completed[plan.plan_id] = bar_hash
        return self.snapshot()
