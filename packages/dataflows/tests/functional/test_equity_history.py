"""Attested RAW source admission, market parity and exact calendar slicing."""
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from dataflows import (AssetClass, BarFrequency, EquityDataRequest,
    EquityFrequencyFacts, EquityProduct, EquityQuery, EquitySourceCoverage, InstrumentId,
    MarketId, PriceAdjustment, SourceRef, TimeInterval,
    TradingSession, versioned_equity_bindings)
from dataflows.errors import DataContractError, IncompleteDataError


def facts(market):
    instrument = InstrumentId(market, AssetClass.STOCK, '600000.SH' if market is MarketId.CN else 'LITE')
    source = SourceRef('independent-fixture', 'raw-economic-v1')
    zone = ZoneInfo(instrument.timezone)
    sessions = []
    for day in (27, 28, 29):
        segments = ((9, 30, 11, 30), (13, 0, 15, 0)) if market is MarketId.CN else ((9, 30, 16, 0),)
        sessions.append(TradingSession(date(2026, 10, day), instrument.timezone, tuple(
            TimeInterval(datetime(2026, 10, day, a, b, tzinfo=zone),
                datetime(2026, 10, day, c, d, tzinfo=zone)) for a, b, c, d in segments)))
    sessions = tuple(sessions)
    versions = []
    for frequency in BarFrequency:
        grid = tuple(bar for s in sessions for bar in s.bars(frequency))
        starts = [b.start for b in grid]
        bars = pd.DataFrame({'Date': [b.end for b in grid], 'BarStart': starts,
            'AvailableDate': [b.end for b in grid], 'Open': 10., 'High': 11., 'Low': 9.,
            'Close': 10., 'Volume': 1000., 'Amount': 10000.})
        rules = pd.DataFrame({'Date': starts, 'AvailableDate': starts,
            'Tradable': True, 'PriceLimitLower': 5. if market is MarketId.CN else None,
            'PriceLimitUpper': 15. if market is MarketId.CN else None})
        versions.append(EquityFrequencyFacts(frequency, bars, rules))
    coverage = EquitySourceCoverage(date(2026, 10, 27), date(2026, 10, 29),
        'Synthetic complete independent-source receipt; not a real security-history attestation.')
    return dict(instrument=instrument, source=source, coverage=coverage,
        sessions=sessions, frequencies=tuple(versions))


def request(source, product, frequency, *, start=None, end=None):
    return EquityDataRequest(source['instrument'], source['source'], EquityQuery(product,
        start or source['coverage'].start, end or source['coverage'].end, frequency))














@pytest.mark.parametrize('defect', [
    'adjusted',
    'frequency',
], ids=['DFLS-19-C01', 'DFLS-19-C02'])
def test_fetch_has_no_adjustment_frequency_or_source_fallback(defect):
    source = facts(MarketId.CN)
    source['frequencies'] = source['frequencies'][:1]
    bindings = versioned_equity_bindings(**source)
    req = request(source, EquityProduct.BARS, BarFrequency.DAILY)
    binding = bindings[req.parameters.provider_key]
    if defect == 'adjusted':
        req = EquityDataRequest(source['instrument'], source['source'], replace(req.parameters.query, adjustment=PriceAdjustment.BACKWARD))
    elif defect == 'frequency':
        req = request(source, EquityProduct.BARS, BarFrequency.M30)
    elif defect == 'coverage':
        req = request(source, EquityProduct.BARS, BarFrequency.DAILY, start=date(2026, 10, 26))
    else:
        req = EquityDataRequest(source['instrument'], SourceRef('other', 'v1'), req.parameters.query)
    with pytest.raises((DataContractError, IncompleteDataError)):
        binding.fetch(req)
