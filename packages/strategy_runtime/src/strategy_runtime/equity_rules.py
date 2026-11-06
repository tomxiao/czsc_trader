"""Assemble execution constraints from MRS and independently acquired market facts."""

from decimal import Decimal

import pandas as pd

from dataflows import canonical_frame_sha256
from dataflows.equity_data import sessions_from_metadata
from market_rules import PriceLimitMode, SellAvailability, SettlementPoint, resolve_market_rule

from .equity import CashAvailabilityPolicy


def assemble_execution_constraints(instrument, specification, sessions, facts, *, following_session=None):
    """Join the exact interval grid with versioned rules and return an internal execution frame."""
    grid = [(session, interval) for session in sessions for interval in session.bars(specification.decision_clock)]
    if not grid or tuple(pd.to_datetime(facts.Date, utc=True)) != tuple(
            pd.Timestamp(interval.start) for _, interval in grid):
        raise ValueError("dynamic trading facts differ from the execution calendar")
    following = dict(zip((session.session_date for session in sessions), sessions[1:]))
    if following_session is not None:
        if (following_session.session_date <= sessions[-1].session_date
                or following_session.timezone != sessions[-1].timezone):
            raise ValueError("invalid following trading session")
        following[sessions[-1].session_date] = following_session
    rules = {session.session_date: resolve_market_rule(instrument.market.value,
        instrument.asset_class.value, instrument.symbol, session.session_date) for session in sessions}
    if any(rule.quantity_step != specification.quantity_step
           or rule.price_tick != Decimal(str(specification.price_tick)) for rule in rules.values()):
        raise ValueError("MRS trading units differ from the strategy execution specification")
    rule_hashes = {rule: rule.fingerprint for rule in set(rules.values())}
    settled_only = specification.account.cash_availability is CashAvailabilityPolicy.SETTLED_ONLY
    rows = []
    for (session, interval), fact in zip(grid, facts.itertuples(), strict=True):
        rule = rules[session.session_date]
        next_session = following.get(session.session_date)
        unlock_next = rule.sell_availability is SellAvailability.NEXT_SESSION
        settle_next = settled_only and rule.settlement is SettlementPoint.NEXT_SESSION_CLOSE
        if (unlock_next or settle_next) and next_session is None:
            raise ValueError(f"no verified following session for {instrument.symbol} on {session.session_date}")
        low = None if pd.isna(fact.PriceLimitLower) else float(fact.PriceLimitLower)
        high = None if pd.isna(fact.PriceLimitUpper) else float(fact.PriceLimitUpper)
        if rule.price_limits is PriceLimitMode.DATED and fact.Tradable and (low is None or high is None):
            raise ValueError("tradable interval lacks dated price limits")
        if rule.price_limits is PriceLimitMode.NONE and (low is not None or high is not None):
            raise ValueError("dated bounds differ from the MRS price limit rule")
        rows.append(dict(Date=interval.start, AvailableDate=fact.AvailableDate, Tradable=fact.Tradable,
            QuantityStep=rule.quantity_step, PriceTick=float(rule.price_tick),
            PriceLimitPolicy=rule.price_limits.value, PriceLimitLower=low, PriceLimitUpper=high,
            SellRemainderPolicy=rule.remainder.value,
            BuySellableAt=next_session.segments[0].start if unlock_next else interval.start,
            SettlementAt=next_session.segments[-1].end if settle_next else interval.end,
            MarketRuleVersion=rule.version, MarketRuleHash=rule_hashes[rule]))
    return pd.DataFrame(rows)


def execution_constraints(definition, products, metadata):
    """Resolve MRS separately at an execution boundary, keeping DFLS facts unchanged."""
    record = metadata["trading_facts"].get("following_session")
    following = None if record is None else sessions_from_metadata({"sessions": [record]})[0]
    frame = assemble_execution_constraints(definition.instrument, definition.execution_spec,
        sessions_from_metadata(metadata["sessions"]), products["trading_facts"],
        following_session=following)
    identity = {"content_sha256": canonical_frame_sha256(frame),
                "metadata": {"market_rules": sorted(set(frame.MarketRuleHash))}}
    return frame, identity
