"""Revalidate retained S018 prices through DFLS; explicitly restate old research facts.

No supplier calls, old asset mutation, company-action inference or private asset reads.
The dynamic facts are the EX001 research assumption, not historical halt evidence.
"""
from dataclasses import asdict
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID

import pandas as pd

from czsc_trader.application import create_research_context
from czsc_trader.research_tools import ResearchBatchRef, EquitySources
from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct,
                       EquityQuery, InstrumentId, MarketId, PreparedDataRef,
                       PriceAdjustment, ProviderBinding, ProviderConfig, ProviderKey,
                       SourceRef, PreparePolicy)
from dataflows.equity_data import equity_metadata, session_record, sessions_from_metadata
from strategy_runtime import ExecutionResources

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
FIRST, LAST = date(2022, 1, 3), date(2026, 10, 30)
SOURCE = SourceRef('futu', 's018-hfq-target-repack-20261108-v1')
SOURCES = EquitySources(SOURCE, SOURCE, SOURCE)
MU = InstrumentId(MarketId.US, AssetClass.STOCK, 'MU')
SOXX = InstrumentId(MarketId.US, AssetClass.ETF, 'SOXX')
HFQ_ORIGINAL = SourceRef('futu', 's018-mu-soxx-hfq-research-20261104-v1')
RAW_ORIGINAL = SourceRef('futu', 's018-mu-daily-20261104')


def _read_reference(root, experiment, filename):
    path = root / f'research/S018/experiments/{experiment}/others/{filename}.json'
    content = path.read_bytes()
    row = json.loads(content)['reference']
    return PreparedDataRef(UUID(row['space_id']), UUID(row['preparation_id']),
                           row['manifest_sha256']), {
        'path': path.relative_to(root).as_posix(),
        'file_sha256': sha256(content).hexdigest(), 'reference': row}


def request(instrument, product, adjustment=PriceAdjustment.NONE):
    return EquityDataRequest(instrument, SOURCE,
        EquityQuery(product, FIRST, LAST, BarFrequency.DAILY, adjustment))


