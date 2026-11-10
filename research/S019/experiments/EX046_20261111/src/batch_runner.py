"""Explicit fixed-design S019 accounts using public TDR execution and recovery."""
import argparse
import ast
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sys
from time import perf_counter
from zoneinfo import ZoneInfo

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'research/RSCH_AGENT.md').is_file())
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'research/S019/experiments/EX013_20261110/src'))
from runner import metrics, read_account  # noqa: E402
from data_window import replay_context, HISTORY_START, SOURCE  # noqa: E402
from czsc_trader import research_tools as d  # noqa: E402
from czsc_trader.application import RepositoryContext, load_candidate, publish_evidence  # noqa: E402
from czsc_trader.research_tools.equity_replay import materialize_equity  # noqa: E402
from czsc_trader.research_tools.evaluation_access import EvaluationAccess  # noqa: E402
from dataflows import TimeInterval  # noqa: E402
from strategy_manager import CandidateKey  # noqa: E402
from strategy_runtime import (ExecutionResources, EquityStrategyCandidate, equity_source_hash,  # noqa: E402
    StrategyStateSchema, StateRecord)

RESOURCES = {'workers': 12, 'native_threads': 1, 'batch_size': 12, 'random_seed': 19}


@dataclass(frozen=True)
class TrialSpec:
    label: str
    parameters: dict
    control_account: str | None = None

    @classmethod
    def parse(cls, row):
        assert isinstance(row, dict) and set(row) <= {'label', 'parameters', 'control_account'}
        assert isinstance(row['label'], str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,79}', row['label'])
        assert isinstance(row['parameters'], dict) and row['parameters']
        control = row.get('control_account')
        if control is not None:
            assert isinstance(control, str) and not Path(control).is_absolute()
            path = (ROOT / control).resolve()
            assert path.is_relative_to(ROOT / 'research/S019') and path.is_file()
        return cls(row['label'], row['parameters'], control)


def read(path):
    return json.loads(path.read_bytes())


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save(path, value, scratch):
    temporary = scratch / (path.name + '.pending')
    temporary.write_bytes(encoded(value))
    os.replace(temporary, path)


def immutable(path, value, scratch):
    if path.exists():
        assert read(path) == json.loads(encoded(value)), f'Immutable evidence changed: {path}'
    else:
        save(path, value, scratch)


def validate_source_state_schema(source, schema):
    """Check literal StateRecord fields/types; dynamic value types need step probes."""
    tree = ast.parse(source.read_text(encoding='utf-8'))
    checks = []
    defaults = {'float': 0.0, 'int': 0, 'bool': False, 'str': '',
                'datetime': datetime(2024, 1, 1, tzinfo=timezone.utc)}
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != 'StateRecord':
            continue
        assert len(call.args) == 1 and not call.keywords and isinstance(call.args[0], ast.Tuple), 'StateRecord requires explicit field pairs for preflight'
        nodes = {}
        for pair in call.args[0].elts:
            assert isinstance(pair, ast.Tuple) and len(pair.elts) == 2
            key = pair.elts[0]
            assert isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value not in nodes
            nodes[key.value] = pair.elts[1]
        matches = []
        for scope, fields in (('account', schema.account_fields), ('cycle', schema.cycle_fields)):
            if set(nodes) != {f.key for f in fields}:
                continue
            sample = StateRecord(tuple((f.key, nodes[f.key].value if isinstance(nodes[f.key], ast.Constant)
                else defaults[f.value_type.value]) for f in fields))
            schema.validate_record(sample, scope=scope)
            matches.append(scope)
        assert matches, f'StateRecord at line {call.lineno} differs from declared state fields: {sorted(nodes)}'
        checks.append({'line': call.lineno, 'fields': sorted(nodes), 'matching_scopes': matches})
    assert checks, 'Expected explicit StateRecord constructors in this strategy family'
    return {'status': 'PASS', 'checks': checks,
        'coverage': 'Exact literal field sets and literal value types; variable value types require synthetic step probes.'}


def candidate_ids_in_record(content):
    found = set(re.findall(r'"(?:candidate_id|id|proposed_candidate_id)"\s*:\s*"(C\d{4})"', content))
    if '"reserved_proposed_candidate_ids"' in content:
        record = json.loads(content)
        if isinstance(record, dict):
            reserved = record.get('reserved_proposed_candidate_ids', [])
            assert isinstance(reserved, list) and all(isinstance(cid, str) and re.fullmatch(r'C\d{4}', cid) for cid in reserved)
            found.update(reserved)
    return found


