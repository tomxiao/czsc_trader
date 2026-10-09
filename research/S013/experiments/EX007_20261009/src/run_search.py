"""Optuna fixed queue, one main-process study, TDR FULL spawn evaluations."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import time

import optuna
from common import (
    PROTOCOLS, RUNS, CACHE, SOURCE_CALLS, context, read, write, request,
    cache_read, cache_write, config_hash, SOURCE,
)
from economics_r4 import summarize, search_value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('plan', nargs='?', default='initial_plan.json')
    parser.add_argument('--start-id', type=int, default=3000)
    args = parser.parse_args()
    plan = read(PROTOCOLS / args.plan)
    source_base = SOURCE
    for filename, expected in plan['source_files'].items():
        assert sha256((source_base / filename).read_bytes()).hexdigest() == expected
    assert read(RUNS / 'precheck.json')['status'] == 'PASS'
    if plan.get('precheck_file'):
        assert read(RUNS / plan['precheck_file'])['status'] == 'PASS'
    rows_path = RUNS / (plan['name'] + '.json')
    rows = read(rows_path)['rows'] if rows_path.exists() else []
    if any(row['status'] != 'SUCCEEDED' for row in rows):
        raise RuntimeError('Recorded failures require an explicit researcher decision')
    completed = {row['index']: row for row in rows}
    research = context(4)
    control, _ = cache_read(CACHE / 'C3000.pkl.gz')
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction='maximize',
        sampler=optuna.samplers.RandomSampler(seed=13), study_name=plan['name'])
    configurations = plan['configurations']
    for index in range(len(configurations)):
        study.enqueue_trial({'configuration': index})
    initial = time.perf_counter()
    for offset in range(0, len(configurations), 4):
        pending, selected = [], []
        for index in range(offset, min(offset + 4, len(configurations))):
            trial = study.ask()
            actual = trial.suggest_int('configuration', 0, len(configurations) - 1)
            assert actual == index
            if index in completed:
                study.tell(trial, search_value(completed[index]))
                continue
            config = configurations[index]
            identifier = f'C{args.start_id + index:04}'
            # Reuse only prospectively declared, completed FULL equivalence controls.
            cached = CACHE / f'{identifier}.pkl.gz'
            if (identifier in plan.get('prechecked_controls', [])) and cached.exists():
                bound, result = cache_read(cached)
                assert dict(bound.strategy.payload['parameters']) == config['parameters']
                selected.append((trial, index, config, bound, result))
            else:
                bound = research.evaluation.prepare(request(identifier,
                    deepcopy(config['parameters']), control.execution_data))
                pending.append(bound)
                selected.append((trial, index, config, bound, None))
        outcomes = iter(research.evaluation.evaluate_many(tuple(pending))) if pending else iter(())
        failures = []
        for trial, index, config, bound, cached_result in selected:
            outcome = None if cached_result is not None else next(outcomes)
            status = 'SUCCEEDED' if outcome is None else outcome.status.value
            row = {'index': index, 'candidate_id': bound.strategy.candidate_id,
                   'label': config['label'], 'parent': config.get('parent', 'C9023'),
                   'parameters': config['parameters'], 'config_hash': config_hash(config['parameters']),
                   'search': plan['name'], 'status': status, 'trial': trial.number}
            if status == 'SUCCEEDED':
                result = cached_result if outcome is None else outcome.result
                row.update(summarize(result))
                row['negative_year_min_profit'] = min(row['annual'][year]['return']
                                                       for year in row['negative_buyhold_years'])
                study.tell(trial, search_value(row))
                cache_write(CACHE / f'{bound.strategy.candidate_id}.pkl.gz', (bound, result))
            else:
                row['error'] = {'code': outcome.error.code, 'message': outcome.error.message}
                study.tell(trial, state=optuna.trial.TrialState.FAIL)
                failures.append(row)
            rows.append(row)
        write(rows_path, {'plan': args.plan, 'rows': rows,
                         'elapsed_seconds': time.perf_counter() - initial,
                         'status': 'COMPLETE' if len(rows) == len(configurations) else 'PARTIAL',
                         'external_provider_access': bool(SOURCE_CALLS)})
        cache_write(CACHE / (plan['name'] + '-study.pkl.gz'), study)
        valid = [r for r in rows if r['status'] == 'SUCCEEDED']
        best = min(valid, key=lambda r: r['deficit']) if valid else None
        print(json.dumps({'plan': plan['name'], 'completed': len(rows), 'total': len(configurations),
            'qualified': sum(r['qualified'] for r in valid), 'best': None if best is None else {
                k: best[k] for k in ('candidate_id', 'net_cagr', 'closed_trades', 'negative_year_min_profit', 'deficit')},
            'elapsed': time.perf_counter() - initial}), flush=True)
        if failures:
            raise RuntimeError('Formal failures saved; no automatic retries')
    assert not SOURCE_CALLS


if __name__ == '__main__':
    main()
