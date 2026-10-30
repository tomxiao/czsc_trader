"""DEV acceptance: authenticated EX027 accounts against V3 replay, without publication.

Run with the repository virtualenv. Outputs are confined to .tmp; immutable
research evidence is read only. Exact comparison uses the formal account JSON
precision (pandas default 10 decimals), plus explicit bijective ID translation
and UTC timestamp normalization. Explanation text/numbers are never rounded.
"""
# ruff: noqa: E402
import argparse
import cProfile
from dataclasses import asdict
from datetime import date, datetime, timezone
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import pstats
import re
from statistics import median
import sys
from time import perf_counter
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True
SCRATCH = ROOT / '.tmp/equity-replay-benchmark'
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(SCRATCH)

from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct,
                       EquityQuery, InstrumentId, MarketId, PreparedDataRef, ProviderConfig, SourceRef)
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, EquityStrategyCandidate,
    EquityStrategyDefinition, ExecutionResources, PreparedReplay, ResearchExecutionSpec,
    UsEquitySpec, equity_source_hash, run_replay)
from trading_execution_engine.equity import EquityHistoricalExecutor
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvidenceRef, ResearchBatchRef

WORK = ROOT / 'research/S017/experiments/EX027_20261029'
PREP = ROOT / 'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json'
FIXTURE = ROOT / 'tests/support/equity_m005_v3.py'
SPEC = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
    AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
INSTRUMENT = InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE')
SOURCE = SourceRef('futu', 's017-development-gap-known-interruptions-v1-20261028')
PARAMETERS = {
    'C0048': {'exit_mechanism': 'S017-M009', 'max_holding_bars': 65},
    'C0049': {'exit_mechanism': 'S017-M010', 'max_holding_bars': 65},
    'C0050': {'exit_mechanism': 'S017-M011', 'max_holding_bars': 65, 'trailing_atr_multiple': 3.},
}
TABLES = {'decisions': 'decisions', 'orders': 'orders', 'fills': 'fills',
          'corporate_action_entries': 'actions', 'account_points': 'account_points',
          'account_daily': 'account_daily', 'trades': 'trades'}
ID_FIELDS = ('decision_id', 'order_id', 'fill_id', 'cycle_id')
ISO_TIME = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$')
ACTIVE_REPORT = None
ENGINE_PATHS = (
    'packages/strategy_runtime/src/strategy_runtime/equity.py',
    'packages/strategy_runtime/src/strategy_runtime/equity_definition.py',
    'packages/strategy_runtime/src/strategy_runtime/equity_features.py',
    'packages/strategy_runtime/src/strategy_runtime/equity_replay.py',
    'packages/strategy_runtime/src/strategy_runtime/equity_source_runtime.py',
    'packages/trading_execution_engine/src/trading_execution_engine/equity.py',
    'packages/trading_execution_engine/src/trading_execution_engine/fills.py',
)


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def save_profile(profiler, output, key):
    """Persist instrumented diagnostics separately from unprofiled benchmarks."""
    path = output / f'{key}-profile.prof'
    profiler.dump_stats(path)
    stream = io.StringIO()
    stream.write('CPROFILE INSTRUMENTED DIAGNOSTIC; NOT A PERFORMANCE BENCHMARK\n')
    stats = pstats.Stats(profiler, stream=stream)
    for order in ('tottime', 'cumulative'):
        stream.write('\nTOP 30 BY ' + order.upper() + '\n')
        stats.sort_stats(order).print_stats(30)
    (output / f'{key}-profile.txt').write_text(stream.getvalue(), encoding='utf-8')
    rows = []
    for (file, line, function), (primitive, total, own, cumulative, _) in stats.stats.items():
        rows.append({'file': file, 'line': line, 'function': function,
            'primitive_calls': primitive, 'total_calls': total, 'own_seconds': own,
            'cumulative_seconds': cumulative})
    save(output / f'{key}-profile.json', {'measurement': 'CPROFILE_INSTRUMENTED_NOT_BENCHMARK',
        'profile_total_seconds': stats.total_tt,
        'top30_own': sorted(rows, key=lambda row: row['own_seconds'], reverse=True)[:30],
        'top30_cumulative': sorted(rows, key=lambda row: row['cumulative_seconds'], reverse=True)[:30],
        'all_functions': rows})


