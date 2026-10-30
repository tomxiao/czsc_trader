"""One new M008 configuration, one necessary V4 control, one shared benchmark."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import json
from time import perf_counter
from uuid import UUID

from common import (ROOT, WORK, EXPERIMENT, PARAMETERS, context, prepare_data,
    candidate, request, read, save, digest, material, authenticate)
from dataflows import PreparedDataRef
from czsc_trader.application import publish_evidence_many
from czsc_trader.research_tools import (ResearchExecutionSession, ExecutionCheckpointRequest,
    CheckpointMode, EvaluationEvidenceWrite)
from czsc_trader.research_tools.equity_replay import materialize_equity


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def verify_signals(payloads):
    old_path = ROOT/'research/S017/experiments/EX025_20261029/others/signal_facts.json.gz'
    old_report = read(ROOT/'research/S017/experiments/EX025_20261029/report_ref.json')['report']
    snapshot = read(authenticate(old_report))
    if digest(old_path) not in {ref['sha256'] for ref in snapshot['evidence']}:
        raise ValueError('Old signal membership is not bound by its published report')
    old = json.loads(gzip.decompress(old_path.read_bytes()))
    expected = {instant(row['signal_at']): row['signals'] for row in old}
    checks = {}
    for key, payload in payloads.items():
        mechanism = PARAMETERS[key]['entry_mechanism']
        decisions = payload['runs']['candidate']['decisions']
        mismatches, count = [], 0
        for decision in decisions:
            facts = {row['key']: row['text'] for row in decision['explanation']['basis']}
            stamp = instant(decision['observed_through'])
            signal = facts['entry_signal'] == 'True'
            count += signal
            if stamp not in expected or signal != (mechanism in expected[stamp]):
                mismatches.append(decision['observed_through'])
        if len(decisions) != len(expected) or mismatches or count != {'C0061': 399, 'C0062': 324}[key]:
            raise ValueError('Formal signals differ from the retained expression: ' + key)
        checks[key] = {'decisions': len(decisions), 'signals': count, 'mismatches': mismatches}
    save(WORK/'others/signal_validation.json', {'status': 'PASS', 'accounts': checks,
        'retained_signal_sha256': digest(old_path), 'retained_report': old_report,
        'strategy_source_sha256': digest(WORK/'src/strategy.py')})


def run(mode='CREATE'):
    started = perf_counter()
    checked = read(WORK/'others/precheck.json')
    if checked['status'] != 'PASS' or checked['strategy_source_sha256'] != digest(WORK/'src/strategy.py'):
        raise ValueError('Current focused precheck must pass before formal accounts')
    mode = CheckpointMode(mode)
    frozen_path = WORK/'others/pre_account_evidence.json'
    if frozen_path.exists():
        if mode is not CheckpointMode.RESUME:
            raise ValueError('An existing run requires explicit RESUME')
        for relative, reference in read(frozen_path).items():
            if digest(WORK/relative) != digest(authenticate(reference)):
                raise ValueError('Frozen source changed: ' + relative)
        ref = read(WORK/'others/data_preparation.json')['reference']
        prepared = PreparedDataRef(UUID(ref['space_id']), UUID(ref['preparation_id']), ref['manifest_sha256'])
        research = context()
    else:
        if mode is not CheckpointMode.CREATE:
            raise ValueError('No run exists to resume')
        research, prepared, _ = prepare_data()
    candidates = {key: candidate(key) for key in PARAMETERS}
    declarations = {'parameters': PARAMETERS, 'definitions': {key: c.definition.to_dict() for key, c in candidates.items()}}
    definitions = WORK/'protocols/definitions.json'
    if definitions.exists() and read(definitions) != json.loads(json.dumps(declarations, default=str)):
        raise ValueError('Frozen definitions changed')
    if not definitions.exists():
        save(definitions, declarations)
    if not frozen_path.exists():
        paths = [WORK/'src/common.py', WORK/'src/strategy.py', WORK/'src/accounts.py', WORK/'src/precheck.py',
            *sorted((WORK/'protocols').glob('*.*')), WORK/'others/precheck.json',
            WORK/'others/data_preparation.json', WORK/'others/data_preparation_status.json']
        save(frozen_path, {str(p.relative_to(WORK)).replace('\\', '/'): material(research, 'account-source-'+str(i), p).to_dict()
            for i, p in enumerate(paths)})
    seen_phases = set()

    def progress(event):
        phase = str(event.phase)
        if phase not in seen_phases:
            print('PROGRESS', json.dumps(asdict(event), default=str), flush=True)
            seen_phases.add(phase)

    with ResearchExecutionSession(research, experiment=EXPERIMENT,
            checkpoint=ExecutionCheckpointRequest(EXPERIMENT.experiment_id+'-formal-v4', mode), on_progress=progress) as execution:
        handles = tuple(research.evaluation.prepare(request(c, prepared), execution=execution) for c in candidates.values())
        outcomes = research.evaluation.evaluate_many(handles, execution=execution)
        save(WORK/'others/execution_status.json', [{'candidate': p.candidate.candidate_id, 'status': o.status.value,
            'error': None if o.error is None else asdict(o.error)} for p, o in zip(handles, outcomes, strict=True)])
        if any(o.status.value != 'SUCCEEDED' or o.result is None for o in outcomes):
            raise ValueError('Formal account failed; inspect explicit status before any retry')
        payloads = {p.candidate.candidate_id: materialize_equity(o.result).payload for p, o in zip(handles, outcomes, strict=True)}
        verify_signals(payloads)
        publications = publish_evidence_many(research, tuple(EvaluationEvidenceWrite(EXPERIMENT,
            'formal-'+p.candidate.candidate_id, p, o.result) for p, o in zip(handles, outcomes, strict=True)), execution=execution)
        save(WORK/'others/publication_status.json', [asdict(p) for p in publications])
        save(WORK/'others/execution_stats.json', {'session': asdict(execution.stats),
            'equity': asdict(execution.equity_statistics), 'wall_seconds': perf_counter()-started})
        if any(p.status.value != 'PUBLISHED' for p in publications):
            raise ValueError('Formal evidence publication incomplete; inspect before retry')
        manifest = {}
        for p, o, published in zip(handles, outcomes, publications, strict=True):
            key = p.candidate.candidate_id
            value = payloads[key]
            manifest[key] = {'evidence': published.reference.to_dict(), 'evaluation_identity': value['evaluation_identity'],
                'evaluation_id': value['evaluation_id'], 'request_hash': o.result.request_hash,
                'candidate': value['runs']['candidate']['metrics'], 'buy_hold': value['runs']['buy_hold']['metrics']}
        save(WORK/'others/accounts.json', manifest)
        benchmark_runs = execution.equity_statistics.benchmark_runs
        save(WORK/'others/account_run_status.json', {'status': 'PUBLISHED', 'new_economic_configurations': 1,
            'technical_control_replays': 1, 'shared_benchmark_runs': benchmark_runs,
            'formal_candidate_paths': len(manifest)})
        if benchmark_runs != 1:
            raise ValueError('The two accounts did not reuse exactly one shared benchmark')
    print('FORMAL_ACCOUNTS_PUBLISHED', sorted(manifest), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('CREATE', 'RESUME'), default='CREATE')
    args = parser.parse_args()
    run(args.mode)
