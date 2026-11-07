"""Resolve supplied interval facts against static rules; never acquire market data."""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import pandas as pd

from . import MarketRule, PriceLimitMode, SellAvailability, SettlementPoint, resolve_market_rule
from ..instruments import InstrumentId
from ..policy import ResearchExecutionSpec


@dataclass(frozen=True, slots=True)
class RuleInterval:
    session: date
    start: datetime
    end: datetime
    following_open: datetime | None
    following_close: datetime | None

    def __post_init__(self):
        if (type(self.session) is not date or any(not isinstance(t, datetime) or t.utcoffset() is None
                for t in (self.start, self.end)) or self.start >= self.end):
            raise ValueError('market rule interval requires a local session and aware ordered bounds')
        for value in (self.following_open, self.following_close):
            if value is not None and (not isinstance(value, datetime) or value.utcoffset() is None or value <= self.end):
                raise ValueError('following session bounds must be aware and later than the execution interval')
        if self.following_open is not None and self.following_close is not None and self.following_open >= self.following_close:
            raise ValueError('following session bounds must be ordered')


@dataclass(frozen=True, slots=True)
class StaticExecutionContext:
    """Resolved static rules and account timing, without dynamic trading facts."""
    period: RuleInterval
    rule: MarketRule
    buy_sellable_at: datetime
    settlement_at: datetime

    def to_record(self):
        return dict(Date=self.period.start, QuantityStep=self.rule.quantity_step,
            PriceTick=float(self.rule.price_tick), SellRemainderPolicy=self.rule.remainder.value,
            BuySellableAt=self.buy_sellable_at, SettlementAt=self.settlement_at,
            MarketRuleVersion=self.rule.version, MarketRuleHash=self.rule.fingerprint)


def resolve_execution_context(instrument: InstrumentId, specification: ResearchExecutionSpec,
                              period: RuleInterval) -> StaticExecutionContext:
    """Resolve one supplied calendar interval identically for every channel."""
    if type(instrument) is not InstrumentId or type(specification) is not ResearchExecutionSpec or type(period) is not RuleInterval:
        raise TypeError('execution context requires EC instrument, specification and calendar interval')
    rule = resolve_market_rule(instrument.market.value, instrument.asset_class.value, instrument.symbol, period.session)
    if rule.quantity_step != specification.quantity_step or rule.price_tick != Decimal(str(specification.price_tick)):
        raise ValueError('market trading units differ from the strategy requirements')
    unlock_next = rule.sell_availability is SellAvailability.NEXT_SESSION
    settle_next = specification.account.cash_availability.value == 'SETTLED_ONLY' and rule.settlement is SettlementPoint.NEXT_SESSION_CLOSE
    if (unlock_next and period.following_open is None) or (settle_next and period.following_close is None):
        raise ValueError(f'no verified following session for {instrument.symbol} on {period.session}')
    return StaticExecutionContext(period, rule,
        period.following_open if unlock_next else period.start,
        period.following_close if settle_next else period.end)


def assemble_constraints(instrument, specification, intervals, facts):
    if not intervals or tuple(pd.to_datetime(facts.Date, utc=True)) != tuple(pd.Timestamp(x.start) for x in intervals):
        raise ValueError('dynamic trading facts differ from the execution calendar')
    rows = []
    for period, fact in zip(intervals, facts.itertuples(), strict=True):
        context = resolve_execution_context(instrument, specification, period)
        rule = context.rule
        low = None if pd.isna(fact.PriceLimitLower) else float(fact.PriceLimitLower)
        high = None if pd.isna(fact.PriceLimitUpper) else float(fact.PriceLimitUpper)
        if rule.price_limits is PriceLimitMode.DATED and fact.Tradable and (low is None or high is None):
            raise ValueError('tradable interval lacks dated price limits')
        if rule.price_limits is PriceLimitMode.NONE and (low is not None or high is not None):
            raise ValueError('dated bounds differ from the market price limit rule')
        rows.append(dict(**context.to_record(), AvailableDate=fact.AvailableDate, Tradable=fact.Tradable,
            PriceLimitPolicy=rule.price_limits.value, PriceLimitLower=low, PriceLimitUpper=high,
        ))
    return pd.DataFrame(rows)