def preflight(work, scratch):
    assert work.parent == ROOT / 'research/S019/experiments'
    assert re.fullmatch(r'EX\d{3}_\d{8}', work.name)
    for name in ('src/strategy.py', 'protocols/specs.json', 'protocols/plan.md'):
        assert (work / name).is_file(), name
    config = read(work / 'protocols/specs.json')
    required = {'base_candidate', 'candidate_start', 'round_budget', 'parameter_schema', 'specs'}
    assert required <= set(config) <= required | {'state_schema'}
    assert re.fullmatch(r'C\d{4}', config['base_candidate'])
    budget = config['round_budget']
    assert set(budget) == {'allocated_rounds', 'round_index', 'remaining_after_completion', 'total_round'}
    assert all(type(v) is int for v in budget.values())
    assert budget['allocated_rounds'] == 6 and 1 <= budget['round_index'] <= 6
    assert budget['remaining_after_completion'] == 6-budget['round_index']
    assert budget['total_round'] == 4+budget['round_index']
    specs = [TrialSpec.parse(row) for row in config['specs']]
    assert specs and len({r.label for r in specs}) == len(specs)
    assert len({json.dumps(r.parameters, sort_keys=True) for r in specs}) == len(specs), 'Duplicate parameter payloads'
    first = config['candidate_start']
    assert type(first) is int and 622 <= first and first+len(specs) <= 10000
    ids = {f'C{i:04}' for i in range(first, first+len(specs))}
    used, conflicts = set(), []
    for directory in (work.parent, ROOT / 'research/registrations/S019'):
        for path in directory.rglob('*.json'):
            if path.is_relative_to(work):
                continue
            found = candidate_ids_in_record(path.read_text(encoding='utf-8'))
            used.update(found)
            if found & ids:
                conflicts.append(str(path.relative_to(ROOT)))
    for directory in (ROOT / 'research/S019/assets/candidates').iterdir():
        if re.fullmatch(r'C\d{4}', directory.name):
            used.add(directory.name)
    assert not conflicts and not used.intersection(ids), f'Candidate ID collision: {conflicts}'
    assert first == max(int(cid[1:]) for cid in used)+1, 'Start at next unused S019 candidate ID'
    repo = RepositoryContext.discover(ROOT)
    base = load_candidate(repo, CandidateKey('S019', config['base_candidate']))
    state_schema = StrategyStateSchema.from_dict(config['state_schema']) if 'state_schema' in config else base.definition.state_schema
    state_validation = validate_source_state_schema(work / 'src/strategy.py', state_schema)
    immutable(work / 'others/state_schema_preflight.json', state_validation, scratch)
    schema = json.loads(base.definition.parameter_schema_json)
    extension = config['parameter_schema']
    assert isinstance(extension, dict)
    for key, value in extension.items():
        assert isinstance(value, dict) and set(value) == {'type'}
        assert value['type'] in ('boolean', 'string', 'integer', 'number')
        assert key not in schema or schema[key] == value, 'Existing schema changes require explicit new runner contract'
    schema.update(extension)
    source_hash = equity_source_hash(work / 'src', ('strategy.py',))
    candidates, controls = [], {}
    for index, spec in enumerate(specs):
        assert set(spec.parameters) == set(schema), f'Incomplete parameters: {spec.label}'
        for key, value in spec.parameters.items():
            kind = schema[key]['type']
            allowed = {'boolean': (bool,), 'string': (str,), 'integer': (int,), 'number': (float, int)}[kind]
            assert type(value) in allowed, (spec.label, key, value)
            assert not isinstance(value, (float, int)) or math.isfinite(value)
        definition = replace(base.definition, source_files=('strategy.py',), source_sha256=source_hash, state_schema=state_schema,
            parameters_json=json.dumps(spec.parameters, sort_keys=True, separators=(',', ':'), allow_nan=False),
            parameter_schema_json=json.dumps(schema, sort_keys=True, separators=(',', ':')))
        candidate = EquityStrategyCandidate('S019', f'C{first+index:04}', definition, work / 'src')
        candidates.append(candidate)
        if spec.control_account is not None:
            ref, payload = read_account(ROOT / spec.control_account)
            request = payload['request']
            assert request['fee_rate'] == .001 and request['scenario_id'] == 'STANDARD'
            assert request['window_id'] == 'FULL' and request['measurement_tier'] == 'FORMAL'
            controls[spec.label] = {'path': spec.control_account, 'reference': ref.to_dict(),
                'reference_file_sha256': digest(ROOT / spec.control_account)}
    dependency_names = ('runner', 'data_window', 'prepare_data', 'load_data')
    dependencies = {str(Path(sys.modules[name].__file__).resolve().relative_to(ROOT)).replace('\\', '/'):
                    digest(Path(sys.modules[name].__file__)) for name in dependency_names}
    jobs = [{'label': spec.label, 'candidate_id': c.candidate_id, 'parameters': spec.parameters,
             'definition': c.definition.to_dict(), 'content_hash': c.content_identity.content_sha256,
             'control_account': spec.control_account} for spec, c in zip(specs, candidates, strict=True)]
    manifest = {'version': 1, 'experiment': work.name, 'runner_sha256': digest(Path(__file__)),
        'plan_sha256': digest(work / 'protocols/plan.md'), 'specs_sha256': digest(work / 'protocols/specs.json'),
        'source_sha256': source_hash, 'dependencies': dependencies,
        'base_candidate': config['base_candidate'], 'base_content_hash': base.content_identity.content_sha256,
        'resources': RESOURCES, 'fee_rate': .001, 'checkpoint_run_id': work.name.lower()+'-stage2-fixed',
        'expected_strategy_accounts': len(jobs), 'expected_benchmark_identities': 1,
        'candidate_start': first, 'next_candidate_start': first+len(jobs),
        'round_budget': budget, 'budget_mutation': 'NONE; round settlement is owned by experiment close',
        'controls': controls, 'jobs': jobs}
    manifest = json.loads(encoded(manifest))
    immutable(work / 'protocols/run_manifest.json', manifest, scratch)
    for spec, candidate in zip(specs, candidates, strict=True):
        immutable(work / f'others/{spec.label}_definition.json', candidate.definition.to_dict(), scratch)
    print('PREFLIGHT_PASS', work.name, 'jobs', len(jobs), 'ids', first, first+len(jobs)-1,
          'controls', list(controls), 'resources', RESOURCES, flush=True)
    return repo, specs, candidates, manifest


