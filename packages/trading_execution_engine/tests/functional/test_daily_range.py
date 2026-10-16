from datetime import date, datetime

import pytest

from trading_execution_engine import DailyQuote, FillTimePrecision, OrderSpec, SessionPriceLimits, resolve_fill


@pytest.mark.parametrize("side,kind,limit,open_price,low,high,price,precision", [
    ("BUY", "LIMIT", 10.1, 10., 9.8, 10., 10., "TIMESTAMP"),
    ("BUY", "LIMIT", 9.8, 10., 9.8, 10.2, 9.8, "SESSION"),
    ("BUY", "LIMIT", 9.79, 10., 9.8, 10.2, None, None),
    ("BUY", "LIMIT", 11., 11., 11., 11., 11., "TIMESTAMP"),
    ("SELL", "MARKET", None, 10., 9.8, 10.2, 10., "TIMESTAMP"),
    ("SELL", "MARKET", None, 9., 9., 9., None, None),
    ("SELL", "MARKET", None, 9., 9., 9.01, 9.01, "SESSION"),
])
def test_daily_range_fills_are_complete_and_preserve_observable_time_precision(
    side, kind, limit, open_price, low, high, price, precision,
):
    fill = resolve_fill(OrderSpec(side, kind, 100, limit), session_open=open_price,
                        session_time=datetime(2026, 9, 18, 9, 30), intraday_touches=(),
                        session_limits=SessionPriceLimits(date(2026, 9, 18), 9., 11., .01),
                        daily_quote=DailyQuote(low, high))
    assert fill.filled is (price is not None)
    assert fill.price == price
    if fill.filled:
        assert isinstance(fill.time_precision, FillTimePrecision)
        assert fill.time_precision == precision
        assert fill.filled_at.hour == (0 if precision == "SESSION" else 9)
    else:
        assert fill.filled_at is None
