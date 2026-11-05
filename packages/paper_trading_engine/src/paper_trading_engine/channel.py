"""Immutable execution-channel identities and fail-closed scope validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from .broker import PaperTradingSafetyError


FUTU_SIMULATE_CN_CHANNEL_ID = "futu_simulate_cn"
FUTU_US_SIM_CHANNEL_ID = "futu_US_sim_channel"
LEGACY_FUTU_CHANNEL_ID = "futu"
CHANNEL_RECONCILIATION_ACCOUNT_TYPE = "CHANNEL_RECONCILIATION"
STRATEGY_ACCOUNT_TYPE = "STRATEGY"


class TradingSession(StrEnum):
    RTH = "RTH"
    ETH = "ETH"


@dataclass(frozen=True, slots=True)
class ChannelProfile:
    channel_id: str
    market: str
    currency: str
    timezone: str
    quantity_step: int


_PROFILES = {
    FUTU_SIMULATE_CN_CHANNEL_ID: ChannelProfile(
        FUTU_SIMULATE_CN_CHANNEL_ID, "CN", "CNY", "Asia/Shanghai", 100),
    FUTU_US_SIM_CHANNEL_ID: ChannelProfile(
        FUTU_US_SIM_CHANNEL_ID, "US", "USD", "America/New_York", 1),
}


def channel_profile(channel_id: str) -> ChannelProfile:
    try:
        return _PROFILES[channel_id]
    except (KeyError, TypeError) as exc:
        raise PaperTradingSafetyError("unsupported explicit simulation channel") from exc


@dataclass(frozen=True, slots=True)
class ChannelAccountConfig:
    """Exact external simulator identity and permitted order session."""

    channel_account_id: str
    channel_id: str
    broker_account_id: int
    session: TradingSession = TradingSession.RTH

    def __post_init__(self):
        if type(self.channel_account_id) is not str or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", self.channel_account_id
        ) is None:
            raise ValueError("channel account id must be a stable identifier")
        profile = channel_profile(self.channel_id)
        if type(self.broker_account_id) is not int or self.broker_account_id <= 0:
            raise ValueError("broker account id must be an explicit positive integer")
        try:
            session = TradingSession(self.session)
        except (ValueError, TypeError) as exc:
            raise ValueError("session must be RTH or ETH") from exc
        if profile.market == "CN" and session is not TradingSession.RTH:
            raise ValueError("CN simulation supports RTH only")
        object.__setattr__(self, "session", session)

    @property
    def profile(self) -> ChannelProfile:
        return channel_profile(self.channel_id)

    @property
    def market(self) -> str:
        return self.profile.market

    @property
    def currency(self) -> str:
        return self.profile.currency

    @property
    def timezone(self) -> str:
        return self.profile.timezone


def require_futu_simulate_cn(channel_id: object) -> str:
    """Return the only supported broker channel or reject before any I/O."""
    if channel_id != FUTU_SIMULATE_CN_CHANNEL_ID:
        raise PaperTradingSafetyError(
            "PTE only permits the explicit futu_simulate_cn execution channel"
        )
    return FUTU_SIMULATE_CN_CHANNEL_ID


def require_futu_simulate_cn_broker(broker: object) -> str:
    """Ensure a broker adapter declares the precise channel it can execute."""
    return require_futu_simulate_cn(getattr(broker, "channel_id", None))
