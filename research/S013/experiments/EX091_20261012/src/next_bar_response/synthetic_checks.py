"""Independent EX091 pure-feature audit synthetic boundary checks only."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd

WORK = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run():
    primary = load('next_response_primary_synthetic', WORK / 'features.py')
    audit = load('next_response_scalar_synthetic', WORK / 'audit_features.py')
    axis = pd.bdate_range('2021-11-01', periods=50).as_unit('ns')
    records = []
    for day_number, day in enumerate(axis):
        body = (-.012, .018, -.009, -.003, .008, -.004, .011, -.001)
        for j, clock in enumerate(audit.CLOCKS):
            records.append({'Date': day + pd.Timedelta(clock + ':00'), 'Open': 100.,
                            'Close': 100 * np.exp(body[j] + .0001 * np.sin(day_number + j)),
                            'Volume': float((j + 1) * (1 + day_number % 4))})
    bars = pd.DataFrame(records)
    checks, rejected = [], []
    outputs, traces = primary.build(bars, axis)
    proof = audit.verify(bars, axis, outputs, traces)
    checks.append('all50 scalar features and traces including calendar-year crossing')
    for limit in range(1, len(axis) + 1):
        f, t = primary.build(bars.iloc[:8 * limit], axis[:limit])
        audit.verify(bars.iloc[:8 * limit], axis[:limit], f, t)
        pd.testing.assert_frame_equal(f, outputs.iloc[:limit], check_exact=True)
        pd.testing.assert_frame_equal(t, traces.iloc[:limit], check_exact=True)
    checks.append('all50 prefix truncations invariant')
    selected_axis = axis[-10:]
    f, t = primary.build(bars, selected_axis)
    audit.verify(bars, selected_axis, f, t)
    pd.testing.assert_frame_equal(f, outputs.loc[selected_axis].rename_axis('Date'), check_exact=True)
    checks.append('selected axis retains full earlier profile history')
    assert traces.iloc[19].past_clock_samebar_reason == 'INSUFFICIENT_PAST20_FULL_SESSIONS'
    assert traces.iloc[20].past_window_dates == [d.isoformat() for d in axis[:20]]
    assert traces.iloc[20].past_clock_available
    altered = bars.copy()
    altered.loc[altered.Date.dt.normalize() == axis[20], 'Volume'] *= np.arange(1, 9)
    af, at = primary.build(altered, axis)
    audit.verify(altered, axis, af, at)
    assert at.iloc[20].past_clock_weights == traces.iloc[20].past_clock_weights
    assert at.iloc[21].past_clock_weights != traces.iloc[21].past_clock_weights
    checks.append('past20 excludes current profile and adapts next session')
    equal = bars.copy()
    equal.Volume = 1.
    f, t = primary.build(equal, axis)
    audit.verify(equal, axis, f, t)
    np.testing.assert_allclose(f.X, 0., atol=3e-17)
    checks.append('equal negative-source volumes make X zero')
    no_source = bars.copy()
    no_source.Close = no_source.Open
    no_source.loc[np.arange(len(no_source)) % 8 == 7, 'Close'] *= .99
    f, t = primary.build(no_source, axis)
    audit.verify(no_source, axis, f, t)
    assert f.sources_count.eq(0).all() and f.X.isna().all() and f.U.isna().all()
    assert t.iloc[-1].past_clock_next_response_reason == 'NO_NEGATIVE_SOURCE_PAIR'
    checks.append('last-bar negative body never becomes source; no-source remains NA')
    zero_successor = bars.copy()
    day_mask = zero_successor.Date.dt.normalize() == axis[25]
    zero_successor.loc[day_mask, 'Close'] = zero_successor.loc[day_mask, 'Open']
    zero_successor.loc[25 * 8, 'Close'] = 99.
    f, t = primary.build(zero_successor, axis)
    audit.verify(zero_successor, axis, f, t)
    assert f.iloc[25].X == f.iloc[25].S == f.iloc[25].U == 0.
    checks.append('actual zero successor response remains zero not missing')
    zero_source = bars.copy()
    for i in range(len(axis)):
        ids = [8 * i + j for j in traces.iloc[i].source_indices]
        zero_source.loc[ids, 'Volume'] = 0.
    f, t = primary.build(zero_source, axis)
    audit.verify(zero_source, axis, f, t)
    assert t.X_reason.eq('ZERO_SOURCE_VOLUME').all()
    assert f.X.isna().all() and f.U.notna().all()
    assert t.iloc[20].past_clock_next_response_reason == 'ZERO_PAST_CLOCK_SOURCE_WEIGHT'
    checks.append('zero source weights refuse X and future-clock projection')
    zero_day = bars.copy()
    zero_day.loc[zero_day.Date.dt.normalize() == axis[10], 'Volume'] = 0.
    f, t = primary.build(zero_day, axis)
    audit.verify(zero_day, axis, f, t)
    assert t.iloc[10].X_reason == 'ZERO_SESSION_VOLUME'
    assert t.iloc[30].past_clock_samebar_reason == 'ZERO_VOLUME_IN_PAST20_PROFILE'
    assert t.iloc[31].past_clock_available
    checks.append('zero whole profile invalidates exact20 without skipping; recovers after20')
    scaled = bars.copy()
    for i in range(len(axis)):
        ix = slice(8 * i, 8 * i + 7)
        scaled.loc[ix, ['Open', 'Close']] *= np.exp((i % 5) - 2)
        scaled.loc[ix, 'Volume'] *= 10. ** ((i % 3 - 1) * 100)
    sf, st = primary.build(scaled, axis)
    audit.verify(scaled, axis, sf, st)
    pd.testing.assert_frame_equal(sf, outputs, check_exact=False, atol=3e-13, rtol=2e-10)
    checks.append('per-session price and extreme volume unit scales invariant')
    for kind in ('missing_bar', 'wrong_clock', 'duplicate', 'unordered', 'nan_price', 'zero_price',
                 'negative_volume', 'nan_volume', 'missing_column', 'duplicate_column', 'non_datetime',
                 'timezone', 'nat', 'absent_axis', 'duplicated_axis', 'unordered_axis', 'intraday_axis',
                 'timezone_axis', 'empty_axis'):
        bad, aa = bars.copy(), axis.copy()
        if kind == 'missing_bar':
            bad = bad.drop(index=3)
        elif kind == 'wrong_clock':
            bad.loc[0, 'Date'] += pd.Timedelta(minutes=1)
        elif kind == 'duplicate':
            bad.loc[1, 'Date'] = bad.loc[0, 'Date']
        elif kind == 'unordered':
            bad = bad.iloc[::-1]
        elif kind == 'nan_price':
            bad.loc[0, 'Close'] = np.nan
        elif kind == 'zero_price':
            bad.loc[0, 'Open'] = 0.
        elif kind == 'negative_volume':
            bad.loc[0, 'Volume'] = -1.
        elif kind == 'nan_volume':
            bad.loc[0, 'Volume'] = np.nan
        elif kind == 'missing_column':
            bad = bad.drop(columns='Volume')
        elif kind == 'duplicate_column':
            bad = pd.concat([bad, bad[['Volume']]], axis=1)
        elif kind == 'non_datetime':
            bad.Date = bad.Date.astype(str)
        elif kind == 'timezone':
            bad.Date = bad.Date.dt.tz_localize('Asia/Shanghai')
        elif kind == 'nat':
            bad.loc[0, 'Date'] = pd.NaT
        elif kind == 'absent_axis':
            aa = pd.DatetimeIndex([axis[-1] + pd.Timedelta(days=10)])
        elif kind == 'duplicated_axis':
            aa = axis.insert(1, axis[0])
        elif kind == 'unordered_axis':
            aa = axis[::-1]
        elif kind == 'intraday_axis':
            aa += pd.Timedelta(minutes=1)
        elif kind == 'timezone_axis':
            aa = aa.tz_localize('Asia/Shanghai')
        elif kind == 'empty_axis':
            aa = pd.DatetimeIndex([])
        try:
            audit.reconstruct(bad, aa)
        except ValueError:
            rejected.append(kind)
        else:
            raise AssertionError('Independent audit accepted ' + kind)
    result = {'status': 'PASS', 'synthetic_only': True, 'real_inputs_read': 0,
              'accounts': 0, 'experiments_allocated': 0, 'regressions': 0,
              'checks': checks, 'check_count': len(checks), 'rejections': rejected,
              'rejection_count': len(rejected), 'scalar_verification': proof,
              'source_sha256': {name: sha256((WORK / name).read_bytes()).hexdigest()
                                for name in ('features.py', 'audit_features.py', 'synthetic_checks.py')}}
    (WORK / 'synthetic_checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({'status': 'PASS', 'checks': len(checks), 'refusals': len(rejected), 'real_inputs': 0})


if __name__ == '__main__':
    run()