def request_for(exp, candidate):
    zone = ZoneInfo('America/New_York')
    window = TimeInterval(datetime(2022, 1, 3, 9, 30, tzinfo=zone), datetime(2026, 10, 30, 16, tzinfo=zone))
    return d.EquityEvaluationRequest(exp, candidate, window, HISTORY_START, d.EquitySources(SOURCE, SOURCE, SOURCE),
        100000., .001, benchmark=d.EvaluationBenchmark(d.EquityBuyHold(candidate.definition.execution_spec)),
        window_id='FULL', scenario_id='STANDARD', measurement_tier='FORMAL', drawdown_basis='SESSION_CLOSE',
        concentration_basis='MAX_SINGLE')


def check_control(work, spec, scratch):
    _, old = read_account(ROOT / spec.control_account)
    ref, new = read_account(work / f'others/{spec.label}_account.json')
    a, b = old['runs']['candidate'], new['runs']['candidate']
    assert a['metrics'] == b['metrics'], f'Control metrics differ: {spec.label}'
    economic = ('session', 'time', 'cash', 'equity', 'quantity', 'receivable', 'close',
                'bar_status', 'valuation_price_at', 'valuation_stale', 'execution_blocked')
    for key in ('account_daily', 'account_points'):
        assert [tuple(r[k] for k in economic) for r in a[key]] == [tuple(r[k] for k in economic) for r in b[key]], spec.label
    assert [(r['execution_start'], r['target']) for r in a['decisions']] == [(r['execution_start'], r['target']) for r in b['decisions']], spec.label
    columns = ('interval_start', 'side', 'quantity', 'price', 'fees')
    assert [tuple(r[k] for k in columns) for r in a['fills']] == [tuple(r[k] for k in columns) for r in b['fills']], spec.label
    value = {'status': 'PASS', 'control': spec.control_account, 'new_account': ref.to_dict(),
        'daily_and_bar_economic_paths': 'EXACT_EQUAL', 'targets_and_fills': 'EXACT_EQUAL',
        'daily_points': len(a['account_daily']), 'bar_points': len(a['account_points']),
        'decisions': len(a['decisions']), 'fills': len(a['fills'])}
    immutable(work / f'others/{spec.label}_parity.json', value, scratch)


