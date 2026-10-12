"""Artificial fixed co-down paths: no real inputs or labels are read."""
from hashlib import sha256
import json
from math import fsum, log, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

import features

WORK = Path(__file__).resolve().parent


def path(a, b, index):
    rows = [[100., 100.]]
    previous = 100.
    for gap_loss, body_loss in zip(a, b):
        opening = previous * np.exp(-gap_loss)
        closing = opening * np.exp(-body_loss)
        rows.append([opening, closing])
        previous = closing
    return pd.DataFrame(rows, index=index, columns=['open', 'close'])


calendar = pd.bdate_range('2019-10-01', periods=500).as_unit('ns')
rng = np.random.default_rng(92)
a = rng.uniform(-.005, .012, 499)
b = rng.uniform(-.005, .012, 499)
prices = path(a, b, calendar)
frame, traces = features.build(prices, calendar, calendar)
assert frame.iloc[:20].isna().all().all()
assert frame.iloc[20:].notna().all().all()
assert all(row['reason'] == 'INSUFFICIENT_HISTORY' for row in traces[:20])
assert all(row['window_complete'] and row['predecessor_position'] == i - 20 and row['window_positions'] == list(range(i - 19, i + 1)) for i, row in enumerate(traces) if i >= 20)
scalar_windows = 0
for i in range(20, len(calendar)):
    left = i - 19
    aa = [max(-(log(float(prices.iloc[j].open)) - log(float(prices.iloc[j - 1].close))), 0.) for j in range(left, i + 1)]
    bb = [max(-(log(float(prices.iloc[j].close)) - log(float(prices.iloc[j].open))), 0.) for j in range(left, i + 1)]
    ma, mb = fsum(aa) / 20, fsum(bb) / 20
    ea, eb = fsum(x * x for x in aa) / 20, fsum(x * x for x in bb) / 20
    numerator = fsum(x * z for x, z in zip(aa, bb)) / 20 - ma * mb
    expected = [numerator / sqrt(ea * eb), ma, mb, sqrt(ea), sqrt(eb), sum(x > 0 for x in aa) / 20, sum(x > 0 for x in bb) / 20]
    np.testing.assert_allclose(frame.iloc[i].to_numpy(), expected, atol=2e-13, rtol=2e-11)
    scalar_windows += 1

axis = calendar[calendar.year >= 2020]
selected, selected_trace = features.build(prices, axis, calendar)
pd.testing.assert_frame_equal(selected, frame.loc[axis], check_exact=True)
assert all(pd.Timestamp(row['signal_date']).year >= 2020 for row in selected_trace)
assert tuple(selected.columns) == features.COLUMNS and not any('label' in name or 'return_4' in name for name in selected.columns)
cut = calendar[calendar.year == 2021][0]
prefix_calendar = calendar[calendar <= cut]
prefix_axis = axis[axis <= cut]
prefix, prefix_trace = features.build(prices.loc[prefix_calendar], prefix_axis, prefix_calendar)
pd.testing.assert_frame_equal(prefix, selected.loc[prefix_axis], check_exact=True)
assert prefix_trace == selected_trace[:len(prefix_trace)]
changed = prices.copy()
changed.loc[calendar > cut] *= .013
future_changed, _ = features.build(changed, axis, calendar)
pd.testing.assert_frame_equal(future_changed.loc[prefix_axis], selected.loc[prefix_axis], check_exact=True)
scaled, _ = features.build(prices * 7.25, axis, calendar)
np.testing.assert_allclose(scaled.to_numpy(), selected.to_numpy(), atol=2e-12, rtol=2e-10, equal_nan=True)
cross = selected_trace[axis.get_loc(cut)]
assert cross['window_complete'] and any(pd.Timestamp(date).year == 2020 for date in cross['window_dates'])

short_calendar = pd.bdate_range('2020-01-02', periods=21).as_unit('ns')
fixed_a = np.tile([0., .002, .008, .014], 5)
fixed_b = np.tile([0., .003, .009, .015], 5)
paired = path(fixed_a, fixed_b, short_calendar)
repaired = path(fixed_a, fixed_b[::-1], short_calendar)
first, _ = features.build(paired, short_calendar, short_calendar)
second, _ = features.build(repaired, short_calendar, short_calendar)
np.testing.assert_allclose(first.iloc[-1, 1:], second.iloc[-1, 1:], atol=2e-13, rtol=2e-11)
assert abs(first.iloc[-1, 0] - second.iloc[-1, 0]) > .1

