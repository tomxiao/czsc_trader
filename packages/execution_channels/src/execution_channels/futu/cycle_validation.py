"""Validate account-owned allocation plans without invoking a strategy runtime."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
import math
from ..session_contracts import PlannedOrder, validate_entry_cycle_plan_facts
from ..contracts import OrderSide, OrderType

class AdviceContractError(ValueError):
    """The strategy CLI emitted a payload PTE cannot execute safely."""

def _validate_cycle_decision(*, signal, before, after, status, actual_quantity,
                             target_quantity, cycle_quantity, orders, cash, fee, fraction,
                             signal_identity):
    """Adapt PTE values to the same semantic validator used by SRT plans."""
    validate_entry_cycle_plan_facts(
        cycle_target=signal, entry_cycle_before=before, entry_cycle_after=after, cycle_status=status,
        target_position=float(signal.active), actual_quantity=actual_quantity, target_quantity=target_quantity,
        cycle_target_quantity=cycle_quantity, allocation_fraction=fraction, available_cash=cash, fee_rate=fee,
        signal_identity=signal_identity,
        orders=tuple(PlannedOrder(OrderSide(order.side), order.quantity, OrderType(order.order_type),
                                  Decimal(str(order.limit_price))) for order in orders),
        plan_mode="NONE", legs=(),
    )

def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdviceContractError(f"{name} must be an object")
    return value

def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdviceContractError(f"{name} must be an integer")
    return value

@dataclass(frozen=True)
class OrderSpec:
    side: str
    quantity: int
    order_type: str
    limit_price: float
    time_in_force: str

    @classmethod
    def from_payload(cls, payload: object) -> "OrderSpec":
        value = _object(payload, "order")
        price = value.get("limit_price")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise AdviceContractError("order limit price must be numeric")
        price = float(price)
        if not math.isfinite(price) or price <= 0:
            raise AdviceContractError("order limit price must be positive and finite")
        quantity = _integer(value.get("quantity"), "order quantity")
        if quantity <= 0 or quantity % 100:
            raise AdviceContractError("order quantity must use positive 100-share lots")
        side = str(value.get("side", ""))
        if side not in {"BUY", "SELL"}:
            raise AdviceContractError("order side must be BUY or SELL")
        order_type = str(value.get("order_type", ""))
        if order_type not in {"LIMIT", "MARKET"}:
            raise AdviceContractError("order type must be LIMIT or MARKET")
        if side == "BUY" and order_type != "LIMIT":
            raise AdviceContractError("buy orders must use LIMIT")
        if side == "SELL" and order_type not in {"LIMIT", "MARKET"}:
            raise AdviceContractError("sell orders must use LIMIT or MARKET")
        if value.get("time_in_force") != "DAY":
            raise AdviceContractError("order time in force must be DAY")
        return cls(side, quantity, order_type, price, "DAY")