def build_data_context(repository, execution_spec):
    """Return (research context, sources, provenance) without preparing new assets."""
    root = repository.root
    old = create_research_context(repository, ResearchBatchRef('S018'),
        providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=execution_spec, resources=ExecutionResources(1, 1, 17))
    hfq_ref, hfq_receipt = _read_reference(root, 'EX049_20261104', 'data_preparation')
    raw_ref, raw_receipt = _read_reference(root, 'EX001_20261104', 'daily_preparation')
    frames, identities, calendars, old_metadata = {}, {}, {}, {}
    original_rows = []
    for instrument, adjustment, original, prepared in (
        (MU, PriceAdjustment.BACKWARD, HFQ_ORIGINAL, hfq_ref),
        (SOXX, PriceAdjustment.BACKWARD, HFQ_ORIGINAL, hfq_ref),
        (MU, PriceAdjustment.NONE, RAW_ORIGINAL, raw_ref),
    ):
        for product in (EquityProduct.BARS, EquityProduct.SESSIONS):
            price_basis = adjustment if product is EquityProduct.BARS else PriceAdjustment.NONE
            query = EquityDataRequest(instrument, original,
                EquityQuery(product, FIRST, LAST, BarFrequency.DAILY, price_basis))
            result = old.data.fetch(query, prepared=prepared)
            if not result.ready:
                raise RuntimeError(f'retained input unavailable: {query}: {result.error}')
            key = (instrument, product, price_basis)
            if key in identities and identities[key] != result.identity.content_sha256:
                raise ValueError('retained independent calendars disagree')
            frames[key] = pd.DataFrame(result.dataframe, copy=True)
            identities[key] = result.identity.content_sha256
            old_metadata[key] = dict(result.identity.metadata)
            sessions = sessions_from_metadata(result.identity.metadata)
            if instrument in calendars and calendars[instrument] != sessions:
                raise ValueError('retained source calendars disagree')
            calendars[instrument] = sessions
            original_rows.append({'symbol': instrument.symbol, 'product': product.value,
                'adjustment': price_basis.value, 'source': asdict(original),
                'prepared': asdict(prepared), 'content_sha256': result.identity.content_sha256,
                'rows': len(result.dataframe),
                'available_at': result.identity.metadata.get('available_at'),
                'publication_time_verified': result.identity.metadata.get('publication_time_verified'),
                'original_research_bar_policy': result.identity.metadata.get('research_bar_policy'),
                'download_receipts': result.identity.metadata.get('download_receipts', [])})

    assumption_path = root / 'research/S018/experiments/EX001_20261104/src/check_daily_readiness.py'
    provenance = {
        'schema_version': 1, 'source': asdict(SOURCE),
        'scope': {'start': FIRST.isoformat(), 'end': LAST.isoformat()},
        'operation': 'RETAINED_DFLS_PRICES_REVALIDATED_NO_NUMERICAL_ADJUSTMENT',
        'original_preparation_receipts': [hfq_receipt, raw_receipt], 'inputs': original_rows,
        'dynamic_facts': {
            'kind': 'EXPLICIT_RESTATEMENT_OF_EXISTING_RESEARCH_ASSUMPTIONS',
            'source_path': assumption_path.relative_to(root).as_posix(),
            'source_sha256': sha256(assumption_path.read_bytes()).hexdigest(),
            'original_futu_adapter_commit': '57f925496',
            'original_futu_adapter_path': 'packages/dataflows/src/dataflows/futu_equity.py',
            'tradable': True, 'price_limit_lower': None, 'price_limit_upper': None,
            'availability': 'SESSION_ELIGIBILITY_RESEARCH_ASSUMPTION',
            'historical_halt_coverage_verified': False,
            'old_constraints_product_read': False,
        },
        'limitations': [
            'No live supplier download or independent historical halt verification.',
            'Old prices retain BAR_CLOSE_RESEARCH_ASSUMPTION availability.',
            'PROVIDER_ADJUSTED identifies the original Futu HFQ acquisition; this run only revalidates metadata.',
            'Old equity.constraints cannot be requested by current public DFLS; its documented assumptions are restated, not claimed as migrated source rows.',
            'No following session outside the retained coverage is invented.',
        ],
    }
    provenance_sha = sha256(json.dumps(provenance, sort_keys=True, default=str).encode()).hexdigest()

    def fetch(query):
        p, q = query.parameters, query.parameters.query
        if (p.source != SOURCE or p.instrument not in calendars
                or q.frequency is not BarFrequency.DAILY or q.start < FIRST or q.end > LAST):
            raise ValueError('request exceeds the explicit retained source')
        if q.product is not EquityProduct.SESSIONS and (
                p.instrument, EquityProduct.BARS, q.adjustment) not in frames:
            raise ValueError('requested price basis has no retained source')
        complete = calendars[p.instrument]
        selected = tuple(s for s in complete if q.start <= s.session_date <= q.end)
        if not selected:
            raise ValueError('request has no retained sessions')
        meta = equity_metadata(query, selected,
            availability_basis=('SESSION_ELIGIBILITY_RESEARCH_ASSUMPTION'
                if q.product is EquityProduct.TRADING_FACTS else 'BAR_CLOSE_RESEARCH_ASSUMPTION'))
        meta.update(retained_input_operation=provenance['operation'],
                    retained_provenance_sha256=provenance_sha,
                    publication_time_verified=False)
        if q.product is EquityProduct.TRADING_FACTS:
            stamps = [bar.start for session in selected for bar in session.bars(q.frequency)]
            frame = pd.DataFrame({'Date': stamps, 'AvailableDate': stamps, 'Tradable': True,
                                 'PriceLimitLower': None, 'PriceLimitUpper': None})
            meta.update(tradability_basis='RESEARCH_ASSUMPTION_NOT_HISTORICAL_HALT_EVIDENCE',
                        rule_basis='RESEARCH_ASSUMPTIONS',
                        original_assumption_source_sha256=provenance['dynamic_facts']['source_sha256'])
            following = next((s for s in complete if s.session_date > q.end), None)
            if following is not None:
                meta['following_session'] = session_record(following)
            return frame, meta
        key = (p.instrument, q.product, q.adjustment)
        source_frame = frames[key]
        days = source_frame.Date.dt.tz_convert(p.instrument.timezone).dt.date
        frame = source_frame.loc[(days >= q.start) & (days <= q.end)].copy().reset_index(drop=True)
        original_meta = old_metadata[key]
        meta.update(original_content_sha256=identities[key],
                    original_source_revision=original_meta['source_revision'],
                    original_vendor=original_meta['vendor'])
        for name in ('calendar_source', 'download_receipts', 'daily_volume_scope',
                     'download_complete'):
            if name in original_meta:
                meta[name] = original_meta[name]
        if q.product is EquityProduct.BARS:
            if 'research_bar_policy' in original_meta:
                policy = original_meta['research_bar_policy']
                if policy['kind'] not in ('MISSING_UNTRADABLE_RESEARCH_V1', 'OBSERVATION_GAPS_V2'):
                    raise ValueError('unknown retained observation policy')
                # The original remote page receipts describe the full download,
                # not a later local range selection. Retain them as provenance;
                # admit the unchanged row statuses through the explicit-facts
                # contract instead of inventing new remote download receipts.
                evidence = json.dumps({'original_content_sha256': identities[key],
                    'original_research_bar_policy': policy,
                    'retained_provenance_sha256': provenance_sha}, sort_keys=True)
                meta.update(observation_contract='EXPLICIT_SOURCE_OBSERVATIONS_V1',
                    observation_basis='RETAINED_SOURCE_STATUS_NOT_HISTORICAL_HALT_EVIDENCE',
                    coverage_evidence=evidence,
                    coverage_evidence_sha256=sha256(evidence.encode()).hexdigest(),
                    observation_policy_migration='PRESERVE_RETAINED_BAR_STATUS_AND_EXECUTION_BLOCKING')
            meta['acquisition_method'] = ('PROVIDER_ADJUSTED'
                if q.adjustment is PriceAdjustment.BACKWARD else 'PROVIDER_RAW')
            meta['price_source_api'] = 'futu.request_history_kline (retained DFLS publication)'
        return frame, meta

    bindings = {ProviderKey(product, MarketId.US, SOURCE):
        ProviderBinding(SOURCE.provider, SOURCE.revision, fetch) for product in EquityProduct}
    context = create_research_context(repository, ResearchBatchRef('S018'),
        providers=ProviderConfig(bindings={}, equity_bindings=bindings),
        execution_spec=execution_spec, resources=ExecutionResources(1, 1, 17))
    return context, SOURCES, provenance


