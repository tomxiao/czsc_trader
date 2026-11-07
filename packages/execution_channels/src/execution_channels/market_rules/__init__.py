"""Versioned market rules without data, strategy or account dependencies."""

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
import json


class PriceLimitMode(StrEnum):
    DATED = "DATED_LIMITS"
    NONE = "EXPLICIT_UNBOUNDED"


class SellAvailability(StrEnum):
    IMMEDIATE = "IMMEDIATE"
    NEXT_SESSION = "NEXT_SESSION"


class RemainderPolicy(StrEnum):
    STRICT_STEP = "STRICT_STEP"
    FULL_LIQUIDATION = "FULL_LIQUIDATION"


class SettlementPoint(StrEnum):
    INTERVAL_END = "INTERVAL_END"
    NEXT_SESSION_CLOSE = "NEXT_SESSION_CLOSE"


@dataclass(frozen=True, slots=True)
class MarketRule:
    market: str
    asset_class: str
    version: str
    effective_from: date
    quantity_step: int
    price_tick: Decimal
    price_limits: PriceLimitMode
    sell_availability: SellAvailability
    remainder: RemainderPolicy
    settlement: SettlementPoint
    symbol: str | None = None

    def __post_init__(self):
        if self.market not in {"CN", "US"} or self.asset_class not in {"ETF", "STOCK"}:
            raise ValueError("unsupported market or asset class")
        if type(self.effective_from) is not date or type(self.version) is not str or not self.version.strip():
            raise ValueError("market rule requires a version and effective date")
        if (type(self.quantity_step) is not int or self.quantity_step <= 0
                or type(self.price_tick) is not Decimal
                or not self.price_tick.is_finite() or self.price_tick <= 0):
            raise ValueError("invalid market rule trading units")
        for value, enum in ((self.price_limits, PriceLimitMode), (self.sell_availability, SellAvailability),
                            (self.remainder, RemainderPolicy), (self.settlement, SettlementPoint)):
            if type(value) is not enum:
                raise TypeError(f"market rule requires {enum.__name__}")
        if self.symbol is not None and (type(self.symbol) is not str or not self.symbol.strip()):
            raise ValueError("invalid market rule symbol")

    @property
    def fingerprint(self):
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), default=str)
        return sha256(payload.encode()).hexdigest()


_BASE_DATE = date(2000, 1, 1)
_BASE_RULES = (
    MarketRule("CN", "ETF", "cn-etf-v1", _BASE_DATE, 100, Decimal(".001"),
               PriceLimitMode.DATED, SellAvailability.NEXT_SESSION,
               RemainderPolicy.FULL_LIQUIDATION, SettlementPoint.NEXT_SESSION_CLOSE),
    MarketRule("CN", "STOCK", "cn-stock-v1", _BASE_DATE, 100, Decimal(".01"),
               PriceLimitMode.DATED, SellAvailability.NEXT_SESSION,
               RemainderPolicy.FULL_LIQUIDATION, SettlementPoint.NEXT_SESSION_CLOSE),
    MarketRule("US", "STOCK", "us-stock-v1", _BASE_DATE, 1, Decimal(".01"),
               PriceLimitMode.NONE, SellAvailability.IMMEDIATE,
               RemainderPolicy.FULL_LIQUIDATION, SettlementPoint.NEXT_SESSION_CLOSE),
    MarketRule("US", "ETF", "us-etf-v1", _BASE_DATE, 1, Decimal(".01"),
               PriceLimitMode.NONE, SellAvailability.IMMEDIATE,
               RemainderPolicy.FULL_LIQUIDATION, SettlementPoint.NEXT_SESSION_CLOSE),
)


def resolve_market_rule(market: str, asset_class: str, symbol: str, session: date,
                        *, rules: tuple[MarketRule, ...] = _BASE_RULES) -> MarketRule:
    """Resolve the unique applicable rule, preferring an explicit symbol override."""
    if type(session) is not date or type(symbol) is not str or not symbol.strip():
        raise ValueError("market rule resolution requires symbol and local session date")
    matches = [rule for rule in rules if rule.market == market and rule.asset_class == asset_class
               and rule.symbol in (None, symbol) and rule.effective_from <= session]
    if not matches:
        raise ValueError(f"no market rule for {market}/{asset_class}/{symbol} on {session}")
    def priority(rule):
        return rule.symbol is not None, rule.effective_from

    selected = max(matches, key=priority)
    if sum(priority(rule) == priority(selected) for rule in matches) != 1:
        raise ValueError(f"ambiguous market rules for {market}/{asset_class}/{symbol} on {session}")
    return selected
