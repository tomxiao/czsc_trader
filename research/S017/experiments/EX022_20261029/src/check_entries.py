"""Synthetic pre-run checks of competing entry definitions; no historical outcomes."""
# ruff: noqa: E402
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
import numpy as np
import pandas as pd
from entries import NAMES, compute, scalar_at, predicates


def fixture():
    n = 340
    random = np.random.default_rng(23)
    close = 100+np.cumsum(random.normal(0, 1.8, n))
    high, low = close+random.uniform(.1, 2, n), close-random.uniform(.1, 2, n)
    ends = pd.date_range('2020-01-02', periods=n, freq='30min', tz='UTC')
    bars = pd.DataFrame({'Date': ends, 'BarStart': ends-pd.Timedelta(minutes=30),
                         'Open': close, 'High': high, 'Low': low, 'Close': close})
    # Deep but bounded move below the old mean supplies a known recent D.
    bars.loc[200:219, ['Open', 'High', 'Low', 'Close']] = [70, 71, 69, 70]
    bars.loc[207, ['Open', 'High', 'Low', 'Close']] = [69.5, 71, 68, 69.5]
    return bars


def worker(bars):
    flags, ready, facts = compute(bars)
    return flags.to_dict('list'), ready.tolist(), facts.to_json(double_precision=15)


def run():
    checks = []
    p = dict(background=True, current_d=True, close=10.1, previous_high=10,
             low=8, reference_low=8, reference_low_index=6, index=10,
             post_low_high=10, previous_atr=2, recent_low3=8, prior_low3=7, prior_high3=10)
    out = predicates(**p)
    assert out == {'B': True, 'C': True, 'F': False, 'T': True, 'H': True}
    assert predicates(**dict(p, low=9))['T']
    assert not predicates(**dict(p, low=9+1e-8))['T']
    assert not predicates(**dict(p, low=8-1e-8))['T']
    assert predicates(**dict(p, low=7.9))['F']
    assert not predicates(**dict(p, low=7.9, close=8))['F']
    assert not predicates(**dict(p, close=10))['T']
    assert predicates(**dict(p, reference_low_index=7))['T']
    assert not predicates(**dict(p, reference_low_index=8))['T']
    assert not predicates(**dict(p, post_low_high=10-1e-8))['T']
    assert not predicates(**dict(p, recent_low3=7))['H']
    assert not predicates(**dict(p, close=10))['H']
    assert not any(predicates(**dict(p, background=False, current_d=False)).values())
    checks.append('F_T_H_strict_and_inclusive_boundaries_and_background')
    bars = fixture()
    flags, ready, facts = compute(bars)
    assert not ready.iloc[:77].any() and ready.iloc[77:].all()
    assert not flags.iloc[:77].to_numpy().any()
    assert not facts.D.iloc[:65].notna().any() and facts.D.iloc[65:].notna().all()
    assert (flags.F <= flags.B).all() and (flags['T'] <= flags.B).all() and (flags.H <= flags.B).all()
    assert not (flags.F & flags['T']).any()
    checks.append('complete_D_background_history_and_signal_subsets')
    for i in range(77, len(bars)):
        assert flags.iloc[i].to_dict() == scalar_at(bars, i), i
    checks.append('independent_scalar_vector_full_synthetic_population')
    for cut in (77, 120, 201, 210, 260, 339):
        small_flags, small_ready, small_facts = compute(bars.iloc[:cut+1].copy())
        pd.testing.assert_frame_equal(small_flags, flags.iloc[:cut+1])
        pd.testing.assert_series_equal(small_ready, ready.iloc[:cut+1])
        pd.testing.assert_frame_equal(small_facts, facts.iloc[:cut+1])
    checks.append('future_suffix_does_not_change_past_flags_or_facts')
    # Each positive case is built as OHLC then checked through compute, not just predicates.
    f = bars.copy()
    f.loc[210, ['Open', 'High', 'Low', 'Close']] = [70, 72, 67, 71.5]
    ff, _, _ = compute(f)
    assert ff.iloc[210].F and not ff.iloc[210]['T']
    t = bars.copy()
    t.loc[208:209, ['Open', 'High', 'Low', 'Close']] = [70, 73, 69, 70]
    t.loc[210, ['Open', 'High', 'Low', 'Close']] = [70, 75, 68.5, 74]
    tf, _, tx = compute(t)
    assert tf.iloc[210]['T'] and not tf.iloc[210].F
    assert tx.iloc[210].reference_low_index == 207
    repeat = t.copy()
    repeat.loc[209, 'Low'] = 68
    rf, rr, rx = compute(repeat)
    assert rx.iloc[210].reference_low_index == 209 and not rf.iloc[210]['T'] and rr.iloc[210]
    assert rx.iloc[210].post_low_bars == 0 and np.isnan(rx.iloc[210].post_low_high)
    h = bars.copy()
    h.loc[205:207, ['Open', 'High', 'Low', 'Close']] = [70, 71, 67, 70]
    h.loc[208:209, ['Open', 'High', 'Low', 'Close']] = [70, 71, 69, 70]
    h.loc[210, ['Open', 'High', 'Low', 'Close']] = [71, 73, 69, 72]
    hf, _, _ = compute(h)
    assert hf.iloc[210].H
    for frame in (f, t, repeat, h):
        calculated, _, _ = compute(frame)
        assert calculated.iloc[210].to_dict() == scalar_at(frame, 210)
    checks.append('OHLC_positive_cases_last_low_and_empty_interval_not_excluded')
    flat = bars.copy()
    flat.loc[:, ['High', 'Low', 'Close']] = 100
    flat_flags, flat_ready, _ = compute(flat)
    assert not flat_ready.any() and not flat_flags.to_numpy().any()
    bad = bars.copy()
    bad.loc[100, 'Date'] = bad.loc[99, 'Date']
    try:
        compute(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('Duplicate dates must fail')
    checks.append('zero_volatility_unavailable_and_duplicate_time_rejected')
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        actual = list(pool.map(worker, [bars, t]))
    assert actual == [worker(bars), worker(t)]
    assert list(flags) == list(NAMES)
    checks.append('two_spawn_process_equivalence')
    return checks


if __name__ == '__main__':
    print('ENTRY_CHECKS_PASS', run(), flush=True)
