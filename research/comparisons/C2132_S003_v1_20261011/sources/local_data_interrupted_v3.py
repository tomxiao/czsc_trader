"""Explicit existing-only providers for the approved S003/C2132 comparison.

Daily/calendar/30m facts are pinned prepared S013 inputs. 5m bars are the
manifest-authenticated S003 HFQ observations, reversibly expressed in raw
units using the same S003 daily price basis. No external provider is called.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
from datetime import date
from functools import lru_cache
from hashlib import sha256
import importlib
from importlib.metadata import version
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from dataflows import Dataset, DataStatus, ProviderBinding, ProviderConfig
from dataflows.history_repair import frame_content_sha256
from dataflows.ohlcv_quality import build_quality_evidence
from dataflows.local_strategy_data import fetch_strategy_feature_evidence
from czsc_trader.application import RepositoryContext, create_research_context, load_candidate
from czsc_trader.research_tools import (
    EvaluationBenchmark, EvaluationCost, EvaluationRequest, EvaluationResources,
    EvaluationWindow, ExecutionPriceBasis, LimitBuyHold, ResearchBatchRef,
)
from strategy_manager import CandidateKey
from strategy_runtime import ImplementationDependency, StrategyCandidate

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
CACHE = ROOT / '.tmp/s013-mechanism-EX058/N0.pkl.gz'
OLD_COMMON = ROOT / 'research/S013/experiments/EX058_20261011/src/common.py'
RAW = ROOT / 'data/raw'
START, END = date(2021, 4, 23), date(2026, 9, 8)
LOCAL_CALLS = []
EXTERNAL_CALLS = []


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def plain(value):
    return json.loads(json.dumps(value, default=dict, allow_nan=False))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + '\n', encoding='utf-8')


def forbidden(request):
    EXTERNAL_CALLS.append(str(request))
    raise RuntimeError('External source not authorized: ' + str(request))


def seed_provider(request):
    parameters = request.parameters
    expected = ROOT / 'strategies/S003/releases/v1/runtime/strategy_runtime/resources/s003_v1_seed.csv.gz'
    selected = (parameters.repository_root / parameters.source_path).resolve()
    if selected != expected.resolve() or parameters.source_sha256 != file_hash(expected):
        raise ValueError('only the exact frozen S003 seed resource is authorized')
    LOCAL_CALLS.append({'dataset': str(request.dataset), 'source_key': 'frozen-S003-local-seed',
                        'source_sha256': parameters.source_sha256,
                        'start': request.start, 'end': request.end})
    return fetch_strategy_feature_evidence(request)


def canonical_csv(path):
    frame = pd.read_csv(path)
    frame = frame.rename(columns={'date': 'Date', 'datetime': 'Date', 'open': 'Open',
                                 'high': 'High', 'low': 'Low', 'close': 'Close',
                                 'volume': 'Volume', 'amount': 'Amount'})
    frame['Date'] = pd.to_datetime(frame['Date'], errors='raise')
    if frame['Date'].duplicated().any() or not frame['Date'].is_monotonic_increasing:
        raise ValueError('source timestamps invalid: ' + path.name)
    return frame.loc[:, ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Amount']]


@lru_cache(maxsize=1)
def existing_sources():
    # The persisted pickle uses common.restore_mapping. Bind only its exact
    # original decoder module, never a new same-name experiment helper.
    sys.path.insert(0, str(OLD_COMMON.parent))
    common = importlib.import_module('common')
    if Path(common.__file__).resolve() != OLD_COMMON.resolve():
        raise ValueError('persisted cache decoder identity differs')
    bound, unused_result = common.cache_read(CACHE)
    del unused_result
    old_context = common.context(1)
    execution = bound.execution_data
    pinned = {}
    for name, request in execution.requests.items():
        result = old_context.data.fetch(request, prepared=execution.prepared)
        if result.status is not DataStatus.READY or result.identity is None:
            raise RuntimeError('Pinned source unavailable: ' + name)
        pinned[name] = (result.dataframe.copy(), plain(result.identity.metadata),
                        plain({item.name: getattr(result.identity, item.name)
                               for item in fields(result.identity)}))
    if common.SOURCE_CALLS:
        raise AssertionError('Pinned source unexpectedly called supplier')
    del bound
    return pinned


def coverage_subset(metadata, first, last):
    coverage = deepcopy(metadata['daily_session_coverage'])
    calendar = pd.DataFrame(coverage['calendar'])
    selected = pd.to_datetime(calendar['Date']).between(first, last)
    calendar = calendar.loc[selected].reset_index(drop=True)
    if not pd.DatetimeIndex(pd.to_datetime(calendar.Date)).equals(pd.date_range(first, last)):
        raise ValueError('source calendar does not cover derived range')
    expected = calendar.loc[calendar.is_open.eq(1), 'Date'].tolist()
    coverage.update(start_date=first.date().isoformat(), end_date=last.date().isoformat(),
                    expected_dates=expected, verified_sessions=len(expected),
                    calendar=calendar.to_dict('records'), calendar_sha256=frame_content_sha256(calendar))
    return coverage


@lru_cache(maxsize=1)
def local_five_minute():
    sources = existing_sources()
    manifest_path = RAW / '510500_intraday_manifest.json'
    daily_manifest_path = RAW / '510500_manifest.json'
    manifest = read(manifest_path)
    daily_manifest = read(daily_manifest_path)
    if manifest['symbol'] != '510500.SH' or manifest['adjustment']['mode'] != 'hfq':
        raise ValueError('S003 minute source identity differs')
    references = {manifest_path.relative_to(ROOT).as_posix(): file_hash(manifest_path),
                  daily_manifest_path.relative_to(ROOT).as_posix(): file_hash(daily_manifest_path),
                  CACHE.relative_to(ROOT).as_posix(): file_hash(CACHE)}
    pieces, daily_pieces = [], []
    for year in range(2021, 2027):
        minute_path = RAW / f'510500_5m_{year}.csv'
        daily_path = RAW / f'510500_daily_{year}.csv'
        for path, expected in ((minute_path, manifest['files'][minute_path.name]['sha256']),
                               (daily_path, daily_manifest['files'][daily_path.name]['sha256'])):
            actual = file_hash(path)
            if actual != expected:
                raise ValueError('S003 immutable source file hash differs: ' + path.name)
            references[path.relative_to(ROOT).as_posix()] = actual
        pieces.append(canonical_csv(minute_path))
        daily_pieces.append(canonical_csv(daily_path))
    adjusted_minute = pd.concat(pieces, ignore_index=True)
    old_adjusted_daily = pd.concat(daily_pieces, ignore_index=True).set_index('Date')
    first, last = old_adjusted_daily.index[0], old_adjusted_daily.index[-1]
    if last != pd.Timestamp(END):
        raise ValueError('S003 local minute cutoff differs from approved cutoff')
    raw_full, raw_metadata, raw_identity = sources['execution_daily']
    reference = raw_full.loc[pd.to_datetime(raw_full.Date).between(first, last)].copy()
    reference['Date'] = pd.to_datetime(reference['Date'], errors='raise')
    raw_daily = reference.set_index('Date')
    if not raw_daily.index.equals(old_adjusted_daily.index):
        raise ValueError('S003/S013 daily source sessions differ')
    # Legacy intraday and legacy adjusted daily share one fixed normalization.
    # Reverse it to RAW; modern TDR subsequently applies its own shared HFQ
    # anchor. Preserve all source OHLC without rounding or price repair.
    factor = old_adjusted_daily['Close'] / raw_daily['Close']
    if not np.isfinite(factor).all() or not factor.gt(0).all():
        raise ValueError('invalid same-day legacy price factor')
    ratio_errors = {}
    for column in ('Open', 'High', 'Low', 'Close'):
        error = (old_adjusted_daily[column] / factor - raw_daily[column]).abs()
        ratio_errors[column] = float(error.max())
        if not error.le(.001).all():
            raise ValueError('legacy price scale not supported by all daily OHLC: ' + column)
    days = pd.to_datetime(adjusted_minute.Date).dt.normalize()
    scales = days.map(factor)
    if scales.isna().any():
        raise ValueError('minute session has no independently supplied daily factor')
    minute = adjusted_minute.copy()
    for column in ('Open', 'High', 'Low', 'Close'):
        minute[column] = minute[column] / scales
    minute['Volume'] = minute['Volume'] * scales
    minute['AvailableDate'] = minute['Date']
    coverage = coverage_subset(raw_metadata, first, last)
    quality = build_quality_evidence(reference.reset_index(drop=True), intraday=minute,
                                     frequency='5m', expected_dates=coverage['expected_dates'])
    inaccurate = {day: row['minute_fields'] for day, row in quality['sessions'].items()
                  if not row['minute_complete'] or not row['minute_accurate']}
    metadata = deepcopy(sources['execution_30m'][1])
    for name in ('repair_records', 'validation', 'migration_origin', 'ohlcv_quality',
                 'provider_binding', 'provider_revision', 'dfls_revision'):
        metadata.pop(name, None)
    metadata.update(period='5m', adjustment='none', daily_session_coverage=coverage,
                    ohlcv_quality_evidence=quality,
                    reference_daily_sha256=quality['reference_daily_sha256'],
                    local_derivation={
                        'operation': 'legacy_hfq_price / (legacy_daily_Close / pinned_raw_daily_Close); volume * same factor; amount unchanged',
                        'normalization_anchor': 'legacy daily HFQ scale is removed; TDR chooses one pre-window HFQ anchor shared by both accounts and benchmark',
                        'source_files': references, 'raw_daily_identity': raw_identity,
                        'factor_sha256': frame_content_sha256(pd.DataFrame({'Date': factor.index,
                                                                          'Factor': factor.to_numpy()})),
                        'legacy_daily_to_raw_max_absolute_ohlc_error': ratio_errors,
                        'derived_raw_5m_frame_sha256': frame_content_sha256(minute),
                        'minute_quality_not_accurate_sessions': inaccurate,
                        'price_repair_or_rounding': False, 'external_calls': [],
                    })
    audit = {'status': 'DERIVED_EXISTING_5M', 'sessions': len(coverage['expected_dates']),
             'rows': len(minute), 'first': str(minute.Date.iloc[0]), 'last': str(minute.Date.iloc[-1]),
             'source_files': references, 'derivation': metadata['local_derivation'],
             'quality_thresholds_are_public_DFLS_contract': True}
    write(WORK / 'local_5m_audit.json', audit)
    return minute, metadata


def provider(request):
    if request.symbol not in {'510500.SH', 'SSE'}:
        raise ValueError('only authorized comparison ETF/SSE supported')
    sources = existing_sources()
    keys = {Dataset.ETF_OHLCV: 'adjusted_daily', Dataset.ETF_UNADJUSTED_DAILY: 'execution_daily',
            Dataset.TRADING_CALENDAR: 'trading_calendar'}
    if request.dataset in keys:
        source_key = keys[request.dataset]
        frame, metadata, identity = sources[source_key]
    elif request.dataset is Dataset.ETF_UNADJUSTED_INTRADAY and request.frequency == '30m':
        source_key = 'execution_30m'
        frame, metadata, identity = sources[source_key]
    elif request.dataset is Dataset.ETF_UNADJUSTED_INTRADAY and request.frequency == '5m':
        frame, metadata = local_five_minute()
        identity = {'derived_5m': metadata['local_derivation']}
        source_key = 'S003-existing-hfq-5m-to-raw'
    else:
        raise ValueError('no authorized local dataset/frequency: ' + str(request))
    start = pd.Timestamp(request.start)
    end = pd.Timestamp(request.end)
    if len(request.end) == 10:
        end = end + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    available = pd.to_datetime(frame.Date)
    selected = frame.loc[available.between(start, end)].copy().reset_index(drop=True)
    if selected.empty:
        raise ValueError('no existing local observations in requested interval')
    selected.attrs = {}
    metadata = deepcopy(metadata)
    metadata['comparison_local_parent'] = {'source_key': source_key,
                                            'cache_sha256': file_hash(CACHE),
                                            'original_identity': identity,
                                            'selected_frame_sha256': frame_content_sha256(selected),
                                            'operation': 'DATE_SLICE_ONLY_EXCEPT_EXPLICIT_5M_UNIT_CONVERSION'}
    LOCAL_CALLS.append({'dataset': str(request.dataset), 'frequency': request.frequency,
                        'start': request.start, 'end': request.end, 'rows': len(selected),
                        'source_key': source_key, 'source_fingerprint': frame_content_sha256(selected)})
    return selected, metadata


def context(family, workers=1):
    if family not in {'S013', 'S003'}:
        raise ValueError('comparison family must be S013 or S003')
    bindings = {dataset: ProviderBinding('comparison-existing-local-evidence',
                                         file_hash(Path(__file__)), provider)
                for dataset in (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV,
                                Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY)}
    bindings[Dataset.STRATEGY_FEATURE_EVIDENCE] = ProviderBinding(
        'comparison-frozen-S003-local-seed', file_hash(Path(__file__)), seed_provider)
    # Other datasets cannot fall through to a credentialed built-in supplier.
    for dataset in Dataset:
        if dataset not in bindings:
            bindings[dataset] = ProviderBinding('comparison-forbidden-external', 'v1', forbidden)
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef(family),
                                  providers=ProviderConfig(bindings=bindings),
                                  resources=EvaluationResources(workers, 1, 13))


def prepare_centers():
    dependencies = tuple(ImplementationDependency(x, version(x))
                         for x in ('numpy', 'pandas', 'czsc-strategy-runtime'))
    summary = {'status': 'PREPARATION_PROBE', 'account_evaluations': 0,
               'external_calls': EXTERNAL_CALLS, 'centers': {}, 'local_calls': LOCAL_CALLS}
    for family in ('S013', 'S003'):
        ctx = context(family)
        if family == 'S013':
            candidate = load_candidate(ctx.repository, CandidateKey('S013', 'C2132'))
        else:
            payload = read(ROOT / 'strategies/S003/versions/v1.json')['strategy_payload']
            candidate = StrategyCandidate('S003', 'C9900', payload,
                                          ROOT / 'strategies/S003/releases/v1/runtime/strategy_runtime')
        request = EvaluationRequest(
            ROOT, 'comparison-local-prepare-probe', candidate,
            {'candidate_id': candidate.reference_id,
             'source_files': list(candidate.payload['runtime']['source_files']),
             'implementation_sha256': candidate.payload['runtime']['source_sha256']},
            '510500.SH', 'etf', (EvaluationWindow('common', START, END),), END, 1_000_000,
            (EvaluationCost('baseline', .001, 'FORMAL'),),
            benchmark=EvaluationBenchmark(LimitBuyHold(lot_size=100, premium=.01, price_tick=.001,
                                                       price_limit_ratio=.1, maximum_order_quantity=1_000_000)),
            workers=1, dependencies=dependencies, price_basis=ExecutionPriceBasis.HFQ_RESEARCH)
        try:
            bound = ctx.evaluation.prepare(request)
        except Exception as exc:
            summary['centers'][family] = {'status': 'FAILED', 'type': type(exc).__name__, 'error': str(exc)}
        else:
            summary['centers'][family] = {'status': 'PREPARED',
                                          'sessions': len(bound.execution_data.evaluation_sessions),
                                          'pricing': bound.execution_data.pricing.to_dict(),
                                          'has_5m': bound.execution_data.execution_five_minute is not None,
                                          'prepared': {
                                              'space_id': str(bound.execution_data.prepared.space_id),
                                              'preparation_id': str(bound.execution_data.prepared.preparation_id),
                                              'manifest_sha256': bound.execution_data.prepared.manifest_sha256}}
    summary['status'] = 'PASS' if all(x['status'] == 'PREPARED' for x in summary['centers'].values()) else 'FAILED'
    summary['source_sha256'] = file_hash(Path(__file__))
    write(WORK / 'local_prepare_probe.json', summary)
    print(json.dumps({'status': summary['status'], 'centers': summary['centers'],
                      'account_evaluations': 0, 'external_calls': EXTERNAL_CALLS}, default=str))
    return summary


if __name__ == '__main__':
    prepare_centers()
