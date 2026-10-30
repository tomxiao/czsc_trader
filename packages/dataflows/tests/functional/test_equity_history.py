"""Attested RAW source admission, market parity and exact calendar slicing."""
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from dataflows import (AssetClass, BarFrequency, Dataflows, DataSpace, EquityDataRequest,
    EquityFrequencyFacts, EquityProduct, EquityQuery, EquitySourceCoverage, InstrumentId,
    MarketId, PreparePolicy, PriceAdjustment, ProviderConfig, SourceRef, TimeInterval,
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
            'QuantityStep': 100 if market is MarketId.CN else 1, 'PriceTick': .01, 'Tradable': True,
            'PriceLimitPolicy': 'DATED_LIMITS' if market is MarketId.CN else 'EXPLICIT_UNBOUNDED',
            'PriceLimitLower': 5. if market is MarketId.CN else None,
            'PriceLimitUpper': 15. if market is MarketId.CN else None,
            'SellRemainderPolicy': 'STRICT_STEP',
            'BuySellableAt': [s + timedelta(days=1) if market is MarketId.CN else s for s in starts],
            'SettlementAt': starts})
        versions.append(EquityFrequencyFacts(frequency, bars, rules))
    stamp = sessions[1].segments[0].start
    actions = pd.DataFrame([{'Date': stamp, 'AvailableDate': stamp, 'EventId': 'cash-1',
        'Kind': 'CASH_DIVIDEND', 'Ratio': 1., 'CashPerShare': .5, 'PayAt': sessions[2].segments[0].start}])
    coverage = EquitySourceCoverage(date(2026, 10, 27), date(2026, 10, 29),
        'Synthetic complete independent-source receipt; not a real security-history attestation.', True)
    return dict(instrument=instrument, source=source, coverage=coverage,
        sessions=sessions, frequencies=tuple(versions), actions=actions)


def request(source, product, frequency, *, start=None, end=None):
    return EquityDataRequest(source['instrument'], source['source'], EquityQuery(product,
        start or source['coverage'].start, end or source['coverage'].end, frequency))


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('frequency', [BarFrequency.DAILY, BarFrequency.M30])
def test_both_markets_publish_pinned_raw_facts_with_exact_source_rules(tmp_path, market, frequency):
    source = facts(market)
    bindings = versioned_equity_bindings(**source)
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path('assets')),
        providers=ProviderConfig(bindings={}, equity_bindings=bindings))
    requests = tuple(request(source, product, frequency) for product in EquityProduct)
    prepared = flows.prepare(requests, policy=PreparePolicy.REUSE)
    assert prepared.ready, [(item.status, item.error) for item in prepared.items]
    rows = flows.fetch(requests[0], prepared=prepared.reference)
    assert rows.ready, rows.error
    assert len(rows.dataframe) == (3 if frequency is BarFrequency.DAILY else 24 if market is MarketId.CN else 39)
    assert rows.identity.metadata['economic_price_basis'] == 'RAW'
    assert rows.identity.metadata['action_history_complete'] is True
    rules = flows.fetch(request(source, EquityProduct.CONSTRAINTS, frequency), prepared=prepared.reference)
    assert rules.ready, rules.error
    assert set(rules.dataframe.PriceLimitPolicy) == ({'DATED_LIMITS'} if market is MarketId.CN else {'EXPLICIT_UNBOUNDED'})


def test_provider_owns_admitted_values_and_derives_empty_subrange_from_complete_history():
    source = facts(MarketId.CN)
    bindings = versioned_equity_bindings(**source)
    req = request(source, EquityProduct.BARS, BarFrequency.M30)
    source['frequencies'][1].bars.loc[:, 'Close'] = 999.
    frame, _ = bindings[req.parameters.provider_key].fetch(req)
    assert frame.Close.eq(10.).all()
    frame.loc[:, 'Close'] = 888.
    assert bindings[req.parameters.provider_key].fetch(req)[0].Close.eq(10.).all()
    empty = request(source, EquityProduct.ACTIONS, BarFrequency.M30, end=date(2026, 10, 27))
    selected, metadata = bindings[empty.parameters.provider_key].fetch(empty)
    assert selected.Kind.tolist() == ['NONE'] and metadata['no_actions_verified'] is True
    assert metadata['action_history_complete'] is True
    assert metadata['coverage_evidence_sha256']


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('frequency', [BarFrequency.DAILY, BarFrequency.M30])
def test_explicit_source_gap_and_resumption_do_not_invent_prices(tmp_path, market, frequency):
    source = facts(market)
    for item in source['frequencies']:
        item.bars['BarStatus'] = 'OBSERVED'
        item.bars['ExecutionBlocked'] = False
        missing = item.bars.BarStart.dt.day.eq(28)
        item.bars.loc[missing, 'BarStatus'] = 'MISSING'
        item.bars.loc[missing, 'ExecutionBlocked'] = True
        item.bars.loc[missing, ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']] = float('nan')
        item.constraints.loc[missing, 'Tradable'] = False
    bindings = versioned_equity_bindings(**source)
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path('assets')),
        providers=ProviderConfig(bindings={}, equity_bindings=bindings))
    req = request(source, EquityProduct.BARS, frequency)
    prepared = flows.prepare((req,), policy=PreparePolicy.REUSE)
    assert prepared.ready, [(item.status, item.error) for item in prepared.items]
    result = flows.fetch(req, prepared=prepared.reference)
    assert result.ready, result.error
    frame = result.dataframe
    absent = frame.BarStart.dt.day.eq(28)
    assert frame.loc[absent, ['Open', 'Close', 'Volume']].isna().all().all()
    assert frame.loc[absent, 'ExecutionBlocked'].all()
    assert frame.loc[frame.BarStart.dt.day.eq(29), 'BarStatus'].eq('OBSERVED').all()
    assert result.identity.metadata['observation_basis'] == 'SOURCE_FACTS_NOT_INFERRED_HISTORICAL_HALTS'


