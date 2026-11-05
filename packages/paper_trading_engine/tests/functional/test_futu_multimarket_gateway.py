"""Independent CN/US gateway boundaries, using SDK-shaped broker responses."""
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from paper_trading_engine.broker import OrderIntent, PaperTradingSafetyError
from paper_trading_engine.channel import (
    ChannelAccountConfig, FUTU_SIMULATE_CN_CHANNEL_ID, FUTU_US_SIM_CHANNEL_ID,
)
from paper_trading_engine.futu_gateway import FutuGateway, FutuGatewayError


def sdk():
    return SimpleNamespace(
        RET_OK=0, TrdEnv=SimpleNamespace(SIMULATE="SIMULATE"),
        TrdMarket=SimpleNamespace(CN="CN", US="US"),
        Currency=SimpleNamespace(CNH="CNH", USD="USD"),
        Session=SimpleNamespace(RTH="RTH", ETH="ETH"),
        TrdSide=SimpleNamespace(BUY="BUY", SELL="SELL"),
        OrderType=SimpleNamespace(NORMAL="NORMAL", MARKET="MARKET"),
        TimeInForce=SimpleNamespace(DAY="DAY"), ModifyOrderOp=SimpleNamespace(CANCEL="CANCEL"),
        SysConfig=SimpleNamespace(enable_console_log=lambda _: None),
    )


class Trade:
    def __init__(self, market="US"):
        self.accounts = [dict(acc_id=77, trd_env="SIMULATE", acc_status="ACTIVE",
                              trdmarket_auth=[market], acc_type="MARGIN",
                              sim_acc_type="STOCK_AND_OPTION")]
        self.funds = dict(currency="N/A", cash=900000, us_cash=1000,
                          total_assets=1000, frozen_cash=0, market_val=0, power=2000000)
        self.positions = []
        self.orders = []
        self.calls = []

    def get_acc_list(self):
        return 0, self.accounts

    def accinfo_query(self, **kwargs):
        self.calls.append(("funds", kwargs))
        return 0, [self.funds]

    def position_list_query(self, **kwargs):
        self.calls.append(("positions", kwargs))
        return 0, self.positions

    def order_list_query(self, **kwargs):
        self.calls.append(("orders", kwargs))
        return 0, self.orders

    def history_order_list_query(self, **kwargs):
        self.calls.append(("history", kwargs))
        return 0, self.orders

    def place_order(self, **kwargs):
        self.calls.append(("place", kwargs))
        return 0, [dict(order_id="same-external-id", code=kwargs["code"], trd_side=kwargs["trd_side"],
                        qty=kwargs["qty"], price=kwargs["price"], order_type=kwargs["order_type"],
                        order_status="SUBMITTED", dealt_qty=0, dealt_avg_price=0,
                        remark=kwargs["remark"], session=kwargs.get("session", "RTH"),
                        create_time="2026-11-05 08:02:00", updated_time="2026-11-05 08:02:00")]

    def modify_order(self, **kwargs):
        self.calls.append(("cancel", kwargs))
        return 0, []

    def close(self):
        pass


def gateway(market="US", session="RTH"):
    channel = FUTU_US_SIM_CHANNEL_ID if market == "US" else FUTU_SIMULATE_CN_CHANNEL_ID
    config = ChannelAccountConfig("sim-" + market.lower(), channel, 77, session)
    trade = Trade(market)
    return FutuGateway(config=config, sdk=sdk(), trade_context=trade), trade


def intent(market="US", session="RTH"):
    return OrderIntent("PTE-intent", "decision", "MU" if market == "US" else "588080.SH",
                       "BUY", 1 if market == "US" else 100, 10.12,
                       session=session, channel_account_id="sim-" + market.lower())


@pytest.mark.parametrize("market,currency,broker_code", [("CN", "CNY", "SH.588080"), ("US", "USD", "US.MU")])
def test_exact_simulator_binding_shared_for_both_markets(market, currency, broker_code):
    adapter, trade = gateway(market)
    snapshot = adapter.account_snapshot()
    assert snapshot.account.currency == currency
    assert snapshot.account.channel_account_id == "sim-" + market.lower()
    assert snapshot.account.cash == (1000 if market == "US" else 900000)
    result = adapter.place_order(intent(market))
    assert result.channel_order_id == "same-external-id"
    assert result.channel_account_id == "sim-" + market.lower()
    adapter.order_snapshot()
    adapter.historical_order_snapshot("2026-11-05", "2026-11-05")
    adapter.cancel_order(result.channel_order_id)
    for _, args in trade.calls:
        assert args["acc_id"] == 77 and args["trd_env"] == "SIMULATE"
    placed = next(args for name, args in trade.calls if name == "place")
    assert placed["code"] == broker_code
    assert placed["adjust_limit"] == 0
    funds_args = next(args for name, args in trade.calls if name == "funds")
    assert funds_args.get("currency") == ("USD" if market == "US" else None)


