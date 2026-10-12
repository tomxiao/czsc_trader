"""Pure synthetic episode-clock strategy checks; no market or account inputs."""
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
PACKAGE = '_s013_episode_synthetic'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(WORK / 'strategy_runtime')]
sys.modules[PACKAGE] = package
policy = importlib.import_module(PACKAGE + '.strategies.policy_kernel')
observer = importlib.import_module(PACKAGE + '.strategies.pureobserver')
adapter = importlib.import_module(PACKAGE + '.strategies.episode_clock_range')
parent = importlib.import_module(PACKAGE + '.strategies.boundary_bear_recovery_range')


def parameters():
    route = {'acf_min': .1, 'cooldown': 0, 'entry': .9, 'exit': .99,
             'limit_premium': .01, 'max_hold': 4, 'momentum_min': None,
             'range_window': 120, 'stop_loss': None, 'trailing_stop': None}
    bull = {**route, 'acf_min': None, 'entry': .675, 'exit': .95,
            'max_hold': 8, 'range_window': 180}
    return {'bear': route, 'bull': bull,
            'confirmation': {'enabled': True, 'lookback': 120, 'orientation': 1,
                             'profile': 'all', 'scope': 'both', 'threshold': -.2},
            'context': {'entry_gate': 'all', 'volume_basis': 'ADJUSTED', 'weighting': 'EQUAL_BLOCKS'},
            'exit_on_regime_change': True, 'regime_threshold': 0., 'regime_window': 20,
            'mechanism': adapter.MECHANISM, 'episode_enabled': True}


def make_base(sessions, regimes=None, close=None):
    n = len(sessions)
    regimes = np.array(['bear'] * n) if regimes is None else np.asarray(regimes)
    close = np.full(n, 100.) if close is None else np.asarray(close, float)
    features = {route: pd.DataFrame({'range_position': np.full(n, .5), 'acf1': np.full(n, .2),
                                    'close': close, 'momentum20': np.full(n, .01)}, index=sessions)
                for route in ('bull', 'bear')}
    def series(value):
        return pd.Series(value, index=sessions)

    previous = np.concatenate((regimes[:1], regimes[:-1]))
    return {'features': features, 'score': series(np.full(n, .3)),
            'normalized': pd.DataFrame(.3, index=sessions, columns=('acf', 'turnover', 'volume')),
            'signal_close': series(close), 'signal_open': series(close * .999),
            'previous_close': series(close), 'momentum': series(np.where(regimes == 'bull', .01, -.01)),
            'previous_momentum': series(np.where(previous == 'bull', .01, -.01)),
            'regimes': regimes, 'previous_regimes': previous,
            'raw_bear_acf': features['bear'].acf1.copy()}


