"""Pure profit-latch synthetic semantics and public strategy adapter checks."""
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys
import types
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[2]
PACKAGE = '_s013_latch_synthetic'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(WORK / 'strategy_runtime')]
sys.modules[PACKAGE] = package
policy = importlib.import_module(PACKAGE + '.strategies.policy_kernel')
sigma_module = importlib.import_module(PACKAGE + '.strategies.locked_sigma')
adapter = importlib.import_module(PACKAGE + '.strategies.profit_latch_range')
parent = importlib.import_module(PACKAGE + '.strategies.boundary_bear_recovery_range')


def parameters():
    bear = {'acf_min': .1, 'cooldown': 0, 'entry': .9, 'exit': .99,
            'limit_premium': .01, 'max_hold': 4, 'momentum_min': None,
            'range_window': 120, 'stop_loss': None, 'trailing_stop': None}
    bull = {**bear, 'acf_min': None, 'entry': .675, 'exit': .95,
            'max_hold': 8, 'range_window': 180}
    return {'bear': bear, 'bull': bull,
            'confirmation': {'enabled': True, 'lookback': 120, 'orientation': 1,
                             'profile': 'all', 'scope': 'both', 'threshold': -.2},
            'context': {'entry_gate': 'all', 'volume_basis': 'ADJUSTED', 'weighting': 'EQUAL_BLOCKS'},
            'exit_on_regime_change': True, 'regime_threshold': 0., 'regime_window': 20,
            'mechanism': adapter.MECHANISM,
            'profit_latch': {'enabled': True, 'volatility_window': 20, 'activation_multiple': 1.0}}


def make_base(axis, prices):
    n = len(axis)
    close = np.r_[prices, np.full(n - len(prices), prices[-1])].astype(float)
    features = {route: pd.DataFrame({'range_position': np.full(n, .5), 'acf1': np.full(n, .2),
                                    'close': close, 'momentum20': np.full(n, .01)}, index=axis)
                for route in ('bull', 'bear')}

    def series(values):
        return pd.Series(values, index=axis)

    regimes = np.array(['bear'] * n)
    return {'features': features, 'score': series(np.full(n, .3)),
            'normalized': pd.DataFrame(.3, index=axis, columns=('acf', 'turnover', 'volume')),
            'signal_close': series(close), 'signal_open': series(close * .999),
            'previous_close': series(close), 'momentum': series(np.full(n, -.01)),
            'previous_momentum': series(np.full(n, -.01)), 'regimes': regimes,
            'previous_regimes': regimes.copy(), 'raw_bear_acf': features['bear'].acf1.copy(),
            'sigma_knowncurrent': series(np.full(n, .01))}