zero_gap = path(np.zeros(20), fixed_b, short_calendar)
zero_body = path(fixed_a, np.zeros(20), short_calendar)
for zero_path in (zero_gap, zero_body):
    zero_frame, zero_trace = features.build(zero_path, short_calendar, short_calendar)
    assert np.isnan(zero_frame.iloc[-1, 0]) and zero_frame.iloc[-1, 1:].notna().all()
    assert zero_trace[-1]['reason'] == 'ZERO_NEGATIVE_ENERGY_DENOMINATOR'

# Constant negative legs provide a true zero centered numerator with positive energy.
constant_a = np.full(20, .125)
constant_b = np.full(20, .25)
constant_frame, constant_trace = features.build(path(constant_a, constant_b, short_calendar), short_calendar, short_calendar)
assert constant_trace[-1]['denominator'] > 0
assert constant_trace[-1]['numerator'] == 0 and constant_frame.iloc[-1, 0] == 0
assert constant_trace[-1]['reason'] == 'AVAILABLE'

refused = 0
for kind in ('missing_session', 'duplicate_prices', 'unordered_prices', 'zero_price', 'infinite_price', 'missing_price', 'bad_columns', 'axis_outside', 'axis_gap', 'calendar_duplicate', 'timezone', 'intraday'):
    pp, aa, cc = prices.copy(), axis.copy(), calendar.copy()
    if kind == 'missing_session':
        pp = pp.drop(pp.index[100])
    elif kind == 'duplicate_prices':
        pp.index = pd.DatetimeIndex([pp.index[0], *pp.index[:-1]])
    elif kind == 'unordered_prices':
        pp = pp.iloc[::-1]
    elif kind == 'zero_price':
        pp.iloc[30, 0] = 0
    elif kind == 'infinite_price':
        pp.iloc[30, 0] = np.inf
    elif kind == 'missing_price':
        pp.iloc[30, 0] = np.nan
    elif kind == 'bad_columns':
        pp = pp.rename(columns={'open': 'Open'})
    elif kind == 'axis_outside':
        aa = aa.union(pd.DatetimeIndex([cc[-1] + pd.Timedelta(days=1)]))
    elif kind == 'axis_gap':
        aa = aa.delete(20)
    elif kind == 'calendar_duplicate':
        cc = pd.DatetimeIndex([cc[0], *cc[:-1]])
    elif kind == 'timezone':
        pp.index, aa, cc = pp.index.tz_localize('UTC'), aa.tz_localize('UTC'), cc.tz_localize('UTC')
    else:
        pp.index = pp.index + pd.Timedelta(hours=1)
        cc, aa = cc + pd.Timedelta(hours=1), aa + pd.Timedelta(hours=1)
    try:
        features.build(pp, aa, cc)
    except ValueError:
        refused += 1
    else:
        raise AssertionError('Invalid co-down input accepted: ' + kind)

output = {'status': 'PASS', 'checks': ['Full20 plus preceding Close required', 'All480 scalar sliding windows',
          'Axis-only outputs and no2019labels', 'Causal prefix and future mutation invariance',
          'Cross-year history not reset', 'Marginals unchanged with different daily pairing',
          'Zero negative energy is explicit NA', 'Zero centered numerator never mapped to missing',
          'Constant price-unit scaling invariant', 'Exact declared calendar and strict inputs'],
          'refusals': refused, 'artificial_calendar_rows': 500, 'scalar_windows': scalar_windows,
          'real_inputs': 0, 'real_statistics': 0, 'new_models': 0, 'new_accounts': 0, 'experiment_allocation': 0,
          'files': {name: sha256((WORK / name).read_bytes()).hexdigest() for name in ('features.py', 'checks.py')}}
with (WORK / 'checks.json').open('w', encoding='utf-8') as stream:
    json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
print({'status': 'PASS', 'checks': len(output['checks']), 'refusals': refused, 'real_inputs': 0})
