"""Independent CN/US gateway boundaries, using SDK-shaped broker responses."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from execution_channels.futu.broker import OrderIntent, PaperTradingSafetyError
from execution_channels.futu.channel import (
    ChannelAccountConfig, FUTU_SIMULATE_CN_CHANNEL_ID, FUTU_US_SIM_CHANNEL_ID,
)
from execution_channels.futu.futu_gateway import FutuGateway, FutuGatewayError


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


# Independent risk: EC14; responsibility-level assertions.
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


# Independent risk: EC14; responsibility-level assertions.
@pytest.mark.parametrize('mutation', [
    {'trd_env':'REAL'}, {'acc_id':78}, {'trdmarket_auth':['CN']},
], ids=['EC14-EX01-real-account','EC14-EX02-account-id','EC14-EX03-market-authority'])
def test_rejects_wrong_us_account_before_order(mutation):
    adapter, trade = gateway()
    trade.accounts[0].update(mutation)
    with pytest.raises(FutuGatewayError):
        adapter.place_order(intent())
    assert not any(name == "place" for name, _ in trade.calls)


# Independent risk: EC14; responsibility-level assertions.
def test_duplicate_exact_identity_is_ambiguous():
    adapter, trade = gateway()
    trade.accounts *= 2
    with pytest.raises(FutuGatewayError, match="ambiguous"):
        adapter.account_snapshot()


# Independent risk: EC14; responsibility-level assertions.
@pytest.mark.parametrize('field,value', [('us_cash',None),('currency','CNY')],
                         ids=['EC14-C04','EC14-C05'])
def test_us_does_not_guess_cash_or_currency(field, value):
    adapter, trade = gateway()
    trade.funds[field] = value
    with pytest.raises(FutuGatewayError):
        adapter.account_snapshot()


# Independent risk: EC06; responsibility-level assertions.


# Independent risk: EC14; responsibility-level assertions.
# Independent risk: EC14; responsibility-level assertions.
def test_EC14_EX04_cross_channel_order_is_rejected_before_broker_call():
    adapter, trade = gateway()
    with pytest.raises(PaperTradingSafetyError, match='channel account'):
        adapter.place_order(replace(intent(), channel_account_id='another'))
    assert trade.calls == []


def test_eth_limit_order_and_market_rejection():
    adapter, trade = gateway(session="ETH")
    adapter.place_order(intent(session="ETH"))
    args = next(args for name, args in trade.calls if name == "place")
    assert args["session"] == "ETH"
    with pytest.raises(PaperTradingSafetyError, match="limit orders only"):
        adapter.place_order(replace(intent(session="ETH"), side="SELL", order_type="MARKET"))
    assert sum(name == "place" for name, _ in trade.calls) == 1


# Independent risk: EC14; responsibility-level assertions.
def test_unknown_order_type_and_status_are_not_coerced():
    adapter, trade = gateway()
    adapter.place_order(intent())
    row = dict(order_id="1", code="US.MU", trd_side="BUY", qty=1, price=10,
               order_type="NORMAL", order_status="UNRECOGNIZED", dealt_qty=0, dealt_avg_price=0)
    trade.orders = [row]
    with pytest.raises(FutuGatewayError, match="order status"):
        adapter.order_snapshot()
