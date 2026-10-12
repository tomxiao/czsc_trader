"""Synthetic online PG maturity/prefix and stationary-fit verification only."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

import kernel

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prob = load('online_synthetic_probability', ROOT / 'research/S013/experiments/EX084_20261012/src/kernel.py')
gain = load('online_synthetic_gain', ROOT / 'research/S013/experiments/EX086_20261012/src/kernel.py')
clock = load('online_synthetic_clock', ROOT / 'research/S013/experiments/EX083_20261012/src/kernel.py')
worker = load('online_synthetic_worker', WORK / 'worker.py')
axis = pd.bdate_range('2020-09-01', periods=400).as_unit('ns')
rng = np.random.default_rng(90)
features = pd.DataFrame(rng.normal(0, 1, (400, 14)), index=axis, columns=kernel.FEATURES)
features.iloc[117, 5] = np.nan
old = pd.DataFrame(rng.normal(.003, .002, (400, 2)), index=axis, columns=kernel.INPUTS)
old.loc[axis.year < 2021] = np.nan
y = np.where(np.arange(400) % 2 == 0, .008, -.006) + rng.normal(0, .0004, 400)
y[[12, 30, 150]] = 0
y[-5:] = np.nan
labels = pd.DataFrame({'return_4': y, 'label_end_return_4': pd.Series(axis, index=axis).shift(-5)}, index=axis)
labels.iloc[130, 1] = axis[150]
scores, result = kernel.analyze(features, labels, old, prob, gain, clock)
single_blocks = [kernel.forecasts(features, labels, old, prob, gain, families=(family,)) for family in kernel.FAMILIES]
combined = pd.concat([block[0] for block in single_blocks], axis=1)
combined_traces = [row for block in single_blocks for row in block[1]]
pd.testing.assert_frame_equal(combined, scores, check_exact=True)
assert combined_traces == result['fit_trace']
assert kernel.summarize(combined, labels, combined_traces, clock) == result
parallel, parallel_traces = worker.runner(features, labels, old,
    ROOT / 'research/S013/experiments/EX084_20261012/src/kernel.py',
    ROOT / 'research/S013/experiments/EX086_20261012/src/kernel.py')
pd.testing.assert_frame_equal(parallel, scores, check_exact=True)
assert parallel_traces == result['fit_trace']
assert result['schedule_count'] == 48 and len(result['bootstrap']['records']) == 500
assert tuple(result['bootstrap']['summary']) == kernel.QUANTITIES
assert scores.loc[axis.year == 2020, 'confirmation_online_pg'].isna().all()
assert np.isnan(scores.iloc[117].original14_online_pg)
assert scores.iloc[-5:].notna().all().all()
for family, name in zip(kernel.FAMILIES, kernel.INPUTS):
    np.testing.assert_array_equal(scores[family + '_historical'], old[name])

stationary = 0
for row in result['fit_trace']:
    ids = row['train_positions']
    i, date = row['position'], pd.Timestamp(row['signal_date'])
    assert all(j < i and axis[j].year >= 2020 and labels.label_end_return_4.iloc[j] <= date and features.iloc[j].notna().all() for j in ids)
    assert 117 not in ids
    if date < axis[150]:
        assert 130 not in ids
    assert row['nonpositive_n'] == int((labels.return_4.iloc[ids] <= 0).sum())
    assert row['zero_net_n'] == int((labels.return_4.iloc[ids] == 0).sum())
    if not row['available']:
        assert row['probability_fit'] is None and row['gain_fit'] is None
        continue
    train = features.iloc[ids].to_numpy(float)
    tx = np.column_stack([gain.rank(train[:, j], train[:, j]) for j in range(14)])[:, row['columns']]
    binary = (labels.return_4.iloc[ids].to_numpy() > 0).astype(float)
    a = np.column_stack((np.ones(len(ids)), tx))
    beta = np.asarray(row['probability_fit']['coefficients'])
    penalty = np.r_[0., np.full(tx.shape[1], 10.)]
    fitted = np.exp(-np.logaddexp(0, -(a @ beta)))
    p_gradient = a.T @ (fitted - binary) + penalty * beta
    g_beta = np.asarray(row['gain_fit']['coefficients'])
    ga = a[binary > 0]
    magnitude = labels.return_4.iloc[ids].to_numpy()[binary > 0]
    g_gradient = ga.T @ (1 - magnitude * np.exp(-(ga @ g_beta))) + penalty * g_beta
    assert np.max(np.abs(p_gradient)) <= 1e-10
    assert np.max(np.abs(g_gradient)) <= 1e-10
    assert row['online_pg'] == row['probability'] * row['gain'] - (1 - row['probability']) * row['loss_mean']
    assert row['gain'] > 0 and 0 < row['probability'] < 1
    stationary += 2
assert stationary == result['new_daily_models']
cross = axis[axis.year == 2022][0]
cross_rows = [row for row in result['fit_trace'] if row['signal_date'] == cross.isoformat()]
assert len(cross_rows) == 2 and all(row['available'] and any(axis[j].year == 2020 for j in row['train_positions']) and any(axis[j].year == 2021 for j in row['train_positions']) for row in cross_rows)

cut = cross
keep = axis <= cut
prefix, _ = kernel.forecasts(features.loc[keep], labels.loc[keep], old.loc[keep], prob, gain)
pd.testing.assert_frame_equal(prefix, scores.loc[keep], check_exact=True)
future_features, future_labels, future_old = features.loc[keep].copy(), labels.loc[keep].copy(), old.loc[keep].copy()
future_labels.loc[future_labels.label_end_return_4 > cut, 'return_4'] = .9
changed, _ = kernel.forecasts(future_features, future_labels, future_old, prob, gain)
pd.testing.assert_frame_equal(changed, scores.loc[keep], check_exact=True)

refused = 0
for families in ((), ('confirmation', 'confirmation'), ('unknown',)):
    try:
        kernel.forecasts(features, labels, old, prob, gain, families=families)
    except ValueError:
        refused += 1
    else:
        raise AssertionError('Invalid family subset accepted')
for kind in ('infinite_feature', 'feature_columns', 'old_columns', 'order', 'label_axis', 'infinite_y', 'bad_factor', 'unpaired_maturity', 'not_future', '2020_old', 'timezone'):
    bad_features, bad_labels, bad_old = features.copy(), labels.copy(), old.copy()
    if kind == 'infinite_feature':
        bad_features.iloc[120, 0] = np.inf
    elif kind == 'feature_columns':
        bad_features = bad_features.iloc[:, ::-1]
    elif kind == 'old_columns':
        bad_old = bad_old.iloc[:, ::-1]
    elif kind == 'order':
        bad_features, bad_labels, bad_old = bad_features.iloc[::-1], bad_labels.iloc[::-1], bad_old.iloc[::-1]
    elif kind == 'label_axis':
        bad_labels.index = bad_labels.index + pd.Timedelta(days=1)
    elif kind == 'infinite_y':
        bad_labels.iloc[120, 0] = np.inf
    elif kind == 'bad_factor':
        bad_labels.iloc[120, 0] = -1.
    elif kind == 'unpaired_maturity':
        bad_labels.iloc[120, 1] = pd.NaT
    elif kind == 'not_future':
        bad_labels.iloc[120, 1] = axis[120]
    elif kind == '2020_old':
        bad_old.iloc[0, 0] = 0.
    else:
        bad_features.index = bad_features.index.tz_localize('UTC')
        bad_labels.index = bad_old.index = bad_features.index
    try:
        kernel.forecasts(bad_features, bad_labels, bad_old, prob, gain)
    except ValueError:
        refused += 1
    else:
        raise AssertionError('Invalid online PG input accepted: ' + kind)

output = {'status': 'PASS', 'checks': ['Exact historical forecast reuse', 'Expanding mature training only',
          'Current and training original14 complete', 'Delayed labels excluded', 'Zero net truth is nonpositive',
          'All valid probability/gain gradients stationary', 'Cross-year state not reset', 'Prefix exact',
          'Unmatured extreme truth cannot change past', 'Feature-only tail retained', 'All48 clocks and500x12 bootstrap',
          'Single-family merge exact to default', 'Summarize equals analyze', 'Two-process BLAS1 worker score and trace exact'],
          'refusals': refused, 'artificial_signals': 400, 'synthetic_fit_count': stationary,
          'real_inputs': 0, 'real_statistics': 0, 'new_accounts': 0, 'experiment_allocation': 0,
          'files': {name: sha256((WORK / name).read_bytes()).hexdigest() for name in ('kernel.py', 'focused_checks.py', 'worker.py')}}
with (WORK / 'focused_checks.json').open('w', encoding='utf-8') as stream:
    json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
print({'status': 'PASS', 'checks': len(output['checks']), 'refusals': refused, 'synthetic_fit_count': stationary, 'real_inputs': 0})
