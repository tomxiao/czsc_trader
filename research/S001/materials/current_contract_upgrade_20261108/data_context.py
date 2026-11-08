"""Bounded DFLS re-publication of authenticated S001 HFQ and RAW observations."""
from copy import deepcopy
from datetime import date, datetime, time
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dataflows import (BarFrequency, Dataset, EquityProduct, PriceAdjustment, ProviderBinding,
    ProviderConfig, ProviderKey, SourceRef, TimeInterval, TradingSession)
from dataflows.equity_data import equity_metadata, session_record
from strategy_runtime import ExecutionResources
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EquitySources, ResearchBatchRef

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = SourceRef('tushare', 's001-current-target-retained-20261108-v1')
FIRST, LAST = date(2026, 8, 1), date(2026, 11, 5)
ZONE = ZoneInfo('Asia/Shanghai')


def _at(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), ZONE)


def _reader():
    spec = importlib.util.spec_from_file_location('s001_retained_reader', HERE / 'verify.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_data_context(candidate):
    reader = _reader()
    frames, observation_provenance, _ = reader.retained_inputs()
    execution, execution_provenance = reader.retained_execution_inputs()
    calendar = frames['calendar']
    open_days = pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1), 'Date'])
    week_ends = open_days.groupby(open_days.dt.to_period('W-SUN')).max()
    weekly = frames['weekly']
    expected = weekly.Date.dt.to_period('W-SUN').map(week_ends)
    frames['weekly'] = weekly.loc[weekly.Date.eq(expected)].copy()
    assert pd.Timestamp('2026-09-30') in set(frames['weekly'].Date)
    assert pd.Timestamp('2026-11-05') not in set(frames['weekly'].Date)
    days = pd.to_datetime(execution['calendar'].loc[execution['calendar'].IsOpen.eq(1), 'Date']).dt.date
    sessions = tuple(TradingSession(day, str(ZONE), (
        TimeInterval(_at(day, 9, 30), _at(day, 11, 30)),
        TimeInterval(_at(day, 13), _at(day, 15)))) for day in days)
    raw = execution['raw_daily'].copy()
    raw.index = pd.to_datetime(raw.Date).dt.date
    adjusted = frames['daily'].copy()
    adjusted.index = pd.to_datetime(adjusted.Date).dt.date
    limits = execution['limits'].copy()
    limits.index = pd.to_datetime(limits.Date).dt.date
    factors = adjusted.Close.reindex(raw.index).astype(float) / raw.Close.astype(float)
    assert factors.notna().all() and factors.gt(0).all()
    coverage = execution_provenance['limits']['identity']['metadata']['daily_session_coverage']
    suspended = set(coverage.get('suspended_dates', ()))
    provenance = {'observation': reader.compact_provenance(observation_provenance), 'execution': execution_provenance,
        'source': {'provider': SOURCE.provider, 'revision': SOURCE.revision},
        'scope': {'first': FIRST.isoformat(), 'last': LAST.isoformat()},
        'hfq_acquisition_method': 'DFLS_ADJUSTED',
        'operation': 'RETAINED_TUSHARE_HFQ_AND_RAW_REVALIDATION',
        'bounds_conversion': 'Actual Tushare etf_limit RAW bounds multiplied by same-session retained HFQ/RAW close ratio',
        'weekly_rule': 'Only bars dated on the calendar-confirmed last trading day of their week',
        'limitations': ['No supplier refresh', 'Historical publication time follows original supplier schedule assumption',
                       'No independent new halt or corporate-action investigation']}
    provenance_hash = sha256(json.dumps(provenance, sort_keys=True, default=str).encode()).hexdigest()

    def fetch_observation(request):
        if request.dataset is Dataset.TRADING_CALENDAR:
            key = 'calendar'
            source = frames[key]
            upper = source.Date.max().date()
        else:
            if request.dataset is not Dataset.ETF_OHLCV or request.symbol != candidate.instrument.symbol:
                raise ValueError('unsupported retained S001 observation')
            key = {'daily': 'daily', '30m': 'm30', 'weekly': 'weekly'}[request.frequency]
            source, upper = frames[key], LAST
        start, end = pd.Timestamp(request.start), pd.Timestamp(request.end)
        if start.date() < date(2020, 11, 16) or end.date() > upper:
            raise ValueError('observation request exceeds authenticated retained S001 range')
        selected = source.loc[source.Date.dt.normalize().between(start, end)].copy().reset_index(drop=True)
        metadata = deepcopy(observation_provenance['identity']['inputs'][key]['identity']['metadata'])
        metadata.update(retained_provenance_sha256=provenance_hash,
            retained_parent_content_sha256=observation_provenance['identity']['inputs'][key]['identity']['content_sha256'])
        return selected, metadata

    def fetch_equity(request):
        p, q = request.parameters, request.parameters.query
        if (p.source != SOURCE or p.instrument != candidate.instrument or q.frequency is not BarFrequency.DAILY
                or q.start < FIRST or q.end > LAST):
            raise ValueError('equity request exceeds retained S001 technical coverage')
        selected = tuple(s for s in sessions if q.start <= s.session_date <= q.end)
        if not selected:
            raise ValueError('empty retained S001 session range')
        following = next((s for s in sessions if s.session_date > q.end), None)
        metadata = equity_metadata(request, selected, availability_basis=(
            'VENDOR_PREOPEN_SCHEDULE_NOT_HISTORICALLY_VERIFIED' if q.product is EquityProduct.TRADING_FACTS
            else 'RETAINED_BAR_CLOSE_AVAILABILITY'))
        metadata.update(retained_provenance_sha256=provenance_hash, vendor='tushare',
                        source_publication_timestamp_verified=False)
        if following is not None:
            metadata['following_session'] = session_record(following)
        if q.product is EquityProduct.SESSIONS:
            return pd.DataFrame({'Date': [s.segments[0].start for s in selected],
                'AvailableDate': [s.segments[0].start for s in selected],
                'SessionDate': [s.session_date.isoformat() for s in selected]}), metadata
        if q.product is EquityProduct.TRADING_FACTS:
            if q.adjustment not in (PriceAdjustment.NONE, PriceAdjustment.BACKWARD):
                raise ValueError('unsupported retained fact price scale')
            rows = []
            for session in selected:
                day = session.session_date
                factor = float(factors.loc[day]) if q.adjustment is PriceAdjustment.BACKWARD else 1.
                rows.append({'Date': session.segments[0].start, 'AvailableDate': _at(day, 9, 30),
                    'Tradable': day.isoformat() not in suspended,
                    'PriceLimitLower': float(limits.loc[day, 'DownLimit']) * factor,
                    'PriceLimitUpper': float(limits.loc[day, 'UpLimit']) * factor})
            metadata.update(tradability_basis='TUSHARE_ETF_LIMIT_SESSION_COVERAGE',
                original_content_sha256=execution_provenance['limits']['identity']['content_sha256'])
            return pd.DataFrame(rows), metadata
        if q.product is not EquityProduct.BARS or q.adjustment not in (PriceAdjustment.NONE, PriceAdjustment.BACKWARD):
            raise ValueError('unsupported retained S001 product')
        source = adjusted if q.adjustment is PriceAdjustment.BACKWARD else raw
        data = source.loc[[s.session_date for s in selected]].copy().reset_index(drop=True)
        data['Date'] = [s.segments[-1].end for s in selected]
        data['BarStart'] = [s.segments[0].start for s in selected]
        data['AvailableDate'] = [_at(s.session_date, 17) for s in selected]
        metadata.update(acquisition_method=('DFLS_ADJUSTED' if q.adjustment is PriceAdjustment.BACKWARD else 'PROVIDER_RAW'),
            price_source_api=('Tushare retained etf.ohlcv; original DFLS HFQ calculation' if q.adjustment is PriceAdjustment.BACKWARD
                              else 'Tushare retained ETF_UNADJUSTED_DAILY'))
        return data, metadata

    providers = ProviderConfig(
        bindings={dataset: ProviderBinding('s001-retained-observation', '20261108-v1', fetch_observation)
                  for dataset in (Dataset.ETF_OHLCV, Dataset.TRADING_CALENDAR)},
        equity_bindings={ProviderKey(product, candidate.instrument.market, SOURCE):
            ProviderBinding(SOURCE.provider, SOURCE.revision, fetch_equity) for product in EquityProduct})
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S001'),
        providers=providers, execution_spec=candidate.definition.execution_spec, resources=ExecutionResources(1, 1, 17))
    return context, EquitySources(SOURCE, SOURCE, SOURCE), provenance
