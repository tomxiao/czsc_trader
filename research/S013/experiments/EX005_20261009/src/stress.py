"""Stage-three cost counterfactuals; diagnostics do not change eligibility."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

import argparse
from dataclasses import replace
import json

from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite, EvaluationCost
from common import EXPERIMENT, PROTOCOLS, RUNS, CACHE, SOURCE_CALLS, context, read, write, cache_read, cache_write
from diagnose import rows
from economics_r4 import summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--extension', action='store_true')
    args = parser.parse_args()
    plan_path = PROTOCOLS / ('extra_stress_plan.json' if args.extension else 'stress_plan.json')
    valid = [row for row in rows() if row['status'] == 'SUCCEEDED']
    if plan_path.exists():
        raise RuntimeError('Stress plan already exists; use an explicit continuation, not overwrite')
    qualified = [row['candidate_id'] for row in valid if row['qualified']]
    # Include up to three useful contrasting trade-offs, then publish before computing costs.
    contrasting = []
    filters = [r for r in valid if r['gates']['negative_buyhold_year_profit']
               and r['gates']['annual_drawdown'] and r['candidate_id'] not in qualified]
    if filters:
        contrasting.append(max(filters, key=lambda r: r['negative_year_min_profit'])['candidate_id'])
        contrasting.append(min(filters, key=lambda r: r['deficit'])['candidate_id'])
    if args.extension:
        contrasting.extend(read(RUNS / 'selection.json')['frontier'])
    output = read(RUNS / 'cost_diagnostics.json')['rows'] if args.extension else []
    already = {row['candidate_id'] for row in output}
    candidates = [identifier for identifier in dict.fromkeys(qualified + contrasting)
                  if identifier not in already]
    if not candidates:
        print({'additional_cost_requests': 0}, flush=True)
        return
    plan = {'name': 'stage3_cost_diagnostics', 'candidates': candidates,
            'selection': ('all remaining standard-qualified configurations and current stage-three tradeoff frontier'
                          if args.extension else 'all standard-qualified new configurations plus the best observed annual-margin and deficit counterexamples'),
            'scenarios': [{'name': 'baseline', 'one_way_cost': .001, 'level': 'FORMAL'},
                          {'name': 'stress20', 'one_way_cost': .002, 'level': 'STRESS'},
                          {'name': 'stress30', 'one_way_cost': .003, 'level': 'STRESS'}],
            'eligibility': 'only original baseline four gates; costs are diagnostics',
            'no_stage4': 'this is stage-three mechanism attribution; no assessment/ranking/phase promotion',
            'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1}}
    write(plan_path, plan)
    research = context(4)
    ref = publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT,
        'stage3-cost-counterfactual-plan' + ('-extension' if args.extension else ''),
        plan_path.read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / (plan_path.stem + '_reference.json'), ref.to_dict())
    total = len(output) + len(candidates)
    for offset in range(0, len(candidates), 4):
        requests = []
        for identifier in candidates[offset:offset + 4]:
            bound, _ = cache_read(CACHE / f'{identifier}.pkl.gz')
            requests.append(replace(bound, costs=(EvaluationCost('baseline', .001, 'FORMAL'),
                EvaluationCost('stress20', .002, 'STRESS'), EvaluationCost('stress30', .003, 'STRESS'))))
        outcomes = research.evaluation.evaluate_many(tuple(requests))
        for bound, outcome in zip(requests, outcomes, strict=True):
            if outcome.status.value != 'SUCCEEDED':
                write(RUNS / 'stress_failure.json', {'candidate': bound.strategy.candidate_id,
                    'status': outcome.status.value, 'error': outcome.error.message})
                raise RuntimeError('cost diagnostic failed, no automatic retry')
            result = outcome.result
            original, baseline = cache_read(CACHE / f'{bound.strategy.candidate_id}.pkl.gz')
            lhs, rhs = baseline.runs[0].execution, result.runs[0].execution
            from pandas.testing import assert_frame_equal
            for name in ('account_daily', 'decisions', 'orders', 'fills', 'trades'):
                assert_frame_equal(getattr(lhs, name), getattr(rhs, name), check_exact=True)
            cache_write(CACHE / f'{bound.strategy.candidate_id}-stress.pkl.gz', (bound, result))
            scenarios = {}
            for run in result.runs:
                scenarios[run.scenario_id] = summarize(replace(result, runs=(run,)))
            output.append({'candidate_id': bound.strategy.candidate_id, 'scenarios': scenarios,
                           'baseline_ledger': 'EXACT_EQUAL'})
        write(RUNS / 'cost_diagnostics.json', {'rows': output, 'status': 'COMPLETE'
              if len(output) == total else 'PARTIAL', 'external_provider_access': bool(SOURCE_CALLS)})
        print(json.dumps({'cost_diagnostic_completed': len(output), 'total': total}), flush=True)
    assert not SOURCE_CALLS


if __name__ == '__main__':
    main()
