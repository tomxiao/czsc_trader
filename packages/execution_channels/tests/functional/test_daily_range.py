"""EC07: observable touch prices and explicit adverse slippage."""
from datetime import date,datetime
import pytest
from execution_channels.historical import DailyQuote,OrderSpec,SessionPriceLimits,resolve_fill


@pytest.mark.parametrize('side,limit,opened,low,high,price,precision',[
    pytest.param('BUY',10.1,10.,9.8,10.,10.,'TIMESTAMP',id='EC07-C01'),
    pytest.param('BUY',9.8,10.,9.8,10.2,9.8,'SESSION',id='EC07-C02'),
    pytest.param('SELL',10.2,10.,9.8,10.2,10.2,'SESSION',id='EC07-C03'),
    pytest.param('BUY',9.79,10.,9.8,10.2,None,None,id='EC07-C04'),
])
def test_daily_touch_preserves_price_reason_and_observable_precision(side,limit,opened,low,high,price,precision):
    fill=resolve_fill(OrderSpec(side,'LIMIT',100,limit),session_open=opened,
        session_time=datetime(2026,9,18,9,30),intraday_touches=(),
        session_limits=SessionPriceLimits(date(2026,9,18),9.,11.,.01),daily_quote=DailyQuote(low,high))
    assert fill.filled is (price is not None) and fill.price==price
    if price is None:
        assert fill.filled_at is None and fill.reason=='DAILY_RANGE_NOT_REACHED'
    else:
        assert fill.time_precision==precision
        assert fill.filled_at.hour==(0 if precision=='SESSION' else 9)


@pytest.mark.parametrize('side,limit,expected',[
    pytest.param('BUY',10.2,10.01,id='EC07-C05'),
    pytest.param('SELL',9.8,9.99,id='EC07-C06'),
])
def test_positive_slippage_is_adverse_within_the_given_limit(side,limit,expected):
    fill=resolve_fill(OrderSpec(side,'LIMIT',100,limit),session_open=10.,
        session_time=datetime(2026,9,18,9,30),intraday_touches=(),slippage_bp=10)
    assert fill.filled and fill.price==pytest.approx(expected)
    assert (10.<fill.price<limit) if side=='BUY' else (limit<fill.price<10.)
