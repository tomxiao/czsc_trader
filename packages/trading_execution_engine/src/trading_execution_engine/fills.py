from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Iterable


@dataclass(frozen=True)
class OrderSpec:
    side: str
    order_type: str
    quantity: float
    limit_price: float | None = None

    def __post_init__(self) -> None:
        if self.side not in {"BUY", "SELL"}:
            raise ValueError(f"unsupported side: {self.side}")
        if self.order_type not in {"LIMIT", "MARKET"}:
            raise ValueError(f"unsupported order type: {self.order_type}")
        if not isfinite(float(self.quantity)) or self.quantity <= 0:
            raise ValueError("order quantity must be positive and finite")
        if self.order_type == "LIMIT":
            if self.limit_price is None or not isfinite(float(self.limit_price)) or self.limit_price <= 0:
                raise ValueError("limit order requires a positive finite limit price")


@dataclass(frozen=True)
class FillDecision:
    filled: bool
    price: float | None
    filled_at: datetime | None
    trigger: str | None


def resolve_fill(
    order: OrderSpec,
    *,
    session_open: float,
    session_time: datetime,
    intraday_touches: Iterable[tuple[datetime, float]],
    slippage_bp: float = 0.0,
    inclusive_touch: bool = False,
) -> FillDecision:
    """Resolve one order using one canonical fill rule.

    ``intraday_touches`` contains lows for buys and highs for sells in time order.
    Slippage is adverse to the trader and is applied after the market/limit trigger.
    """

    open_price = float(session_open)
    slippage = float(slippage_bp) / 10_000.0
    if not isfinite(open_price) or open_price <= 0:
        raise ValueError("session open must be positive and finite")
    if not isfinite(slippage) or not 0 <= slippage < 1:
        raise ValueError("slippage_bp must be finite and in [0, 10000)")
    touches = tuple((timestamp, float(value)) for timestamp, value in intraday_touches)
    if any(not isfinite(value) or value <= 0 for _, value in touches):
        raise ValueError("intraday prices must be positive and finite")

    raw_price: float | None = None
    filled_at: datetime | None = None
    trigger: str | None = None
    if order.order_type == "MARKET":
        raw_price, filled_at, trigger = open_price, session_time, "OPEN_MARKET"
    else:
        limit = float(order.limit_price)
        open_crosses = open_price <= limit if order.side == "BUY" else open_price >= limit
        if open_crosses:
            raw_price, filled_at, trigger = open_price, session_time, "OPEN"
        else:
            for timestamp, touch in touches:
                if order.side == "BUY":
                    crosses = touch <= limit if inclusive_touch else touch < limit
                else:
                    crosses = touch >= limit if inclusive_touch else touch > limit
                if crosses:
                    raw_price, filled_at, trigger = limit, timestamp, "INTRADAY_LIMIT"
                    break
    if raw_price is None or filled_at is None:
        return FillDecision(False, None, None, None)
    price = raw_price * (1.0 + slippage if order.side == "BUY" else 1.0 - slippage)
    if not isfinite(price) or price <= 0:
        raise ValueError("fill price must be positive and finite")
    return FillDecision(True, price, filled_at, trigger)
