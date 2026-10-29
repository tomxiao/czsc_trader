"""Synthetic-only checks of numbered entry contracts and causality."""

import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor

# Set native-library limits before importing NumPy, including spawned children.
for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from numbered_entries import NAMES, compute, prepare_scalar, scalar_at  # noqa: E402


def sample():
    stamps = []
    for day in pd.bdate_range('2024-02-01', periods=34):
        for minute in range(570, 960, 30):
            stamps.append((day + pd.Timedelta(minutes=minute)).tz_localize(
                'America/New_York').tz_convert('UTC'))
    starts = pd.DatetimeIndex(stamps)
    return pd.DataFrame({'Date': starts + pd.Timedelta(minutes=30), 'BarStart': starts,
                         'Open': 100., 'High': 101., 'Low': 99., 'Close': 100.,
                         'Volume': 100.})


def candle(bars, offset, opening, high, low, close, volume=100.):
    bars.loc[bars.index[offset], ['Open', 'High', 'Low', 'Close', 'Volume']] = (
        opening, high, low, close, volume)


def checked_last(bars, number, expected):
    flags, ready, _ = compute(bars)
    assert ready.iloc[-1], 'Predicate failure must not remove a ready opportunity'
    assert bool(flags.iloc[-1][number]) is expected, (number, flags.iloc[-1])
    assert scalar_at(bars, len(bars) - 1) == flags.iloc[-1].to_dict()


def worker(bars):
    flags, ready, facts = compute(bars)
    return (flags.to_numpy().tolist(), ready.to_list(),
            facts.same_slot_volume_median20.fillna(-1).to_list())