@pytest.mark.parametrize('defect', ['invented-price', 'missing-row', 'missing-block-flag'])
def test_explicit_source_observations_reject_fabrication_and_incomplete_grid(defect):
    source = facts(MarketId.CN)
    for item in source['frequencies']:
        item.bars['BarStatus'] = 'OBSERVED'
        item.bars['ExecutionBlocked'] = False
    item = source['frequencies'][0]
    if defect == 'invented-price':
        item.bars.loc[1, 'BarStatus'] = 'MISSING'
        item.bars.loc[1, 'ExecutionBlocked'] = True
    elif defect == 'missing-row':
        source['frequencies'] = (replace(item, bars=item.bars.iloc[:-1]), source['frequencies'][1])
    else:
        item.bars.drop(columns=['ExecutionBlocked'], inplace=True)
    with pytest.raises((DataContractError, IncompleteDataError)):
        versioned_equity_bindings(**source)


def test_source_selection_uses_admitted_indexes_without_reparsing_or_revalidating(monkeypatch):
    from dataflows import equity_history
    source = facts(MarketId.CN)
    bindings = versioned_equity_bindings(**source)
    req = request(source, EquityProduct.BARS, BarFrequency.M30,
        start=date(2026, 10, 28), end=date(2026, 10, 28))
    def unexpected(*args, **kwargs):
        raise AssertionError('a selected source must not reparse or revalidate full history')
    monkeypatch.setattr(equity_history.pd, 'to_datetime', unexpected)
    monkeypatch.setattr(equity_history, 'validate_equity_frame', unexpected)
    selected, metadata = bindings[req.parameters.provider_key].fetch(req)
    assert len(selected) == 8
    assert metadata['coverage_start'] == metadata['coverage_end'] == '2026-10-28'


@pytest.mark.parametrize('defect', ['partial-actions', 'unverified-none', 'event-outside', 'missing-pay',
    'missing-grid', 'missing-rules', 'limit-policy', 'limit-bounds', 'unbounded-limits', 'sell-before', 'settle-before'])
def test_source_admission_rejects_missing_or_inconsistent_facts(defect):
    source = facts(MarketId.CN)
    if defect == 'partial-actions':
        with pytest.raises(IncompleteDataError, match='complete'):
            replace(source['coverage'], actions_complete=False)
        return
    if defect == 'unverified-none':
        source['actions'].loc[:, 'Kind'] = 'NONE'
    elif defect == 'event-outside':
        source['actions'].loc[:, 'Date'] += pd.Timedelta(days=5)
    elif defect == 'missing-pay':
        source['actions'].loc[:, 'PayAt'] = None
    elif defect == 'missing-grid':
        item = source['frequencies'][0]
        source['frequencies'] = (replace(item, bars=item.bars.iloc[:-1]), source['frequencies'][1])
    else:
        frame = source['frequencies'][0].constraints
        if defect == 'missing-rules':
            frame.drop(columns=['BuySellableAt'], inplace=True)
        elif defect == 'limit-policy':
            frame.loc[0, 'PriceLimitPolicy'] = 'GUESS_FROM_MARKET'
        elif defect == 'limit-bounds':
            frame.loc[0, 'PriceLimitLower'] = 100.
        elif defect == 'unbounded-limits':
            frame.loc[0, 'PriceLimitPolicy'] = 'EXPLICIT_UNBOUNDED'
        elif defect == 'sell-before':
            frame.loc[0, 'BuySellableAt'] = frame.Date.iloc[0] - pd.Timedelta(seconds=1)
        else:
            frame.loc[0, 'SettlementAt'] = frame.Date.iloc[0] - pd.Timedelta(seconds=1)
    with pytest.raises((DataContractError, IncompleteDataError)):
        versioned_equity_bindings(**source)


@pytest.mark.parametrize('defect', ['adjusted', 'frequency', 'coverage', 'source'])
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
