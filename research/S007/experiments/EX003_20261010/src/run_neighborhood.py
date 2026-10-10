"""Evaluate the eight prospectively fixed, unscreened joint points."""
from dataclasses import replace
import optuna
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite, EvaluationLineage, EvidenceRef
from common import ROOT, PROTOCOLS, RUNS, EXPERIMENT, DEPENDENCIES
from common import context, request, candidate, cache_read, read, write, material
from offline_inputs import supplier


def main():
    assert read(RUNS/'center_reproduction.json')['status'] == 'PASS'
    assert read(RUNS/'c2132_center_reproduction.json')['status'] == 'PASS'
    plan = read(PROTOCOLS/'adapted_plan.json')
    center_request, _ = cache_read(ROOT/'.tmp/s007-four-metrics/center.pkl.gz')
    research = context(4, supplier)
    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.RandomSampler(seed=13),
                                storage=optuna.storages.InMemoryStorage(), study_name='S007-fixed-eight-joint-points')
    for index in range(8):
        study.enqueue_trial({'fixed_index': index})
    trials, requests = [], []
    lineages = {}
    parent_ref = EvidenceRef.from_dict(read(RUNS/'center_reference.json'))
    for case in plan['cases']:
        trial = study.ask()
        index = trial.suggest_int('fixed_index', 0, 7)
        assert index == case['index']
        identity = research.runtime.identify(candidate(case['candidate_id'], case['parameters']), dependencies=DEPENDENCIES)
        assert identity.content_sha256 == case['content_sha256']
        assert identity.source_sha256 == case['source_sha256']
        before = plan['center']['parameters']['rule']['score']
        after = case['parameters']['rule']['score']
        changes = {'rule.score.'+key: {'before': before[key], 'after': after[key]}
                   for key in after if before[key] != after[key]}
        derivation = CandidateDerivation(CandidateKey('S007', 'C9000'), plan['center']['content_sha256'],
            CandidateKey('S007', case['candidate_id']), case['content_sha256'],
            CandidateDerivationKind.PARAMETERS, changes,
            read(PROTOCOLS/'adapted_plan_reference.json')['sha256'],
            CandidateEvidence(parent_ref.repository_path, parent_ref.sha256))
        lineages[case['candidate_id']] = derivation.to_dict()
        bound = research.evaluation.prepare(replace(request(case, center_request.execution_data),
                                                   lineage=EvaluationLineage(derivation)))
        trials.append(trial)
        requests.append(bound)
    write(RUNS/'lineages.json', lineages)
    write(PROTOCOLS/'lineages_reference.json', material('four-diagnostics-parameter-lineages',
        RUNS/'lineages.json').to_dict())
    outcomes = research.evaluation.evaluate_many(tuple(requests))
    rows = []
    for case, trial, bound, outcome in zip(plan['cases'], trials, requests, outcomes, strict=True):
        row = {'candidate_id': case['candidate_id'], 'index': case['index'], 'parameters': case['parameters'],
               'content_sha256': case['content_sha256'], 'source_sha256': case['source_sha256'],
               'status': outcome.status.value}
        if outcome.status.value == 'SUCCEEDED':
            result = outcome.result
            ref = publish_evidence(research, EvaluationEvidenceWrite(EXPERIMENT,
                'four-diagnostics-neighbor-'+case['candidate_id'].lower(), bound, result))
            row.update(evidence=ref.to_dict(), metrics=result.runs[0].observation.to_dict(),
                       result_hash=result.result_hash, request_hash=result.request_hash)
            study.tell(trial, result.runs[0].observation.net_cagr)
        else:
            row['error'] = {'code': outcome.error.code, 'message': outcome.error.message}
            study.tell(trial, state=optuna.trial.TrialState.FAIL)
        rows.append(row)
        write(RUNS/'neighborhood'/(case['candidate_id']+'.json'), row)
    panel = {'scope': 'All eight prospective points; no economic filtering or replacements',
             'count': len(rows), 'successes': sum(x['status']=='SUCCEEDED' for x in rows), 'rows': rows,
             'optuna': {'version': optuna.__version__, 'seed': 13, 'sampler': 'fixed enqueued points; RandomSampler(13)',
                        'trial_states': [x.state.name for x in study.trials]},
             'resources': plan['resources'], 'plan': read(PROTOCOLS/'adapted_plan_reference.json')}
    write(RUNS/'neighborhood.json', panel)
    write(PROTOCOLS/'neighborhood_reference.json', material('four-diagnostics-eight-point-panel',
        RUNS/'neighborhood.json').to_dict())
    print({'count': len(rows), 'successes': panel['successes'],
           'points': [{'candidate_id': x['candidate_id'], 'status': x['status'],
                       'net_cagr': x.get('metrics', {}).get('net_cagr')} for x in rows]}, flush=True)


if __name__ == '__main__':
    main()