def run():
    checks = []
    bars = sample()
    candle(bars, -2, 99., 100., 98., 98.)
    candle(bars, -1, 99., 100., 98., 99.1)
    checked_last(bars, NAMES[0], True)  # Drop exactly equals ATR13.
    candle(bars, -1, 99., 100., 98., 99.)
    checked_last(bars, NAMES[0], False)  # Half recovery equality is insufficient.
    candle(bars, -1, 99., 101., 98., 100.)
    candle(bars, -2, 99., 100., 98., 98.1)
    checked_last(bars, NAMES[0], False)
    checks.append('S017-M003_drop_inclusive_recovery_strict')

    bars = sample()
    candle(bars, -4, 100., 100.5, 97.5, 99.)
    candle(bars, -3, 99., 99.5, 97.5, 98.5)
    candle(bars, -2, 98.5, 98.75, 97.75, 98.)
    candle(bars, -1, 98., 100., 97.9, 99.)
    checked_last(bars, NAMES[1], True)
    original = bars.copy()
    candle(bars, -1, 98., 100., 97.9, 98.75)
    checked_last(bars, NAMES[1], False)
    bars = original.copy()
    candle(bars, -3, 99., 99.5, 96.5, 98.5)
    checked_last(bars, NAMES[1], False)
    bars = original.copy()
    candle(bars, -2, 98.5, 99., 97., 98.)
    checked_last(bars, NAMES[1], False)
    bars = original.copy()
    candle(bars, -4, 100., 100.5, 97.5, 98.)
    candle(bars, -3, 98., 99., 97., 98.)
    candle(bars, -2, 98., 98.5, 97.5, 98.)
    checked_last(bars, NAMES[1], False)
    checks.append('S017-M004_decline_count_and_strict_range_recovery')

    bars = sample()
    candle(bars, -2, 100., 100., 98., 99.5, 150.)
    candle(bars, -1, 99.5, 101., 99., 100.5)
    checked_last(bars, NAMES[2], True)  # Volume and range equality both inclusive.
    original = bars.copy()
    for column, value in [('Volume', 149.99), ('Open', 99.5), ('Low', 97.99)]:
        bars = original.copy()
        bars.loc[len(bars) - 2, column] = value
        checked_last(bars, NAMES[2], False)
    bars = original.copy()
    bars.loc[len(bars) - 1, 'Close'] = 100.
    checked_last(bars, NAMES[2], False)
    bars = original.copy()
    bars.loc[len(bars) - 2, 'Low'] = 80.
    _, _, facts = compute(bars)
    assert facts.atr_before_prior.iloc[-1] == 2.
    assert facts.previous_atr.iloc[-1] > facts.atr_before_prior.iloc[-1]
    checked_last(bars, NAMES[2], False)
    checks.append('S017-M005_inclusive_volume_range_strict_candle_recovery')
    checks.append('S017-M005_ATR_excludes_prior_TR')

    bars = sample()
    local = bars.BarStart.dt.tz_convert('America/New_York')
    prior = local.iloc[-2]
    same_slot = (local.dt.hour == prior.hour) & (local.dt.minute == prior.minute)
    indices = bars.index[same_slot]
    bars.loc[indices, 'Volume'] = np.arange(len(indices)) + 100.
    # Simulate a half-day: remove the reference slot, rather than insert zero.
    missing = indices[-10]
    missing_day = local.iloc[missing].date()
    half_day_afternoon = (local.dt.date == missing_day) & (local.dt.hour >= 13)
    bars = bars.loc[~half_day_afternoon].reset_index(drop=True)
    local = bars.BarStart.dt.tz_convert('America/New_York')
    prior = local.iloc[-2]
    eligible = ((local.dt.date < prior.date()) & (local.dt.hour == prior.hour)
                & (local.dt.minute == prior.minute))
    expected = float(bars.loc[eligible, 'Volume'].iloc[-20:].median())
    _, ready, facts = compute(bars)
    assert ready.iloc[-1] and facts.same_slot_volume_median20.iloc[-1] == expected
    assert facts.same_slot_history_count.iloc[-1] == 20
    # The UTC clock changes across DST, while local slot remains identical.
    assert bars.loc[eligible, 'BarStart'].dt.hour.nunique() == 2
    previous_median = facts.same_slot_volume_median20.iloc[-1]
    today = local.dt.date == prior.date()
    bars.loc[today, 'Volume'] = 1_000_000.
    assert compute(bars)[2].same_slot_volume_median20.iloc[-1] == previous_median
    assert scalar_at(bars, len(bars) - 1) == compute(bars)[0].iloc[-1].to_dict()
    checks.append('S017-M005_same_local_slot_DST_half_day_excludes_prior_day')

    bars = sample()
    flags, ready, facts = compute(bars)
    assert not ready.iloc[:20 * 13 + 1].any()
    assert ready.iloc[20 * 13 + 1:].all()
    assert not flags.to_numpy().any()  # Flat bars are ready but have no signal.
    assert scalar_at(bars, 20 * 13) is None
    checks.append('common_history_readiness_independent_of_shape')
    generator = np.random.default_rng(24029)
    close = 100. + np.cumsum(generator.normal(0., .4, len(bars)))
    opening = np.r_[100., close[:-1]]
    bars['Open'], bars['Close'] = opening, close
    bars['High'] = np.maximum(opening, close) + generator.uniform(.01, 1., len(bars))
    bars['Low'] = np.minimum(opening, close) - generator.uniform(.01, 1., len(bars))
    bars['Volume'] = generator.integers(10, 500, len(bars)).astype(float)
    flags, ready, facts = compute(bars)
    prepared = prepare_scalar(bars)
    assert all(not array.flags.writeable for array in prepared)
    for i in range(len(bars)):
        scalar = scalar_at(bars, i)
        assert scalar_at(bars, i, prepared=prepared) == scalar
        assert (scalar is not None) == bool(ready.iloc[i])
        if scalar is not None:
            assert scalar == flags.iloc[i].to_dict(), i
    checks.append('independent_scalar_all_synthetic_bars')
    checks.append('prepared_raw_readonly_scalar_matches_unprepared')
    cutoff = 350
    prefix_flags, prefix_ready, prefix_facts = compute(bars.iloc[:cutoff])
    pd.testing.assert_frame_equal(prefix_flags, flags.iloc[:cutoff])
    pd.testing.assert_series_equal(prefix_ready, ready.iloc[:cutoff])
    pd.testing.assert_frame_equal(prefix_facts, facts.iloc[:cutoff])
    altered = bars.copy()
    altered.loc[cutoff:, ['Open', 'High', 'Low', 'Close', 'Volume']] *= 10
    pd.testing.assert_frame_equal(compute(altered)[0].iloc[:cutoff], prefix_flags)
    pd.testing.assert_frame_equal(compute(altered)[2].iloc[:cutoff], prefix_facts)
    checks.append('future_suffix_prefix_and_mutation_causality')
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        first, second = list(pool.map(worker, [bars, bars]))
    assert first == second == worker(bars)
    checks.append('two_spawn_workers_identical_to_serial')
    return checks


if __name__ == '__main__':
    print({'status': 'PASS', 'checks': run()}, flush=True)
