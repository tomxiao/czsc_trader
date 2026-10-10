"""Authenticated historical S007 inputs, newly checked by current DFLS quality rules.

No account evaluation, no old preparation resigning, and no post-cutoff price data.
"""
from functools import lru_cache
from hashlib import sha256
import json
import pandas as pd
import numpy as np
from dataflows import Dataset, canonical_frame_sha256
from dataflows.ohlcv_quality import build_quality_evidence, bind_quality_frame, validate_quality_metadata
from dataflows.history_repair import frame_content_sha256
from dataflows.contract import ETF_INTRADAY_OBSERVATION_RULE

from common import ROOT, PROTOCOLS, SOURCE, read
from czsc_trader.research_tools import EvidenceRef
END = '2026-09-02'
WORK = ROOT / '.tmp/s007-four-metrics/offline-source'
VALUE_COLUMNS = ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']


def hashed(path):
    return sha256(path.read_bytes()).hexdigest()


def old_frame(manifest, prefix, frequency, provenance):
    frames = []
    for year in range(2020, 2027):
        name = f'{prefix}{year}.csv'
        path = ROOT / 'data/raw' / name
        entry = manifest['files'][name]
        digest = hashed(path)
        if digest != entry['sha256']:
            raise ValueError(f'Historical manifest mismatch: {name}')
        frame = pd.read_csv(path)
        frame = frame.rename(columns={'date': 'Date', 'datetime': 'Date', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume', 'amount': 'Amount'})
        frame.Date = pd.to_datetime(frame.Date)
        if (frame.Date.dt.normalize() > pd.Timestamp(END)).any():
            raise ValueError(f'Historical file exceeds authorized cutoff: {name}')
        if len(frame) != entry['rows']:
            raise ValueError(f'Historical manifest row count mismatch: {name}')
        provenance[name] = {'sha256': digest, 'frequency': frequency, 'rows': len(frame)}
        frames.append(frame[['Date', *VALUE_COLUMNS]])
    result = pd.concat(frames, ignore_index=True).sort_values('Date').reset_index(drop=True)
    if result.Date.duplicated().any():
        raise ValueError('Historical market source contains duplicate dates')
    return result


@lru_cache(maxsize=1)
def sources():
    manifests = [ROOT / 'data/raw/588080_manifest.json', ROOT / 'data/raw/588080_execution_manifest.json']
    records = {'manifests': {path.relative_to(ROOT).as_posix(): hashed(path) for path in manifests}, 'files': {}}
    hfq_manifest, raw_manifest = [json.loads(path.read_text(encoding='utf-8')) for path in manifests]
    if any(value['requested_end'] != END for value in (hfq_manifest, raw_manifest)):
        raise ValueError('Original manifest cutoff differs')
    hfq = old_frame(hfq_manifest, '588080_daily_', 'daily', records['files'])
    raw = old_frame(raw_manifest, '588080_execution_daily_', 'daily', records['files'])
    hfq30 = old_frame(hfq_manifest, '588080_30m_', '30m', records['files'])
    h, r = hfq.set_index('Date'), raw.set_index('Date')
    if not h.index.equals(r.index):
        raise ValueError('Historical HFQ and raw daily dates differ')
    factor = h.Close / r.Close
    price_error = max(float(np.max(np.abs(h[column] / factor - r[column]))) for column in VALUE_COLUMNS[:4])
    volume_error = float(np.max(np.abs(h.Volume * factor - r.Volume)))
    amount_error = float(np.max(np.abs(h.Amount - r.Amount)))
    if not all(np.allclose(h[column] / factor, r[column], rtol=1e-12, atol=1e-12) for column in VALUE_COLUMNS[:4]):
        raise ValueError('Historical daily prices do not share one HFQ factor per day')
    if not np.allclose(h.Volume * factor, r.Volume, rtol=1e-12, atol=1e-6) or amount_error != 0:
        raise ValueError('Historical HFQ inverse-volume or amount relationship differs')
    raw30 = hfq30.copy()
    f30 = raw30.Date.dt.normalize().map(factor)
    if f30.isna().any():
        raise ValueError('Historical minute factor date missing')
    for column in VALUE_COLUMNS[:4]:
        raw30[column] = raw30[column] / f30
    raw30.Volume = raw30.Volume * f30
    records['restoration'] = {'method': 'raw OHLC = HFQ OHLC / daily Close ratio; raw Volume = HFQ Volume * ratio; Amount unchanged',
                              'daily_price_max_absolute_error': price_error, 'daily_volume_max_absolute_error': volume_error,
                              'daily_amount_max_absolute_error': amount_error, 'minimum_factor': float(factor.min()),
                              'maximum_factor': float(factor.max()), 'factor_series_sha256': canonical_frame_sha256(factor.rename('Factor').reset_index())}
    references = read(PROTOCOLS / 'offline_source_references.json')
    calendar_path = EvidenceRef.from_dict(references['calendar']).resolve(ROOT)
    calendar_report_path = EvidenceRef.from_dict(references['calendar_report']).resolve(ROOT)
    report = json.loads(calendar_report_path.read_text(encoding='utf-8'))
    if hashed(calendar_path) != report['datasets']['calendar']['csv_sha256']:
        raise ValueError('Independent trade_cal snapshot hash differs from original receipt')
    calendar = pd.read_csv(calendar_path)
    calendar.Date = pd.to_datetime(calendar.Date)
    calendar = calendar.reset_index(drop=True)
    if not pd.DatetimeIndex(calendar.Date).equals(pd.date_range(calendar.Date.min(), calendar.Date.max())):
        raise ValueError('Independent trade_cal snapshot omits natural dates')
    instrument_path = EvidenceRef.from_dict(references['instrument']).resolve(ROOT)
    instrument = json.loads(instrument_path.read_text(encoding='utf-8'))
    if len(instrument) != 1 or instrument[0]['ts_code'] != '588080.SH':
        raise ValueError('Independent fund_basic listing source differs')
    listing = pd.to_datetime(instrument[0]['list_date'], format='%Y%m%d').date().isoformat()
    if listing != '2020-11-16':
        raise ValueError('Listing date differs from original market start')
    records['calendar'] = {'path': calendar_path.relative_to(ROOT).as_posix(), 'sha256': hashed(calendar_path),
                           'receipt_sha256': hashed(calendar_report_path), 'original_source_end': report['end'],
                           'actual_used_end': END, 'source': 'Tushare trade_cal; independent of price rows',
                           'listing_source': instrument_path.relative_to(ROOT).as_posix(), 'listing_sha256': hashed(instrument_path)}
    # The original factor receipt is retained; the actual factor used above is
    # independently tied to every authenticated raw/HFQ daily observation.
    factor_hash = hfq_manifest['adjustment']['factor_sha256']
    return raw, hfq, raw30, calendar, listing, records, factor_hash


def supplier(request):
    if request.dataset != Dataset.TRADING_CALENDAR and (
            request.end > END or (request.required_cutoff and request.required_cutoff > END)):
        raise ValueError('Offline S007 supplier refuses post-development-cutoff requests')
    if request.dataset == Dataset.STRATEGY_FEATURE_EVIDENCE:
        parameters = request.parameters
        seed = SOURCE / 'resources/s007_v1_seed.csv.gz'
        if (request.symbol != 'S007-v1' or parameters.repository_root != SOURCE
                or parameters.source_path != 'resources/s007_v1_seed.csv.gz'
                or hashed(seed) != parameters.source_sha256):
            raise ValueError('Frozen feature seed identity differs')
        frame = pd.read_csv(seed)
        frame.Date = pd.to_datetime(frame.Date)
        frame = frame.loc[frame.Date.between(request.start, request.end)].reset_index(drop=True)
        return frame, {'vendor': 'repository', 'source_path': parameters.source_path,
            'source_sha256': parameters.source_sha256, 'source_time_field': 'Date',
            'availability_time_field': 'Date', 'source_calendar': 'SSE',
            'available_at': 'Immutable historical selected feature seed; already used in strategy selection'}
    raw, hfq, raw30, calendar, listing, provenance, factor_hash = sources()
    first, last = pd.Timestamp(request.start).normalize(), pd.Timestamp(request.end).normalize()
    if first < calendar.Date.min() or last > calendar.Date.max() or first > last:
        raise ValueError('Offline source does not cover requested dates')
    cal = calendar.loc[calendar.Date.between(first, last)].copy().reset_index(drop=True)
    if request.dataset == Dataset.TRADING_CALENDAR:
        if request.symbol != 'SSE' or request.frequency != 'daily':
            raise ValueError('Unsupported calendar request')
        return cal, {'vendor': 'tushare', 'exchange': 'SSE', 'source_calendar': 'SSE', 'source_time_field': 'Date',
                     'availability_time_field': 'Date', 'available_at': 'SOURCE_PERIOD_CLOSE',
                     'historical_source_provenance': provenance['calendar']}
    if request.symbol != '588080.SH':
        raise ValueError('Unsupported symbol')
    selected_raw = raw.loc[raw.Date.between(first, last)].copy().reset_index(drop=True)
    expected = cal.loc[cal.IsOpen.eq(1) & cal.Date.ge(pd.Timestamp(listing)), 'Date'].dt.strftime('%Y-%m-%d').tolist()
    canonical = pd.DataFrame({'Date': cal.Date.dt.strftime('%Y-%m-%d'), 'is_open': cal.IsOpen.astype(int)})
    coverage = {'source': 'trade_cal', 'exchange': 'SSE', 'start_date': request.start, 'end_date': request.end,
                'listing_date': listing, 'listing_source': 'fund_basic', 'verified_sessions': len(expected),
                'expected_dates': expected, 'calendar': canonical.to_dict('records'), 'calendar_sha256': frame_content_sha256(canonical)}
    minute = None
    adjustment = 'none'
    if request.dataset == Dataset.ETF_UNADJUSTED_DAILY and request.frequency == 'daily':
        frame = selected_raw.copy()
    elif request.dataset == Dataset.ETF_OHLCV and request.frequency == 'daily':
        frame = hfq.loc[hfq.Date.between(first, last)].copy().reset_index(drop=True)
        adjustment = 'hfq'
    elif request.dataset == Dataset.ETF_UNADJUSTED_INTRADAY and request.frequency == '30m':
        minute = raw30.loc[raw30.Date.dt.normalize().between(first, last)].copy().reset_index(drop=True)
        frame = minute.copy()
    else:
        raise ValueError('Offline supplier only supports HFQ/raw daily and raw 30m')
    evidence = build_quality_evidence(selected_raw, intraday=minute, frequency=request.frequency, expected_dates=expected)
    frame['AvailableDate'] = frame.Date if minute is not None else frame.Date.dt.normalize() + pd.Timedelta(hours=17)
    metadata = {'vendor': 'tushare', 'vendor_symbol': '588080.SH', 'market': 'a_share', 'asset_type': 'etf',
                'period': request.frequency, 'adjustment': adjustment, 'source_calendar': 'SSE',
                'source_time_field': 'Date', 'availability_time_field': 'AvailableDate',
                'available_at': 'SOURCE_PERIOD_CLOSE', 'daily_session_coverage': coverage,
                'ohlcv_quality_evidence': bind_quality_frame(evidence, frame, adjustment=adjustment),
                'historical_source_provenance': provenance}
    if adjustment == 'hfq':
        metadata.update(adjustment_factor_source='fund_adj', adjustment_factor_sha256=factor_hash,
                        adjustment_factor_publication_schedule='daily 17:00 Asia/Shanghai',
                        adjustment_factor_publication_timestamp_verified=False, adjustment_factor_revision_history_verified=False,
                        available_at='scheduled fund_adj daily 17:00 Asia/Shanghai; historical publication unverified')
    elif minute is not None:
        metadata.update(available_at=ETF_INTRADAY_OBSERVATION_RULE, availability_basis='MARKET_BAR_CLOSE_ASSUMPTION',
                        source_publication_timestamp_verified=False, historical_revision_history_verified=False, live_feed_latency_verified=False)
    metadata['ohlcv_quality'] = validate_quality_metadata(metadata, request, frame)
    return frame, metadata


def main():
    from dataflows import DataRequest
    WORK.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, dataset, frequency in [('raw-daily', Dataset.ETF_UNADJUSTED_DAILY, 'daily'),
                                      ('hfq-daily', Dataset.ETF_OHLCV, 'daily'),
                                      ('raw-30m', Dataset.ETF_UNADJUSTED_INTRADAY, '30m')]:
        request = DataRequest(dataset, '588080.SH', '2020-12-01', END, END, frequency)
        try:
            frame, metadata = supplier(request)
            frame.to_csv(WORK / (name + '.csv.gz'), index=False, compression={'method': 'gzip', 'mtime': 0})
            (WORK / (name + '-metadata.json')).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            rows.append({'name': name, 'status': 'PASS', 'rows': len(frame), 'quality': metadata['ohlcv_quality'],
                         'content_sha256': canonical_frame_sha256(frame)})
        except Exception as error:
            rows.append({'name': name, 'status': 'FAILED', 'error_type': type(error).__name__, 'message': str(error)})
    (WORK / 'quality-check.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == '__main__':
    main()
