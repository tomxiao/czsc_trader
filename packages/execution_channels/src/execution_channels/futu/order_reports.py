"""Shared cumulative-order validation and atomic fill/report accounting."""
from contextlib import nullcontext
from datetime import datetime
from decimal import Decimal

from .broker import KNOWN_ORDER_STATUSES, TERMINAL_ORDER_STATUSES


def apply_order_report(store, payload, *, occurred_at: str, settlement_at: str | None = None):
    """Apply a confirmed report once; a failure rolls back both fills and release."""
    context = nullcontext() if store._atomic_decision_depth else store.atomic_decision_update()
    with context:
        order_id = str(payload['channel_order_id'])
        previous = store.account_order(order_id)
        status = str(payload['status'])
        quantity = payload['cumulative_filled_quantity']
        average = Decimal(str(payload['average_fill_price']))
        old_quantity = int(previous['cumulative_filled_quantity'])
        if status not in KNOWN_ORDER_STATUSES:
            raise ValueError('unknown channel order status')
        if type(quantity) is not int or not old_quantity <= quantity <= int(previous['quantity']):
            raise ValueError('cumulative order quantity cannot decrease or exceed ordered shares')
        if not average.is_finite() or average < 0 or (quantity and average <= 0):
            raise ValueError('invalid cumulative order average price')
        if quantity == old_quantity and quantity and average != Decimal(str(previous['average_fill_price'])):
            raise ValueError('same cumulative fill carries a different price')
        if previous.get('report_applied_at') and previous['status'] in TERMINAL_ORDER_STATUSES:
            if status != previous['status'] or quantity != old_quantity:
                raise ValueError('terminal channel order cannot change without explicit reconciliation')
        if status == 'FILLED_ALL' and quantity != int(previous['quantity']):
            raise ValueError('fully filled status differs from ordered quantity')
        if status == 'FILLED_PART' and not 0 < quantity < int(previous['quantity']):
            raise ValueError('partial status requires a strict partial quantity')
        stamp = datetime.fromisoformat(occurred_at)
        if stamp.utcoffset() is None:
            raise ValueError('channel report requires timezone-aware occurrence time')
        if previous.get('report_applied_at') and stamp < datetime.fromisoformat(previous['report_applied_at']):
            raise ValueError('channel event time cannot move backwards')
        notional = payload.get('cumulative_notional')
        if notional is not None and Decimal(str(notional)) != average * quantity:
            raise ValueError('cumulative notional differs from quantity and price')
        result = store.apply_fill_increment(order_id, cumulative_quantity=quantity,
            average_price=average, occurred_at=occurred_at, settlement_at=settlement_at)
        value = dict(payload)
        value['average_fill_price'] = str(average)
        value['report_applied_at'] = occurred_at
        store.update_channel_order_report(order_id, value)
        return result
