"""Qualify external order identities by channel account at the I/O boundary."""
from dataclasses import replace
from urllib.parse import quote, unquote

from .broker import BrokerSnapshot, PaperTradingSafetyError
from .channel import ChannelAccountConfig
from .channel_accounts import DEFAULT_CHANNEL_ACCOUNT


class ScopedBroker:
    def __init__(self, broker, config: ChannelAccountConfig):
        if type(config) is not ChannelAccountConfig:
            raise TypeError("scoped broker requires ChannelAccountConfig")
        if broker.channel_id != config.channel_id or getattr(broker, "channel_account_id", "") != config.channel_account_id:
            raise PaperTradingSafetyError("broker differs from channel account binding")
        self.broker, self.config = broker, config
        self.channel_id, self.channel_account_id = config.channel_id, config.channel_account_id

    def qualify(self, raw_id):
        if type(raw_id) is not str or not raw_id:
            raise PaperTradingSafetyError("broker order id must be nonempty")
        if self.channel_account_id == DEFAULT_CHANNEL_ACCOUNT:
            return raw_id
        return self.channel_account_id + ":" + quote(raw_id, safe="")

    def raw_id(self, order_id):
        if self.channel_account_id == DEFAULT_CHANNEL_ACCOUNT:
            if ":" in order_id:
                raise PaperTradingSafetyError("order belongs to another channel account")
            return order_id
        prefix = self.channel_account_id + ":"
        if not order_id.startswith(prefix):
            raise PaperTradingSafetyError("order belongs to another channel account")
        raw = unquote(order_id[len(prefix):])
        if self.qualify(raw) != order_id:
            raise PaperTradingSafetyError("noncanonical qualified order id")
        return raw

    def _order(self, value):
        if value.channel_account_id != self.channel_account_id:
            raise PaperTradingSafetyError("broker order belongs to another channel account")
        return replace(value, channel_order_id=self.qualify(value.channel_order_id),
                       broker_order_id=value.channel_order_id)

    def _snapshot(self, value):
        if value.account.channel_account_id != self.channel_account_id:
            raise PaperTradingSafetyError("broker snapshot belongs to another channel account")
        return BrokerSnapshot(value.account, value.positions, tuple(self._order(x) for x in value.orders))

    def snapshot(self):
        return self._snapshot(self.broker.snapshot())

    def account_snapshot(self):
        return self._snapshot(self.broker.account_snapshot())

    def order_snapshot(self):
        return tuple(self._order(x) for x in self.broker.order_snapshot())

    def historical_order_snapshot(self, start, end):
        return tuple(self._order(x) for x in self.broker.historical_order_snapshot(start, end))

    def place_order(self, intent):
        if intent.channel_account_id != self.channel_account_id:
            raise PaperTradingSafetyError("intent belongs to another channel account")
        return self._order(self.broker.place_order(intent))

    def cancel_order(self, channel_order_id):
        self.broker.cancel_order(self.raw_id(channel_order_id))

    def close(self):
        self.broker.close()
