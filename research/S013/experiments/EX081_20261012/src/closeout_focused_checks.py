"""Synthetic-only method and causality checks before EX081 allocation."""
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
import pandas as pd
import kernel
import audit

WORK = Path(__file__).resolve().parent
rng = np.random.default_rng(41)
axis = pd.bdate_range('2020-09-01', periods=400).as_unit('ns')
features = pd.DataFrame(rng.normal(size=(400, 14)), index=axis, columns=kernel.FEATURES)
features['confirmation_score'] = rng.uniform(-.4, .4, 400)
features['momentum20'] = rng.uniform(-.15, .15, 400)
features.iloc[:19, features.columns.get_loc('intraday_energy20')] = np.nan
cf, state = features.confirmation_score.to_numpy(), np.sign(features.momentum20.to_numpy())
truth = .002 * cf + .001 * state + .025 * cf * state + rng.normal(0, .003, 400)
ends = pd.Series(axis, index=axis).shift(-5)
truth[-5:] = np.nan
labels = pd.DataFrame({'return_4': truth, 'label_end_return_4': ends}, index=axis)
prior = pd.DataFrame(np.nan, index=axis, columns=kernel.MODELS[:3])
complete = np.isfinite(features.to_numpy()).all(axis=1)
for year in (2021, 2022):
    first = axis[axis.year == year][0]
    train = complete & np.isfinite(truth) & (axis.year < year) & (ends < first).to_numpy()
    test = complete & (axis.year == year)
    rt = audit.cdf(cf[train], cf[train])
    rv = audit.cdf(cf[train], cf[test])
    expected, _ = audit.ridge([[v] for v in rt], truth[train], [[v] for v in rv])
    prior.loc[test, 'training_mean'] = audit.mean(truth[train])
    prior.loc[test, 'confirmation_only'] = expected
    prior.loc[test, 'original14_joint'] = expected  # Artificial prior identity, not actual old14.

np.testing.assert_allclose(kernel.rank(np.array([0., 0., 2., 4.]), np.array([-1., 0., 4., 9.])), [0., .25, .875, 1.])
same_cf = np.array([2., 2.])
z = kernel.design(np.array([0., 2., 4.]), same_cf, np.array([-1., 1.]), True)
assert z[0, 0] == z[1, 0] and z[0, 2] == -z[1, 2]
scores, result = kernel.analyze(features, labels, prior)
proof = audit.verify(features, labels, prior, scores, result)
assert proof['status'] == 'PASS' and scores.loc[axis.year == 2020].isna().all().all()

cut = axis[axis.year == 2022][0]
keep = axis <= cut
prefix_labels = labels.loc[keep].copy()
late = prefix_labels.label_end_return_4 > cut
prefix_labels.loc[late, 'return_4'] = np.nan
prefix_labels.loc[late, 'label_end_return_4'] = pd.NaT
prefix, _ = kernel.forecasts(features.loc[keep], prefix_labels, prior.loc[keep])
np.testing.assert_allclose(prefix.to_numpy(), scores.loc[keep].to_numpy(), atol=2e-12, equal_nan=True)
changed = features.copy()
changed.loc[axis > cut] *= -3
different, _ = kernel.forecasts(changed, labels, prior)
np.testing.assert_allclose(different.loc[keep].to_numpy(), scores.loc[keep].to_numpy(), atol=2e-12, equal_nan=True)
changed_truth = labels.copy()
changed_truth.loc[(axis.year == 2022) & np.isfinite(truth), 'return_4'] += .4
same, _ = kernel.forecasts(features, changed_truth, prior)
np.testing.assert_allclose(same.to_numpy(), scores.to_numpy(), atol=2e-12, equal_nan=True)
assert scores.loc[axis[-5:], kernel.NEW_MODELS].notna().all().all()

clock = kernel.episodes(pd.Series(np.ones(11), index=axis[:11]), np.r_[np.zeros(10), np.nan])
assert [x['position'] for x in clock['records']] == [0, 5, 10]
assert clock['accepted'] == 3 and clock['mature'] == 2 and clock['account_return'] is None
refused = 0
bad_cases = []
bad = labels.copy()
bad.iloc[35, bad.columns.get_loc('label_end_return_4')] = axis[35]
bad_cases.append((features, bad, prior))
bad = features.copy()
bad.iloc[21, 0] = np.inf
bad_cases.append((bad, labels, prior))
bad_cases.append((features.drop(columns=['acf1']), labels, prior))
bad = prior.copy()
bad.iloc[0] = 0.
bad_cases.append((features, labels, bad))
for args in bad_cases:
    try:
        kernel.forecasts(*args)
    except ValueError:
        refused += 1
    else:
        raise AssertionError('Invalid method input admitted')
output = {'status': 'PASS', 'artificial_signals': 400, 'checks': [
    'Training ECDF midpoint ties/extremes', 'Context interaction reverses with signed momentum',
    'Independent scalar annual centered ridge and all groups', 'All500 bootstrap records/10quantities',
    'Strict maturity and prefix with only1current test row', 'Future features do not alter past',
    'Future test labels do not alter same-year forecasts', '2020unavailable and feature-only tail retained',
    'Fourday exit priority, no same-signal reentry, missing terminal truth preserved'],
    'refusals': refused, 'independent': proof,
    'files': {name: sha256((WORK / name).read_bytes()).hexdigest() for name in ('kernel.py', 'audit.py', 'focused_checks.py')},
    'real_inputs': 0, 'real_statistics': 0, 'new_accounts': 0, 'experiment_allocation': 0, 'publication': 0}
with (WORK / 'focused_checks.json').open('x', encoding='utf-8') as stream:
    json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
print({'status': output['status'], 'checks': len(output['checks']), 'refusals': refused, 'real_inputs': 0})
