"""Retained S011/S015 DFLS assets through current HFQ/RAW product contracts."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef, EvidenceRef, EquitySources
from dataflows import (BarFrequency, EquityProduct, MarketId, PriceAdjustment, ProviderBinding,
    ProviderConfig, ProviderKey, SourceRef)
from dataflows.bar_utils import apply_hfq_adjustment, with_scheduled_hfq_availability
from dataflows.equity_data import equity_metadata, session_record, sessions_from_metadata
from strategy_runtime import StrategyInputBinding, ExecutionResources

ROOT = Path(__file__).resolve().parents[4]
SOURCE = SourceRef('tushare-cn-market', 'v1')
END = date(2026, 10, 20)


def _artifact():
    owner = ROOT / 'research/S015/experiments/EX094_20261106/others/account_STANDARD.json'
    reference = EvidenceRef.from_dict(json.loads(owner.read_bytes())['new_reference'])
    path = reference.resolve(ROOT)
    saved = json.loads(path.read_bytes())['input_ref']
    artifact = path.parent / (saved['sha256'] + '.json')
    content = artifact.read_bytes()
    assert sha256(content).hexdigest() == saved['sha256']
    return json.loads(content), {'account': reference.to_dict(), 'input_sha256': saved['sha256']}


def _frame(rows):
    frame = pd.DataFrame(rows)
    for column in ('Date', 'AvailableDate', 'BarStart'):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame


def build_data_context(candidate):
    strategy_id = candidate.strategy_id
    assert strategy_id in ('S011', 'S015')
    repo = RepositoryContext.discover(ROOT)
    artifact, provenance = _artifact()
    products = artifact['products']
    raw = _frame(products['bars'])
    hfq = _frame(products['auxiliary:hfq:bars'])
    intraday_raw = _frame(products['auxiliary:intraday:bars'])
    assert raw.Date.equals(hfq.Date)
    # The retained daily product already incorporates DFLS fund_adj. Reuse its
    # exact scale in DFLS's own adjustment routine, with explicit provenance.
    factors = pd.DataFrame({'Date': raw.Date.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None).dt.normalize(),
                            'AdjFactor': hfq.Close / raw.Close})
    for column in ('Open', 'High', 'Low', 'Close'):
        assert ((raw[column] * factors.AdjFactor - hfq[column]).abs() < 1e-10).all()
    local = intraday_raw.copy()
    local['Date'] = local.Date.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    adjusted = apply_hfq_adjustment(local, factors)
    adjusted = with_scheduled_hfq_availability(adjusted, factor_source='fund_adj', period='30m')
    adjusted['Date'] = adjusted.Date.dt.tz_localize('Asia/Shanghai').dt.tz_convert('UTC')
    adjusted['AvailableDate'] = adjusted.AvailableDate.dt.tz_localize('Asia/Shanghai').dt.tz_convert('UTC')
    constraints = _frame(products['constraints'])[['Date', 'AvailableDate', 'Tradable', 'PriceLimitLower', 'PriceLimitUpper']]
    days = raw.Date.dt.tz_convert('Asia/Shanghai').dt.date
    scale = dict(zip(days, factors.AdjFactor))
    sessions = sessions_from_metadata(artifact['data']['sessions']['metadata'])
    first = sessions[0].session_date

    # Fetch retained public DFLS assets for overlap validation and S011 tables.
    binding_path = ROOT / 'research/S011/experiments/EX084_20261026/others/S011-v1/equivalence/new_binding.json'
    binding = StrategyInputBinding.from_mapping(json.loads(binding_path.read_bytes()))
    old_context = create_research_context(repo, ResearchBatchRef('S011'),
        providers=ProviderConfig(bindings={}, equity_bindings={}))
    retained = {}
    for name in ('bars', 'market', 'spx'):
        fetched = old_context.data.fetch(binding.plan.requests[name], prepared=binding.prepared)
        if not fetched.ready:
            raise RuntimeError(str(fetched.error))
        retained[name] = fetched
    supplied = retained['bars'].dataframe.copy()
    supplied['Date'] = pd.to_datetime(supplied.Date).dt.tz_localize('Asia/Shanghai').dt.tz_convert('UTC')
    common = adjusted.set_index('Date').loc[supplied.Date]
    difference = (common[['Open', 'High', 'Low', 'Close']].to_numpy() - supplied[['Open', 'High', 'Low', 'Close']].to_numpy())
    assert abs(difference).max() < 1e-10
    provenance.update({'public_binding': binding.to_dict(),
        'assets': {k: {'content_sha256': v.identity.content_sha256, 'rows': len(v.dataframe)} for k, v in retained.items()},
        'hfq_intraday_method': 'DFLS_ADJUSTED: apply_hfq_adjustment with retained daily HFQ/RAW scale; direct overlapping HFQ OHLC verified',
        'hfq_intraday_overlap_max_difference': float(abs(difference).max()),
        'intraday_raw_rows': len(intraday_raw), 'derived_hfq_rows': len(adjusted),
        'dynamic_facts': 'Original published constraints Date/AvailableDate/Tradable/Lower/Upper retained; historical tradability assumption unchanged; no action inference',
        'coverage_start': first.isoformat(), 'coverage_end': END.isoformat(), 'supplier_fetches': 0})
    provenance_hash = sha256(json.dumps(provenance, sort_keys=True, default=str).encode()).hexdigest()

    def fetch(request):
        p, query = request.parameters, request.parameters.query
        if p.instrument != candidate.instrument or p.source != SOURCE or query.start < first or query.end > END:
            raise ValueError('request exceeds explicitly retained ETF source')
        selected = tuple(s for s in sessions if query.start <= s.session_date <= query.end)
        metadata = equity_metadata(request, selected, availability_basis='RETAINED_SOURCE_PUBLICATION_SCHEDULE_UNVERIFIED')
        metadata.update(retained_provenance_sha256=provenance_hash, publication_time_verified=False,
                        historical_revision_history_verified=False, calendar_source='retained DFLS Tushare trade_cal')
        following = next((s for s in sessions if s.session_date > query.end), None)
        if following is not None:
            metadata['following_session'] = session_record(following)
        if query.product is EquityProduct.SESSIONS:
            return pd.DataFrame({'Date': [s.segments[0].start for s in selected],
                'AvailableDate': [s.segments[0].start for s in selected],
                'SessionDate': [s.session_date.isoformat() for s in selected]}), metadata
        if query.product is EquityProduct.TRADING_FACTS:
            if query.frequency is not BarFrequency.DAILY:
                raise ValueError('retained dynamic facts are daily only')
            frame = constraints.copy()
            if query.adjustment is PriceAdjustment.BACKWARD:
                multipliers = frame.Date.dt.tz_convert('Asia/Shanghai').dt.date.map(scale)
                assert multipliers.notna().all()
                for column in ('PriceLimitLower', 'PriceLimitUpper'):
                    frame[column] *= multipliers
            elif query.adjustment is not PriceAdjustment.NONE:
                raise ValueError('unsupported adjustment')
        elif query.product is EquityProduct.BARS:
            if query.frequency is BarFrequency.DAILY:
                frame = hfq.copy() if query.adjustment is PriceAdjustment.BACKWARD else raw.copy()
            elif query.frequency is BarFrequency.M30:
                frame = adjusted.copy() if query.adjustment is PriceAdjustment.BACKWARD else intraday_raw.copy()
            else:
                raise ValueError('unsupported retained frequency')
            metadata['acquisition_method'] = 'DFLS_ADJUSTED' if query.adjustment is PriceAdjustment.BACKWARD else 'PROVIDER_RAW'
            metadata['price_source_api'] = 'retained Tushare DFLS asset; fund_adj scale and DFLS adjustment routine'
        else:
            raise ValueError('unsupported current product')
        dates = frame.Date.dt.tz_convert('Asia/Shanghai').dt.date
        return frame.loc[(dates >= query.start) & (dates <= query.end)].copy().reset_index(drop=True), metadata

    tables = {binding.plan.requests[name].dataset: name for name in ('market', 'spx')}
    def observation(request):
        name = tables[request.dataset]
        original = binding.plan.requests[name]
        if request.start < original.start or request.end > original.end:
            raise ValueError('table request exceeds retained source')
        frame = retained[name].dataframe.copy()
        stamps = pd.to_datetime(frame.Date)
        return frame.loc[(stamps >= request.start) & (stamps < pd.Timestamp(request.end) + pd.Timedelta(days=1))].copy(), dict(retained[name].identity.metadata)

    table_bindings = {dataset: ProviderBinding('retained-tushare', provenance_hash, observation) for dataset in tables} if strategy_id == 'S011' else {}
    equity_bindings = {ProviderKey(product, MarketId.CN, SOURCE): ProviderBinding(SOURCE.provider, SOURCE.revision, fetch)
                       for product in EquityProduct}
    context = create_research_context(repo, ResearchBatchRef(strategy_id),
        providers=ProviderConfig(bindings=table_bindings, equity_bindings=equity_bindings),
        execution_spec=candidate.definition.execution_spec, resources=ExecutionResources(1, 1, 17))
    return context, EquitySources(SOURCE, SOURCE, SOURCE), provenance