def authenticate(value):
    ref = EvidenceRef.from_dict(value)
    path = ref.resolve(ROOT)
    if digest(path) != ref.sha256:
        raise ValueError('Evidence content differs from authenticated reference')
    return path


def validate_runtime_statistics(statistics, source_size):
    """This single-file fixture must load once per account without step checks."""
    expected = {'source_checks': 0, 'source_bytes_read': source_size, 'module_loads': 1}
    for key, value in expected.items():
        actual = statistics.get(key)
        if type(actual) is not int or actual != value:
            raise ValueError(f'Account loading contract differs for {key}: {actual!r} != {value}')


def normalized(value, maps=None, field=None):
    if isinstance(value, dict):
        return {key: normalized(item, maps, key) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized(item, maps, field) for item in value]
    if maps is not None and field in ID_FIELDS and value is not None:
        return maps[field][value]
    if isinstance(value, str) and ISO_TIME.fullmatch(value):
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat()
    return value


def differences(left, right, limit=20):
    """Count every differing leaf, retaining a bounded diagnostic sample."""
    samples, counts = [], {}

    def add(path, a, b):
        leaf = path.rsplit('.', 1)[-1]
        counts[leaf] = counts.get(leaf, 0) + 1
        if len(samples) < limit:
            samples.append({'path': path, 'reference': a, 'actual': b})

    def walk(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                if key not in a or key not in b:
                    add(path + '.' + key, a.get(key, '<ABSENT>'), b.get(key, '<ABSENT>'))
                else:
                    walk(a[key], b[key], path + '.' + key)
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                add(path + '.length', len(a), len(b))
            for index, (aa, bb) in enumerate(zip(a, b)):
                walk(aa, bb, f'{path}[{index}]')
        elif a != b or (isinstance(a, bool) != isinstance(b, bool)):
            add(path, a, b)

    walk(left, right, '')
    return {'count': sum(counts.values()), 'by_field': counts, 'samples': samples}


def identity_maps(reference, actual):
    """Align by causal point/order keys, then validate all foreign-key edges."""
    maps = {key: {} for key in ID_FIELDS}

    def bind(table, field, keys):
        before, after = reference[table], actual[table]
        old_ids = set()
        if len(before) != len(after):
            raise ValueError(f'{table} row count differs before identity alignment')
        for old, new in zip(before, after):
            old_keys = normalized({key: old[key] for key in keys})
            new_keys = normalized({key: new[key] for key in keys}, maps)
            if old_keys != new_keys:
                raise ValueError(f'{table} causal matching keys differ: {old_keys} != {new_keys}')
            if new[field] in maps[field] or old[field] in old_ids:
                raise ValueError(f'{field} mapping must be one-to-one')
            maps[field][new[field]] = old[field]
            old_ids.add(old[field])

    bind('decisions', 'decision_id', ('observed_through', 'decision_at', 'execution_start',
                                    'execution_end', 'portfolio_revision'))
    bind('orders', 'order_id', ('decision_id', 'valid_start', 'valid_end', 'side'))
    bind('fills', 'fill_id', ('order_id', 'interval_start', 'interval_end', 'side'))
    old_buys = [row for row in reference['fills'] if row['side'] == 'BUY']
    new_buys = [row for row in actual['fills'] if row['side'] == 'BUY']
    for old, new in zip(old_buys, new_buys):
        if maps['fill_id'][new['fill_id']] != old['fill_id']:
            raise ValueError('Cycle roots must follow matching actual BUY fills')
        if new['cycle_id'] in maps['cycle_id'] or old['cycle_id'] in maps['cycle_id'].values():
            raise ValueError('Actual BUY cycle roots must be unique')
        maps['cycle_id'][new['cycle_id']] = old['cycle_id']
    for field, mapping in maps.items():
        old_domain, new_domain = set(mapping.values()), set(mapping)
        for tables, domain in ((reference, old_domain), (actual, new_domain)):
            for rows in tables.values():
                for row in rows:
                    if row.get(field) is not None and row[field] not in domain:
                        raise ValueError(f'Orphan {field} outside the authenticated identity graph')
    return maps


def load_inputs():
    pre = read(WORK / 'others/pre_run_evidence.json')
    if (digest(authenticate(pre['strategy-source'])) != digest(WORK / 'src/strategy.py')
            or digest(authenticate(pre['prepared-reference'])) != digest(PREP)
            or digest(PREP) != '56f66ca596fc659c8b88b044b455447314a53d4dbcb17d45441eb5733cd33802'):
        raise ValueError('Historical source or prepared reference changed')
    saved = read(PREP)
    value = saved['reference']
    if value['manifest_sha256'] != 'bdba8f6a3e9475ed62a3295bdcccd6bb2286f5e081ec44b79811c1bcb72dce93':
        raise ValueError('Unapproved prepared manifest')
    prepared = PreparedDataRef(UUID(value['space_id']), UUID(value['preparation_id']), value['manifest_sha256'])
    research = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S017'),
        providers=ProviderConfig(bindings={}), execution_spec=SPEC,
        resources=ExecutionResources(max_workers=1, native_threads_per_worker=1, random_seed=17))
    frames, identities = {}, {}
    for item in saved['items']:
        product = EquityProduct(item['product'])
        request = EquityDataRequest(INSTRUMENT, SOURCE,
            EquityQuery(product, date(2018, 11, 1), date(2025, 12, 31), BarFrequency.M30))
        fetched = research.data.fetch(request, prepared=prepared)
        if not fetched.ready or fetched.identity.content_sha256 != item['sha256']:
            raise ValueError('Certified data unavailable or changed: ' + product.value)
        frames[product.value] = fetched.dataframe.reset_index(drop=True)
        identities[product.value] = fetched.identity.content_sha256
    bars = frames[EquityProduct.BARS.value]
    if (len(frames) != 4 or len(bars) != 23298 or not bars.BarStatus.eq('OBSERVED').all()
            or not bars.AvailableDate.eq(bars.Date).all()
            or bars.Date.max().tz_convert('America/New_York').date() > date(2025, 12, 31)
            or bars.Date.min().tz_convert('America/New_York').date() < date(2018, 11, 1)):
        raise ValueError('The V3 equivalent fixture requires the certified observed 2018-2025 population')
    return frames, {'prepared_reference': value, 'products': identities,
                    'historical_source_sha256': digest(WORK / 'src/strategy.py'),
                    'historical_source_closure_sha256': equity_source_hash(WORK / 'src', ('strategy.py',))}


