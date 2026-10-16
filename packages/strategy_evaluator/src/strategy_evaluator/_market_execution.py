"""Independent audit of declared market bounds; no dependency on the executor."""
from datetime import date, datetime, time
from math import isfinite
import re
from typing import Any, Mapping


def market_limits(value: Mapping[str, Any] | None, sessions) -> dict[str, tuple[float, float]]:
    if value is None:
        return {}  # Explicit price-only numerical evidence has no market identity.
    if (not isinstance(value, Mapping) or set(value) != {"contract_version", "symbol", "sessions", "suspended_sessions", "suspension_information"}
            or value["contract_version"] != "DAILY_RANGE_V3"
            or value["suspension_information"] not in {"PROVIDED", "NOT_PROVIDED"}
            or not isinstance(value["symbol"], str)
            or re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", value["symbol"]) is None
            or not isinstance(value["sessions"], (tuple, list)) or not value["sessions"]):
        raise ValueError("invalid market execution contract")
    result = {}
    previous = ""
    for item in value["sessions"]:
        if not isinstance(item, Mapping) or set(item) != {"session", "down_limit", "up_limit", "price_tick"}:
            raise ValueError("invalid session price limits")
        day = item["session"]
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day or day <= previous:
            raise ValueError("invalid market sessions")
        lower, upper = item["down_limit"], item["up_limit"]
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not isfinite(x) for x in (lower, upper)):
            raise ValueError("invalid market limit prices")
        if not 0 < lower < upper:
            raise ValueError("invalid market limit prices")
        tick = item["price_tick"]
        if isinstance(tick, bool) or not isinstance(tick, (int, float)) or not isfinite(tick) or tick <= 0:
            raise ValueError("invalid market price tick")
        result[day] = (float(lower), float(upper))
        previous = day
    halted = value["suspended_sessions"]
    if value["suspension_information"] == "NOT_PROVIDED" and halted:
        raise ValueError("unprovided suspension information cannot declare suspended sessions")
    if (not isinstance(halted, (list, tuple)) or sorted(set(halted)) != list(halted)
            or any(date.fromisoformat(day).isoformat() != day for day in halted)
            or set(halted).intersection(result)):
        raise ValueError("invalid suspended sessions")
    if not set(str(item)[:10] for item in sessions).issubset(set(result) | set(halted)):
        raise ValueError("market limits do not cover audit sessions")
    return result


def blocked_order(side: str, open_price: float, bounds: tuple[float, float] | None,
                  *, order_type: str = "MARKET", limit_price: float | None = None) -> bool:
    if bounds is None:
        return False
    lower, upper = bounds
    if side.upper() not in {"BUY", "SELL"} or order_type not in {"MARKET", "LIMIT"}:
        raise ValueError("invalid market order semantics")
    tolerance = max(abs(lower), abs(upper)) * 1e-10
    if not isfinite(open_price):
        raise ValueError("opening price must be finite")
    if not lower - tolerance <= open_price <= upper + tolerance:
        raise ValueError("opening price outside market limits")
    if order_type == "LIMIT":
        if isinstance(limit_price, bool) or not isinstance(limit_price, (int, float)) or not isfinite(limit_price):
            raise ValueError("invalid market order limit")
        return not lower - tolerance <= limit_price <= upper + tolerance
    return False


def validate_market_prices(rows, limits: Mapping[str, tuple[float, float]], *, time_field: str,
                           fields=("open", "high", "low", "close")) -> None:
    """Check observable price coordinates even on days without any order."""
    if not limits:
        return
    for row in rows:
        bounds = limits.get(str(row[time_field])[:10])
        if bounds is None:
            continue  # Pre-evaluation warmup observations need no execution rule.
        lower, upper = bounds
        tolerance = max(abs(lower), abs(upper)) * 1e-10
        for field in fields:
            if field not in row:
                continue
            value = row[field]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or not lower - tolerance <= value <= upper + tolerance):
                raise ValueError("execution price outside market limits")


def strict_market_number(value: Any, *, integer: bool = False, positive: bool = False) -> None:
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
            or (integer and type(value) is not int) or value < 0 or (positive and value == 0)):
        raise ValueError("market execution requires finite nonnegative values and integer quantities")


def market_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or "T" not in value and " " not in value:
        raise ValueError("market fills and bars require explicit session timestamps")
    result = datetime.fromisoformat(value)
    if result.tzinfo is not None:
        raise ValueError("market timestamps must use local Shanghai session time")
    clock = result.time()
    if not (time(9, 30) <= clock <= time(11, 30) or time(13) <= clock <= time(15)):
        raise ValueError("market timestamp is outside continuous trading sessions")
    return result


def market_session(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("market sessions require ISO dates or midnight timestamps")
    result = datetime.fromisoformat(value)
    if result.tzinfo is not None or result.time() != time(0):
        raise ValueError("market session must be a local midnight date")
    return result.date().isoformat()


def expected_market_fill(side: str, order_type: str, limit: float, open_price: float,
                         session: str, bars, *, daily=None, bounds=None, price_tick=0.001) -> tuple[str, float, datetime] | None:
    opening = datetime.combine(date.fromisoformat(session), time(9, 30))
    if daily is not None:
        midnight = datetime.combine(date.fromisoformat(session), time(0))
        if side == "SELL" and order_type == "MARKET" and bounds is not None and abs(open_price - bounds[0]) <= abs(bounds[0]) * 1e-10:
            price = open_price + price_tick
            return ("DAILY_OPEN_PLUS_TICK", price, midnight) if daily["high"] + abs(price) * 1e-12 >= price else None
        if order_type == "MARKET":
            return "OPEN_MARKET", open_price, opening
        if open_price <= limit if side == "BUY" else open_price >= limit:
            return "OPEN", open_price, opening
        if daily["low"] <= limit if side == "BUY" else daily["high"] >= limit:
            return "DAILY_LIMIT", limit, midnight
        return None
    if order_type == "MARKET":
        return "OPEN_MARKET", open_price, opening
    crosses_open = open_price <= limit if side == "BUY" else open_price >= limit
    if crosses_open:
        return "OPEN", open_price, opening
    field = "low" if side == "BUY" else "high"
    for bar in bars:
        price = bar[field]
        crosses = price < limit if side == "BUY" else price > limit
        if crosses:
            return "INTRADAY_LIMIT", limit, market_timestamp(bar["time"])
    return None
