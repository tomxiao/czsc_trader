"""Recorded external channel facts. This module never reads the PTE ledger."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_HALF_EVEN

from .broker import (BrokerAccount, BrokerOrder, BrokerPosition, BrokerSnapshot,
                     BrokerOrderRejectedError, BrokerSubmissionUncertainError,
                     TERMINAL_ORDER_STATUSES)
from .inspection_contracts import (PteOrderUpdate,
                                   InspectionOrderStatus, SubmissionOutcome)


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)


class RecordedFillBroker:
    """A deterministic replacement of the broker I/O boundary, never strategy logic."""

    channel_id = "futu_simulate_cn"
    model_version = "RECORDED_FILLS_V1"

    def __init__(self, initial_cash, symbol, submissions, updates, now):
        self.initial_cash = money(initial_cash)
        self.cash = self.initial_cash
        self.symbol = symbol
        self.quantity = 0
        self.price = Decimal("0")
        self.now = now
        self.submissions = {x.order: x for x in submissions}
        self.updates = {x.event_id: x for x in updates}
        self.keys = {}
        self.orders = {}
        self.intents = {}
        self.fees = {}
        self.called = []
        self.used_submissions = set()
        self.used_updates = set()
        self.cancelled = []

    def bind_intents(self, key_by_intent):
        for intent_id, key in key_by_intent.items():
            previous = self.keys.get(intent_id)
            if previous is not None and previous != key:
                raise ValueError("one actual intent cannot change its scenario order key")
            self.keys[intent_id] = key

    def _new_order(self, key, intent):
        return BrokerOrder(
            f"INSPECT-{len(self.intents)}", intent.symbol, intent.side, intent.quantity,
            intent.limit_price, "SUBMITTED", 0, 0.0, intent.intent_id,
            created_at=self.now().isoformat(), updated_at=self.now().isoformat(),
            order_type=intent.order_type,
        )

    def place_order(self, intent):
        self.called.append(intent.intent_id)
        key = self.keys.get(intent.intent_id)
        result = self.submissions.get(key)
        if result is None or key in self.used_submissions:
            raise ValueError("unexpected or repeated channel submission")
        if result.observed_at != self.now():
            raise ValueError("channel submission occurred at undeclared time")
        if intent.order_type == "MARKET" and result.outcome is SubmissionOutcome.UNKNOWN:
            raise ValueError("recorded market order requires synchronous fill or rejection")
        self.used_submissions.add(key)
        self.intents[key] = intent
        if result.outcome is SubmissionOutcome.REJECTED:
            raise BrokerOrderRejectedError("recorded channel rejection")
        if result.outcome is SubmissionOutcome.UNKNOWN:
            raise BrokerSubmissionUncertainError("recorded unknown channel result")
        self.orders[key] = self._new_order(key, intent)
        if intent.order_type == "MARKET":
            immediate = [x for x in self.updates.values() if x.order == key and x.observed_at == self.now()]
            if len(immediate) != 1 or immediate[0].status is not InspectionOrderStatus.FILLED:
                raise ValueError("recorded market order requires synchronous complete fill")
            self.apply(immediate[0])
        return self.orders[key]

    def apply(self, update: PteOrderUpdate):
        key = update.order
        if key not in self.intents:
            raise ValueError("channel report references an unsubmitted order")
        if self.submissions[key].outcome is SubmissionOutcome.REJECTED:
            raise ValueError("rejected order cannot acquire channel fills")
        order = self.orders.get(key)
        if order is None:
            order = self._new_order(key, self.intents[key])
        quantity = update.cumulative_filled_quantity
        fee = money(update.cumulative_fee)
        prior_fee = self.fees.get(key, Decimal("0"))
        if quantity < order.cumulative_filled_quantity or quantity > order.quantity or fee < prior_fee:
            raise ValueError("recorded cumulative fill or fee is invalid")
        if update.status is InspectionOrderStatus.OPEN and quantity:
            raise ValueError("OPEN report cannot contain fills")
        if update.status is InspectionOrderStatus.PARTIAL and not 0 < quantity < order.quantity:
            raise ValueError("PARTIAL report must be strictly between empty and full")
        if update.status is InspectionOrderStatus.FILLED and quantity != order.quantity:
            raise ValueError("FILLED report must complete the order")
        status = {
            InspectionOrderStatus.OPEN: "SUBMITTED",
            InspectionOrderStatus.PARTIAL: "FILLED_PART",
            InspectionOrderStatus.FILLED: "FILLED_ALL",
            InspectionOrderStatus.CANCELLED: "CANCELLED_PART" if quantity else "CANCELLED_ALL",
        }[update.status]
        if order.status in TERMINAL_ORDER_STATUSES and (
            status != order.status or quantity != order.cumulative_filled_quantity
            or money(update.average_fill_price) != money(order.average_fill_price) or fee != prior_fee
        ):
            raise ValueError("terminal order facts cannot be changed")
        prior_value = money(Decimal(order.cumulative_filled_quantity) * Decimal(str(order.average_fill_price)))
        next_value = money(Decimal(quantity) * update.average_fill_price)
        increment = quantity - order.cumulative_filled_quantity
        if next_value < prior_value or (increment == 0 and next_value != prior_value):
            raise ValueError("cumulative execution value cannot move without new shares")
        gross = next_value - prior_value
        self.cash = money(self.cash + (gross if order.side == "SELL" else -gross) - (fee - prior_fee))
        self.quantity += increment if order.side == "BUY" else -increment
        if self.quantity < 0 or self.cash < 0:
            raise ValueError("recorded channel would create negative holdings or cash")
        self.fees[key] = fee
        self.orders[key] = replace(order, status=status, cumulative_filled_quantity=quantity,
                                   average_fill_price=float(update.average_fill_price),
                                   updated_at=update.observed_at.isoformat())
        self.used_updates.add(update.event_id)

    def snapshot(self):
        frozen = sum((money(Decimal(row.quantity - row.cumulative_filled_quantity) * Decimal(str(row.limit_price)))
                      for row in self.orders.values()
                      if row.side == "BUY" and row.status not in TERMINAL_ORDER_STATUSES), Decimal("0"))
        value = money(self.price * self.quantity)
        return BrokerSnapshot(
            BrokerAccount("SIMULATE", "CN", float(self.cash), float(self.cash + value), float(frozen), float(value)),
            (BrokerPosition(self.symbol, self.quantity),) if self.quantity else (),
            tuple(self.orders.values()),
        )

    def account_snapshot(self):
        return self.snapshot()

    def order_snapshot(self):
        return tuple(self.orders.values())

    def historical_order_snapshot(self, start, end):
        return self.order_snapshot()

    def cancel_order(self, order_id):
        # The cancel request is observable. Only a declared later channel report
        # confirms cancellation; never manufacture a successful reply.
        self.cancelled.append(order_id)

    def close(self):
        pass