@pytest.mark.parametrize("mutation", [
    {"trd_env": "REAL"}, {"acc_status": "DISABLED"}, {"acc_id": 78},
    {"trdmarket_auth": ["CN"]}, {"trdmarket_auth": "US"},
    {"sim_acc_type": "FUTURES"}, {"acc_type": "CASH"}, {"trd_market": "CN"},
])
def test_rejects_wrong_us_account_before_order(mutation):
    adapter, trade = gateway()
    trade.accounts[0].update(mutation)
    with pytest.raises(FutuGatewayError):
        adapter.place_order(intent())
    assert not any(name == "place" for name, _ in trade.calls)


def test_duplicate_exact_identity_is_ambiguous():
    adapter, trade = gateway()
    trade.accounts *= 2
    with pytest.raises(FutuGatewayError, match="ambiguous"):
        adapter.account_snapshot()


@pytest.mark.parametrize("field,value", [("us_cash", None), ("us_cash", "N/A"),
    ("frozen_cash", float("nan")), ("total_assets", -1), ("currency", "CNY")])
def test_us_does_not_guess_cash_or_currency(field, value):
    adapter, trade = gateway()
    trade.funds[field] = value
    with pytest.raises(FutuGatewayError):
        adapter.account_snapshot()


@pytest.mark.parametrize("position", [
    dict(code="US.MU", qty=1), dict(code="US.MU", qty=1, can_sell_qty=2),
    dict(code="US.MU", qty=.5, can_sell_qty=.5),
    dict(code="US.MU", qty=1, can_sell_qty=1, position_side="SHORT"),
    dict(code="SH.588080", qty=1, can_sell_qty=1),
])
def test_us_positions_require_explicit_long_integer_sellable_shares(position):
    adapter, trade = gateway()
    trade.positions = [position]
    with pytest.raises((FutuGatewayError, PaperTradingSafetyError)):
        adapter.account_snapshot()


def test_us_sale_availability_and_cumulative_precision():
    adapter, trade = gateway()
    trade.positions = [dict(code="US.MU", qty=1, can_sell_qty=1, position_side="LONG")]
    assert adapter.account_snapshot().positions[0].sellable_quantity == 1
    row = dict(order_id="1", code="US.MU", trd_side="BUY", qty=3, price=757.68,
               order_type="NORMAL", order_status="FILLED_PART", dealt_qty=2,
               dealt_avg_price="756.306", remark="x", session="RTH",
               create_time="2026-11-05 08:02:00", updated_time="2026-11-05 08:02:01")
    trade.orders = [row]
    order = adapter.order_snapshot()[0]
    assert order.cumulative_notional == Decimal("1512.612")
    assert order.updated_at == "2026-11-05T08:02:01-05:00"
    trade.orders[0]["updated_time"] = "2026-07-05 08:02:01"
    assert adapter.order_snapshot()[0].updated_at.endswith("-04:00")


@pytest.mark.parametrize("change", [dict(channel_account_id="another"), dict(session="ETH"),
    dict(quantity=True), dict(quantity=1.5), dict(limit_price=10.123), dict(symbol="US.MU"),
    dict(symbol="MU.US"), dict(time_in_force="GTC")])
def test_us_order_boundaries_before_mutation(change):
    adapter, trade = gateway()
    with pytest.raises((FutuGatewayError, PaperTradingSafetyError)):
        adapter.place_order(replace(intent(), **change))
    assert not trade.calls


def test_eth_limit_order_and_market_rejection():
    adapter, trade = gateway(session="ETH")
    adapter.place_order(intent(session="ETH"))
    args = next(args for name, args in trade.calls if name == "place")
    assert args["session"] == "ETH"
    with pytest.raises(PaperTradingSafetyError, match="limit orders only"):
        adapter.place_order(replace(intent(session="ETH"), side="SELL", order_type="MARKET"))
    assert sum(name == "place" for name, _ in trade.calls) == 1


def test_unknown_order_type_and_status_are_not_coerced():
    adapter, trade = gateway()
    adapter.place_order(intent())
    row = dict(order_id="1", code="US.MU", trd_side="BUY", qty=1, price=10,
               order_type="STOP", order_status="SUBMITTED", dealt_qty=0, dealt_avg_price=0)
    trade.orders = [row]
    with pytest.raises(FutuGatewayError, match="order type"):
        adapter.order_snapshot()
    row.update(order_type="NORMAL", order_status="UNRECOGNIZED")
    with pytest.raises(FutuGatewayError, match="order status"):
        adapter.order_snapshot()


@pytest.mark.parametrize("kwargs", [dict(channel_account_id="../bad"), dict(broker_account_id=True),
    dict(broker_account_id=0), dict(channel_id="futu"), dict(session="ALL"),
    dict(channel_id=FUTU_SIMULATE_CN_CHANNEL_ID, session="ETH")])
def test_configuration_rejects_ambiguous_scope(kwargs):
    args = dict(channel_account_id="us", channel_id=FUTU_US_SIM_CHANNEL_ID,
                broker_account_id=77, session="RTH")
    args.update(kwargs)
    with pytest.raises((ValueError, PaperTradingSafetyError)):
        ChannelAccountConfig(**args)
