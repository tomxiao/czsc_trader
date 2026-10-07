"""S013 authorized phase-two DFLS preparation; no cross-batch input reuse."""
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
import json
from pathlib import Path
from collections.abc import Mapping
from uuid import UUID

import pandas as pd
from dataflows import DataRequest, Dataset, PreparePolicy, DataCoverageRequirement, DataIdentity
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef, EvaluationResources

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parent

def encode(value):
    if isinstance(value, DataIdentity):
        result = {f.name: encode(getattr(value, f.name)) for f in fields(value) if f.name != 'metadata'}
        result['metadata'] = compact_metadata(encode(value.metadata))
        return result
    if is_dataclass(value):
        return {f.name: encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [encode(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (UUID, Path, pd.Timestamp, datetime)):
        return str(value)
    if hasattr(value, 'item'):
        return value.item()
    return value

def compact_metadata(metadata):
    result = dict(metadata)
    coverage = dict(result.get('daily_session_coverage', {}))
    if coverage:
        dates = coverage.pop('expected_dates', [])
        if dates:
            coverage['expected_date_count'] = len(dates)
        for key in tuple(coverage):
            if isinstance(coverage[key], (list, dict)) and len(coverage[key]) > 100:
                coverage[key + '_count'] = len(coverage.pop(key))
        result['daily_session_coverage'] = coverage
    quality = result.get('ohlcv_quality', {})
    anomalous = set()
    for detail in quality.values():
        if isinstance(detail, dict):
            anomalous.update(detail.get('inaccurate_dates', []))
            anomalous.update(detail.get('incomplete_dates', []))
    evidence = dict(result.get('ohlcv_quality_evidence', {}))
    if evidence:
        sessions = evidence.pop('sessions', {})
        evidence.pop('date_sha256', None)
        evidence.pop('row_sha256', None)
        evidence.pop('observation_sha256', None)
        if sessions:
            evidence['session_count'] = len(sessions)
            evidence['anomalous_sessions'] = {k: v for k, v in sessions.items() if k in anomalous}
        evidence['full_evidence_location'] = 'PreparedDataRef定位的S013独立DFLS资产；本材料仅选定异常和摘要'
        result['ohlcv_quality_evidence'] = evidence
    return result

def save(name, value):
    (WORK / name).write_text(json.dumps(encode(value), ensure_ascii=False, indent=2,
        allow_nan=False) + '\n', encoding='utf-8', newline='\n')

def main():
    repository = RepositoryContext.discover(ROOT)
    research = create_research_context(repository, ResearchBatchRef('S013'),
        resources=EvaluationResources(max_workers=8, native_threads_per_worker=1, random_seed=13))
    result = {'recorded_at': datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
              'space': research.data.binding.space.path.as_posix(), 'space_id': str(research.data.binding.space_id)}
    calendar_request = DataRequest(Dataset.TRADING_CALENDAR, 'SSE', '2019-09-01', '2026-09-30', '2026-09-30')
    calendar = research.data.prepare((calendar_request,), policy=PreparePolicy.REUSE)
    result['calendar'] = encode(calendar)
    save('data_preparation.json', result)
    if not calendar.ready:
        print(json.dumps({'calendar_status': calendar.status.value,
            'errors': [encode(x.error) for x in calendar.items]}, ensure_ascii=False))
        return
    fetched_calendar = research.data.fetch(calendar_request, prepared=calendar.reference)
    if not fetched_calendar.ready:
        raise RuntimeError(encode(fetched_calendar.error))
    frame = fetched_calendar.dataframe
    sessions = pd.DatetimeIndex(frame.loc[frame.IsOpen.eq(1), 'Date']).normalize().sort_values()
    prior = sessions[sessions < pd.Timestamp('2020-01-01')]
    assert len(prior) >= 60
    warmup_start = prior[-60].strftime('%Y-%m-%d')
    pool = sessions[(sessions >= '2020-01-01') & (sessions <= '2026-09-30')]
    result['warmup_start'] = warmup_start
    result['warmup_sessions'] = 60
    result['pool_sessions'] = len(pool)
    result['first_pool_session'] = pool[0].strftime('%Y-%m-%d')
    result['last_pool_session'] = pool[-1].strftime('%Y-%m-%d')
    coverage = DataCoverageRequirement(maximum_start_lag_days=None, minimum_sessions=60,
                                       observations_through='2019-12-31')
    requests = (
        DataRequest(Dataset.ETF_OHLCV, '510500.SH', warmup_start, '2026-09-30', '2026-09-30', coverage=coverage),
        DataRequest(Dataset.ETF_UNADJUSTED_DAILY, '510500.SH', warmup_start, '2026-09-30', '2026-09-30', coverage=coverage),
    )
    daily = research.data.prepare(requests, policy=PreparePolicy.REUSE)
    result['daily'] = encode(daily)
    save('data_preparation.json', result)
    print(json.dumps({'daily_status': daily.status.value, 'pool_sessions': len(pool),
        'warmup_start': warmup_start, 'errors': [encode(x.error) for x in daily.items if not x.ready]}, ensure_ascii=False), flush=True)
    if daily.ready:
        result['daily_fetch'] = {}
        for request in requests:
            market = research.data.fetch(request, prepared=daily.reference)
            assert market.ready, encode(market.error)
            dates = pd.DatetimeIndex(market.dataframe.Date).normalize()
            assert dates.equals(sessions[sessions >= warmup_start])
            key = 'adjusted' if request.dataset is Dataset.ETF_OHLCV else 'unadjusted'
            result['daily_fetch'][key] = {
                'identity': encode(market.identity), 'columns': list(market.dataframe.columns),
                'rows': len(market.dataframe), 'dtypes': {k: str(v) for k, v in market.dataframe.dtypes.items()},
            }
        save('data_preparation.json', result)
    minute_request = DataRequest(Dataset.ETF_UNADJUSTED_INTRADAY, '510500.SH',
        pool[0].strftime('%Y-%m-%d'), '2026-09-30', '2026-09-30', frequency='30m')
    minute = research.data.prepare((minute_request,), policy=PreparePolicy.REUSE)
    result['execution_30m'] = encode(minute)
    save('data_preparation.json', result)
    print(json.dumps({'execution_30m_status': minute.status.value,
        'errors': [encode(x.error) for x in minute.items if not x.ready]}, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    main()