def zero_statistics():
    return {'input_snapshots': 0, 'candidate_runs': 0, 'benchmark_runs': 0, 'account_timings': []}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', required=True, type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    assert not args.recover or args.run
    work = args.experiment.resolve()
    scratch = ROOT / '.tmp' / (work.name.lower()+'-accounts')
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ.update(TEMP=str(scratch), TMP=str(scratch), PYTHONDONTWRITEBYTECODE='1',
        OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    repo, specs, candidates, manifest = preflight(work, scratch)
    if not args.run:
        return
    path = work / 'others/results.json'
    assert args.recover or not path.exists(), 'Existing results require --recover'
    results = read(path) if path.exists() else {'status': 'RUNNING', 'manifest': manifest, 'accounts': {}, 'batches': []}
    assert results['manifest'] == manifest
    assert set(results['accounts']) <= {s.label for s in specs}
    attempts_path = work / 'others/attempts.json'
    attempts = read(attempts_path) if attempts_path.exists() else []
    for old in attempts:
        if old['status'] == 'RUNNING':
            old.update(status='INTERRUPTED_WITH_PARTIAL_STATISTICS', statistics_complete=False)
    attempt = {'attempt': len(attempts)+1, 'started_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'RUNNING', 'statistics_complete': True, 'equity_statistics': zero_statistics(),
        'elapsed_seconds': 0., 'completed_at_start': len(results['accounts']), 'error': None, 'resources': RESOURCES,
        'error_note': 'Explicit recovery; prior unknown task counts remain incomplete.' if args.recover else None}
    attempts.append(attempt)
    save(attempts_path, attempts, scratch)
    results.update(status='RUNNING', error=None)
    started, execution, caught, in_compute = perf_counter(), None, None, False

    def snapshot(status):
        attempt.update(status=status, elapsed_seconds=perf_counter()-started,
            equity_statistics=asdict(execution.equity_statistics) if execution is not None and execution.equity_statistics is not None else zero_statistics())
        if execution is not None:
            attempt['execution_stats'] = asdict(execution.stats)
            if attempt['execution_stats']['unknown']:
                attempt['statistics_complete'] = False
        save(attempts_path, attempts, scratch)
        results['workload'] = {key: sum(a['equity_statistics'][key] for a in attempts)
                              for key in ('input_snapshots', 'candidate_runs', 'benchmark_runs')}
        results['workload']['account_timings'] = [t for a in attempts for t in a['equity_statistics']['account_timings']]
        results.update(elapsed_seconds=sum(a['elapsed_seconds'] for a in attempts),
            replay_statistics_complete=all(a['statistics_complete'] for a in attempts), attempt_count=len(attempts),
            round_budget=manifest['round_budget'], rounds_debited_by_runner=0)
        save(path, results, scratch)

    try:
        base = replay_context(repo, candidates[0].definition.execution_spec)
        context = replace(base, evaluation=EvaluationAccess(dataflows=base.data,
            resources=ExecutionResources(12, 1, 19), strategy_id=base.strategy_id, execution_spec=base.execution_spec))
        exp = d.ExperimentRef('S019', work.name)
        checkpoint = d.ExecutionCheckpointRequest(manifest['checkpoint_run_id'], d.CheckpointMode.RESUME if args.recover else d.CheckpointMode.CREATE)
        with d.ResearchExecutionSession(context, experiment=exp, checkpoint=checkpoint,
                on_progress=lambda value: print(value, flush=True)) as execution:
            prepared = [(spec, context.evaluation.prepare(request_for(exp, candidate), execution=execution))
                        for spec, candidate in zip(specs, candidates, strict=True)]
            assert len({p.snapshot.sha256 for _, p in prepared}) == 1, 'Expected shared inputs'
            assert len({p.benchmark_identity.sha256 for _, p in prepared}) == 1
            immutable(work / 'protocols/prepared_request_manifest.json', [
                {'label': s.label, 'request_sha256': sha256(p.contract_content).hexdigest(),
                 'input_snapshot_sha256': p.snapshot.sha256, 'benchmark_identity': p.benchmark_identity.sha256}
                for s, p in prepared], scratch)
            for spec, handle in prepared:
                if spec.label not in results['accounts']:
                    continue
                row = results['accounts'][spec.label]
                ref = d.EvidenceRef.from_dict(row['account_ref'])
                raw = ref.resolve(ROOT).read_bytes()
                assert sha256(raw).hexdigest() == ref.sha256
                header = json.loads(raw)
                assert header['request'] == json.loads(handle.contract_content)
                assert row['request_sha256'] == header['request_hash'] == sha256(handle.contract_content).hexdigest()
                assert row['definition'] == json.loads(encoded(handle.candidate.definition.to_dict()))
                immutable(work / f'others/{spec.label}_account.json', ref.to_dict(), scratch)
            snapshot('RUNNING')
            # All economic controls must pass before any remaining structural variants execute.
            groups = ([pair for pair in prepared if pair[0].control_account],
                      [pair for pair in prepared if not pair[0].control_account])
            for group in groups:
                pending = [pair for pair in group if pair[0].label not in results['accounts']]
                for offset in range(0, len(pending), RESOURCES['batch_size']):
                    batch, begun = pending[offset:offset+RESOURCES['batch_size']], perf_counter()
                    in_compute = True
                    outcomes = context.evaluation.evaluate_many(tuple(h for _, h in batch), execution=execution)
                    in_compute = False
                    snapshot('RUNNING')
                    statuses = []
                    for (spec, handle), outcome in zip(batch, outcomes, strict=True):
                        statuses.append({'label': spec.label, 'status': outcome.status.value,
                                         'error': str(outcome.error) if outcome.error else None})
                        if outcome.result is None:
                            continue
                        ref = publish_evidence(context, d.EvaluationEvidenceWrite(exp, spec.label, handle, outcome.result), execution=execution)
                        payload = materialize_equity(outcome.result).payload
                        run, bh = payload['runs']['candidate'], payload['runs']['buy_hold']
                        m, b = metrics(run, bh['metrics']['daily_max_drawdown']), metrics(bh, bh['metrics']['daily_max_drawdown'])
                        assert all(r['observed_through'] <= r['decision_at'] <= r['execution_start'] and 0 <= r['target'] <= 1 for r in run['decisions'])
                        assert all(r['cash'] >= -1e-8 and r['quantity'] >= 0 for r in run['account_points'])
                        assert all(r['quantity'] > 0 and r['quantity'] == int(r['quantity']) for r in run['fills'])
                        assert payload['request']['lineage'] is None
                        results['accounts'][spec.label] = {'label': spec.label,
                            'candidate_id': handle.candidate.candidate_id,
                            'content_hash': handle.candidate.content_identity.content_sha256,
                            'request_sha256': outcome.result.request_hash, 'parameters': spec.parameters,
                            'definition': handle.candidate.definition.to_dict(), 'account_ref': ref.to_dict(),
                            'candidate': m, 'benchmark': b, 'role': 'CONTROL' if spec.control_account else 'STRUCTURAL_EXPERIMENT',
                            'audit': {'chronology': 'PASS', 'cash_longonly_integer': 'PASS'}}
                        immutable(work / f'others/{spec.label}_account.json', ref.to_dict(), scratch)
                        save(path, results, scratch)
                        print('ACCOUNT', spec.label, handle.candidate.candidate_id, m['nar'], m['calmar'], m['eligible'], flush=True)
                    results['batches'].append({'attempt': attempt['attempt'], 'statuses': statuses, 'seconds': perf_counter()-begun})
                    snapshot('RUNNING')
                    assert all(r['status'] == 'SUCCEEDED' for r in statuses), 'Inspect failed accounts before explicit recovery'
                for spec, _ in group:
                    if spec.control_account:
                        check_control(work, spec, scratch)
            assert len(results['accounts']) == len(specs)
            results['status'] = 'COMPLETE'
    except BaseException as error:
        caught = error
        if in_compute:
            attempt['statistics_complete'] = False
        attempt['error'] = repr(error)
        results.update(status='STOPPED', error=repr(error))
        raise
    finally:
        snapshot('COMPLETE' if caught is None and results['status'] == 'COMPLETE' else 'STOPPED')
    print('ROUND_ACCOUNTS_COMPLETE', len(results['accounts']), results['workload']['candidate_runs'],
          results['workload']['benchmark_runs'], flush=True)


if __name__ == '__main__':
    main()
