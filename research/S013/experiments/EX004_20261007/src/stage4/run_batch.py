"""One spawn batch per parent process; Optuna manages even fixed perturbations."""
import argparse
import time
from dataclasses import replace
import optuna
from strategy_manager import CandidateDerivation
from czsc_trader.research_tools import EvaluationCost, EvaluationLineage, EvaluationEvidenceWrite
from czsc_trader.research_tools.assessment import build_assessment_evidence
from czsc_trader.application import publish_evidence
from phase4_common import ROOT, RESULTS, CACHE, EXPERIMENT, context, request, read, save, cache_read, cache_write, PLANS
from economics_r4 import summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('batch', type=int)
    args = parser.parse_args()
    plan, lineages = read(PLANS/'plan.json'), read(RESULTS/'lineages.json')
    cases = plan['cases'][args.batch*4:(args.batch+1)*4]
    if not cases:
        raise ValueError('batch outside declared plan')
    output = RESULTS/f'batch_{args.batch:02}.json'
    if output.exists():
        previous = read(output)
        if all(r['status'] == 'SUCCEEDED' for r in previous['rows']):
            print({'batch': args.batch, 'status': 'REUSED_PUBLISHED_SUCCESS'}, flush=True)
            return
        raise RuntimeError('An explicit successor retry plan is required; original failure preserved')
    research = context(4)
    first, _ = cache_read(ROOT/'.tmp/s013-stage3-hfq/precheck.pkl.gz')
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.RandomSampler(seed=13),
                               study_name=f'S013_stage4_batch_{args.batch:02}')
    for index in range(len(cases)):
        study.enqueue_trial({'configuration': index})
    pending, trials = [], []
    for _ in cases:
        trial = study.ask()
        index = trial.suggest_int('configuration', 0, len(cases)-1)
        case = cases[index]
        req = request(case['number'], case['parameters'], first.execution_data)
        if case['kind'] == 'PARAMETERS':
            req = replace(req, lineage=EvaluationLineage(CandidateDerivation.from_dict(lineages[case['candidate_id']])))
        else:
            req = replace(req, costs=tuple(EvaluationCost(name, float(cost), 'STRESS')
                for name, cost in plan['cost_scenarios'].items()))
        pending.append(research.evaluation.prepare(req))
        trials.append((trial, case))
    started = time.perf_counter()
    outcomes = research.evaluation.evaluate_many(tuple(pending))
    rows = []
    for (trial, case), bound, outcome in zip(trials, pending, outcomes, strict=True):
        row = {'candidate_id': case['candidate_id'], 'kind': case['kind'],
               'status': outcome.status.value, 'request_sha256': outcome.request_hash,
               'trial': trial.number}
        if outcome.status.value == 'SUCCEEDED':
            result = outcome.result
            facts = build_assessment_evidence(bound, result)
            ref = publish_evidence(research, EvaluationEvidenceWrite(EXPERIMENT,
                f'stage-four-{case["kind"].lower()}-{case["candidate_id"].lower()}', bound, result))
            row.update({'reference': ref.to_dict(), 'result_sha256': result.result_hash,
                        'evaluations': [f.evaluation_id for f in facts]})
            if case['kind'] == 'PARAMETERS':
                row['four_gates'] = summarize(result)
            else:
                row['scenarios'] = {run.scenario_id: {'net_cagr': run.observation.net_cagr,
                    'full_max_drawdown': run.observation.max_drawdown,
                    'closed_trades': run.observation.closed_trades}
                    for run in result.runs}
            cache_write(CACHE/f'{case["candidate_id"]}_{case["kind"].lower()}.pkl.gz', (bound, result))
            study.tell(trial, result.runs[0].observation.net_cagr)
        else:
            row['error'] = {'code': outcome.error.code, 'message': outcome.error.message}
            study.tell(trial, state=optuna.trial.TrialState.FAIL)
        rows.append(row)
    save(output.name, {'batch': args.batch, 'elapsed_seconds': time.perf_counter()-started,
                       'rows': rows, 'optuna': {'direction': 'maximize', 'seed': 13,
                       'trials': [{'number': t.number, 'params': t.params, 'value': t.value,
                                   'state': t.state.name} for t in study.trials]}})
    print({'batch': args.batch, 'completed': len(rows),
           'statuses': [r['status'] for r in rows], 'seconds': time.perf_counter()-started}, flush=True)
    if any(r['status'] != 'SUCCEEDED' for r in rows):
        raise RuntimeError('Declared account attempts retained; explicit retry decision needed')


if __name__ == '__main__':
    main()