def run():
    checks, refusals = [], []
    p = parameters()
    axis = pd.bdate_range('2021-12-21', periods=30).as_unit('ns')
    base = make_base(axis, [100., 99., 102., 100.])
    table = policy.decisions(p, axis, base)
    assert table.iloc[1].signal_reason == 'hold' and not table.iloc[1].profit_latch_after
    assert table.iloc[2].profit_latch_activated and table.iloc[2].signal_reason == 'hold'
    assert table.iloc[3].signal_reason == 'profit_floor' and table.iloc[3].profit_floor_triggered
    assert not table.iloc[3].profit_latch_after and np.isnan(table.iloc[3].profit_sigma_after)
    assert table.iloc[4].last_exit_reason == 'profit_floor' and table.iloc[4].last_exit_category is None
    checks.append('early loss allowed before activation; profit floor later; nonTIME memory cleared')
    varying = make_base(axis, [100., 102., 100.5, 100.])
    varying['sigma_knowncurrent'].iloc[1:] = .5
    locked = policy.decisions(p, axis, varying)
    assert locked.iloc[1].profit_latch_activated and locked.iloc[1].profit_sigma_after == .01
    assert locked.iloc[2].profit_latch_after and locked.iloc[2].signal_reason == 'hold'
    assert locked.iloc[3].signal_reason == 'profit_floor'
    assert 100.5 / 102 - 1 < -.01
    checks.append('entry sigma locked; latch one-way; anchor floor differs from ordinary peak stop')
    near = make_base(axis, [100., 101., 100.])
    near['sigma_knowncurrent'][:] = np.log(101 / 100)
    tied = policy.decisions(p, axis, near)
    assert tied.iloc[1].profit_latch_activated and tied.iloc[2].signal_reason == 'profit_floor'
    low_gain = make_base(axis, [100., 100.1, 100.])
    low = policy.decisions(p, axis, low_gain)
    assert low.iloc[2].signal_reason == 'hold' and not low.iloc[2].profit_latch_after
    checks.append('activation exact positive equality accepted; subthreshold profit does not arm')
    zero = make_base(axis, [100., 100., 100.01, 100.])
    zero['sigma_knowncurrent'][:] = 0.
    zr = policy.decisions(p, axis, zero)
    assert not zr.iloc[0].profit_latch_after and not zr.iloc[1].profit_latch_after
    assert zr.iloc[2].profit_latch_activated and zr.iloc[3].signal_reason == 'profit_floor'
    checks.append('genuine zero sigma retained; zero gain never activates')
    for reason in ('loss', 'trailing', 'range', 'time', 'regime'):
        pp = deepcopy(p)
        bb = make_base(axis, [100., 102., 99.])
        if reason == 'loss':
            pp['bear']['stop_loss'] = .005
        elif reason == 'trailing':
            pp['bear']['trailing_stop'] = .01
        elif reason == 'range':
            bb['features']['bear'].loc[axis[2], 'range_position'] = pp['bear']['exit']
        elif reason == 'time':
            pp['bear']['max_hold'] = 2
        else:
            bb['regimes'][2:] = 'bull'
            bb['previous_regimes'][3:] = 'bull'
            bb['momentum'].iloc[2:] = .01
            bb['previous_momentum'].iloc[3:] = .01
        result = policy.decisions(pp, axis, bb)
        assert result.iloc[2].signal_reason == reason and not result.iloc[2].profit_floor_triggered
        assert not result.iloc[2].profit_latch_after
    checks.append('all five original exit classes precede profit_floor with original reason')
    persist = deepcopy(p)
    persist['exit_on_regime_change'] = False
    persist['bear']['max_hold'] = 60
    switched = make_base(axis, [100., 102., 101., 100.])
    switched['regimes'][2:] = 'bull'
    switched['previous_regimes'][3:] = 'bull'
    switched['momentum'].iloc[2:] = .01
    switched['previous_momentum'].iloc[3:] = .01
    active = policy.decisions(persist, axis, switched)
    assert active.iloc[2].profit_latch_after and active.iloc[2].signal_reason == 'hold'
    assert active.iloc[3].signal_reason == 'profit_floor'
    checks.append('raw regime flip without exit does not clear latch')
    crossed = deepcopy(p)
    crossed['bear']['max_hold'] = 60
    prices = np.full(len(axis), 101.)
    prices[0], prices[1] = 100., 102.
    crossing = axis.get_loc(axis[axis.year == 2022][0])
    prices[crossing:] = 100.
    rr = policy.decisions(crossed, axis, make_base(axis, prices))
    assert rr.iloc[crossing].profit_latch_before and rr.iloc[crossing].signal_reason == 'profit_floor'
    checks.append('latch and locked sigma do not reset at calendar-year boundary')
    for limit in range(1, len(axis) + 1):
        subset = {key: {route: frame.iloc[:limit] for route, frame in value.items()} if key == 'features'
                  else value.iloc[:limit] if isinstance(value, (pd.Series, pd.DataFrame)) else value[:limit]
                  for key, value in base.items()}
        pd.testing.assert_frame_equal(policy.decisions(p, axis[:limit], subset), table.iloc[:limit], check_exact=True)
    altered = deepcopy(base)
    altered['sigma_knowncurrent'].iloc[15:] = .4
    altered['features']['bear'].loc[axis[15]:, 'close'] = 1000.
    ar = policy.decisions(p, axis, altered)
    pd.testing.assert_frame_equal(ar.iloc[:15], table.iloc[:15], check_exact=True)
    checks.append('all30 prefixes and future state-input perturbations invariant')
    all_days = pd.bdate_range('2020-01-01', periods=320).as_unit('ns')
    z = np.arange(len(all_days))
    close = 100 * np.exp(.05 * np.sin(z / 4) + .02 * np.sin(z / 9) + .0001 * z)
    close_series = pd.Series(close, index=all_days)
    sessions = all_days[-100:]
    sigma = sigma_module.sigma_known(close_series, sessions, 20)
    for day, value in sigma.items():
        i = all_days.get_loc(day)
        window = close_series.iloc[i - 20:i + 1].to_numpy()
        expected = float(np.sqrt(np.mean(np.diff(np.log(window)) ** 2)))
        assert np.isclose(value, expected, atol=3e-15, rtol=2e-12)
    np.testing.assert_array_equal(sigma_module.sigma_known(pd.Series(100., index=all_days), sessions, 20), np.zeros(len(sessions)))
    prefix_sigma = sigma_module.sigma_known(close_series.iloc[:270], sessions[:50], 20)
    pd.testing.assert_series_equal(prefix_sigma, sigma.iloc[:50], check_exact=True)
    checks.append('known sigma includes exact T-L..T closes; RMS not demeaned; zero/prefix exact')
    open_price = close * np.exp(.004 * np.sin(z / 3))
    daily = pd.DataFrame({'Date': all_days, 'Open': open_price,
                          'High': np.maximum(open_price, close) * 1.01,
                          'Low': np.minimum(open_price, close) * .99, 'Close': close,
                          'Volume': 1000 * np.exp(.3 * np.sin(z / 5))})
    daily['Amount'] = daily.Volume * daily.Close
    native_inputs = {'daily': daily}
    old_p = deepcopy(p)
    old_p.pop('profit_latch')
    old_p['mechanism'] = adapter.PARENT_MECHANISM
    old = parent.BoundaryBearRecoveryRange(ParameterSet(old_p))
    disabled = deepcopy(p)
    disabled['profit_latch']['enabled'] = False
    off = adapter.ProfitLatchRange(ParameterSet(disabled))
    pd.testing.assert_frame_equal(off.calculate_history(native_inputs, sessions), old.calculate_history(native_inputs, sessions), check_exact=True)
    on = adapter.ProfitLatchRange(ParameterSet(p))
    assert set(policy.DIAGNOSTICS).issubset(on.calculate_history(native_inputs, sessions).columns)
    assert on.definition.decision == old.definition.decision and on.definition.execution == old.definition.execution
    for window in (10, 60):
        for multiple in (.5, 3.0):
            boundary = deepcopy(p)
            boundary['profit_latch'].update(volatility_window=window, activation_multiple=multiple)
            instance = adapter.ProfitLatchRange(ParameterSet(boundary))
            assert instance._warmup >= window + 1
    checks.append('OFF exact complete parent table, ON contracts and full new parameter boundaries')
    for kind in ('window_low', 'window_high', 'window_float', 'multiple_low', 'multiple_high',
                 'multiple_int', 'multiple_nan', 'enabled_int', 'unknown_field', 'wrong_mechanism',
                 'nan_sigma', 'negative_sigma', 'nan_score', 'unaligned_sigma', 'missing_sigma',
                 'insufficient_history', 'nonpositive_close'):
        try:
            if kind in ('nan_sigma', 'negative_sigma', 'nan_score', 'unaligned_sigma', 'missing_sigma'):
                bad = deepcopy(base)
                if kind == 'nan_sigma':
                    bad['sigma_knowncurrent'].iloc[0] = np.nan
                elif kind == 'negative_sigma':
                    bad['sigma_knowncurrent'].iloc[0] = -.01
                elif kind == 'nan_score':
                    bad['score'].iloc[0] = np.nan
                elif kind == 'unaligned_sigma':
                    bad['sigma_knowncurrent'] = bad['sigma_knowncurrent'].iloc[:-1]
                else:
                    del bad['sigma_knowncurrent']
                policy.decisions(p, axis, bad)
            elif kind == 'insufficient_history':
                sigma_module.sigma_known(close_series, all_days[:20], 20)
            elif kind == 'nonpositive_close':
                bad_close = close_series.copy()
                bad_close.iloc[0] = 0.
                sigma_module.sigma_known(bad_close, sessions, 20)
            else:
                bad_p = deepcopy(p)
                settings = bad_p['profit_latch']
                if kind.startswith('window_'):
                    settings['volatility_window'] = {'window_low': 9, 'window_high': 61, 'window_float': 20.0}[kind]
                elif kind.startswith('multiple_'):
                    settings['activation_multiple'] = {'multiple_low': .499, 'multiple_high': 3.001,
                                                       'multiple_int': 1, 'multiple_nan': np.nan}[kind]
                elif kind == 'enabled_int':
                    settings['enabled'] = 1
                elif kind == 'unknown_field':
                    settings['floor'] = .0
                else:
                    bad_p['mechanism'] = 'invalid'
                adapter.ProfitLatchRange(ParameterSet(bad_p))
        except ValueError:
            refusals.append(kind)
        else:
            raise AssertionError('Illegal input accepted: ' + kind)
    inherited = ('__init__.py', 'range_reversion.py', 'adaptive_range.py', 'confirmed_range.py',
                 'reentry_confirmed_range.py', 'boundary_bear_recovery_range.py')
    for name in inherited:
        original = ROOT / 'research/S013/experiments/EX058_20261011/src/strategy_runtime/strategies' / name
        assert original.read_bytes() == (WORK / 'strategy_runtime/strategies' / name).read_bytes()
    result = {'status': 'PASS', 'synthetic_only': True, 'real_inputs_read': 0, 'accounts': 0,
              'experiments_allocated': 0, 'checks': checks, 'check_count': len(checks),
              'rejections': refusals, 'rejection_count': len(refusals), 'inherited_sources': 'EXACT_BYTES',
              'off_parent_complete_table': 'EXACT_SYNTHETIC', 'signal_floor_actual_breakeven': 'NOT_CLAIMED',
              'strong_counterevidence': 'EX025/26 rebound truncation, EX077 price cycle; activation surface may add fragility',
              'source_sha256': {path.name: sha256(path.read_bytes()).hexdigest()
                                for path in [WORK / 'checks.py', *sorted((WORK / 'strategy_runtime/strategies').glob('*.py'))]}}
    (WORK / 'checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({'status': 'PASS', 'checks': len(checks), 'refusals': len(refusals), 'real_inputs': 0})


if __name__ == '__main__':
    run()
