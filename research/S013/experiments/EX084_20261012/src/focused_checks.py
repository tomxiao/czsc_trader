"""Synthetic probability, payoff, causal annual training and clock checks."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
import kernel
import audit

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


clock = load('synthetic_clock', ROOT / 'research/S013/experiments/EX083_20261012/src/kernel.py')
clock_audit = load('synthetic_clock_audit', ROOT / 'research/S013/experiments/EX083_20261012/src/audit.py')
axis = pd.bdate_range('2020-09-01', periods=400).as_unit('ns')
rng = np.random.default_rng(93)
features = pd.DataFrame(rng.normal(size=(400, 14)), index=axis, columns=kernel.FEATURES)
features.iloc[:19, 6] = np.nan
y = .020 * features.momentum20.to_numpy() + .007 * features.confirmation_score.to_numpy() + rng.normal(0, .01, 400)
y[-5:] = np.nan
ends = pd.Series(axis, index=axis).shift(-5)
labels = pd.DataFrame({'return_4': y, 'label_end_return_4': ends}, index=axis)
prior = pd.DataFrame(np.nan, index=axis, columns=kernel.MODELS[:3])
complete = np.isfinite(features.to_numpy()).all(axis=1)
for year in (2021, 2022):
    first = axis[axis.year == year][0]
    train = complete & np.isfinite(y) & (axis.year < year) & (ends < first).to_numpy()
    test = complete & (axis.year == year)
    prior.loc[test, 'training_mean'] = audit.mean(y[train])
    prior.loc[test, 'confirmation_only'] = .001 * features.confirmation_score[test]
    prior.loc[test, 'original14_joint'] = .001 * features.momentum20[test]
probs, nets, result = kernel.analyze(features, labels, prior, clock)
proof = audit.verify(features, labels, prior, probs, nets, result, clock_audit)
assert proof['status'] == 'PASS'
for year, row in result['fit_years'].items():
    test = axis.year == int(year)
    p = row['payoffs']
    assert p is not None
    for probability, net in zip(kernel.PROBABILITIES[1:], kernel.MODELS[3:]):
        np.testing.assert_array_equal(nets.loc[test, net].to_numpy() > 0, probs.loc[test, probability].to_numpy() > p['break_even_probability'])
constant, _ = kernel.fit(np.zeros((60, 1)), np.r_[np.ones(40), np.zeros(20)], np.zeros((5, 1)))
np.testing.assert_allclose(constant, 2/3, atol=1e-14)
np.testing.assert_allclose(kernel.rank(np.array([0., 0., 2., 4.]), np.array([-1., 0., 4., 9.])), [-.5, -.25, .375, .5])
cut = axis[axis.year == 2022][0]
keep = axis <= cut
prefix_labels = labels.loc[keep].copy()
late = prefix_labels.label_end_return_4 > cut
prefix_labels.loc[late, 'return_4'] = np.nan
prefix_labels.loc[late, 'label_end_return_4'] = pd.NaT
pp, nn, _ = kernel.forecasts(features.loc[keep], prefix_labels, prior.loc[keep])
np.testing.assert_allclose(pp, probs.loc[keep], atol=3e-12, equal_nan=True)
np.testing.assert_allclose(nn, nets.loc[keep], atol=3e-12, equal_nan=True)
changed = features.copy()
changed.loc[axis > cut] *= -3
pp, nn, _ = kernel.forecasts(changed, labels, prior)
np.testing.assert_allclose(pp.loc[keep], probs.loc[keep], atol=3e-12, equal_nan=True)
np.testing.assert_allclose(nn.loc[keep], nets.loc[keep], atol=3e-12, equal_nan=True)
changed_labels = labels.copy()
changed_labels.loc[(axis.year == 2022) & np.isfinite(y), 'return_4'] += .4
pp, nn, _ = kernel.forecasts(features, changed_labels, prior)
np.testing.assert_allclose(pp, probs, atol=3e-12, equal_nan=True)
np.testing.assert_allclose(nn, nets, atol=3e-12, equal_nan=True)
assert probs.loc[axis.year == 2020].isna().all().all()
assert probs.iloc[-5:].notna().all().all() and nets.iloc[-5:, 3:].notna().all().all()
refused = 0
cases = []
bad = features.copy()
bad.iloc[31, 0] = np.inf
cases.append((bad, labels, prior))
bad = labels.copy()
bad.iloc[31, 1] = axis[31]
cases.append((features, bad, prior))
bad = prior.copy()
bad.iloc[0] = 0.
cases.append((features, labels, bad))
for args in cases:
    try:
        kernel.forecasts(*args)
    except ValueError:
        refused += 1
    else:
        raise AssertionError('Invalid method input admitted')
try:
    kernel.fit(np.zeros((40, 1)), np.ones(40), np.zeros((1, 1)))
except ValueError:
    refused += 1
else:
    raise AssertionError('One-class logistic fallback admitted')
output = {'status': 'PASS', 'checks': ['Scalar Newton logistic and payoffs independent', 'Economic zero threshold equals historical break-even probability',
          'Constant feature equals training class frequency', 'CDF midpoint ties and extremes', 'Annual maturity/prefix with only1current T',
          'Future test features and labels do not alter past forecasts', '2020unavailable and feature-only tail retained',
          'All30clocks and5000bootstrap quantities'], 'refusals': refused, 'artificial_signals': 400,
          'real_inputs': 0, 'real_statistics': 0, 'new_accounts': 0, 'experiment_allocation': 0, 'independent': proof,
          'files': {name: sha256((WORK/name).read_bytes()).hexdigest() for name in ('kernel.py', 'audit.py', 'focused_checks.py')}}
with (WORK/'focused_checks.json').open('x',encoding='utf-8') as stream:
    json.dump(output,stream,ensure_ascii=False,indent=2,allow_nan=False)
print({'status':'PASS','checks':len(output['checks']),'refusals':refused,'real_inputs':0})