def run():
    checks, refusals = [], []
    p = parameters()
    axis = pd.bdate_range('2021-12-21', periods=30).as_unit('ns')
    base = make_base(axis)
    reference = policy.decisions(p, axis, base)
    assert reference.iloc[0].episode_age == 0 and reference.iloc[0].signal_reason == 'entry'
    assert reference.iloc[4].episode_expired and reference.iloc[4].signal_reason == 'time'
    assert not reference.iloc[4].episode_live and reference.iloc[4].target_position == 0
    assert reference.iloc[5].episode_reason == 'start' and reference.iloc[5].signal_reason == 'entry'
    checks.append('market age starts0, TIME priority, endT no reentry, nextT can restart')
    delayed = deepcopy(base)
    delayed['score'].iloc[:3] = -.3
    delayed['normalized'].iloc[:3] = -.3
    late = policy.decisions(p, axis, delayed)
    assert late.iloc[3].signal_reason == 'entry' and late.iloc[4].signal_reason == 'time'
    pd.testing.assert_frame_equal(late[list(observer.COLUMNS)], reference[list(observer.COLUMNS)], check_exact=True)
    rejected = deepcopy(base)
    rejected['features']['bear']['acf1'] = -.2
    rejected['raw_bear_acf'][:] = -.2
    never = policy.decisions(p, axis, rejected)
    assert never.target_position.eq(0).all()
    pd.testing.assert_frame_equal(never[list(observer.COLUMNS)], reference[list(observer.COLUMNS)], check_exact=True)
    checks.append('same market different confirmation/ACF/accepted holding leaves observer exact')
    no_early_entry = deepcopy(base)
    no_early_entry['score'].iloc[:4] = -.3
    no_early_entry['normalized'].iloc[:4] = -.3
    blocked_expiry = policy.decisions(p, axis, no_early_entry)
    assert blocked_expiry.iloc[4].signal_reason == 'episode_entry_rejected'
    assert blocked_expiry.iloc[4].target_position == 0 and blocked_expiry.iloc[5].signal_reason == 'entry'
    checks.append('flat transaction cannot enter ending market episode')
    stop = deepcopy(p)
    stop['bear']['stop_loss'] = .01
    fall = make_base(axis, close=np.r_[100., 98., np.full(len(axis) - 2, 99.)])
    repeated = policy.decisions(stop, axis, fall)
    assert repeated.iloc[1].signal_reason == 'loss' and repeated.iloc[2].signal_reason == 'entry'
    assert repeated.iloc[0].episode_id == repeated.iloc[2].episode_id
    checks.append('original stop exit and repeat entry allowed inside same market episode')
    both = make_base(axis)
    both['features']['bear'].loc[axis[4], 'range_position'] = p['bear']['exit']
    result = policy.decisions(p, axis, both)
    assert result.iloc[4].episode_reason == 'range' and not result.iloc[4].episode_expired
    assert result.iloc[4].signal_reason == 'range' and not result.iloc[4].episode_live
    checks.append('range equality ends before TIME and preserves original exit priority')
    routes = ['bear', 'bull', *(['bull'] * (len(axis) - 2))]
    crossed = policy.decisions(p, axis, make_base(axis, routes))
    assert crossed.iloc[1].episode_route == 'bear' and crossed.iloc[1].episode_reason == 'regime'
    assert crossed.iloc[1].signal_reason == 'regime' and crossed.iloc[2].episode_route == 'bull'
    one = deepcopy(p)
    one['bear']['max_hold'] = 1
    timed = policy.decisions(one, axis, make_base(axis, routes))
    assert timed.iloc[1].episode_reason == timed.iloc[1].signal_reason == 'time'
    checks.append('route locked through endingT; TIME beats regime; new route starts nextT')
    tied = make_base(axis)
    tied['features']['bear']['range_position'] = p['bear']['entry']
    tied['features']['bear']['acf1'] = p['bear']['acf_min']
    tied['score'][:] = p['confirmation']['threshold']
    tied['normalized'][:] = p['confirmation']['threshold']
    tie_result = policy.decisions(p, axis, tied)
    assert tie_result.iloc[0].signal_reason == 'entry'
    fixed = deepcopy(p)
    fixed['bear']['momentum_min'] = .01
    tied_episode = observer.observe(fixed, tied['features'], tied['regimes'], axis)
    assert tied_episode.iloc[0].episode_live
    checks.append('original entry/ACF/score/momentum equalities retain inclusive semantics')
    below = make_base(axis, close=np.r_[100., 99., 99., 99., 98., np.full(len(axis) - 5, 99.)])
    below['features']['bear'].loc[axis[5], 'acf1'] = -.2
    recovered = policy.decisions(p, axis, below)
    assert recovered.iloc[5].last_exit_category == 'BELOW'
    assert recovered.iloc[5].entry_acf_recovery_applies and recovered.iloc[5].signal_reason == 'entry'
    checks.append('TIME BELOW original transaction anchor and recovery feedback retained')
    assert reference.iloc[5].last_exit_category == 'EQUAL' and not reference.iloc[5].entry_acf_recovery_applies
    above = make_base(axis, close=np.r_[100., np.full(len(axis) - 1, 101.)])
    above_result = policy.decisions(p, axis, above)
    assert above_result.iloc[5].last_exit_category == 'ABOVE'
    assert not above_result.iloc[5].entry_acf_recovery_applies
    checks.append('TIME equality/above keep original category and no recovery exception')
    for limit in range(1, len(axis) + 1):
        cut = {key: {r: frame.iloc[:limit] for r, frame in value.items()} if key == 'features'
               else value.iloc[:limit] if isinstance(value, (pd.Series, pd.DataFrame)) else value[:limit]
               for key, value in base.items()}
        pd.testing.assert_frame_equal(policy.decisions(p, axis[:limit], cut), reference.iloc[:limit], check_exact=True)
    crossing = axis.get_loc(axis[axis.year == 2022][0])
    assert reference.iloc[crossing].episode_id == reference.iloc[crossing - 1].episode_id
    assert reference.iloc[crossing].episode_age == reference.iloc[crossing - 1].episode_age + 1
    assert reference.iloc[crossing].episode_reason == 'time'
    checks.append('all30 causal prefixes and no calendar-year reset')
    all_days = pd.bdate_range('2020-01-01', periods=320).as_unit('ns')
    z = np.arange(len(all_days))
    close = 100 * np.exp(.05 * np.sin(z / 4) + .02 * np.sin(z / 9) + .0001 * z)
    open_price = close * np.exp(.004 * np.sin(z / 3))
    daily = pd.DataFrame({'Date': all_days, 'Open': open_price,
                          'High': np.maximum(open_price, close) * 1.01,
                          'Low': np.minimum(open_price, close) * .99, 'Close': close,
                          'Volume': 1000 * np.exp(.3 * np.sin(z / 5))})
    daily['Amount'] = daily.Volume * daily.Close
    native_inputs = {'daily': daily}
    sessions = all_days[-100:]
    old_p = deepcopy(p)
    old_p.pop('episode_enabled')
    old_p['mechanism'] = adapter.PARENT_MECHANISM
    old = parent.BoundaryBearRecoveryRange(ParameterSet(old_p))
    disabled = deepcopy(p)
    disabled['episode_enabled'] = False
    off = adapter.EpisodeClockRange(ParameterSet(disabled))
    pd.testing.assert_frame_equal(off.calculate_history(native_inputs, sessions), old.calculate_history(native_inputs, sessions), check_exact=True)
    enabled = adapter.EpisodeClockRange(ParameterSet(p))
    on = enabled.calculate_history(native_inputs, sessions)
    assert set(observer.COLUMNS).issubset(on.columns)
    assert enabled.definition.decision == old.definition.decision
    assert enabled.definition.execution == old.definition.execution
    assert enabled.definition.inputs == old.definition.inputs
    checks.append('adapter OFF exact original complete table, ON original public contracts')
    for kind in ('nan_score', 'nan_normalized', 'nan_acf', 'nan_market_position', 'zero_market_close',
                 'unknown_route', 'missing_base_key', 'unaligned_series', 'unordered_axis',
                 'integer_episode_switch', 'wrong_mechanism'):
        bad = deepcopy(base)
        try:
            if kind == 'nan_score':
                bad['score'].iloc[2] = np.nan
            elif kind == 'nan_normalized':
                bad['normalized'].iloc[2, 0] = np.nan
            elif kind == 'nan_acf':
                bad['features']['bear'].iloc[2, 1] = np.nan
            elif kind == 'nan_market_position':
                bad['features']['bear'].iloc[2, 0] = np.nan
            elif kind == 'zero_market_close':
                bad['features']['bear'].iloc[2, 2] = 0.
            elif kind == 'unknown_route':
                bad['regimes'][2] = 'bad'
            elif kind == 'missing_base_key':
                del bad['previous_close']
            elif kind == 'unaligned_series':
                bad['score'] = bad['score'].iloc[:-1]
            elif kind == 'unordered_axis':
                observer.observe(p, bad['features'], bad['regimes'], axis[::-1])
                raise AssertionError('Unordered axis accepted')
            elif kind == 'integer_episode_switch':
                illegal = deepcopy(p)
                illegal['episode_enabled'] = 1
                adapter.EpisodeClockRange(ParameterSet(illegal))
                raise AssertionError('Nonboolean switch accepted')
            elif kind == 'wrong_mechanism':
                illegal = deepcopy(p)
                illegal['mechanism'] = 'invalid'
                adapter.EpisodeClockRange(ParameterSet(illegal))
                raise AssertionError('Wrong mechanism accepted')
            policy.decisions(p, axis, bad)
        except ValueError:
            refusals.append(kind)
        else:
            raise AssertionError('Illegal input accepted: ' + kind)
    inherited = ('__init__.py', 'range_reversion.py', 'adaptive_range.py', 'confirmed_range.py',
                 'reentry_confirmed_range.py', 'boundary_bear_recovery_range.py')
    for name in inherited:
        original = ROOT / 'research/S013/experiments/EX058_20261011/src/strategy_runtime/strategies' / name
        assert original.read_bytes() == (WORK / 'strategy_runtime/strategies' / name).read_bytes()
    result = {'status': 'PASS', 'synthetic_only': True, 'real_inputs_read': 0,
              'accounts': 0, 'experiments_allocated': 0, 'checks': checks,
              'check_count': len(checks), 'rejections': refusals, 'rejection_count': len(refusals),
              'observer_transaction_independence': 'EXACT_SYNTHETIC',
              'off_parent_complete_table': 'EXACT_SYNTHETIC', 'inherited_sources': 'EXACT_BYTES',
              'initial_boundary': 'empty observer and transaction at first FULL signal; no warmup episodes',
              'actual_fill_or_account_equivalence': 'NOT_CLAIMED',
              'source_sha256': {path.name: sha256(path.read_bytes()).hexdigest()
                                for path in [WORK / 'checks.py', *sorted((WORK / 'strategy_runtime/strategies').glob('*.py'))]}}
    (WORK / 'checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({'status': 'PASS', 'checks': len(checks), 'refusals': len(refusals), 'real_inputs': 0})


if __name__ == '__main__':
    run()
