"""Static timing is identical across channel contexts and historical facts."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from execution_channels.instruments import InstrumentId, MarketId, AssetClass, BarFrequency
from execution_channels.policy import (ResearchExecutionSpec, CnEquitySpec, UsEquitySpec,
    AccountPolicy, CashAvailabilityPolicy)
from execution_channels.market_rules.constraints import (
    RuleInterval, resolve_execution_context, assemble_constraints,
)


def fixture(market, settled):
    cn = market is MarketId.CN
    instrument = InstrumentId(market, AssetClass.STOCK, '600000.SH' if cn else 'MU')
    specification = ResearchExecutionSpec(CnEquitySpec() if cn else UsEquitySpec(),
        BarFrequency.DAILY, AccountPolicy('CNY' if cn else 'USD',
        CashAvailabilityPolicy.SETTLED_ONLY if settled else CashAvailabilityPolicy.IMMEDIATE_RESEARCH),
        100 if cn else 1, .01, .01, 0.)
    start = datetime(2026, 11, 6, 1, 30, tzinfo=timezone.utc)
    period = RuleInterval(date(2026, 11, 6), start, start + timedelta(hours=6),
        start + timedelta(days=3), start + timedelta(days=3, hours=6))
    return instrument, specification, period


@pytest.mark.parametrize('market', (MarketId.CN, MarketId.US))
@pytest.mark.parametrize('settled', (False, True))
def test_shared_context_preserves_timing_without_inventing_dynamic_facts(market, settled):
    instrument, specification, period = fixture(market, settled)
    context = resolve_execution_context(instrument, specification, period)
    assert context.buy_sellable_at == (period.following_open if market is MarketId.CN else period.start)
    assert context.settlement_at == (period.following_close if settled else period.end)
    static = context.to_record()
    assert not {'Tradable', 'AvailableDate', 'PriceLimitLower', 'PriceLimitUpper', 'PriceLimitPolicy'} & static.keys()
    facts = pd.DataFrame([dict(Date=period.start, AvailableDate=period.start, Tradable=True,
        PriceLimitLower=9. if market is MarketId.CN else None,
        PriceLimitUpper=11. if market is MarketId.CN else None)])
    historical = assemble_constraints(instrument, specification, (period,), facts).iloc[0]
    assert all(historical[key] == value for key, value in static.items())
    assert historical.PriceLimitPolicy == ('DATED_LIMITS' if market is MarketId.CN else 'EXPLICIT_UNBOUNDED')
    no_next = replace(period, following_open=None, following_close=None)
    if market is MarketId.CN or settled:
        with pytest.raises(ValueError, match='no verified following session'):
            resolve_execution_context(instrument, specification, no_next)
    else:
        assert resolve_execution_context(instrument, specification, no_next).buy_sellable_at == period.start


def test_invalid_following_calendar_and_market_units_are_rejected():
    instrument, specification, period = fixture(MarketId.CN, True)
    with pytest.raises(ValueError, match='later than the execution interval'):
        replace(period, following_open=period.end)
    with pytest.raises(ValueError, match='ordered'):
        replace(period, following_close=period.following_open)
    with pytest.raises(ValueError, match='trading units differ'):
        resolve_execution_context(instrument, replace(specification, quantity_step=1), period)
    with pytest.raises(TypeError, match='EC instrument'):
        resolve_execution_context('600000.SH', specification, period)
