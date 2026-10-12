"""Synthetic causal forecast calibration checks; real input reads are forbidden."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

import kernel

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[2]
spec = importlib.util.spec_from_file_location('calibration_synthetic_clock', ROOT / 'research/S013/experiments/EX083_20261012/src/kernel.py')
clock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clock)

axis = pd.bdate_range('2020-09-01', periods=400).as_unit('ns')
rng = np.random.default_rng(79)
scores = pd.DataFrame(rng.normal(.004, .002, (400, 2)), index=axis, columns=kernel.INPUTS)
scores.loc[axis.year == 2020] = np.nan
scores.iloc[115, 1] = np.nan
y = rng.normal(.002, .015, 400)
y[-5:] = np.nan
labels = pd.DataFrame({'return_4': y, 'label_end_return_4': pd.Series(axis, index=axis).shift(-5)}, index=axis)
states, signals, result = kernel.analyze(scores, labels, clock)
assert result['schedule_count'] == 48
assert len(result['bootstrap']['records']) == 500
assert tuple(result['bootstrap']['summary']) == kernel.QUANTITIES
first = np.flatnonzero(scores.iloc[:, 0].notna())[0]
assert not states.iloc[first:first + 24].confirmation_available.any()
assert states.iloc[first + 24].confirmation_available
first_trace = next(row for row in result['state_traces'] if row['family'] == 'confirmation' and row['available'])
assert first_trace['positions'] == list(range(first, first + 20))
assert first_trace['max_maturity'] == axis[first + 24].isoformat()
assert np.isnan(signals.iloc[115].original14_calibrated)
assert all(115 not in row['positions'] for row in result['state_traces'] if row['family'] == 'original14')
for family, name in zip(kernel.FAMILIES, kernel.INPUTS):
    np.testing.assert_array_equal(signals[family + '_historical'], scores[name])
    for row in result['state_traces']:
        if row['family'] != family or not row['available']:
            continue
        date = pd.Timestamp(row['signal_date'])
        ids = row['positions']
        expected = float(scores.loc[date, name] + np.mean(labels.return_4.iloc[ids].to_numpy() - scores[name].iloc[ids].to_numpy()))
        assert signals.loc[date, family + '_calibrated'] == expected
        np.testing.assert_allclose(expected, signals.loc[date, family + '_rawmean'] + scores.loc[date, name] - states.loc[date, family + '_past20_forecast_mean'], rtol=0, atol=2e-14)
        assert all(axis[j] < date and labels.label_end_return_4.iloc[j] <= date for j in ids)

cut = axis[axis.year == 2022][0]
keep = axis <= cut
ss, dd, _ = kernel.decisions(scores.loc[keep], labels.loc[keep])
pd.testing.assert_frame_equal(ss, states.loc[keep], check_exact=True)
pd.testing.assert_frame_equal(dd, signals.loc[keep], check_exact=True)
crossing = [row for row in result['state_traces'] if row['signal_date'] == cut.isoformat()]
assert len(crossing) == 2 and all(row['available'] and row['model_year_crossing'] for row in crossing)

future_scores = scores.copy()
future_scores.loc[axis > cut] *= -50
future_labels = labels.copy()
future_labels.loc[labels.label_end_return_4 > cut, 'return_4'] = .8
ss, dd, _ = kernel.decisions(future_scores, future_labels)
pd.testing.assert_frame_equal(ss.loc[keep], states.loc[keep], check_exact=True)
pd.testing.assert_frame_equal(dd.loc[keep], signals.loc[keep], check_exact=True)
missing_q_labels = labels.copy()
missing_q_labels.iloc[115, missing_q_labels.columns.get_loc('return_4')] = .9
ss, dd, _ = kernel.decisions(scores, missing_q_labels)
pd.testing.assert_frame_equal(ss.filter(like='original14'), states.filter(like='original14'), check_exact=True)
pd.testing.assert_frame_equal(dd.filter(like='original14'), signals.filter(like='original14'), check_exact=True)
assert signals.iloc[-5:].notna().all().all()

refused = 0
for kind in ('infinite_q', '2020_q', 'order', 'columns', 'label_axis', 'infinite_y', 'bad_factor', 'unpaired_maturity', 'not_future', 'timezone', 'intraday_maturity'):
    bad_scores, bad_labels = scores.copy(), labels.copy()
    if kind == 'infinite_q':
        bad_scores.iloc[120, 0] = np.inf
    elif kind == '2020_q':
        bad_scores.iloc[0, 0] = 0.
    elif kind == 'order':
        bad_scores, bad_labels = bad_scores.iloc[::-1], bad_labels.iloc[::-1]
    elif kind == 'columns':
        bad_scores = bad_scores.iloc[:, ::-1]
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
    elif kind == 'timezone':
        bad_scores.index = bad_scores.index.tz_localize('UTC')
        bad_labels.index = bad_scores.index
    else:
        bad_labels.iloc[120, 1] += pd.Timedelta(hours=1)
    try:
        kernel.decisions(bad_scores, bad_labels)
    except ValueError:
        refused += 1
    else:
        raise AssertionError('Invalid causal calibration input accepted: ' + kind)

output = {'status': 'PASS', 'checks': ['Exact historical forecasts', 'Full20 mature issued forecast support',
          'Same-day maturity allowed', 'No missing-q residual creation', 'Scalar20 calibration and identity',
          'Causal prefix invariant', 'Unmatured extreme truth and future forecasts cannot change past',
          'Cross-year state continues', 'Feature-only tail and strict missingness', 'All48 clocks and500x12 bootstrap quantities'],
          'refusals': refused, 'artificial_signals': 400, 'real_inputs': 0, 'real_statistics': 0,
          'new_annual_models': 0, 'new_accounts': 0, 'experiment_allocation': 0,
          'files': {name: sha256((WORK / name).read_bytes()).hexdigest() for name in ('kernel.py', 'focused_checks.py')}}
with (WORK / 'focused_checks.json').open('w', encoding='utf-8') as stream:
    json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
print({'status': 'PASS', 'checks': len(output['checks']), 'refusals': refused, 'real_inputs': 0})
