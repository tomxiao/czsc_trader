"""Current-contract DFLS adapters for authenticated retained S007 inputs only."""
from datetime import date
from hashlib import sha256
import json

import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EquitySources, EvidenceRef, ResearchBatchRef
from dataflows import (BarFrequency, Dataset, EquityProduct, PriceAdjustment,
    ProviderBinding, ProviderConfig, ProviderKey, SourceRef)
from dataflows.equity_data import equity_metadata, session_record, sessions_from_metadata
from dataflows.local_strategy_data import fetch_strategy_feature_evidence
from strategy_runtime import ExecutionResources

from retained_inputs import ROOT, load

SOURCE = SourceRef('tushare-retained', 's007-current-contract-20261108')
FIRST, LAST = date(2026, 8, 1), date(2026, 11, 5)


def build_data_context(candidate):
    frames, original = load()
    ref = EvidenceRef.from_dict(original['reference'])
    path = ref.resolve(ROOT)
    document = json.loads(path.read_bytes())
    raw_input = document['input_ref']
    data_bytes = (path.parent / (raw_input['sha256'] + '.json')).read_bytes()
    if sha256(data_bytes).hexdigest() != raw_input['sha256']:
        raise ValueError('historical input snapshot hash differs')
    snapshot = json.loads(data_bytes)
    facts = pd.DataFrame(snapshot['products']['constraints'])[
        ['Date', 'AvailableDate', 'Tradable', 'PriceLimitLower', 'PriceLimitUpper']].copy()
    for key in ('Date', 'AvailableDate'):
        facts[key] = pd.to_datetime(facts[key], utc=True)
    raw, hfq = frames['raw_daily'], frames['hfq_daily']
    raw_dates = pd.to_datetime(raw.Date, utc=True).dt.tz_convert('Asia/Shanghai').dt.date
    hfq_dates = pd.to_datetime(hfq.Date, utc=True).dt.tz_convert('Asia/Shanghai').dt.date
    if list(raw_dates) != list(hfq_dates):
        raise ValueError('RAW/HFQ daily dates differ')
    ratios = dict(zip(raw_dates, hfq.Close.to_numpy() / raw.Close.to_numpy(), strict=True))
    adjusted_facts = facts.copy(deep=True)
    days = facts.Date.dt.tz_convert('Asia/Shanghai').dt.date
    scales = days.map(ratios)
    if scales.isna().any() or (scales <= 0).any():
        raise ValueError('trading facts have no exact positive retained price-basis ratio')
    for key in ('PriceLimitLower', 'PriceLimitUpper'):
        adjusted_facts[key] = facts[key] * scales
    sessions = sessions_from_metadata(original['inputs']['sessions']['metadata'])
    calendar = original['inputs']['hfq_daily']['metadata']['daily_session_coverage']['calendar']
    provenance = {'source': {'provider': SOURCE.provider, 'revision': SOURCE.revision},
        'retained': original, 'historical_input_sha256': raw_input['sha256'],
        'method': 'UNCHANGED_RETAINED_PRICES_AND_TABLES_WITH_CURRENT_DYNAMIC_FACT_PROJECTION',
        'history_start': FIRST.isoformat(), 'coverage_end': LAST.isoformat(),
        'recommended_replay_window': ['2026-09-03', '2026-11-04'],
        'recommended_technical_window': ['2026-09-01', '2026-09-02'],
        'dynamic_facts': 'Original published constraints projected to dynamic fields; HFQ price bounds scaled by same-session HFQ/RAW ratio',
        'limitations': ['No new external data or independent historical halt verification',
            'HFQ retains original fund_adj publication-time assumptions and DFLS-computed price values',
            'No following trading session beyond the retained 2026-11-05 calendar is invented',
            'Old RAW account performance is not admitted as current HFQ account evidence']}

    def equity_fetch(request):
        p, q = request.parameters, request.parameters.query
        if (p.source != SOURCE or p.instrument != candidate.instrument or q.frequency is not BarFrequency.DAILY
                or q.start < FIRST or q.end > LAST):
            raise ValueError('S007 request exceeds retained daily source coverage')
        selected = tuple(s for s in sessions if q.start <= s.session_date <= q.end)
        if not selected:
            raise ValueError('retained range has no sessions')
        meta = equity_metadata(request, selected, availability_basis='RETAINED_EXPLICIT_SOURCE_TIMESTAMPS')
        meta.update(retained_input_sha256=raw_input['sha256'], calendar_source='retained tushare.trade_cal',
                    publication_time_verified=False)
        following = next((s for s in sessions if s.session_date > q.end), None)
        if following is not None:
            meta['following_session'] = session_record(following)
        if q.product is EquityProduct.TRADING_FACTS:
            source = adjusted_facts if q.adjustment is PriceAdjustment.BACKWARD else facts
            meta.update(original_constraint_sha256=snapshot['data']['constraints']['content_sha256'],
                        dynamic_fact_method=provenance['dynamic_facts'])
        elif q.product is EquityProduct.SESSIONS:
            source = frames['sessions']
        elif q.product is EquityProduct.BARS:
            adjusted = q.adjustment is PriceAdjustment.BACKWARD
            source = hfq if adjusted else raw
            name = 'hfq_daily' if adjusted else 'raw_daily'
            meta.update(acquisition_method='DFLS_ADJUSTED' if adjusted else 'PROVIDER_RAW',
                original_content_sha256=original['inputs'][name]['content_sha256'],
                price_source_api='retained Tushare fund_daily and fund_adj' if adjusted else 'retained Tushare fund_daily')
        else:
            raise ValueError('unsupported retained product')
        source_days = pd.to_datetime(source.Date, utc=True).dt.tz_convert('Asia/Shanghai').dt.date
        return source.loc[source_days.between(q.start, q.end)].copy().reset_index(drop=True), meta

    observations = {item.name: item for item in candidate.definition.observation_inputs}
    by_dataset = {item.dataset: name for name, item in observations.items() if item.asset is None}

    def table_fetch(request):
        name = by_dataset[request.dataset]
        source = frames[name]
        days = pd.to_datetime(source.Date).dt.date
        first, last = date.fromisoformat(request.start), date.fromisoformat(request.end)
        original_request = original['inputs'][name]['binding']['request']
        if first < date.fromisoformat(original_request['start']) or last > date.fromisoformat(original_request['end']):
            raise ValueError('table query exceeds retained source coverage')
        result = source.loc[days.between(first, last)].copy().reset_index(drop=True)
        meta = dict(original['inputs'][name]['metadata'])
        meta.update(retained_original_content_sha256=original['inputs'][name]['content_sha256'])
        return result, meta

    def calendar_fetch(request):
        first, last = date.fromisoformat(request.start), date.fromisoformat(request.end)
        if first < FIRST or last > LAST:
            raise ValueError('calendar query exceeds retained source coverage')
        rows = pd.DataFrame(calendar).rename(columns={'is_open': 'IsOpen'})
        rows['Date'] = pd.to_datetime(rows.Date)
        rows = rows.loc[rows.Date.dt.date.between(first, last)].copy()
        return rows, {'vendor': 'tushare-retained', 'exchange': 'SSE', 'primary_key': ['Date'],
            'frequency': 'daily', 'source_content_sha256': original['inputs']['hfq_daily']['content_sha256']}

    tables = {dataset: ProviderBinding(SOURCE.provider, SOURCE.revision, table_fetch) for dataset in by_dataset}
    tables[Dataset.STRATEGY_FEATURE_EVIDENCE] = ProviderBinding('repository-evidence', 'v1', fetch_strategy_feature_evidence)
    tables[Dataset.TRADING_CALENDAR] = ProviderBinding(SOURCE.provider, SOURCE.revision, calendar_fetch)
    equity = {ProviderKey(product, candidate.instrument.market, SOURCE):
        ProviderBinding(SOURCE.provider, SOURCE.revision, equity_fetch) for product in EquityProduct}
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S007'),
        providers=ProviderConfig(bindings=tables, equity_bindings=equity),
        execution_spec=candidate.definition.execution_spec, resources=ExecutionResources(1, 1, 17))
    return context, EquitySources(SOURCE, SOURCE, SOURCE), provenance
