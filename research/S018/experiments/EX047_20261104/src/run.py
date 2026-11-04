from dataclasses import asdict
from datetime import date, datetime
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import sys
import types
from uuid import UUID
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, ExperimentRequest, create_experiment,
    create_research_context, publish_evidence, publish_evidence_many)
from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct, EquityQuery,
    InstrumentId, MarketId, PreparedDataRef, PreparePolicy, ProviderBinding, ProviderConfig,
    ProviderKey, PriceAdjustment, SourceRef, TimeInterval, futu_equity_bindings)
from strategy_runtime import ExecutionResources, EquityAuxiliaryInput
from strategy_runtime.equity_definition import (EquityStrategyCandidate, EquityStrategyDefinition,
    equity_source_hash, execution_spec_from_dict)
from strategy_runtime.identity import ImplementationDependency
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import StrategyStateSchema, StateField, StateValueType
from strategy_runtime.replay_contracts import StrategyComputation
from czsc_trader.research_tools.equity_replay import materialize_equity

ROOT = Path.cwd()
FAMILY = ROOT / 'research/S018'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str)+'\n', encoding='utf-8')


def reference(value):
    return PreparedDataRef(UUID(value['space_id']), UUID(value['preparation_id']), value['manifest_sha256'])


def open_quotes():
    name = 'futu.common.ft_logger'
    path = ROOT/'.venv/Lib/site-packages/futu/common/ft_logger.py'
    code = path.read_text(encoding='utf-8')
    marker = '__LogPathName__ = "com.futunn.FutuOpenD/Log"'
    assert code.count(marker) == 1
    module = types.ModuleType(name)
    module.__file__, module.__package__ = str(path), 'futu.common'
    sys.modules[name] = module
    exec(compile(code.replace(marker, '__LogPathName__ = '+repr(str(ROOT/'.tmp/s018-futu-logs'))), str(path), 'exec'), module.__dict__)
    import futu as ft
    ft.SysConfig.enable_console_log(False)
    ft.SysConfig.set_all_thread_daemon(True)
    quote = ft.OpenQuoteContext(host='127.0.0.1', port=11111, is_async_connect=True)
    quote.set_sync_query_connect_timeout(15)
    return quote


def metrics(run):
    m = run['metrics']
    counts = m['rolling_60_closed_cycle_counts']
    daily = run['account_daily']
    values = {row['session']: row['equity'] for row in daily}
    prior, years = 100000., {}
    for year in (2023, 2024, 2025, 2026):
        group = [row for row in daily if row['session'].startswith(str(year))]
        years[str(year)] = group[-1]['equity']/prior-1
        prior = group[-1]['equity']
    return dict(annual=m['annualized_return'], dd=m['bar_max_drawdown'],
        calmar=m['annualized_return']/m['bar_max_drawdown'] if m['bar_max_drawdown'] else None,
        closed=m['closed_cycles'], median=m['rolling_60_closed_cycle_median'],
        coverage=sum(n >= 3 for n in counts)/len(counts), year_returns=years,
        october_return=values['2026-10-15']/values['2026-10-01']-1,
        invested_days=sum(row['quantity'] > 0 for row in daily))


def materialized(ref):
    path = ref.resolve(ROOT)
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256
    return materialize_equity(raw, lambda item: (path.parent/(item['sha256']+'.json')).read_bytes()).payload


