"""Synthetic EX083 causal clocks, partition and concentration boundary checks."""
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
import pandas as pd
import kernel
import audit

WORK = Path(__file__).resolve().parent
axis = pd.bdate_range('2020-10-01', periods=500).as_unit('ns')
rng = np.random.default_rng(71)
scores = pd.DataFrame(rng.normal(.001, .008, (500, 6)), index=axis, columns=kernel.MODELS)
scores.loc[axis.year == 2020] = np.nan
scores.iloc[270:278] = np.nan
y = rng.normal(.001, .02, 500)
y[-5:] = np.nan
labels = pd.DataFrame({'return_4': y, 'label_end_return_4': pd.Series(axis, index=axis).shift(-5)}, index=axis)
kernel.validate(scores, labels)
result = {'schedules': {m: {c: kernel.schedule(axis, scores[m].to_numpy(), y, c) for c in kernel.CLOCKS} for m in kernel.MODELS},
          'bootstrap': kernel.bootstrap(y, scores.to_numpy())}
proof = audit.verify(scores, labels, result)
assert proof['status'] == 'PASS'
for clock in kernel.CLOCKS:
    mask = kernel.entries(scores.calendar_only.to_numpy(), clock)
    assert (np.diff(np.flatnonzero(mask)) >= 5).all()
    prefix = kernel.entries(scores.calendar_only.iloc[:281].to_numpy(), clock)
    np.testing.assert_array_equal(mask[:281], prefix)
    changed = scores.calendar_only.to_numpy().copy()
    changed[281:] *= -3
    np.testing.assert_array_equal(mask[:281], kernel.entries(changed, clock)[:281])
assert np.flatnonzero(kernel.entries(np.ones(11), 'greedy')).tolist() == [0, 5, 10]
assert kernel.schedule(axis[:11], np.ones(11), np.r_[np.zeros(10), np.nan], 'greedy')['missing_truth_accepted'] == 1
sample = np.array([.10, .10, .01, -.05, 0.])
a = kernel.attribution(sample, np.ones(5, bool), np.ones(5, bool))
assert a['top_positive_count'] == 1 and a['best_positive_positions'] == [0]
np.testing.assert_allclose(a['top_positive_contribution'], .10/.21)
neg = kernel.attribution(np.array([-.1, 0.]), np.ones(2, bool), np.ones(2, bool))
assert neg['best_positive_contribution'] is None and neg['compound_without_best_positive'] is None
refused = 0
cases = []
bad = scores.copy()
bad.iloc[90, 0] = np.inf
cases.append((bad, labels))
bad = scores.copy()
bad.iloc[0] = 0.
cases.append((bad, labels))
bad = labels.copy()
bad.iloc[80, 1] = axis[80]
cases.append((scores, bad))
bad = scores.copy()
bad.iloc[90, 0] = np.nan
cases.append((bad, labels))
for args in cases:
    try:
        kernel.validate(*args)
    except ValueError:
        refused += 1
    else:
        raise AssertionError('Illegal method inputs admitted')
output = {'status': 'PASS', 'artificial_signals': 500, 'real_inputs': 0, 'real_statistics': 0,
          'new_models': 0, 'new_accounts': 0, 'experiment_allocation': 0, 'refusals': refused,
          'checks': ['Independent36clock schedules and all288panels', 'Causal prefixes and future score alteration',
                     'No sameT reentry and min5gap', 'Truthless final intention preserved',
                     'Topceil10% positive contribution and deterministic ties', 'No winners yields unavailable omission',
                     'Shared500×9fullT bootstrap quantities'],
          'independent': proof, 'files': {name: sha256((WORK/name).read_bytes()).hexdigest() for name in ('kernel.py','audit.py','focused_checks.py')}}
with (WORK/'focused_checks.json').open('x',encoding='utf-8') as stream:
    json.dump(output,stream,ensure_ascii=False,indent=2,allow_nan=False)
print({'status':'PASS','checks':len(output['checks']),'refusals':refused,'real_inputs':0})
