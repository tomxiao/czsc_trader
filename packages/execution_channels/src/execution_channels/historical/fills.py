from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Iterable
from enum import StrEnum

from .market import SessionPriceLimits


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


class FillTimePrecision(StrEnum):
    TIMESTAMP = "TIMESTAMP"
    SESSION = "SESSION"


@dataclass(frozen=True)
class FillDecision:
    filled: bool
    price: float | None
    filled_at: datetime | None
    trigger: str | None
    reason: str | None = None
    time_precision: FillTimePrecision = FillTimePrecision.TIMESTAMP


@dataclass(frozen=True)
class DailyQuote:
    low: float
    high: float

    def __post_init__(self):
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not isfinite(x) or x <= 0
               for x in (self.low, self.high)) or self.low > self.high:
            raise ValueError("daily range requires positive finite ordered prices")


def resolve_fill(
    order: OrderSpec,
    *,
    session_open: float,
    session_time: datetime,
    intraday_touches: Iterable[tuple[datetime, float]],
    slippage_bp: float = 0.0,
    inclusive_touch: bool = False,
    session_limits: SessionPriceLimits | None = None,
    daily_quote: DailyQuote | None = None,
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
    if session_limits is not None:
        if not isinstance(session_limits, SessionPriceLimits):
            raise TypeError("session_limits must be SessionPriceLimits")
        if not isinstance(session_time, datetime):
            raise TypeError("session_time must be a datetime")
        if session_time.date() != session_limits.session:
            raise ValueError("session price limits belong to another session")
        if not session_limits.contains(open_price) or any(
            not session_limits.contains(value) for _, value in touches
        ):
            raise ValueError("market prices are outside session price limits")
        timestamps = tuple(timestamp for timestamp, _ in touches)
        if any(not isinstance(timestamp, datetime) for timestamp in timestamps):
            raise TypeError("intraday price timestamps must be datetimes")
        if any(timestamp.date() != session_limits.session for timestamp in timestamps):
            raise ValueError("intraday prices belong to another session")
        try:
            valid_order = all(timestamp >= session_time for timestamp in timestamps) and all(
                earlier < later for earlier, later in zip(timestamps, timestamps[1:])
            )
        except TypeError as exc:
            raise ValueError("intraday timestamps must use the session time zone") from exc
        if not valid_order:
            raise ValueError("intraday prices must use increasing timestamps at or after session open")
        if order.order_type == "LIMIT" and not session_limits.contains(float(order.limit_price)):
            return FillDecision(False, None, None, None, "ORDER_PRICE_OUTSIDE_LIMITS")
        if daily_quote is None and order.side == "BUY" and session_limits.at_upper(open_price):
            return FillDecision(False, None, None, None, "OPEN_UP_LIMIT_BUY_BLOCKED")
        if daily_quote is None and order.side == "SELL" and session_limits.at_lower(open_price):
            return FillDecision(False, None, None, None, "OPEN_DOWN_LIMIT_SELL_BLOCKED")

    if daily_quote is not None:
        if not isinstance(daily_quote, DailyQuote) or not daily_quote.low <= open_price <= daily_quote.high:
            raise ValueError("daily quote does not contain the opening price")
        if slippage_bp:
            raise ValueError("daily range execution does not accept slippage")
        if session_limits is not None and not all(session_limits.contains(x) for x in (daily_quote.low, daily_quote.high)):
            raise ValueError("daily range is outside session price limits")
        if order.side == "SELL" and order.order_type == "MARKET" and session_limits is not None and session_limits.at_lower(open_price):
            price = open_price + session_limits.price_tick
            if price > daily_quote.high + abs(price) * 1e-12:
                return FillDecision(False, None, None, None, "DAILY_RANGE_NOT_REACHED")
            return FillDecision(True, price, session_time.replace(hour=0, minute=0, second=0, microsecond=0),
                                "DAILY_OPEN_PLUS_TICK", "FILLED", FillTimePrecision.SESSION)
        if order.order_type == "MARKET":
            return FillDecision(True, open_price, session_time, "OPEN_MARKET", "FILLED")
        limit = float(order.limit_price)
        tolerance = max(abs(limit), abs(open_price), abs(daily_quote.low), abs(daily_quote.high)) * 1e-12
        crosses_open = open_price <= limit + tolerance if order.side == "BUY" else open_price + tolerance >= limit
        if crosses_open:
            return FillDecision(True, open_price, session_time, "OPEN", "FILLED")
        reached = daily_quote.low <= limit + tolerance if order.side == "BUY" else daily_quote.high + tolerance >= limit
        if not reached:
            return FillDecision(False, None, None, None, "DAILY_RANGE_NOT_REACHED")
        return FillDecision(True, limit, session_time.replace(hour=0, minute=0, second=0, microsecond=0),
                            "DAILY_LIMIT", "FILLED", FillTimePrecision.SESSION)

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
        return FillDecision(False, None, None, None, "LIMIT_NOT_CROSSED")
    price = raw_price * (1.0 + slippage if order.side == "BUY" else 1.0 - slippage)
    if not isfinite(price) or price <= 0:
        raise ValueError("fill price must be positive and finite")
    if session_limits is not None and not session_limits.contains(price):
        return FillDecision(False, None, None, None, "FILL_PRICE_OUTSIDE_LIMITS")
    return FillDecision(True, price, filled_at, trigger, "FILLED")