def prepare_raw_reference(context):
    """Bind existing RAW prices separately from the HFQ strategy input."""
    from paper_trading_engine.execution_reference import ExecutionReferenceBinding
    raw = request(MU, EquityProduct.BARS)
    ready = context.data.prepare((raw,), policy=PreparePolicy.REUSE)
    if not ready.ready:
        raise RuntimeError(tuple((x.status, x.error) for x in ready.items))
    result = context.data.fetch(raw, prepared=ready.reference)
    if not result.ready:
        raise RuntimeError(result.error)
    return ExecutionReferenceBinding(raw.parameters, ready.reference, result.identity.content_sha256)


def main():
    from czsc_trader.application import RepositoryContext
    from strategy_runtime.equity_definition import execution_spec_from_dict
    frozen = json.loads((ROOT/'strategies/S018/versions/v1.json').read_text(encoding='utf-8'))
    spec = execution_spec_from_dict(frozen['strategy_payload']['equity_definition']['execution_spec'])
    context, _, provenance = build_data_context(RepositoryContext.discover(ROOT), spec)
    queries = tuple(request(instrument, product,
        PriceAdjustment.BACKWARD if product is not EquityProduct.SESSIONS else PriceAdjustment.NONE)
        for instrument, products in ((MU, tuple(EquityProduct)),
                                     (SOXX, (EquityProduct.BARS, EquityProduct.SESSIONS)))
        for product in products) + (request(MU, EquityProduct.BARS),)
    ready = context.data.prepare(queries, policy=PreparePolicy.REFRESH)
    if not ready.ready:
        raise RuntimeError(tuple((x.status, x.error) for x in ready.items))
    checks = []
    originals = {(x['symbol'], x['product'], x['adjustment']): x['content_sha256']
                 for x in provenance['inputs']}
    for query in queries:
        fetched = context.data.fetch(query, prepared=ready.reference)
        if not fetched.ready:
            raise RuntimeError(fetched.error)
        p = query.parameters
        original_hash = originals.get((p.instrument.symbol, p.query.product.value, p.query.adjustment.value))
        if original_hash is not None and original_hash != fetched.identity.content_sha256:
            raise AssertionError('revalidation changed retained numeric content')
        checks.append({'symbol': p.instrument.symbol, 'product': p.query.product.value,
            'adjustment': p.query.adjustment.value, 'rows': len(fetched.dataframe),
            'content_sha256': fetched.identity.content_sha256,
            'original_numeric_content_identical': original_hash is not None,
            'acquisition_method': fetched.identity.metadata.get('acquisition_method'),
            'price_basis_id': fetched.identity.metadata['price_basis_id']})
    output = EXPERIMENT/'others/data_inputs.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    value = {'status': 'READY', 'provenance': provenance, 'prepared': asdict(ready.reference), 'checks': checks}
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')
    print(json.dumps({'status': 'READY', 'checks': checks}, ensure_ascii=False))


if __name__ == '__main__':
    main()
