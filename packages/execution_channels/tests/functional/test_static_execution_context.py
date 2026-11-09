"""EC02: six explicit static-market timing contracts."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import pytest
from execution_channels.instruments import InstrumentId, MarketId, AssetClass, BarFrequency
from execution_channels.policy import (ResearchExecutionSpec, CnEquitySpec, UsEquitySpec,
    AccountPolicy, CashAvailabilityPolicy)
from execution_channels.market_rules.constraints import RuleInterval, resolve_execution_context


def fixture(market, settled=False):
    cn=market is MarketId.CN
    instrument=InstrumentId(market,AssetClass.STOCK,'600000.SH' if cn else 'MU')
    spec=ResearchExecutionSpec(CnEquitySpec() if cn else UsEquitySpec(),BarFrequency.DAILY,
        AccountPolicy('CNY' if cn else 'USD',CashAvailabilityPolicy.SETTLED_ONLY if settled
                      else CashAvailabilityPolicy.IMMEDIATE_RESEARCH),100 if cn else 1,.01,.01,0.)
    start=datetime(2026,11,6,1,30,tzinfo=timezone.utc)
    period=RuleInterval(date(2026,11,6),start,start+timedelta(hours=6),
        start+timedelta(days=3),start+timedelta(days=3,hours=6))
    return instrument,spec,period


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US],ids=['EC02-C01','EC02-C02'])
def test_market_quantity_step_and_confirmed_buy_sellability(market):
    instrument,spec,period=fixture(market)
    context=resolve_execution_context(instrument,spec,period)
    assert spec.quantity_step==(100 if market is MarketId.CN else 1)
    assert context.buy_sellable_at==(period.following_open if market is MarketId.CN else period.start)


def test_EC02_C03_settled_cash_uses_verified_monday_close():
    instrument,spec,period=fixture(MarketId.US,True)
    context=resolve_execution_context(instrument,spec,period)
    assert period.session.weekday()==4
    assert context.settlement_at==period.following_close
    assert context.settlement_at.date().weekday()==0


def test_EC02_C04_immediate_research_cash_uses_interval_end():
    instrument,spec,period=fixture(MarketId.US)
    assert resolve_execution_context(instrument,spec,period).settlement_at==period.end


def test_EC02_C05_cn_without_verified_following_session_rejects():
    instrument,spec,period=fixture(MarketId.CN)
    with pytest.raises(ValueError,match='no verified following session'):
        resolve_execution_context(instrument,spec,replace(period,following_open=None,following_close=None))


def test_EC02_C06_us_immediate_contract_needs_no_following_session_or_dynamic_facts():
    instrument,spec,period=fixture(MarketId.US)
    context=resolve_execution_context(instrument,spec,replace(period,following_open=None,following_close=None))
    assert context.buy_sellable_at==period.start and context.settlement_at==period.end
    assert not {'Tradable','AvailableDate','PriceLimitLower','PriceLimitUpper','PriceLimitPolicy'} & context.to_record().keys()