def main():
    global ACTIVE_REPORT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repetitions', type=int, default=3, choices=(1, 2, 3))
    parser.add_argument('--candidate', choices=tuple(PARAMETERS), help='Limit the DEV check to one reference account')
    parser.add_argument('--profile', action='store_true', help='One instrumented core diagnostic, not a benchmark')
    args = parser.parse_args()
    if args.profile and (args.candidate is None or args.repetitions != 1):
        parser.error('--profile requires --repetitions 1 and one explicit --candidate')
    output = SCRATCH / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:8])
    output.mkdir()
    ACTIVE_REPORT = (output / 'result.json', {'status': 'RUNNING', 'scope': 'DEV benchmark preflight'})
    snapshot = output / 'sources'
    snapshot.mkdir()
    for path in (FIXTURE, Path(__file__), *(ROOT / name for name in ENGINE_PATHS)):
        target = snapshot / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    engine_hashes = {name: digest(snapshot / name) for name in ENGINE_PATHS}
    print('output=' + str(output), flush=True)
    frames, provenance = load_inputs()
    spec = importlib.util.spec_from_file_location('dev_equity_m005_fixture', FIXTURE)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    source_files = (FIXTURE.name,)
    source_hash = equity_source_hash(FIXTURE.parent, source_files)
    graph, schema = fixture.feature_graph(), fixture.state_schema()
    accounts = read(WORK / 'others/accounts.json')
    report = {'status': 'RUNNING', 'scope': 'DEV equivalence; no research experiment or publication',
        'timing_measurement': 'CPROFILE_INSTRUMENTED_NOT_BENCHMARK' if args.profile else 'UNPROFILED_BENCHMARK',
        'fixture_sha256': digest(FIXTURE), 'benchmark_sha256': digest(Path(__file__)),
        'engine_sources': engine_hashes,
        'source_closure_sha256': source_hash, 'sources': provenance, 'candidates': {},
        'account_loading_contract': {'source_checks': 0, 'module_loads': 1,
            'source_bytes_read': FIXTURE.stat().st_size,
            'scope': 'one startup source read and one persistent entrypoint module per account; benchmark file identity checks are separate'},
        'comparison_contract': {'seven_tables': list(TABLES), 'formal_json_double_precision': 10,
            'numeric_tolerance': 0, 'identity_mapping': 'bijection from decision causal points, orders, fills, BUY cycles',
            'time_normalization': 'aware ISO timestamp strings to UTC, including explanation timestamp values'},
        'timing_contract': 'Single process/native thread 1; core includes prepared arrays, TXE initialization, feature evaluation, replay, finish/output DataFrames; excludes DFLS fetch, evidence reading and comparison.'}
    ACTIVE_REPORT = (output / 'result.json', report)
    save(output / 'result.json', report)
    zone = ZoneInfo('America/New_York')
    start, end = datetime(2019, 1, 2, 9, 30, tzinfo=zone), datetime(2025, 12, 31, 16, tzinfo=zone)
    for index, (key, parameters) in enumerate(PARAMETERS.items(), 1):
        if args.candidate is not None and key != args.candidate:
            continue
        evidence = accounts[key]['evidence']
        payload = read(authenticate(evidence))
        if (payload['evaluation_identity'] != accounts[key]['evaluation_identity']
                or payload['request_hash'] != accounts[key]['request_hash']
                or payload['evaluation_identity']['input_sha256'] != provenance['prepared_reference']['manifest_sha256']):
            raise ValueError('Account reference does not match its recorded evaluation identity')
        old_request = payload['request']
        old_definition = old_request['candidate_definition']
        if (old_definition['source_sha256'] != provenance['historical_source_closure_sha256']
                or json.loads(old_definition['parameters_json']) != parameters
                or old_request['specification'] != json.loads(json.dumps(asdict(SPEC)))
                or old_request['fee_rate'] != .001 or old_request['initial_cash'] != 100000.
                or normalized(old_request['window']) != normalized({'start': start.isoformat(), 'end': end.isoformat()})
                or dict(old_request['input_binding']['content_identities']) != {
                    name.split('.')[-1]: value for name, value in provenance['products'].items()}):
            raise ValueError('Reference contract differs from the DEV equivalence fixture')
        reference = {name: payload['runs']['candidate'][name] for name in TABLES.values()}
        definition = EquityStrategyDefinition(INSTRUMENT, SPEC, 261, FIXTURE.stem + ':step', source_files,
            source_hash, json.dumps(parameters), contract_version=3, feedback_mode='CONFIRMED_EXECUTION',
            session_context=False, auxiliary_inputs=(), feature_graph=graph, state_schema=schema)
        # Ephemeral, never registered: the public key contract still requires Sddd/Cdddd.
        candidate = EquityStrategyCandidate('S999', f'C{index:04d}', definition, FIXTURE.parent)
        item = {'historical_candidate': key, 'dev_candidate': candidate.candidate_id,
                'evidence': evidence, 'parameters': parameters, 'runs': []}
        report['candidates'][key] = item
        for repeat in range(args.repetitions):
            profiler = cProfile.Profile() if args.profile else None
            if profiler is not None:
                profiler.enable()
            try:
                timer = perf_counter()
                prepared = PreparedReplay.from_frames(frames[EquityProduct.BARS.value],
                    frames[EquityProduct.CONSTRAINTS.value], graph)
                executor = EquityHistoricalExecutor(specification=SPEC, initial_cash=100000., fee_rate=.001,
                    actions=frames[EquityProduct.ACTIONS.value])
                prep_seconds = perf_counter() - timer
                outcome = run_replay(prepared, candidate, executor, start=start, end=end, fee_rate=.001)
                elapsed = perf_counter() - timer
            finally:
                if profiler is not None:
                    profiler.disable()
                    save_profile(profiler, output, key)
            after_hashes = {name: digest(ROOT / name) for name in ENGINE_PATHS}
            if (after_hashes != engine_hashes or digest(FIXTURE) != report['fixture_sha256']
                    or digest(Path(__file__)) != report['benchmark_sha256']):
                report['status'] = 'INVALID_SOURCE_CHANGED'
                report['engine_sources_after'] = after_hashes
                save(output / 'result.json', report)
                raise ValueError('DEV source changed during the benchmark; rerun after sources stabilize')
            result = outcome.execution_result
            actual = {name: json.loads(getattr(result, field).to_json(
                orient='records', date_format='iso', date_unit='us')) for field, name in TABLES.items()}
            run = {'repeat': repeat + 1, 'core_seconds': elapsed, 'prepare_seconds': prep_seconds,
                   'timing_measurement': report['timing_measurement'],
                   'runtime': asdict(outcome.statistics), 'rows': {name: len(rows) for name, rows in actual.items()},
                   'raw_differences': differences(reference, actual)}
            item['runs'].append(run)
            try:
                validate_runtime_statistics(run['runtime'], report['account_loading_contract']['source_bytes_read'])
                maps = identity_maps(reference, actual)
                aligned = normalized(actual, maps)
                run['aligned_differences'] = differences(normalized(reference), aligned)
                run['identity_counts'] = {field: len(values) for field, values in maps.items()}
                save(output / f'{key}-{repeat + 1}-identity-maps.json', maps)
                run['status'] = 'PASS' if run['aligned_differences']['count'] == 0 else 'FAIL'
            except (KeyError, ValueError) as error:
                run['status'] = 'FAIL'
                run['validation_error'] = str(error)
            save(output / 'result.json', report)
            print(json.dumps({'candidate': key, 'repeat': repeat + 1, 'status': run['status'],
                'core_seconds': elapsed, 'differences': run.get('aligned_differences', {}).get('count'),
                'runtime': run['runtime'],
                'validation_error': run.get('validation_error')}, ensure_ascii=False), flush=True)
            if run['status'] != 'PASS':
                save(output / f'{key}-{repeat + 1}-actual.json', actual)
                report['status'] = 'FAIL'
                save(output / 'result.json', report)
                return 1
        item['median_core_seconds'] = median(run['core_seconds'] for run in item['runs'])
    report['status'] = 'PASS'
    save(output / 'result.json', report)
    print(json.dumps({'status': 'PASS', 'output': str(output),
        'median_core_seconds': {key: item['median_core_seconds'] for key, item in report['candidates'].items()}}), flush=True)
    return 0


if __name__ == '__main__':
    try:
        exit_code = main()
    except BaseException as error:
        if ACTIVE_REPORT is not None:
            report_path, result_report = ACTIVE_REPORT
            if result_report['status'] == 'RUNNING':
                result_report['status'] = 'INTERRUPTED' if isinstance(error, KeyboardInterrupt) else 'FAIL'
            result_report['failure'] = {'type': type(error).__name__, 'message': str(error)}
            save(report_path, result_report)
        raise
    raise SystemExit(exit_code)
