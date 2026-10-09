"""Representative full-account cost counterfactuals, diagnostic only."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

from dataclasses import replace
import argparse
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite, EvaluationCost
from pandas.testing import assert_frame_equal
from common import EXPERIMENT, PROTOCOLS, RUNS, CACHE, SOURCE_CALLS, context, read, write, cache_read, cache_write
from diagnose import rows
from economics_r4 import summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--extension', action='store_true')
    args = parser.parse_args()
    valid = rows()
    assert valid and all(row['status'] == 'SUCCEEDED' for row in valid)
    assert all(read(path)['status'] == 'COMPLETE' for path in RUNS.glob('cost_confirmation_*.json') if 'rows' in read(path))
    additions = [row for row in valid if row['candidate_id'] not in ('C3000', 'C3001', 'C3200')]
    qualified = [row for row in additions if row['qualified']]
    selected = ['C3000', 'C3001']
    selected.extend([max(qualified or additions, key=lambda row: row['net_cagr'])['candidate_id'],
                     max(qualified or additions, key=lambda row: row['negative_year_min_profit'])['candidate_id'],
                     max(additions, key=lambda row: row['negative_year_min_profit'])['candidate_id'],
                     min(additions, key=lambda row: row['deficit'])['candidate_id']])
    output = read(RUNS / 'cost_diagnostics.json')['rows'] if args.extension else []
    if args.extension:
        price_cases = [row for row in additions if row['search'] == 'cost_confirmation_price_margin']
        assert price_cases
        selected.append(max(price_cases, key=lambda row: row['negative_year_min_profit'])['candidate_id'])
    prior = {row['candidate_id'] for row in output}
    candidates = [identifier for identifier in dict.fromkeys(selected) if identifier not in prior]
    plan_path = PROTOCOLS / ('extra_stress_plan.json' if args.extension else 'stress_plan.json')
    assert not plan_path.exists(), 'immutable pressure plan already exists'
    plan = {'name': 'cost_complement_pressure', 'candidates': candidates,
        'selection': 'two exact parent controls; highest CAGR and negative-year margin among new qualified configurations (all new if none qualify), strongest new margin and smallest original four-gate deficit; extension includes strongest price-margin case and evaluates only newly selected identities; ties stable search order',
        'scenarios': [{'name': 'baseline', 'one_way_cost': .001, 'level': 'FORMAL'},
                      {'name': 'stress20', 'one_way_cost': .002, 'level': 'STRESS'},
                      {'name': 'stress30', 'one_way_cost': .003, 'level': 'STRESS'}],
        'eligibility': 'unchanged baseline four gates; pressure diagnostics do not exclude candidates',
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1}}
    write(plan_path, plan)
    research = context(4)
    ref = publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT,
        'cost-complement-pressure-plan' + ('-extension' if args.extension else ''), plan_path.read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / (plan_path.stem + '_reference.json'), ref.to_dict())
    total = len(output) + len(candidates)
    for offset in range(0, len(candidates), 4):
        requests = [replace(cache_read(CACHE / f'{identifier}.pkl.gz')[0], costs=(
            EvaluationCost('baseline', .001, 'FORMAL'), EvaluationCost('stress20', .002, 'STRESS'),
            EvaluationCost('stress30', .003, 'STRESS'))) for identifier in candidates[offset:offset+4]]
        for bound, outcome in zip(requests, research.evaluation.evaluate_many(tuple(requests)), strict=True):
            if outcome.status.value != 'SUCCEEDED':
                write(RUNS / 'stress_failure.json', {'candidate': bound.strategy.candidate_id,
                    'status': outcome.status.value, 'error': outcome.error.message})
                raise RuntimeError('cost diagnostic failed; no automatic retry')
            result = outcome.result
            _, original = cache_read(CACHE / f'{bound.strategy.candidate_id}.pkl.gz')
            baseline = next(run for run in result.runs if run.scenario_id == 'baseline')
            for name in ('account_daily', 'decisions', 'orders', 'fills', 'trades'):
                assert_frame_equal(getattr(original.runs[0].execution, name), getattr(baseline.execution, name), check_exact=True)
            cache_write(CACHE / f'{bound.strategy.candidate_id}-stress.pkl.gz', (bound, result))
            output.append({'candidate_id': bound.strategy.candidate_id, 'baseline_ledger': 'EXACT_EQUAL',
                'scenarios': {run.scenario_id: summarize(replace(result, runs=(run,))) for run in result.runs}})
        write(RUNS / 'cost_diagnostics.json', {'rows': output,
            'status': 'COMPLETE' if len(output) == total else 'PARTIAL',
            'external_provider_access': bool(SOURCE_CALLS)})
        print({'cost_diagnostic_completed': len(output), 'total': total}, flush=True)
    assert not SOURCE_CALLS


if __name__ == '__main__':
    main()
