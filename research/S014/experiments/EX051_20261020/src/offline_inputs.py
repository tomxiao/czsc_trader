"""S014-only, offline composition of authenticated original and prewindow assets.

The providers publish new DFLS preparations; they never edit the source assets or
fetch suppliers.  Quality evidence is rebuilt from the pinned raw observations.
"""
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID

import pandas as pd
from dataflows import (
    DataContractError, DataRequest, Dataset, PreparedDataRef, ProviderBinding,
    ProviderConfig, canonical_frame_sha256,
)
from dataflows.history_repair import frame_content_sha256
from dataflows.ohlcv_quality import build_quality_evidence, bind_quality_frame
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvidenceRef, ResearchBatchRef

ROOT = Path(__file__).resolve().parents[5]
EX = ROOT / "research/S014/experiments/EX017_20261017"
REVISION_SOURCE = EX / "src/pinned_inputs.py"
ORIGINAL = ROOT / 'research/S014/experiments/EX004_20261016/others/result.json'
PREWINDOW = EX / 'others/prewindow_inputs.json'
DATASETS = (
    Dataset.TRADING_CALENDAR, Dataset.STOCK_OHLCV,
    Dataset.STOCK_UNADJUSTED_DAILY, Dataset.SECURITY_PRICE_LIMITS,
    Dataset.SECURITY_TRADING_STATUS,
)


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _original_receipt():
    ref = EvidenceRef.from_dict(_json(ORIGINAL)['evidence']['input-readiness'])
    raw = ref.resolve(ROOT).read_bytes()
    if sha256(raw).hexdigest() != ref.sha256:
        raise DataContractError('Original S014 input evidence changed')
    return json.loads(raw), ref.to_dict()


def _revision():
    _, ref = _original_receipt()
    return sha256((sha256(REVISION_SOURCE.read_bytes()).hexdigest()
                   + ref['sha256'] + sha256(PREWINDOW.read_bytes()).hexdigest()).encode()).hexdigest()


def _request(raw):
    return DataRequest(Dataset(raw['dataset']), raw['symbol'], raw['start'],
                       raw['end'], raw['required_cutoff'], raw.get('frequency', 'daily'))


@lru_cache(maxsize=2)
def _catalog(revision):
    if revision != _revision():
        raise DataContractError('Pinned input implementation or manifest changed')
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'), providers=ProviderConfig(bindings={}))
    old, old_ref = _original_receipt()
    new = _json(PREWINDOW)
    if new['status'] != 'READY':
        raise DataContractError('Prewindow preparation is not READY')
    groups = {}
    for origin, rows in [('original', old['records']), ('prewindow', new['records'])]:
        for item in rows:
            request = _request(item['request'])
            if request.dataset not in DATASETS:
                raise DataContractError('Unexpected pinned S014 dataset')
            raw_ref = item['reference']
            ref = PreparedDataRef(UUID(raw_ref['space_id']), UUID(raw_ref['preparation_id']), raw_ref['manifest_sha256'])
            result = ctx.data.fetch(request, prepared=ref)
            expected = item.get('content_sha256') or item['identity']['content_sha256']
            if not result.ready or result.identity.content_sha256 != expected:
                raise DataContractError('Pinned S014 input identity mismatch', dataset=str(request.dataset))
            frame = result.dataframe.copy(deep=True)
            frame.attrs = {}
            groups.setdefault(request.dataset, []).append((origin, frame, deepcopy(dict(result.identity.metadata)), {
                'origin': origin, 'request': item['request'], 'prepared': raw_ref,
                'content_sha256': expected,
            }))
    result = {}
    for dataset, parts in groups.items():
        original = next(x[1] for x in parts if x[0] == 'original')
        combined = pd.concat([x[1] for x in parts], ignore_index=True)
        order = pd.to_datetime(combined.Date).sort_values(kind='stable').index
        combined = combined.loc[order].reset_index(drop=True)
        if pd.to_datetime(combined.Date).duplicated().any():
            raise DataContractError('Pinned source segments overlap; no implicit deduplication')
        restored = combined.loc[pd.to_datetime(combined.Date).ge('2020-01-01')].reset_index(drop=True)
        pd.testing.assert_frame_equal(restored, original.reset_index(drop=True), check_exact=True)
        if canonical_frame_sha256(restored) != canonical_frame_sha256(original.reset_index(drop=True)):
            raise DataContractError('Original period bytes or schema changed')
        result[dataset] = {'frame': combined, 'parts': parts, 'original_hash': canonical_frame_sha256(original)}
    if set(result) != set(DATASETS):
        raise DataContractError('Pinned dataset set is incomplete')
    return result, old_ref


def _cut(frame, start, end):
    dates = pd.to_datetime(frame.Date)
    return frame.loc[dates.between(pd.Timestamp(start), pd.Timestamp(end))].copy().reset_index(drop=True)


