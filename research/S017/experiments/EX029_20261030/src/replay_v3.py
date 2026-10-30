"""Public V3 replay and exact economic comparison with the retained V2 accounts.

This is implementation equivalence of four existing configurations, not a new
research experiment or an additional mechanism/parameter choice. Never starts a
replay on import. Run only after the parent has authorized the CPU slot.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import json
import re
from time import perf_counter

from common import (WORK, INSTRUMENT, SPEC, EXPERIMENT, context, request,
    read, save, digest, authenticate, material, fetch)
from strategy_v3 import feature_graph, state_schema
from strategy_runtime import (EquityStrategyDefinition, EquityStrategyCandidate, equity_source_hash,
    PreparedReplay, StrategyRuntime, run_replay)
from trading_execution_engine.equity import EquityHistoricalExecutor
from czsc_trader.application import publish_evidence_many
from czsc_trader.research_tools import (CheckpointMode, EvaluationEvidenceWrite,
    ExecutionCheckpointRequest, ResearchExecutionSession)
from czsc_trader.research_tools.equity_replay_v3 import materialize_v3

PAIRS = {'C0051': 'C0055', 'C0052': 'C0056', 'C0053': 'C0057', 'C0054': 'C0058'}
TABLES = ('decisions', 'orders', 'fills', 'actions', 'account_points', 'account_daily', 'trades')
ID_FIELDS = ('decision_id', 'order_id', 'fill_id', 'cycle_id')
ISO_TIME = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$')
FACT_FIELDS = ('entry_signal', 'entry_ready', 'entry_mechanism', 'low_background',
    'held', 'holding_bars', 'max_holding_bars', 'exit_trigger', 'actual_entry')


def definitions():
    values = read(WORK/'protocols/configurations.json')
    if set(values) != set(PAIRS):
        raise ValueError('Exactly the four frozen V2 configurations are required')
    source, files = WORK/'src', ('strategy_v3.py',)
    result = {}
    for old, new in PAIRS.items():
        definition = EquityStrategyDefinition(INSTRUMENT, SPEC, 261, 'strategy_v3:step', files,
            equity_source_hash(source, files), json.dumps(values[old]), contract_version=3,
            feedback_mode='CONFIRMED_EXECUTION', session_context=False, auxiliary_inputs=(),
            feature_graph=feature_graph(), state_schema=state_schema())
        result[new] = EquityStrategyCandidate('S017', new, definition, source)
    return result


def normalized(value, maps=None, field=None):
    if isinstance(value, dict):
        # Narrative/feature float representations may differ by implementation.
        # Economic decisions and their signal/state facts are checked separately.
        return {key: normalized(item, maps, key) for key, item in value.items() if key != 'explanation'}
    if isinstance(value, list):
        return [normalized(item, maps, field) for item in value]
    if maps is not None and field in ID_FIELDS and value is not None:
        return maps[field][value]
    if isinstance(value, str) and ISO_TIME.fullmatch(value):
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat()
    return value


def difference(left, right, limit=20):
    samples, count = [], 0

    def walk(a, b, path):
        nonlocal count
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                if key not in a or key not in b:
                    add(path+'.'+key, a.get(key, '<ABSENT>'), b.get(key, '<ABSENT>'))
                else:
                    walk(a[key], b[key], path+'.'+key)
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                add(path+'.length', len(a), len(b))
            for j, (aa, bb) in enumerate(zip(a, b)):
                walk(aa, bb, f'{path}[{j}]')
        elif a != b or (isinstance(a, bool) != isinstance(b, bool)):
            add(path, a, b)

    def add(path, a, b):
        nonlocal count
        count += 1
        if len(samples) < limit:
            samples.append({'path': path, 'reference': a, 'actual': b})
    walk(left, right, '')
    return {'count': count, 'samples': samples}


def identity_maps(reference, actual):
    maps = {key: {} for key in ID_FIELDS}

    def bind(table, field, keys):
        old, new = reference[table], actual[table]
        if len(old) != len(new):
            raise ValueError(table+' row count differs before identity alignment')
        for before, after in zip(old, new, strict=True):
            if normalized({k: before[k] for k in keys}) != normalized({k: after[k] for k in keys}, maps):
                raise ValueError(table+' causal identity keys differ')
            if after[field] in maps[field] or before[field] in maps[field].values():
                raise ValueError('Identity alignment is not bijective')
            maps[field][after[field]] = before[field]
    bind('decisions', 'decision_id', ('observed_through', 'decision_at', 'execution_start', 'execution_end', 'portfolio_revision'))
    bind('orders', 'order_id', ('decision_id', 'valid_start', 'valid_end', 'side'))
    bind('fills', 'fill_id', ('order_id', 'interval_start', 'interval_end', 'side'))
    before_buys = [r for r in reference['fills'] if r['side'] == 'BUY']
    after_buys = [r for r in actual['fills'] if r['side'] == 'BUY']
    for before, after in zip(before_buys, after_buys, strict=True):
        if (maps['fill_id'][after['fill_id']] != before['fill_id']
                or after['cycle_id'] in maps['cycle_id'] or before['cycle_id'] in maps['cycle_id'].values()):
            raise ValueError('Cycle identity does not follow an actual matching BUY')
        maps['cycle_id'][after['cycle_id']] = before['cycle_id']
    for field, mapping in maps.items():
        for tables, domain in ((reference, set(mapping.values())), (actual, set(mapping))):
            if any(row.get(field) is not None and row[field] not in domain for rows in tables.values() for row in rows):
                raise ValueError('Orphan '+field+' outside causal identity mapping')
    return maps


def facts(decision):
    explanation = decision['explanation']
    values = {item['key']: item['text'] for item in explanation['basis']}
    return normalized({key: values.get(key) for key in FACT_FIELDS})


def packed(path, value):
    path.write_bytes(gzip.compress(json.dumps(value, allow_nan=False).encode(), mtime=0))


def precheck():
    """Actual two-side synthetic ledgers plus every development signal formula."""
    from accounts_v2 import _fixture
    from account_candidate import candidate as v2_candidate
    from strategy import compute
    started = perf_counter()
    candidates, configurations = definitions(), read(WORK/'protocols/configurations.json')
    bars, constraints, sessions, calendars, actions, start, end = _fixture()
    comparisons = {}
    for old, new in PAIRS.items():
        reference = StrategyRuntime(execution_spec=SPEC).create(v2_candidate(old, configurations[old])).run_window(
            bars, constraints, EquityHistoricalExecutor(specification=SPEC, initial_cash=100000., fee_rate=.001, actions=actions),
            start=start, end=end, fee_rate=.001, sessions=sessions, trading_sessions=calendars)
        prepared = PreparedReplay.from_frames(bars, constraints, feature_graph(), sessions=sessions, trading_sessions=calendars)
        actual = run_replay(prepared, candidates[new],
            EquityHistoricalExecutor(specification=SPEC, initial_cash=100000., fee_rate=.001, actions=actions),
            start=start, end=end, fee_rate=.001).execution_result
        keys = ('decisions', 'orders', 'fills', 'corporate_action_entries', 'account_points', 'account_daily', 'trades')
        before, after = [{table: json.loads(getattr(run, name).to_json(orient='records', date_format='iso', date_unit='us'))
                        for table, name in zip(TABLES, keys, strict=True)} for run in (reference, actual)]
        packed(WORK/f'others/v3_equivalence_{old}_v2.json.gz', before)
        packed(WORK/f'others/v3_equivalence_{old}_v3.json.gz', after)
        maps = identity_maps(before, after)
        differences = {table: difference(normalized(before[table]), normalized(after[table], maps)) for table in TABLES}
        facts_diff = difference([facts(r) for r in before['decisions']], [facts(r) for r in after['decisions']])
        comparisons[old+'__'+new] = {'tables': differences, 'signal_and_state_facts': facts_diff,
            'status': 'PASS' if not any(v['count'] for v in [*differences.values(), facts_diff]) else 'FAIL',
            'raw_v2_sha256': digest(WORK/f'others/v3_equivalence_{old}_v2.json.gz'),
            'raw_v3_sha256': digest(WORK/f'others/v3_equivalence_{old}_v3.json.gz')}
        print('SYNTHETIC_PAIR', old, comparisons[old+'__'+new]['status'], flush=True)
    real, _, identities = fetch()
    flags, _, _ = compute(real)
    events = json.loads(gzip.decompress((WORK/'others/events.json.gz').read_bytes()))
    population = [r for r in events if r['n'] == 6]
    closes, highs = real.Close.to_numpy(), real.High.to_numpy()
    misses, mean_differences = [], 0
    from statistics import fmean
    for row in population:
        i = row['i']
        average = sum(float(v) for v in closes[i-65:i])/65
        legacy_mean = fmean(float(v) for v in closes[i-65:i])
        mean_differences += int(average != legacy_mean)
        background = float(closes[i-1]) < average
        breakout = float(closes[i]) > max(float(v) for v in highs[i-6:i])
        computed = {'S017-M012': breakout, 'S017-M017': background and breakout, 'S017-M018': background}
        for name, signal in computed.items():
            if signal != bool(flags.loc[i, name]) or signal != (name in row['signals']):
                misses.append({'i': i, 'mechanism': name})
    result = {'status': 'PASS' if not misses and all(v['status'] == 'PASS' for v in comparisons.values()) else 'FAIL',
        'scope': 'FULL_SYNTHETIC_LEDGER_AND_FULL_DEVELOPMENT_SIGNALS', 'synthetic_pairs': comparisons,
        'development_inputs': identities, 'development_points': len(population),
        'development_signal_comparisons': 3*len(population), 'signal_mismatches': misses,
        'mean_bit_difference_points': mean_differences,
        'numeric_policy': 'V3 Mean65 Python chronological sum/65 versus frozen V2 statistics.fmean; all decisions compared, no assumed bit identity',
        'not_claimed': 'No real seven-year V2/V3 dual-ledger equality; real V3 accounts require public certification.',
        'sources': {p.name: digest(p) for p in (WORK/'src/strategy.py', WORK/'src/strategy_v3.py', WORK/'src/replay_v3.py')},
        'seconds': perf_counter()-started}
    save(WORK/'others/v3_precheck.json', result)
    if result['status'] != 'PASS':
        raise ValueError('V3 equivalence precheck failed; retain both synthetic raw ledgers')
    print('V3_PRECHECK_PASS', flush=True)
    return result


def compare_development_signals():
    events = json.loads(gzip.decompress((WORK/'others/events.json.gz').read_bytes()))
    expected = {normalized(r['signal_at']): r for r in events if r['n'] == 6}
    records, comparisons = read(WORK/'others/accounts_v3.json'), {}
    configurations = read(WORK/'protocols/configurations.json')
    for old, new in PAIRS.items():
        payload = detached(records[new])
        decisions = payload['runs']['candidate']['decisions']
        mechanism = configurations[old]['entry_mechanism']
        mismatches = []
        for row in decisions:
            stamp = normalized(row['observed_through'])
            signal = facts(row)['entry_signal'] == 'True'
            if stamp not in expected or signal != (mechanism in expected[stamp]['signals']):
                mismatches.append(stamp)
        comparisons[new] = {'decisions': len(decisions), 'expected_points': len(expected), 'mismatches': mismatches,
            'evidence': records[new]['evidence']}
        if len(decisions) != len(expected) or mismatches:
            raise ValueError('Published V3 full development signals differ: '+new)
    result = {'status': 'PASS', 'scope': 'PUBLISHED_REAL_V3_SIGNALS_VS_AUTHENTICATED_EVENT_FACTS',
        'accounts': comparisons, 'sources': {p.name: digest(p) for p in (WORK/'src/strategy_v3.py', WORK/'src/replay_v3.py')}}
    save(WORK/'others/v3_development_signal_validation.json', result)
    return result


def detached(record):
    path = authenticate(record['evidence'])
    payload = read(path)
    if payload['schema'] != 'equity-research/v3':
        raise ValueError('Expected an actual public V3 evaluation')
    # The documented resolver receives kind/hash references. materialize_v3
    # authenticates the returned bytes and all owner/input links itself.
    return materialize_v3(payload, lambda ref: (path.parent/(ref['sha256']+'.json')).read_bytes()).payload


def compare():
    started = perf_counter()
    old_rows, new_rows = read(WORK/'others/accounts.json'), read(WORK/'others/accounts_v3.json')
    if set(old_rows) != set(PAIRS) or set(new_rows) != set(PAIRS.values()):
        raise ValueError('Both complete four-account published sides are required')
    pairs = {}
    for old, new in PAIRS.items():
        left, right = read(authenticate(old_rows[old]['evidence'])), detached(new_rows[new])
        if left['schema'] != 'equity-research/v2':
            raise ValueError('The reference side must remain V2')
        contract = ('instrument', 'window', 'history_start', 'initial_cash', 'fee_rate', 'specification',
            'sources', 'drawdown_basis', 'concentration_basis', 'frequency_window_days', 'measurement_tier')
        if any(normalized(left['request'][key]) != normalized(right['request'][key]) for key in contract):
            raise ValueError('Implementation equivalence requires unchanged economic inputs')
        if json.loads(left['request']['candidate_definition']['parameters_json']) != json.loads(right['request']['candidate_definition']['parameters_json']):
            raise ValueError('The V3 counterpart changes frozen mechanism parameters')
        result = {'v2_evidence': old_rows[old]['evidence'], 'v3_evidence': new_rows[new]['evidence'], 'runs': {}}
        for run_name in ('candidate', 'buy_hold'):
            before, after = left['runs'][run_name], right['runs'][run_name]
            a, b = ({table: run[table] for table in TABLES} for run in (before, after))
            maps = identity_maps(a, b)
            table_diff = {table: difference(normalized(a[table]), normalized(b[table], maps)) for table in TABLES}
            fact_diff = difference([facts(row) for row in a['decisions']], [facts(row) for row in b['decisions']])
            metric_diff = difference(before['metrics'], after['metrics'])
            result['runs'][run_name] = {'tables': table_diff, 'signal_and_cycle_facts': fact_diff,
                'metrics': metric_diff, 'identity_map_counts': {k: len(v) for k, v in maps.items()},
                'rows': {table: len(rows) for table, rows in a.items()},
                'equal': not any(d['count'] for d in [*table_diff.values(), fact_diff, metric_diff])}
        result['status'] = 'PASS' if all(v['equal'] for v in result['runs'].values()) else 'FAIL'
        pairs[old+'__'+new] = result
        print('PAIR_COMPARED', old, new, result['status'], flush=True)
    report = {'status': 'PASS' if all(v['status'] == 'PASS' for v in pairs.values()) else 'FAIL',
        'scope': 'FOUR_FIXED_CONFIGURATIONS_V2_V3_IMPLEMENTATION_EQUIVALENCE',
        'comparison_mode': {'numeric_tolerance': 0, 'economic_tables': list(TABLES),
            'identity_alignment': 'bijective causal decision/order/fill/actual BUY cycle mapping',
            'times': 'UTC normalization of timezone-aware ISO spellings',
            'explanation': 'Narrative and numeric feature text excluded; all entry/held/timed-exit state facts compared separately',
            'signal_fact_fields': list(FACT_FIELDS)}, 'pairs': pairs,
        'sources': {p.name: digest(p) for p in (WORK/'src/strategy_v3.py', WORK/'src/replay_v3.py')},
        'seconds': perf_counter()-started}
    save(WORK/'others/v3_equivalence.json', report)
    if report['status'] != 'PASS':
        raise ValueError('Full economic/state equivalence failed; retain both actual sides')
    return report


def run(mode='CREATE'):
    started = perf_counter()
    checked = read(WORK/'others/v3_precheck.json')
    if checked['status'] != 'PASS' or any(digest(WORK/'src'/name) != value for name, value in checked['sources'].items()):
        raise ValueError('Source-bound synthetic-ledger and full-development-signal precheck required')
    candidates, research = definitions(), context(2)
    mode = CheckpointMode(mode)
    frozen = WORK/'others/pre_v3_equivalence_evidence.json'
    files = (WORK/'src/strategy_v3.py', WORK/'src/replay_v3.py', WORK/'protocols/configurations.json',
             WORK/'others/v3_precheck.json')
    if frozen.exists():
        if mode is not CheckpointMode.RESUME:
            raise ValueError('Existing V3 attempt requires explicit RESUME')
        for name, ref in read(frozen).items():
            if digest(WORK/name) != digest(authenticate(ref)):
                raise ValueError('V3 pre-run identity differs')
    else:
        if mode is not CheckpointMode.CREATE:
            raise ValueError('No V3 attempt to resume')
        save(frozen, {str(p.relative_to(WORK)).replace('\\', '/'): material(research, 'v3-source-'+str(j), p).to_dict()
                      for j, p in enumerate(files)})
    save(WORK/'others/definitions_v3.json', {key: c.definition.to_dict() for key, c in candidates.items()})

    def progress(event):
        print(json.dumps(asdict(event), default=str), flush=True)
    with ResearchExecutionSession(research, experiment=EXPERIMENT,
            checkpoint=ExecutionCheckpointRequest(EXPERIMENT.experiment_id+'-v3-equivalence', mode), on_progress=progress) as execution:
        prepared = tuple(research.evaluation.prepare(request(c), execution=execution) for c in candidates.values())
        outcomes = research.evaluation.evaluate_many(prepared, execution=execution)
        statuses = [{'candidate': req.candidate.candidate_id, 'status': outcome.status.value,
            'error': None if outcome.error is None else asdict(outcome.error)}
            for req, outcome in zip(prepared, outcomes, strict=True)]
        save(WORK/'others/execution_status_v3.json', statuses)
        if any(item.status.value != 'SUCCEEDED' for item in outcomes):
            raise ValueError('V3 account failure; inspect retained statuses')
        views = [materialize_v3(item.result).payload for item in outcomes]
        writes = tuple(EvaluationEvidenceWrite(EXPERIMENT, 'v3-equivalent-'+req.candidate.candidate_id, req, item.result)
                       for req, item in zip(prepared, outcomes, strict=True))
        publications = publish_evidence_many(research, writes, execution=execution)
        save(WORK/'others/publication_status_v3.json', [asdict(item) for item in publications])
        save(WORK/'others/execution_stats_v3.json', {'session': asdict(execution.stats),
            'equity': asdict(execution.equity_statistics), 'wall_seconds': perf_counter()-started})
        if any(item.status.value != 'PUBLISHED' for item in publications):
            raise ValueError('V3 evidence publication failed')
        manifest = {}
        for req, item, pub, view in zip(prepared, outcomes, publications, views, strict=True):
            manifest[req.candidate.candidate_id] = {'evidence': pub.reference.to_dict(),
                'evaluation_identity': view['evaluation_identity'], 'evaluation_id': view['evaluation_id'],
                'request_hash': item.result.request_hash, 'execution_status': item.status.value,
                'publication_status': pub.status.value, 'candidate': view['runs']['candidate']['metrics'],
                'buy_hold': view['runs']['buy_hold']['metrics']}
        save(WORK/'others/accounts_v3.json', manifest)
    print('V3_ACCOUNTS_PUBLISHED', sorted(candidates), flush=True)
    return compare_development_signals()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('precheck', 'run', 'compare', 'signals'))
    parser.add_argument('--mode', choices=('CREATE', 'RESUME'), default='CREATE')
    args = parser.parse_args()
    if args.action == 'run':
        run(args.mode)
    elif args.action == 'precheck':
        precheck()
    elif args.action == 'signals':
        compare_development_signals()
    else:
        compare()
