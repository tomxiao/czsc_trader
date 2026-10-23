"""Focused synthetic feature checks; reads only the historical session-date axis."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fixed_price_features', HERE/'src/features.py')
features = importlib.util.module_from_spec(spec)
spec.loader.exec_module(features)
COLS = [c for family in features.FEATURES.values() for c in family]


def main():
    dates = pd.to_datetime(pd.read_csv(HERE.parent/'EX034_20261023/others/adjusted_prices.csv', usecols=['Date']).Date)
    if len(dates) != 509:
        raise AssertionError('Expected the actual 509-session calendar axis')
    records = []

    def check(name, action):
        action()
        records.append({'name': name, 'status': 'PASS'})

    def synthetic(pattern, varying=True):
        daily, bars = [], []
        last = 100.0
        for i, date in enumerate(dates):
            u = np.asarray(pattern, float) * (1+0.1*(i % 7) if varying else 1.0)
            path = last*np.exp(np.r_[0.0, np.cumsum(u)])
            daily.append(dict(Date=date, Open=path[0], High=path.max(), Low=path.min(), Close=path[-1]))
            if i >= 75:
                for j, time in enumerate(features.TIMES):
                    bars.append(dict(Date=pd.Timestamp(f'{date.date()} {time}'), Open=path[j],
                                     High=max(path[j:j+2]), Low=min(path[j:j+2]), Close=path[j+1]))
            last = float(path[-1])
        d = pd.DataFrame(daily)
        return d, d.copy(), pd.DataFrame(bars)

    def equal(actual, expected, atol=2e-10):
        np.testing.assert_allclose(np.asarray(actual, float), np.asarray(expected, float), rtol=2e-10, atol=atol)

    def rejects(triple):
        try:
            features.build(*triple)
        except ValueError:
            return
        raise AssertionError('Illegal input was accepted')

    flat = synthetic([0]*8)
    flat_x = features.build(*flat)
    check('flat_observed_prices_all_24_zero_and_434_rows', lambda: equal(flat_x[COLS], np.zeros((434,24))))

    up = synthetic([.001]*8)
    down = synthetic([-.001]*8)
    up_x, down_x = features.build(*up), features.build(*down)
    for name, x, sign in [('up', up_x, 1), ('down', down_x, -1)]:
        for col in ['efficiency5', 'intraday_efficiency', 'semivariance_balance', 'largest_step_balance',
                    'run_length_balance', 'close_location', 'open_side_occupation', 'excursion_balance']:
            check(f'monotone_{name}_{col}', lambda x=x, col=col, sign=sign: equal(x[col], sign))
        check(f'monotone_{name}_step_persistence', lambda x=x: equal(x.step_persistence, 1))
        check(f'monotone_{name}_distributed_energy', lambda x=x: equal(x.shock_concentration, 1/8))
        check(f'monotone_{name}_no_gap', lambda x=x: equal(x.gap_energy_share, 0))
        check(f'monotone_{name}_no_wicks', lambda x=x: equal(x.wick_rejection, 0))

    recovery = synthetic([-.001]*4+[.001]*4)
    retrace = synthetic([.001]*4+[-.001]*4)
    recovery_x, retrace_x = features.build(*recovery), features.build(*retrace)
    check('reversed_paths_same_endpoint_intraday_return', lambda: equal(recovery_x.intraday_efficiency, retrace_x.intraday_efficiency))
    check('decline_then_recovery_positive_halfday_balance', lambda: equal(recovery_x.halfday_balance, 1))
    check('rise_then_retrace_negative_halfday_balance', lambda: equal(retrace_x.halfday_balance, -1))
    check('decline_then_recovery_positive_return_time_balance', lambda: equal(recovery_x.return_time_balance, 4/7))
    check('rise_then_retrace_negative_return_time_balance', lambda: equal(retrace_x.return_time_balance, -4/7))
    check('recovery_path_negative_open_occupation', lambda: equal(recovery_x.open_side_occupation, -7/8))
    check('retrace_path_positive_open_occupation', lambda: equal(retrace_x.open_side_occupation, 7/8))
    check('equal_negative_steps_choose_earliest_recovery', lambda: equal(recovery_x.post_drop_recovery, 1/7))
    check('equal_negative_steps_choose_earliest_retrace', lambda: equal(retrace_x.post_drop_recovery, -1))

    # Independent scaling of adjusted and raw sources must preserve dimensions.
    scaled = [f.copy() for f in recovery]
    for f, factor in zip(scaled, [3.7, .8, .8]):
        f.loc[:, ['Open','High','Low','Close']] *= factor
    check('independent_adjusted_raw_price_unit_invariance', lambda: equal(features.build(*scaled)[COLS], recovery_x[COLS]))

    # Reciprocal prices reverse log increments. Arithmetic OHLC expressions
    # intentionally have no asserted exact reciprocal symmetry.
    varied = synthetic([.002,-.001,.003,-.002,.001,-.003,.002,.001])
    mirror = []
    for f in varied:
        out = f.copy()
        out['Open'] = 10000/f.Open; out['Close'] = 10000/f.Close
        out['High'] = 10000/f.Low; out['Low'] = 10000/f.High
        mirror.append(out)
    v, m = features.build(*varied), features.build(*mirror)
    varied_scaled = [f.copy() for f in varied]
    for f, factor in zip(varied_scaled, [3.7, .8, .8]):
        f.loc[:, ['Open','High','Low','Close']] *= factor
    check('varied_path_all_features_price_unit_invariance', lambda: equal(features.build(*varied_scaled)[COLS], v[COLS]))
    odd = ['drift5_scaled','efficiency5','intraday_efficiency','semivariance_balance',
           'largest_step_balance','run_length_balance','open_side_occupation',
           'return_time_balance','extrema_order','excursion_balance','halfday_balance','drift_acceleration']
    even = ['step_persistence','shock_concentration','gap_energy_share','direction_alignment','intraday_daily_energy']
    for col in odd:
        check(f'reciprocal_log_path_odd_{col}', lambda col=col: equal(m[col], -v[col]))
    for col in even:
        check(f'reciprocal_log_path_even_{col}', lambda col=col: equal(m[col], v[col]))

    for n in [1,2,20,100,434]:
        prefix = (varied[0].iloc[:75+n], varied[1].iloc[:75+n], varied[2].iloc[:8*n])
        check(f'causal_aligned_prefix_{n}', lambda n=n,prefix=prefix: equal(features.build(*prefix)[COLS], v[COLS].iloc[:n]))

    def mutation(which, edit):
        copy = [f.copy() for f in varied]
        edit(copy[which])
        return copy

    bad_inputs = {
      'missing_ohlc_field': mutation(0, lambda f: f.drop(columns='Low', inplace=True)),
      'nonfinite_price': mutation(0, lambda f: f.__setitem__('Open', f.Open.mask(f.index == 100, np.nan))),
      'negative_price': mutation(1, lambda f: f.__setitem__('Close', f.Close.mask(f.index == 100, -1))),
      'high_below_close': mutation(2, lambda f: f.__setitem__('High', f.High.mask(f.index == 3, 1))),
      'duplicate_date': mutation(0, lambda f: f.__setitem__('Date', f.Date.mask(f.index == 5, f.Date.iloc[4]))),
      'missing_bar': mutation(2, lambda f: f.drop(index=3, inplace=True)),
      'wrong_bar_time': mutation(2, lambda f: f.__setitem__('Date', f.Date.mask(f.index == 3, f.Date.iloc[3]+pd.Timedelta(minutes=1)))),
      'unexpected_bar_date': mutation(2, lambda f: f.__setitem__('Date', f.Date+pd.Timedelta(days=1))),
      'mismatched_daily_axis': mutation(1, lambda f: f.__setitem__('Date', f.Date+pd.Timedelta(days=1))),
    }
    for name, triple in bad_inputs.items():
        check(f'reject_{name}', lambda triple=triple: rejects(triple))

    result = {'status':'PASS','checks':len(records),'records':records,
      'data_use':'Only historical Date column read to construct synthetic inputs; no actual price features or performance computed.',
      'scope':'Focused synthetic shape, mathematical symmetry, price unit invariance, prefix causality and illegal-input checks; not exhaustive integration or performance acceptance.',
      'pre_freeze_correction':'Initial scale check exposed floating-point argmin selection among economically equal negative log steps. Before any feature/label result or formal freeze, post_drop_recovery was changed to choose the earliest negative step within a declared absolute 1e-12 log-return tie tolerance. Exact equal-step and scale invariance regressions now pass.',
      'symmetry_limit':'Arithmetic OHLC ratios and one-sided post_drop_recovery are not assumed exactly reciprocal-price symmetric.'}
    output = HERE/'others/synthetic_checks.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    print(json.dumps({'status':'PASS','checks':len(records),'output':str(output.relative_to(HERE))}))


if __name__ == '__main__':
    main()