def _coverage(catalog, request):
    calendar = _cut(catalog[Dataset.TRADING_CALENDAR]['frame'], request.start, request.end)
    calendar = pd.DataFrame({'Date': pd.to_datetime(calendar.Date).dt.strftime('%Y-%m-%d'),
                             'is_open': calendar.IsOpen.astype(int)})
    if not pd.DatetimeIndex(pd.to_datetime(calendar.Date)).equals(pd.date_range(request.start, request.end)):
        raise DataContractError('Pinned calendar cannot cover request')
    status = _cut(catalog[Dataset.SECURITY_TRADING_STATUS]['frame'], request.start, request.end)
    parts = catalog[Dataset.SECURITY_TRADING_STATUS]['parts']
    listings = {p[2]['daily_session_coverage']['listing_date'] for p in parts}
    if len(listings) != 1:
        raise DataContractError('Pinned listing evidence disagrees')
    listed = listings.pop()
    expected_all = calendar.loc[calendar.is_open.eq(1) & calendar.Date.ge(listed), 'Date'].tolist()
    if pd.to_datetime(status.Date).dt.strftime('%Y-%m-%d').tolist() != expected_all:
        raise DataContractError('Pinned status does not prove each applicable session')
    suspended = pd.to_datetime(status.loc[status.Status.eq('SUSPENDED'), 'Date']).dt.strftime('%Y-%m-%d').tolist()
    proofs = [deepcopy(proof) for part in parts
              for proof in part[2]['daily_session_coverage']['suspension_evidence']
              if proof['date'] in suspended]
    expected = [day for day in expected_all if day not in suspended]
    return {'source': 'trade_cal', 'exchange': 'SSE',
            'start_date': request.start, 'end_date': request.end,
            'listing_date': listed, 'listing_source': 'stock_basic',
            'assembly': 'Authenticated pinned source segments; no new supplier call',
            'verified_sessions': len(expected), 'expected_dates': expected,
            'calendar': calendar.to_dict('records'), 'calendar_sha256': frame_content_sha256(calendar),
            'suspended_dates': suspended, 'suspension_evidence': proofs}


@dataclass(frozen=True)
class PinnedProvider:
    dataset: Dataset
    revision: str

    def __call__(self, request):
        if request.dataset != self.dataset or request.frequency != 'daily':
            raise DataContractError('Pinned provider only supports its declared daily dataset')
        expected_symbol = 'SSE' if self.dataset == Dataset.TRADING_CALENDAR else '600722.SH'
        lower = '2019-12-01' if self.dataset in (Dataset.TRADING_CALENDAR, Dataset.SECURITY_TRADING_STATUS) else (
            '2020-01-01' if self.dataset == Dataset.SECURITY_PRICE_LIMITS else '2019-12-31')
        if (request.symbol != expected_symbol or pd.Timestamp(request.start) < pd.Timestamp(lower)
                or pd.Timestamp(request.end) > pd.Timestamp('2026-10-15')):
            raise DataContractError('Request exceeds pinned S014 scope')
        catalog, old_ref = _catalog(self.revision)
        item = catalog[self.dataset]
        frame = _cut(item['frame'], request.start, request.end)
        metadata = deepcopy(item['parts'][0][2])
        metadata['vendor'] = 's014_pinned_composition'
        metadata['underlying_source_vendor'] = 'tushare'
        for key in ('provider_binding', 'provider_revision', 'dfls_revision', 'data_contract_version',
                    'validation', 'ohlcv_quality', 'daily_session_coverage', 'ohlcv_quality_evidence'):
            metadata.pop(key, None)
        metadata['pinned_composition'] = {
            'kind': 'AUTHENTICATED_SEGMENT_CONCATENATION', 'implementation_sha256': self.revision,
            'original_evidence': old_ref, 'prewindow_receipt_sha256': sha256(PREWINDOW.read_bytes()).hexdigest(),
            'segments': [part[3] for part in item['parts']],
            'original_period_content_sha256': item['original_hash'],
            'original_period_exactly_preserved': True, 'supplier_calls': 0,
        }
        if self.dataset in (Dataset.STOCK_OHLCV, Dataset.STOCK_UNADJUSTED_DAILY, Dataset.SECURITY_TRADING_STATUS, Dataset.SECURITY_PRICE_LIMITS):
            coverage = _coverage(catalog, request)
            metadata['daily_session_coverage'] = coverage
        if self.dataset in (Dataset.STOCK_OHLCV, Dataset.STOCK_UNADJUSTED_DAILY):
            raw = _cut(catalog[Dataset.STOCK_UNADJUSTED_DAILY]['frame'], request.start, request.end)
            quality = build_quality_evidence(raw, expected_dates=coverage['expected_dates'])
            metadata['ohlcv_quality_evidence'] = bind_quality_frame(quality, frame, adjustment=metadata['adjustment'])
            if self.dataset == Dataset.STOCK_OHLCV:
                for part in item['parts']:
                    source_metadata = part[2]
                    if (source_metadata.get('adjustment') != 'hfq'
                            or source_metadata.get('adjustment_factor_source') != 'adj_factor'
                            or source_metadata.get('adjustment_factor_publication_timestamp_verified') is not False
                            or source_metadata.get('adjustment_factor_revision_history_verified') is not False):
                        raise DataContractError('Pinned HFQ provenance differs')
                if not pd.to_datetime(frame.AvailableDate).equals(pd.to_datetime(frame.Date).dt.normalize() + pd.Timedelta(hours=17)):
                    raise DataContractError('Pinned HFQ availability contract differs')
                segment_hashes = [dict(source=part[3], factor_sha256=part[2]['adjustment_factor_sha256'])
                                  for part in item['parts']]
                metadata['adjustment_factor_sha256'] = sha256(json.dumps(segment_hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                metadata['adjustment_factor_hash_semantics'] = 'COMPOSITE_PINNED_SEGMENT_FACTOR_DIGESTS; not an original supplier factor-series digest'
                metadata['adjustment_factor_segments'] = segment_hashes
        return frame, metadata


def get_context(resources=None):
    """Create the standard S014 context with only explicit offline providers."""
    revision = _revision()
    providers = ProviderConfig(bindings={
        dataset: ProviderBinding('S014-EX017-pinned-' + str(dataset), revision, PinnedProvider(dataset, revision))
        for dataset in DATASETS
    })
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'),
                                   resources=resources, providers=providers)