def main():
    protocol = read(Path(sys.argv[1]))
    number = protocol['number']
    assert 45 <= number <= 63
    exp = d.ExperimentRef('S018', f'EX{number:03d}_20261104')
    work = exp.resolve(ROOT)
    repo = RepositoryContext.discover(ROOT)
    baseline_record = read(FAMILY/'experiments/EX025_20261104/others/results.json')['accounts']['C6300']
    spec = execution_spec_from_dict(baseline_record['definition']['execution_spec'])
    offline = create_research_context(repo, d.ResearchBatchRef('S018'),
        providers=ProviderConfig(bindings={}, equity_bindings={}), execution_spec=spec, resources=ExecutionResources(4, 1, 17))
    if not work.exists():
        assert create_experiment(offline, ExperimentRequest('MU sector mechanism', protocol['question'], date(2026, 11, 4))) == exp
    assert not (work/'report_ref.json').exists()
    src, out = work/'src', work/'others'
    out.mkdir(exist_ok=True)
    strategy_bytes = (ROOT/protocol['strategy_source']).read_bytes()
    (src/'strategy.py').write_bytes(strategy_bytes)
    (src/'run.py').write_bytes(Path(__file__).read_bytes())
    protocol['strategy_source'] = (src/'strategy.py').relative_to(ROOT).as_posix()
    protocol['source_sha256'] = equity_source_hash(src, ('strategy.py',))
    save(out/'protocol.json', protocol)
    refs = [publish_evidence(offline, d.MaterialEvidenceWrite(exp, 'protocol', (out/'protocol.json').read_bytes(), 'application/json', 'json')),
            d.EvidenceRef.from_dict(baseline_record['account_ref'])]
    instrument = InstrumentId(MarketId.US, AssetClass.STOCK, 'MU')
    old_ref = reference(read(FAMILY/'experiments/EX001_20261104/others/daily_preparation.json')['reference'])
    old_source = SourceRef('futu', 's018-mu-daily-20261104')
    sources = d.EquitySources(old_source, old_source, SourceRef('s018-mu-actions', 'futu-spglobal-crosscheck-v1'),
        SourceRef('s018-mu-rules', 'daily-research-assumptions-v1'))
    first, last = date(2022, 1, 3), date(2026, 10, 30)
    raw_results = {}
    for product in EquityProduct:
        request = EquityDataRequest(instrument, getattr(sources, product.name.lower()), EquityQuery(product, first, last, BarFrequency.DAILY))
        result = offline.data.fetch(request, prepared=old_ref)
        assert result.ready, result.error
        raw_results[request.parameters] = result
    def frozen_raw(request):
        result = raw_results[request.parameters]
        return result.dataframe, dict(result.identity.metadata)
    bindings = {p.provider_key: ProviderBinding(p.source.provider, p.source.revision, frozen_raw) for p in raw_results}
    hfq_source = SourceRef('futu', 's018-mu-soxx-hfq-research-20261104-v1')
    quote = open_quotes()
    try:
        bindings.update(futu_equity_bindings(source=hfq_source, quote_context=quote, maximum_pages=3))
        context = create_research_context(repo, d.ResearchBatchRef('S018'),
            providers=ProviderConfig(bindings={}, equity_bindings=bindings), execution_spec=spec, resources=ExecutionResources(4, 1, 17))
        auxiliary = tuple(EquityAuxiliaryInput(name, InstrumentId(MarketId.US, asset, symbol), hfq_source,
            BarFrequency.DAILY, 63, 86400*7, 'HFQ') for name, asset, symbol in
            (('mu_hfq', AssetClass.STOCK, 'MU'), ('soxx_hfq', AssetClass.ETF, 'SOXX')))
        observation_requests = tuple(r for item in auxiliary for r in item.requests(first, last))
        ready = context.data.prepare(observation_requests, policy=PreparePolicy.REUSE)
        save(out/'data_preparation.json', {'status': ready.status.value,
            'reference': asdict(ready.reference) if ready.ready else None,
            'items': [{'product': x.request.parameters.query.product.value, 'symbol': x.request.parameters.instrument.symbol,
                'status': x.status.value, 'error': str(x.error) if x.error else None,
                'content_sha256': x.identity.content_sha256 if x.identity else None} for x in ready.items]})
        assert ready.ready, [x.error for x in ready.items]
        checks = {}
        for item in auxiliary:
            result = context.data.fetch(item.requests(first, last)[0], prepared=ready.reference)
            frame = result.dataframe
            prior = pd.read_json(FAMILY/f'experiments/EX044_20261104/others/analysis_{item.instrument.symbol}_hfq.json')
            assert frame.Date.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d').tolist() == prior.time_key.str[:10].tolist()
            delta = np.max(np.abs(frame[['Open', 'High', 'Low', 'Close']].to_numpy()-prior[['open', 'high', 'low', 'close']].to_numpy()))
            assert delta < 1e-8, delta
            checks[item.instrument.symbol] = {'rows': len(frame), 'old_sdk_max_difference': float(delta), 'metadata': dict(result.identity.metadata)}
        save(out/'data_checks.json', checks)
        print('HFQ_READY', {k:(v['rows'],v['old_sdk_max_difference']) for k,v in checks.items()}, flush=True)
        zone = ZoneInfo('America/New_York')
        window = TimeInterval(datetime(2023,1,3,9,30,tzinfo=zone), datetime(2026,10,30,16,tzinfo=zone))
        schema = StrategyStateSchema(cycle_fields=tuple(StateField(name, StateValueType.FLOAT)
            for name in protocol.get('state_fields', ['anchor'])))
        candidates, requests = [], []
        for index, params in enumerate(protocol['configurations']):
            definition = EquityStrategyDefinition(instrument, spec, 63, 'strategy:step', ('strategy.py',),
                equity_source_hash(src, ('strategy.py',)), parameters_json=json.dumps(params),
                dependencies=tuple(ImplementationDependency(name, version(name)) for name in ('numpy', 'pandas')),
                contract_version=4, computation=StrategyComputation.STATEFUL_STEP,
                feature_graph=FeatureGraph((),()), state_schema=schema, auxiliary_inputs=auxiliary)
            candidate = EquityStrategyCandidate('S018', f'C{7500+(number-45)*100+index}', definition, src)
            candidate.verify()
            candidates.append(candidate)
            requests.append(d.EquityEvaluationRequest(exp, candidate, window, first, sources, 100000., .001,
                benchmark=d.EvaluationBenchmark(d.EquityBuyHold(spec)), window_id='MU_DEVELOPMENT',
                drawdown_basis='BAR_CLOSE', concentration_basis='MAX_SINGLE'))
        accounts = {}
        with d.ResearchExecutionSession(context, experiment=exp,
                checkpoint=d.ExecutionCheckpointRequest(f'ex{number}-sector-v1')) as execution:
            handles = tuple(context.evaluation.prepare(request, execution=execution) for request in requests)
            outcomes = context.evaluation.evaluate_many(handles, execution=execution)
            save(out/'execution_status.json', [{'status': x.status.value, 'error': str(x.error) if x.error else None} for x in outcomes])
            assert all(x.status.value == 'SUCCEEDED' for x in outcomes), [str(x.error) for x in outcomes]
            receipts = publish_evidence_many(context, tuple(d.EvaluationEvidenceWrite(exp, candidate.candidate_id, handle, outcome.result)
                for candidate, handle, outcome in zip(candidates, handles, outcomes, strict=True)), execution=execution)
            for candidate, outcome, receipt in zip(candidates, outcomes, receipts, strict=True):
                assert receipt.status.value == 'PUBLISHED', receipt.error
                refs.append(receipt.reference)
                payload = materialize_equity(outcome.result).payload
                run = payload['runs']['candidate']
                x, y = metrics(run), metrics(payload['runs']['buy_hold'])
                assert all(row['observed_through'] < row['execution_start'] for row in run['decisions'])
                gates = dict(calmar=x['calmar'] is not None and x['calmar'] >= 1.5*y['calmar'],
                    dd_absolute=x['dd'] <= .25, dd_relative=x['dd'] <= .8*y['dd'], median=x['median'] >= 6, coverage=x['coverage'] >= .9)
                accounts[candidate.candidate_id] = dict(config=json.loads(candidate.definition.parameters_json),
                    candidate=x, gates=gates, definition=candidate.definition.to_dict(), account_ref=receipt.reference.to_dict())
                if accounts[candidate.candidate_id]['config'].get('entry') == 'raw_control':
                    previous = materialized(refs[1])['runs']['candidate']
                    keys = ('side','quantity','price','fee','interval_start','interval_end')
                    assert [{k:r[k] for k in keys if k in r} for r in run['fills']] == [{k:r[k] for k in keys if k in r} for r in previous['fills']]
                    economic = lambda rows: [{k:v for k,v in row.items() if not k.endswith('_id')} for row in rows]
                    assert economic(run['account_daily']) == economic(previous['account_daily'])
                    save(out/'control_check.json', {'C6300_fills_and_daily_account': 'EXACT_MATCH', 'new': candidate.candidate_id})
                print(candidate.candidate_id, accounts[candidate.candidate_id]['config'], x, gates, flush=True)
            workload = asdict(execution.equity_statistics)
        save(out/'results.json', {'accounts':accounts, 'benchmark':y, 'workload':workload})
        for name in ('results', 'data_preparation', 'data_checks', 'execution_status', 'control_check'):
            path = out/(name+'.json')
            if path.exists():
                refs.append(publish_evidence(context, d.MaterialEvidenceWrite(exp, name, path.read_bytes(), 'application/json', 'json')))
        save(out/'evidence_refs.json', [r.to_dict() for r in refs])
        print('COMPLETED', exp.experiment_id, len(accounts), flush=True)
    finally:
        quote.close()


if __name__ == '__main__':
    main()
