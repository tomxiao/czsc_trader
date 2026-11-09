from datetime import date, datetime
import pickle

import pytest

from execution_channels.historical import (
    MarketExecutionRules, OrderSpec, SessionPriceLimits, SuspensionInformation, resolve_fill,
)


# Independent risk: EC08; responsibility-level assertions.
@pytest.mark.parametrize("side,order_type", [
    pytest.param("BUY", "MARKET", id="EC08-open-BUY-MARKET"),
    pytest.param("SELL", "MARKET", id="EC08-open-SELL-MARKET"),
])
def test_open_limit_blocks_only_the_restricted_direction(side, order_type):
    session = date(2026, 9, 18)
    down, up = 9., 11.
    limits = SessionPriceLimits(session, down, up)
    rules = MarketExecutionRules("510500.SH", (limits,))
    assert rules.for_session(session) is limits
    opened = up if side == "BUY" else down
    touch = down if side == "BUY" else up
    order = OrderSpec(side, order_type, 100, 10. if order_type == "LIMIT" else None)
    fill = resolve_fill(
        order, session_open=opened, session_time=datetime(2026, 9, 18, 9, 30),
        intraday_touches=[(datetime(2026, 9, 18, 10), touch)], session_limits=limits,
    )
    assert not fill.filled and fill.price is None and fill.filled_at is None
    assert fill.reason == ("OPEN_UP_LIMIT_BUY_BLOCKED" if side == "BUY" else "OPEN_DOWN_LIMIT_SELL_BLOCKED")
    opposite = resolve_fill(
        OrderSpec("SELL" if side == "BUY" else "BUY", "MARKET", 100),
        session_open=opened, session_time=datetime(2026, 9, 18, 9, 30),
        intraday_touches=(), session_limits=limits,
    )
    assert opposite.filled and opposite.price == opened


# Independent risk: EC08; responsibility-level assertions.
def test_unprovided_suspension_information_is_explicit_and_survives_transport():
    rules = MarketExecutionRules("588080.SH", (SessionPriceLimits(date(2026, 9, 18), 9., 11.),),
                                 suspension_information=SuspensionInformation.NOT_PROVIDED)
    assert rules.to_dict()["suspension_information"] == "NOT_PROVIDED"
    assert MarketExecutionRules.from_dict(rules.to_dict()) == rules
    assert pickle.loads(pickle.dumps(rules)) == rules
    with pytest.raises(ValueError, match="cannot declare"):
        MarketExecutionRules(rules.symbol, rules.sessions, (date(2026, 9, 17),),
                             SuspensionInformation.NOT_PROVIDED)


# Independent risk: EC07; responsibility-level assertions.


# Independent risk: EC12; responsibility-level assertions.


def test_EC08_C03_explicit_suspension_prevents_fill_with_reason():
    from execution_channels.instruments import MarketId
    from execution_channels.session_contracts import OrderSide
    from test_portfolio_parity import setup, facts, plan, order
    executor, stamp, _ = setup(MarketId.US)
    bar, rule = facts(stamp)
    rule['Tradable'] = False
    executor.execute_account_plan(plan(executor,stamp,(order(OrderSide.BUY,100),)),bar,constraint=rule)
    assert executor.quantity == 0 and executor.cash == 10000.
    assert not executor.rows['fills']
    assert executor.rows['orders'][0]['reason'] == 'NOT_TRADABLE'
