"""Run only the selected EX030 V3 accounts, reusing the public session cache."""
import argparse
from dataclasses import asdict
import gzip
import json
from time import perf_counter

from common import (WORK, INSTRUMENT, SPEC, EXPERIMENT, context, request,
                    read, save, digest, authenticate, material)
from strategy_v3 import feature_graph, state_schema
from strategy_runtime import EquityStrategyDefinition, EquityStrategyCandidate, equity_source_hash
from czsc_trader.application import publish_evidence_many
from czsc_trader.research_tools import (CheckpointMode, EvaluationEvidenceWrite,
    ExecutionCheckpointRequest, ResearchExecutionSession)
from czsc_trader.research_tools.equity_replay_v3 import materialize_v3

EXPECTED = {'C0059': {'entry_mechanism': 'S017-M019', 'max_holding_bars': 6},
            'C0060': {'entry_mechanism': 'S017-M020', 'max_holding_bars': 6}}


def initialize():
    selection = read(WORK/'others/selection.json')['selected_mechanisms']
    if (not isinstance(selection, list) or len(selection) != len(set(selection))
            or not set(selection) <= {'S017-M019', 'S017-M020'}):
        raise ValueError('Only the two predeclared EX030 mechanisms may be selected')
    values = {key: params for key, params in EXPECTED.items() if params['entry_mechanism'] in selection}
    source, files = WORK/'src', ('strategy_v3.py',)
    result = {}
    for key, parameters in values.items():
        definition = EquityStrategyDefinition(INSTRUMENT, SPEC, 261, 'strategy_v3:step', files,
            equity_source_hash(source, files), json.dumps(parameters), contract_version=3,
            feedback_mode='CONFIRMED_EXECUTION', session_context=False, auxiliary_inputs=(),
            feature_graph=feature_graph(), state_schema=state_schema())
        result[key] = EquityStrategyCandidate('S017', key, definition, source)
    for name, value in (('configurations', values), ('definitions', {k: c.definition.to_dict() for k, c in result.items()})):
        path = WORK/f'protocols/{name}.json'
        canonical = json.loads(json.dumps(value, default=str))
        if path.exists() and read(path) != canonical:
            raise ValueError('Initialized fixed account definition changed: '+name)
        if not path.exists():
            save(path, canonical)
    return result


def check_sources():
    checked = read(WORK/'others/entry_checks.json')
    if checked['status'] != 'PASS':
        raise ValueError('Focused entry/state checks must pass before formal replay')
    declared = checked['sources']
    if declared.get('strategy_v3.py') != digest(WORK/'src/strategy_v3.py'):
        raise ValueError('Focused checks must bind the actual V3 strategy source')
    for relative, expected in declared.items():
        if digest(WORK/'src'/relative) != expected:
            raise ValueError('Focused check source changed: '+relative)


def signal_validation(manifest):
    events = json.loads(gzip.decompress((WORK/'others/events.json.gz').read_bytes()))
    expected = {r['signal_at']: r for r in events if r['n'] == 6}
    from datetime import datetime, timezone

    def instant(value):
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)

    expected = {instant(key): value for key, value in expected.items()}
    checks = {}
    for key, record in manifest.items():
        path = authenticate(record['evidence'])
        payload = materialize_v3(read(path), lambda ref: (path.parent/(ref['sha256']+'.json')).read_bytes()).payload
        mechanism = EXPECTED[key]['entry_mechanism']
        decisions = payload['runs']['candidate']['decisions']
        mismatches = []
        for decision in decisions:
            stamp = instant(decision['observed_through'])
            facts = {f['key']: f['text'] for f in decision['explanation']['basis']}
            if stamp not in expected or (facts['entry_signal'] == 'True') != (mechanism in expected[stamp]['signals']):
                mismatches.append(decision['observed_through'])
        if len(decisions) != len(expected) or mismatches:
            raise ValueError('Formal V3 decision population differs from published event membership: '+key)
        checks[key] = {'decisions': len(decisions), 'mismatches': mismatches}
    save(WORK/'others/account_signal_validation.json', {'status': 'PASS', 'accounts': checks,
        'events_sha256': digest(WORK/'others/events.json.gz'), 'source_sha256': digest(WORK/'src/strategy_v3.py')})


