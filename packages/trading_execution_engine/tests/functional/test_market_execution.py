from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import pickle

import pandas as pd
import pytest

from trading_execution_engine import (
    MarketExecutionRules, OrderSpec, SessionPriceLimits, execute_target_positions, resolve_fill,
)


@pytest.mark.parametrize("symbol,down,up", [("600722.SH", 9., 11.), ("510500.SH", 9., 11.), ("588080.SH", 8., 12.)])
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_stock_and_etf_block_open_limit_even_when_the_market_reopens(symbol, down, up, side):
    session = date(2026, 9, 18)
    limits = SessionPriceLimits(session, down, up)
    rules = MarketExecutionRules(symbol, (limits,))
    assert rules.for_session(session) is limits
    opened = up if side == "BUY" else down
    touch = down if side == "BUY" else up
    for order_type in ("MARKET", "LIMIT"):
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


@pytest.mark.parametrize("down,up", [(0., 10.), (11., 10.), (10., 10.), (float("nan"), 10.), (9., float("inf"))])
def test_price_boundaries_reject_invalid_values(down, up):
    with pytest.raises(ValueError):
        SessionPriceLimits(date(2026, 9, 18), down, up)


def test_rule_identity_is_deterministic_and_validates_session_coverage():
    limits = SessionPriceLimits(date(2026, 9, 18), 9, 11)
    rules = MarketExecutionRules("600722.SH", (limits,))
    assert rules.fingerprint == MarketExecutionRules("600722.SH", (SessionPriceLimits(limits.session, 9., 11.),)).fingerprint
    assert rules.fingerprint != MarketExecutionRules("510500.SH", (limits,)).fingerprint
    restored = pickle.loads(pickle.dumps(rules, protocol=pickle.HIGHEST_PROTOCOL))
    assert restored == rules and restored.fingerprint == rules.fingerprint
    assert restored.for_session(limits.session) == limits
    restored = MarketExecutionRules.from_dict(json.loads(json.dumps(rules.to_dict())))
    assert restored.to_dict() == rules.to_dict()
    assert restored.fingerprint == sha256(json.dumps(restored.to_dict(), ensure_ascii=False,
                                                   sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert rules.to_dict() == {"contract_version": "OPEN_LIMIT_BLOCK_V1", "symbol": "600722.SH",
                               "sessions": [{"session": "2026-09-18", "down_limit": 9., "up_limit": 11.}]}
    with pytest.raises(ValueError, match="do not cover"):
        rules.for_session(limits.session + timedelta(days=1))
    with pytest.raises(ValueError, match="unique and increasing"):
        MarketExecutionRules("600722.SH", (limits, limits))
    with pytest.raises(ValueError, match="unique and increasing"):
        MarketExecutionRules("600722.SH", (SessionPriceLimits(date(2026, 9, 21), 9., 11.), limits))
    with pytest.raises(ValueError, match="symbol"):
        MarketExecutionRules("AAPL", (limits,))
    with pytest.raises(TypeError, match="date"):
        SessionPriceLimits(datetime(2026, 9, 18), 9., 11.)


@pytest.mark.parametrize("change", [
    lambda raw: {**raw, "contract_version": "UNKNOWN"},
    lambda raw: {**raw, "extra": 1},
    lambda raw: {key: value for key, value in raw.items() if key != "symbol"},
    lambda raw: {**raw, "symbol": 600722},
    lambda raw: {**raw, "sessions": tuple(raw["sessions"])},
    lambda raw: {**raw, "sessions": []},
    lambda raw: {**raw, "sessions": [None]},
    lambda raw: {**raw, "sessions": [{**raw["sessions"][0], "extra": 1}]},
    lambda raw: {**raw, "sessions": [{**raw["sessions"][0], "session": "20260918"}]},
    lambda raw: {**raw, "sessions": [{**raw["sessions"][0], "session": "2026-02-30"}]},
    lambda raw: {**raw, "sessions": [{**raw["sessions"][0], "session": date(2026, 9, 18)}]},
    lambda raw: {**raw, "sessions": [{**raw["sessions"][0], "down_limit": True}]},
    lambda raw: {**raw, "sessions": [{**raw["sessions"][0], "up_limit": "11.0"}]},
    lambda raw: {**raw, "sessions": [{**raw["sessions"][0], "up_limit": float("nan")}]},
])
def test_market_contract_deserialization_is_closed_and_strict(change):
    raw = MarketExecutionRules("600722.SH", (SessionPriceLimits(date(2026, 9, 18), 9., 11.),)).to_dict()
    with pytest.raises((TypeError, ValueError)):
        MarketExecutionRules.from_dict(change(raw))


@pytest.mark.parametrize("order,reason", [
    (OrderSpec("BUY", "LIMIT", 100, 11.1), "ORDER_PRICE_OUTSIDE_LIMITS"),
    (OrderSpec("SELL", "LIMIT", 100, 8.9), "ORDER_PRICE_OUTSIDE_LIMITS"),
    (OrderSpec("BUY", "LIMIT", 100, 9.5), "LIMIT_NOT_CROSSED"),
])
def test_unfilled_reasons_are_explicit(order, reason):
    fill = resolve_fill(order, session_open=10., session_time=datetime(2026, 9, 18, 9, 30),
                        intraday_touches=(), session_limits=SessionPriceLimits(date(2026, 9, 18), 9., 11.))
    assert not fill.filled and fill.reason == reason


def test_market_limits_validate_all_prices_before_even_a_blocked_order():
    limits = SessionPriceLimits(date(2026, 9, 18), 9., 11.)
    with pytest.raises(ValueError, match="outside"):
        resolve_fill(OrderSpec("BUY", "MARKET", 100), session_open=11.,
                     session_time=datetime(2026, 9, 18, 9, 30),
                     intraday_touches=[(datetime(2026, 9, 18, 10), 8.)], session_limits=limits)
    with pytest.raises(ValueError, match="another session"):
        resolve_fill(OrderSpec("BUY", "MARKET", 100), session_open=10.,
                     session_time=datetime(2026, 9, 21, 9, 30), intraday_touches=(), session_limits=limits)
    fill = resolve_fill(OrderSpec("BUY", "MARKET", 100), session_open=10.99,
                        session_time=datetime(2026, 9, 18, 9, 30), intraday_touches=(),
                        slippage_bp=100, session_limits=limits)
    assert not fill.filled and fill.reason == "FILL_PRICE_OUTSIDE_LIMITS"


@pytest.mark.parametrize("times", [
    [datetime(2026, 9, 21, 10)],
    [datetime(2026, 9, 18, 9)],
    [datetime(2026, 9, 18, 10), datetime(2026, 9, 18, 10)],
    [datetime(2026, 9, 18, 11), datetime(2026, 9, 18, 10)],
    ["2026-09-18T10:00:00"],
])
def test_market_fill_rejects_invalid_touch_timestamps_before_open_fill(times):
    with pytest.raises((TypeError, ValueError)):
        resolve_fill(OrderSpec("BUY", "MARKET", 100), session_open=10.,
                     session_time=datetime(2026, 9, 18, 9, 30),
                     intraday_touches=[(timestamp, 10.) for timestamp in times],
                     session_limits=SessionPriceLimits(date(2026, 9, 18), 9., 11.))


@pytest.mark.parametrize("value", [float("inf"), float("nan"), 0.])
def test_market_fill_rejects_invalid_later_prices_before_open_fill(value):
    with pytest.raises(ValueError, match="positive and finite"):
        resolve_fill(OrderSpec("BUY", "MARKET", 100), session_open=11.,
                     session_time=datetime(2026, 9, 18, 9, 30),
                     intraday_touches=[(datetime(2026, 9, 18, 10), value)],
                     session_limits=SessionPriceLimits(date(2026, 9, 18), 9., 11.))


def test_daily_blocked_orders_retry_without_a_signal_change_and_preserve_the_ledger():
    dates = pd.bdate_range("2026-09-15", periods=4)
    prices = pd.DataFrame({"open": [11., 10., 9., 10.], "close": [10.5, 10., 9.5, 10.]}, index=dates)
    rules = MarketExecutionRules("600722.SH", tuple(SessionPriceLimits(day.date(), 9., 11.) for day in dates))
    result = execute_target_positions(prices, pd.Series([1., 1., 0., 0.], index=dates),
                                      fee_rate=.001, initial_cash=2000., lot_size=100, market_rules=rules)
    assert result.attempts.status.tolist() == ["UNFILLED", "FILLED", "UNFILLED", "FILLED"]
    assert result.orders.execution_date.tolist() == [dates[1], dates[3]]
    assert result.orders.fees.tolist() == [1., 1.]
    assert result.state.cash.tolist() == [2000., 999., 999., 1998.]
    assert result.state.quantity.tolist() == [0., 100., 100., 0.]
    assert result.equity.tolist() == [2000., 1999., 1949., 1998.]


def test_daily_market_contract_rejects_a_later_missing_session_before_any_replay():
    dates = pd.bdate_range("2026-09-17", periods=2)
    prices = pd.DataFrame({"open": [10., 10.], "close": [10., 10.]}, index=dates)
    rules = MarketExecutionRules("600722.SH", (SessionPriceLimits(dates[0].date(), 9., 11.),))
    with pytest.raises(ValueError, match="do not cover"):
        execute_target_positions(prices, pd.Series([1., 1.], index=dates),
                                 fee_rate=.001, initial_cash=2000., market_rules=rules)
