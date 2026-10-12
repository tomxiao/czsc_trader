"""EX092 independent statistics synthetic checks; no real-input reads."""
# ruff: noqa: E402
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import os

for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'

import numpy as np
import pandas as pd

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run():
    kernel = load('co_down_stat_primary_synthetic', WORK / 'kernel.py')
    audit = load('co_down_stat_independent_synthetic', WORK / 'audit_statistics.py')
    numeric = load('co_down_old_numeric_synthetic', ROOT / 'research/S013/experiments/EX075_20261011/src/statistics_draft_v2.py')
    clock = load('co_down_clock_primary_synthetic', ROOT / 'research/S013/experiments/EX083_20261012/src/kernel.py')
    independent_clock = load('co_down_clock_scalar_synthetic', ROOT / 'research/S013/experiments/EX083_20261012/src/audit.py')
    rng = np.random.default_rng(91)
    synthetic_days = [day for year in range(2020, 2027)
                      for day in pd.bdate_range(str(year) + '-01-01',
                          periods=80 if year == 2020 else 55 if year == 2026 else 53)]
    axis = pd.DatetimeIndex(synthetic_days).as_unit('ns')
    features = pd.DataFrame(rng.normal(0, 1, (400, 28)), index=axis, columns=(*audit.CONTROLS, 'X'))
    features.iloc[:20, -1] = np.nan
    features.iloc[126, 7] = np.nan
    features.iloc[axis.get_loc(axis[axis.year == 2021][0]), 2] = np.nan
    y = .001 - .003 * features.X.fillna(0).to_numpy() + rng.normal(0, .01, len(axis))
    ends = pd.Series(axis, index=axis).shift(-5)
    y[-5:] = np.nan
    labels = pd.DataFrame({'return_4': y, 'label_end_return_4': ends}, index=axis)
    labels.iloc[77, 1] = axis[100]
    scores, traces = kernel.forecasts(features, labels, numeric)
    report = kernel.analyze(features, labels, scores, traces, numeric, clock)
    proof = audit.verify(features, labels, scores, report, independent_clock)
    checks = ['full400 scalar ranks, all fits stationary, all panels and bootstraps',
              '28 common features, delayed maturity and first-year-axis cutoff',
              'tail forecast does not require future label availability']
    assert scores.iloc[-5:].notna().all().all()
    assert not scores.iloc[126].notna().any()
    cut = axis[axis.year == 2022][0] + pd.Timedelta(days=5)
    keep = axis <= cut
    prefix, _ = kernel.forecasts(features.loc[keep], labels.loc[keep], numeric)
    pd.testing.assert_frame_equal(prefix, scores.loc[keep], check_exact=False, atol=2e-14, rtol=0)
    np.testing.assert_array_equal(prefix.to_numpy() > 0, scores.loc[keep].to_numpy() > 0)
    future = labels.copy()
    future.loc[future.label_end_return_4 >= axis[axis.year == 2022][0], 'return_4'] = .9
    altered, _ = kernel.forecasts(features.loc[keep], future.loc[keep], numeric)
    pd.testing.assert_frame_equal(altered, scores.loc[keep], check_exact=False, atol=2e-14, rtol=0)
    np.testing.assert_array_equal(altered.to_numpy() > 0, scores.loc[keep].to_numpy() > 0)
    checks.append('prefix and not-yet-mature label mutation preserve predictions')
    cases = [
        ('all_missing', np.full(80, np.nan), np.full(80, np.nan), np.zeros((80, 27))),
        ('small_sample', np.arange(12.), np.arange(12.), np.ones((12, 27))),
        ('constant_component', np.ones(80), np.arange(80.), rng.normal(size=(80, 27))),
        ('constant_target', np.arange(80.), np.ones(80), rng.normal(size=(80, 27))),
        ('thin_residual_df', rng.normal(size=30), rng.normal(size=30), rng.normal(size=(30, 27))),
        ('explained_component', features.iloc[:80, 0].to_numpy(), rng.normal(size=80), features.iloc[:80, :27].to_numpy()),
        ('explained_target', rng.normal(size=80), features.iloc[:80, 0].to_numpy(), features.iloc[:80, :27].to_numpy()),
        ('rank_ties', np.arange(80) % 3, np.arange(80) % 5, rng.normal(size=(80, 27))),
    ]
    for name, x, target, controls in cases:
        audit.compare(numeric.correlation(x, target), audit.correlation(x, target), 'raw/' + name)
        audit.compare(numeric.correlation(x, target, controls), audit.correlation(x, target, controls), 'partial/' + name)
    duplicate = rng.normal(size=(100, 27))
    duplicate[:, 5] = duplicate[:, 0]
    target = rng.normal(size=100)
    audit.compare(numeric.correlation(np.arange(100.), target, duplicate),
                  audit.correlation(np.arange(100.), target, duplicate), 'partial/duplicate_controls')
    checks.append('nine correlation status/rank/df/constant/explained/tie/duplicate cases')
    corrupted = json.loads(json.dumps(report))
    first = next(row for row in corrupted['fit_trace'] if row['reason'] is None)
    first['models']['augmented']['slope'][0] += .01
    try:
        audit.independent_forecasts(features, labels, corrupted['fit_trace'])
    except ValueError:
        checks.append('corrupted ridge beta explicitly rejected')
    else:
        raise AssertionError('Corrupted beta accepted')
    wrong_trace = json.loads(json.dumps(report['fit_trace']))
    first = next(row for row in wrong_trace if row['reason'] is None)
    first['train_positions'].append(399)
    try:
        audit.independent_forecasts(features, labels, wrong_trace)
    except AssertionError:
        checks.append('future training position explicitly rejected')
    else:
        raise AssertionError('Future training point accepted')
    result = {'status': 'PASS', 'synthetic_only': True, 'real_inputs_read': 0,
              'accounts': 0, 'experiments_allocated': 0, 'checks': checks,
              'check_count': len(checks), 'verification': proof,
              'source_sha256': {name: sha256((WORK / name).read_bytes()).hexdigest()
                                for name in ('kernel.py', 'audit_statistics.py', 'audit_statistics_checks.py')}}
    (WORK / 'audit_statistics_checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({'status': 'PASS', 'checks': len(checks), 'real_inputs': 0, 'statistics': proof})


if __name__ == '__main__':
    run()