def run(mode='CREATE'):
    started = perf_counter()
    candidates = initialize()
    if not candidates:
        save(WORK/'others/accounts.json', {})
        save(WORK/'others/account_run_status.json', {'status': 'NOT_RUN', 'new_strategy_accounts': 0,
            'reason': 'Neither conditional entry qualified for the predeclared account comparison'})
        print('NO_SELECTED_ACCOUNTS', flush=True)
        return
    check_sources()
    mode, research = CheckpointMode(mode), context(2)
    files = [WORK/'src/strategy_v3.py', WORK/'src/accounts.py', WORK/'src/common.py',
        *sorted((WORK/'protocols').glob('*.*')), WORK/'others/selection.json', WORK/'others/entry_checks.json']
    frozen = WORK/'others/pre_account_evidence.json'
    if frozen.exists():
        if mode is not CheckpointMode.RESUME:
            raise ValueError('An existing formal run requires explicit RESUME')
        for name, ref in read(frozen).items():
            if digest(WORK/name) != digest(authenticate(ref)):
                raise ValueError('Frozen account source changed: '+name)
    else:
        if mode is not CheckpointMode.CREATE:
            raise ValueError('No formal account run exists to resume')
        save(frozen, {str(p.relative_to(WORK)).replace('\\', '/'): material(research, 'account-source-'+str(j), p).to_dict()
                      for j, p in enumerate(files)})

    def progress(event):
        print(json.dumps(asdict(event), default=str), flush=True)

    with ResearchExecutionSession(research, experiment=EXPERIMENT,
            checkpoint=ExecutionCheckpointRequest(EXPERIMENT.experiment_id+'-formal-v3', mode), on_progress=progress) as execution:
        prepared = tuple(research.evaluation.prepare(request(c), execution=execution) for c in candidates.values())
        outcomes = research.evaluation.evaluate_many(prepared, execution=execution)
        save(WORK/'others/execution_status.json', [{'candidate': p.candidate.candidate_id, 'status': o.status.value,
            'error': None if o.error is None else asdict(o.error)} for p, o in zip(prepared, outcomes, strict=True)])
        if any(o.status.value != 'SUCCEEDED' for o in outcomes):
            raise ValueError('Formal account failed; inspect explicit statuses before retry')
        views = [materialize_v3(o.result).payload for o in outcomes]
        publications = publish_evidence_many(research, tuple(EvaluationEvidenceWrite(EXPERIMENT,
            'formal-'+p.candidate.candidate_id, p, o.result) for p, o in zip(prepared, outcomes, strict=True)), execution=execution)
        save(WORK/'others/publication_status.json', [asdict(p) for p in publications])
        save(WORK/'others/execution_stats.json', {'session': asdict(execution.stats),
            'equity': asdict(execution.equity_statistics), 'wall_seconds': perf_counter()-started})
        if any(p.status.value != 'PUBLISHED' for p in publications):
            raise ValueError('Formal evidence publication failed; inspect statuses')
        manifest = {}
        for p, o, ref, view in zip(prepared, outcomes, publications, views, strict=True):
            manifest[p.candidate.candidate_id] = {'evidence': ref.reference.to_dict(),
                'evaluation_identity': view['evaluation_identity'], 'evaluation_id': view['evaluation_id'],
                'request_hash': o.result.request_hash, 'execution_status': o.status.value,
                'publication_status': ref.status.value, 'candidate': view['runs']['candidate']['metrics'],
                'buy_hold': view['runs']['buy_hold']['metrics']}
        save(WORK/'others/accounts.json', manifest)
        save(WORK/'others/account_run_status.json', {'status': 'PUBLISHED', 'new_strategy_accounts': len(manifest),
            'reused_parent_strategy_accounts': 1, 'shared_benchmark_runs': execution.equity_statistics.benchmark_runs})
    signal_validation(manifest)
    print('FORMAL_ACCOUNTS_PUBLISHED', sorted(manifest), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'run', 'signals'))
    parser.add_argument('--mode', choices=('CREATE', 'RESUME'), default='CREATE')
    args = parser.parse_args()
    if args.action == 'init':
        initialize()
    elif args.action == 'signals':
        signal_validation(read(WORK/'others/accounts.json'))
    else:
        run(args.mode)
