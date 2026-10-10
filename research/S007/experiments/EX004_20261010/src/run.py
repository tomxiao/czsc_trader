"""Evaluate prospectively fixed points; persist full accounts and typed lineage."""
import argparse
from dataclasses import replace
import json
import time

import numpy as np
import pandas as pd
import optuna
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite, EvaluationLineage
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

from aligned_common import (
    ROOT, PROTOCOLS, CACHE, EXPERIMENTS, runs, context, original, candidate, request,
    DEPENDENCIES, BASE, read, write, material, cache_write, fingerprint,
)


def baseline(raw):
    return next(x for x in raw['runs'] if x['scenario_id'] == 'baseline')


def compare_center(old, new):
    a, b = baseline(old), baseline(new)
    checks = {}
    for name in a['ledgers']:
        left, right = pd.DataFrame(a['ledgers'][name]['data']), pd.DataFrame(b['ledgers'][name]['data'])
        assert set(left) == set(right) and len(left) == len(right), name
        fields = [x for x in left if not x.endswith('_id')]
        pd.testing.assert_frame_equal(left[fields], right[fields], check_exact=True, check_dtype=True)
        checks[name] = {'rows': len(left), 'non_identity_fields_exact': fields}
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('strategy', choices=('S007', 'S013'))
    parser.add_argument('--resume-single-worker', action='store_true')
    parser.add_argument('--shard-index', type=int)
    args = parser.parse_args()
    strategy = args.strategy
    root = runs(strategy)
    assert args.shard_index is None or (args.resume_single_worker and strategy == 'S013'
                                       and 0 <= args.shard_index < 3)
    working = root if args.shard_index is None else root/f'shard-{args.shard_index}'
    plan = read(PROTOCOLS/'plan.json')['strategies'][strategy]
    plan_ref = read(PROTOCOLS/'plan_reference.json')
    research = context(strategy, 1 if args.resume_single_worker else 4)
    execution_sources = {'plan': plan_ref,
        'files': [fingerprint(x) for x in sorted((BASE/'src').glob('*.py'))],
        'technical_note': 'Explicit researcher correction: reset parent input_bindings before public prepare for every child and center. First four rejected accounts are preserved in original panel.json/points; no economic results were produced. runtime_binding also follows each child. No point/parameter/implementation changes, no automated fallback or retry.',
        'strategy': strategy}
    write(working/'execution_sources_rebound.json', execution_sources)
    write(working/'execution_sources_rebound_reference.json', material('aligned-execution-source-version-rebound',
        working/'execution_sources_rebound.json', strategy).to_dict())
    if strategy == 'S007' and (root/'panel.json').exists():
        assert all(x['error']['message'] == 'input binding belongs to another strategy or window'
                   for x in read(root/'panel.json')['rows'])
        write(root/'technical_failure_reference.json', material('aligned-initial-binding-failures',
            root/'panel.json', strategy).to_dict())
    old, previous, parent_ref = original(strategy)
    center_id = plan['parent']['candidate_id']
    center_file = root/'center_rebound.json'
    if center_file.exists():
        assert read(center_file)['status'] == 'PASS'
    else:
        bound = research.evaluation.prepare(request(strategy, center_id, plan['center_parameters']))
        result = research.evaluation.evaluate(bound)
        raw = serialize_evaluation_evidence(bound, result)
        checks = compare_center(read(parent_ref.resolve(ROOT)), raw)
        ref = publish_evidence(research, EvaluationEvidenceWrite(EXPERIMENTS[strategy],
            'aligned-distance-center', bound, result))
        cache_write(CACHE/(strategy+'-center.pkl.gz'), (bound, result))
        proof = {'status': 'PASS', 'original': parent_ref.to_dict(), 'evidence': ref.to_dict(),
                 'economic_comparison': checks, 'metrics': result.runs[0].observation.to_dict()}
        write(center_file, proof)
        write(root/'center_rebound_proof_reference.json', material('aligned-center-reproduction-rebound', center_file, strategy).to_dict())
        print({'strategy': strategy, 'center_reproduction': 'PASS'}, flush=True)
    central = next(x for x in previous.runs if x.scenario_id == 'baseline').execution.account_daily
    parent_identity = plan['parent']
    by_id = {}
    for case in plan['cases']:
        if 'candidate_id' in case:
            by_id.setdefault(case['candidate_id'], case)
    if args.shard_index is not None:
        by_id = {k: v for i, (k, v) in enumerate(by_id.items()) if i % 3 == args.shard_index}
    panel_file = working/'panel_rebound.json'
    completed = {x['candidate_id']: x for x in read(panel_file)['rows']} if panel_file.exists() else {}
    if args.shard_index is not None and not completed:
        completed = {x['candidate_id']: x for x in read(root/'panel_rebound.json')['rows']
                     if x['candidate_id'] in by_id}
    if args.resume_single_worker:
        failed = [x for x in completed.values() if x['status'] != 'SUCCEEDED']
        assert all(x['error']['code'] == 'BrokenProcessPool' for x in failed)
        predecessor = material('aligned-pool-failure-predecessor', panel_file, strategy).to_dict() if failed else None
        correction = {'explicit_researcher_decision': True, 'automatic_retry_or_fallback': False,
            'reason': 'Windows invalid multiprocessing handle caused BrokenProcessPool before usable account evidence; use one declared worker, within original max4 cap. Completed accounts reused by exact content identity; failed same fixed configurations evaluated once in an explicit successor attempt.',
            'predecessor': predecessor, 'failed_ids': [x['candidate_id'] for x in failed],
            'workers': 1, 'unchanged': 'all points, parameters, implementation, inputs, prices, costs and windows'}
        if args.shard_index is not None:
            correction['reason'] = 'Disjoint single-worker queue per explicit parallel_decision; no prior failed account outcome is being retried.'
            correction['parallel_decision'] = read(root/'parallel_decision_reference.json')
            correction['shard_index'] = args.shard_index
        write(working/'single_worker_decision.json', correction)
        write(working/'single_worker_decision_reference.json', material('aligned-single-worker-researcher-decision',
            working/'single_worker_decision.json', strategy).to_dict())
        completed = {key: value for key, value in completed.items() if value['status'] == 'SUCCEEDED'}
    assert all(x['status'] == 'SUCCEEDED' for x in completed.values()), 'Explicit decision required for prior failures'
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.RandomSampler(seed=13),
        study_name=f'{strategy}-aligned-fixed-design')
    identifiers = list(by_id)
    for i in range(len(identifiers)):
        study.enqueue_trial({'fixed_index': i})
    initial = time.perf_counter()
    for offset in range(0, len(identifiers), 4):
        selected, pending = [], []
        for index in range(offset, min(offset+4, len(identifiers))):
            trial = study.ask()
            assert trial.suggest_int('fixed_index', 0, len(identifiers)-1) == index
            identifier = identifiers[index]
            if identifier in completed:
                study.tell(trial, completed[identifier]['metrics']['net_cagr'])
                continue
            case = by_id[identifier]
            child_identity = research.runtime.identify(candidate(strategy, identifier, case['parameters']), dependencies=DEPENDENCIES)
            assert child_identity.content_sha256 == case['content_sha256']
            assert child_identity.source_sha256 == parent_identity['source_sha256']
            before, after = plan['center_coordinates'], case['coordinates']
            changes = {k: {'before': before[k], 'after': after[k]} for k in before if before[k] != after[k]}
            derivation = CandidateDerivation(CandidateKey(strategy, center_id), parent_identity['content_sha256'],
                CandidateKey(strategy, identifier), case['content_sha256'], CandidateDerivationKind.PARAMETERS,
                changes, plan_ref['sha256'], CandidateEvidence(parent_ref.repository_path, parent_ref.sha256))
            bound = research.evaluation.prepare(replace(request(strategy, identifier, case['parameters']),
                lineage=EvaluationLineage(derivation)))
            pending.append(bound)
            selected.append((identifier, trial, case, bound, derivation))
        outcomes = research.evaluation.evaluate_many(tuple(pending)) if pending else ()
        failed = False
        for selected_case, outcome in zip(selected, outcomes, strict=True):
            identifier, trial, case, bound, derivation = selected_case
            row = {'candidate_id': identifier, 'status': outcome.status.value,
                   'content_sha256': case['content_sha256'], 'source_sha256': case['source_sha256'],
                   'lineage': derivation.to_dict()}
            if outcome.status.value == 'SUCCEEDED':
                result = outcome.result
                evaluated = result.runs[0]
                ref = publish_evidence(research, EvaluationEvidenceWrite(EXPERIMENTS[strategy],
                    'aligned-distance-'+identifier.lower(), bound, result))
                account = evaluated.execution.account_daily
                assert np.array_equal(account.date.to_numpy(), central.date.to_numpy())
                changes = int(np.count_nonzero(account.target_position.to_numpy() != central.target_position.to_numpy()))
                row.update(evidence=ref.to_dict(), metrics=evaluated.observation.to_dict(),
                           behavior_changed_sessions=changes, behavior_total_sessions=len(account),
                           behavior_change_fraction=changes/len(account), result_hash=result.result_hash,
                           request_hash=result.request_hash)
                study.tell(trial, evaluated.observation.net_cagr)
            else:
                row['error'] = {'code': outcome.error.code, 'message': outcome.error.message}
                study.tell(trial, state=optuna.trial.TrialState.FAIL)
                failed = True
            completed[identifier] = row
            point_directory = 'points-single-worker' if args.resume_single_worker else 'points-rebound'
            write(working/point_directory/(identifier+'.json'), row)
        rows = [completed[k] for k in identifiers if k in completed]
        panel = {'strategy': strategy, 'plan': plan_ref, 'count': len(rows), 'total': len(identifiers),
                 'status': 'COMPLETE' if len(rows) == len(identifiers) else 'PARTIAL', 'rows': rows,
                 'elapsed_seconds_this_run': time.perf_counter()-initial,
                 'optuna': {'sampler': 'fixed queue RandomSampler13', 'version': optuna.__version__,
                            'states': [x.state.name for x in study.trials]}}
        write(panel_file, panel)
        print(json.dumps({'strategy': strategy, 'completed': len(rows), 'total': len(identifiers),
                          'elapsed_seconds': panel['elapsed_seconds_this_run']}, ensure_ascii=False), flush=True)
        if failed:
            raise RuntimeError('Failed point retained; no replacements/retries or partial aggregate')
    write(working/'panel_rebound_reference.json', material('aligned-complete-point-panel-rebound', panel_file, strategy).to_dict())


if __name__ == '__main__':
    main()
