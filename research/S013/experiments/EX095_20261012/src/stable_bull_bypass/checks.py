"""EX095 prospective synthetic score-bypass truth table, no real inputs."""
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
PREFIX = '_s013_stable_bull_synthetic'
package = types.ModuleType(PREFIX)
package.__path__ = [str(WORK / 'strategy_runtime')]
sys.modules[PREFIX] = package
policy = importlib.import_module(PREFIX + '.strategies.policy_kernel')
adapter = importlib.import_module(PREFIX + '.strategies.stable_bull_bypass_range')
parent = importlib.import_module(PREFIX + '.strategies.boundary_bear_recovery_range')


def parameters():
    route = {'acf_min': .1, 'cooldown': 0, 'entry': .9, 'exit': .99,
             'limit_premium': .01, 'max_hold': 4, 'momentum_min': None,
             'range_window': 120, 'stop_loss': None, 'trailing_stop': None}
    bull = {**route, 'acf_min': None, 'entry': .675, 'exit': .95, 'max_hold': 8, 'range_window': 180}
    return {'bear': route, 'bull': bull,
            'confirmation': {'enabled': True, 'lookback': 120, 'orientation': 1,
                             'profile': 'all', 'scope': 'both', 'threshold': -.2},
            'context': {'entry_gate': 'all', 'volume_basis': 'ADJUSTED', 'weighting': 'EQUAL_BLOCKS'},
            'exit_on_regime_change': True, 'regime_threshold': 0., 'regime_window': 20,
            'mechanism': adapter.MECHANISM, 'bypass_enabled': True}


def make_base(axis, regimes=None, close=None, score=None):
    n = len(axis)
    regimes = np.asarray(['bull'] * n if regimes is None else regimes)
    close = np.asarray(np.full(n, 100.) if close is None else close, float)
    score = np.asarray(np.full(n, .3) if score is None else score, float)
    previous = np.r_[regimes[:1], regimes[:-1]]
    feature = {route: pd.DataFrame({'range_position': .5, 'acf1': .2, 'close': close, 'momentum20': .01}, index=axis)
               for route in ('bull', 'bear')}
    return {'features': feature, 'score': pd.Series(score, index=axis),
            'normalized': pd.DataFrame(np.repeat(score[:, None], 3, axis=1), index=axis, columns=('acf', 'turnover', 'volume')),
            'signal_close': pd.Series(close, index=axis), 'signal_open': pd.Series(close * .999, index=axis),
            'previous_close': pd.Series(close, index=axis),
            'momentum': pd.Series(np.where(regimes == 'bull', .01, -.01), index=axis),
            'previous_momentum': pd.Series(np.where(previous == 'bull', .01, -.01), index=axis),
            'regimes': regimes, 'previous_regimes': previous, 'raw_bear_acf': feature['bear'].acf1.copy()}


def run():
    p = parameters()
    axis = pd.bdate_range('2021-12-21', periods=30).as_unit('ns')
    truth_table = []
    for regime in ('bull', 'bear'):
        for previous in ('bull', 'bear'):
            for body in ('up', 'flat', 'down'):
                for score_pass in (False, True):
                    for eligible in (False, True):
                        base = make_base(axis[:1], [regime], score=[.3 if score_pass else -.3])
                        base['previous_regimes'][:] = previous
                        base['previous_momentum'][:] = .01 if previous == 'bull' else -.01
                        base['signal_open'][:] = 99 if body == 'up' else 100 if body == 'flat' else 101
                        base['features'][regime]['range_position'] = .5 if eligible else .999
                        row = policy.decisions(p, axis[:1], base).iloc[0]
                        bypass = regime == previous == 'bull' and body == 'up'
                        boundary = regime == 'bull' and previous == 'bear'
                        expected = eligible and (not boundary or body == 'up') and (score_pass or bypass)
                        assert bool(row.confirmation_pass) == score_pass
                        assert bool(row.bypass_applies) == bypass
                        assert bool(row.effective_confirmation_pass) == (score_pass or bypass)
                        assert bool(row.confirmation_opportunity) == eligible
                        assert bool(row.target_position) == expected
                        assert bool(row.actually_bypassed) == (expected and bypass and not score_pass)
                        truth_table.append({'raw': regime, 'previous_raw': previous, 'body': body,
                            'score_pass': score_pass, 'eligible': eligible, 'bypass_applies': bypass,
                            'accepted': bool(row.target_position), 'actually_bypassed': bool(row.actually_bypassed), 'reason': row.signal_reason})
    assert len(truth_table) == 48
    stable_up = make_base(axis[:1], score=[-.3])
    one = policy.decisions(p, axis[:1], stable_up)
    assert one.iloc[0].signal_reason == 'entry' and one.iloc[0].actually_bypassed
    stable_down = make_base(axis[:1], score=[-.3])
    stable_down['signal_open'][:] = 101.
    not_bypassed = policy.decisions(p, axis[:1], stable_down)
    assert not_bypassed.iloc[0].signal_reason == 'confirmation_rejected'
    # Existing bull-scoped score OFF corresponds to scope='bear': allbull exempt.
    broad = deepcopy(p)
    broad['confirmation']['scope'] = 'bear'
    scoped_off = policy.decisions(broad, axis[:1], stable_down)
    assert scoped_off.iloc[0].signal_reason == 'entry' and not scoped_off.iloc[0].actually_bypassed
    bear_low = make_base(axis[:1], ['bear'], score=[-.3])
    retained = policy.decisions(p, axis[:1], bear_low)
    all_pass = deepcopy(bear_low)
    all_pass['score'][:] = .3
    all_pass['normalized'][:] = .3
    universal_off_counterfactual = policy.decisions(p, axis[:1], all_pass)
    assert retained.iloc[0].signal_reason == 'confirmation_rejected' and universal_off_counterfactual.iloc[0].signal_reason == 'entry'

    priority_cases = []
    for intended in ('loss', 'trailing', 'range', 'time', 'regime'):
        pp = deepcopy(p)
        data = make_base(axis[:6], ['bear', 'bear', 'bear', 'bear', 'bull', 'bull'], close=[100., 105., 105., 105., 95., 100.])
        data['features']['bear'].loc[axis[4], 'range_position'] = pp['bear']['exit'] if intended in ('loss', 'trailing', 'range') else .5
        if intended == 'loss':
            pp['bear']['stop_loss'] = .01
            pp['bear']['trailing_stop'] = .01
        elif intended == 'trailing':
            pp['bear']['trailing_stop'] = .01
        elif intended == 'regime':
            pp['bear']['max_hold'] = 8
        rows = policy.decisions(pp, axis[:6], data)
        assert rows.iloc[4].signal_reason == intended and rows.iloc[4].target_position == 0
        assert not rows.iloc[4].actually_bypassed
        priority_cases.append(intended)
    anchor = make_base(axis[:6], ['bear'] * 6, close=[100., 99., 99., 99., 98., 99.])
    anchor['features']['bear'].loc[axis[5], 'acf1'] = -.2
    rows = policy.decisions(p, axis[:6], anchor)
    assert rows.iloc[4].signal_reason == 'time'
    assert rows.iloc[5].last_exit_category == 'BELOW' and rows.iloc[5].entry_acf_recovery_applies
    assert rows.iloc[5].signal_reason == 'entry' and not rows.iloc[5].bypass_applies
    for price, category in ((100., 'EQUAL'), (101., 'ABOVE')):
        data = make_base(axis[:6], ['bear'] * 6, close=[100., price, price, price, price, price])
        data['features']['bear'].loc[axis[5], 'acf1'] = -.2
        no_recovery = policy.decisions(p, axis[:6], data)
        assert no_recovery.iloc[5].last_exit_category == category
        assert not no_recovery.iloc[5].entry_acf_recovery_applies and no_recovery.iloc[5].target_position == 0
    short = deepcopy(p)
    short['bull']['max_hold'] = 1
    short_history = policy.decisions(short, axis[:3], make_base(axis[:3], score=[-.3] * 3))
    assert short_history.iloc[0].actually_bypassed and short_history.iloc[1].signal_reason == 'time'
    assert short_history.iloc[1].bypass_applies and short_history.iloc[1].effective_confirmation_pass
    assert short_history.iloc[1].target_position == 0 and not short_history.iloc[1].actually_bypassed
    assert short_history.iloc[2].signal_reason == 'entry' and short_history.iloc[2].last_exit_reason == 'time'
    equality = make_base(axis[:1], score=[p['confirmation']['threshold']])
    tied = policy.decisions(p, axis[:1], equality)
    assert tied.iloc[0].confirmation_pass and not tied.iloc[0].actually_bypassed
    held = make_base(axis, score=np.full(len(axis), -.3))
    reference = policy.decisions(p, axis, held)
    assert reference.iloc[0].actually_bypassed and not reference.iloc[1].actually_bypassed
    for limit in range(1, len(axis) + 1):
        prefix = {name: {route: frame.iloc[:limit] for route, frame in value.items()} if name == 'features'
                  else value.iloc[:limit] if isinstance(value, (pd.DataFrame, pd.Series)) else value[:limit]
                  for name, value in held.items()}
        pd.testing.assert_frame_equal(policy.decisions(p, axis[:limit], prefix), reference.iloc[:limit], check_exact=True)
    modified = deepcopy(held)
    modified['score'].iloc[15:] = .4
    modified['normalized'].iloc[15:] = .4
    future = policy.decisions(p, axis, modified)
    pd.testing.assert_frame_equal(future.iloc[:15], reference.iloc[:15], check_exact=True)
    crossing = np.flatnonzero(axis.year == 2022)[0]
    cross_parameters = deepcopy(p)
    cross_parameters['bull']['max_hold'] = 10
    cross_history = policy.decisions(cross_parameters, axis, held)
    assert cross_history.iloc[crossing - 1].target_position == 1 and cross_history.iloc[crossing].signal_reason == 'hold'
    assert cross_history.iloc[crossing + 1].signal_reason == 'time'

    all_days = pd.bdate_range('2020-01-01', periods=320).as_unit('ns')
    z = np.arange(len(all_days))
    close = 100 * np.exp(.05 * np.sin(z / 4) + .02 * np.sin(z / 9) + .0001 * z)
    opening = close * np.exp(.004 * np.sin(z / 3))
    daily = pd.DataFrame({'Date': all_days, 'Open': opening, 'High': np.maximum(opening, close) * 1.01,
                         'Low': np.minimum(opening, close) * .99, 'Close': close,
                         'Volume': 1000 * np.exp(.3 * np.sin(z / 5))})
    daily['Amount'] = daily.Volume * daily.Close
    native_inputs, sessions = {'daily': daily}, all_days[-100:]
    parent_parameters = deepcopy(p)
    parent_parameters.pop('bypass_enabled')
    parent_parameters['mechanism'] = adapter.PARENT_MECHANISM
    original = parent.BoundaryBearRecoveryRange(ParameterSet(parent_parameters))
    off = adapter.StableBullBypassRange(ParameterSet({**p, 'bypass_enabled': False}))
    pd.testing.assert_frame_equal(off.calculate_history(native_inputs, sessions), original.calculate_history(native_inputs, sessions), check_exact=True)
    on = adapter.StableBullBypassRange(ParameterSet(p))
    on_table = on.calculate_history(native_inputs, sessions)
    assert {'bypass_applies', 'effective_confirmation_pass', 'actually_bypassed'}.issubset(on_table.columns)
    assert on.definition.inputs == original.definition.inputs
    assert on.definition.execution == original.definition.execution
    assert on.definition.decision == original.definition.decision
    source = ROOT / 'research/S013/experiments/EX058_20261011/src/strategy_runtime/strategies'
    inherited = ('__init__.py', 'range_reversion.py', 'adaptive_range.py', 'confirmed_range.py', 'reentry_confirmed_range.py', 'boundary_bear_recovery_range.py')
    assert all((source / name).read_bytes() == (WORK / 'strategy_runtime/strategies' / name).read_bytes() for name in inherited)

    refusals = []
    for name in ('integer_switch', 'wrong_enum', 'pseudofoo', 'missing_param', 'nan_score', 'unknown_route', 'zero_price', 'unordered', 'missing_base'):
        pp, bb, ss = deepcopy(p), deepcopy(held), axis
        if name == 'integer_switch':
            pp['bypass_enabled'] = 1
        elif name == 'wrong_enum':
            pp['mechanism'] = 'pseudofoo'
        elif name == 'pseudofoo':
            pp['pseudofoo'] = 1
        elif name == 'missing_param':
            pp.pop('context')
        elif name == 'nan_score':
            bb['score'].iloc[0] = np.nan
        elif name == 'unknown_route':
            bb['regimes'][0] = 'other'
        elif name == 'zero_price':
            bb['signal_open'].iloc[0] = 0
        elif name == 'unordered':
            ss = axis[::-1]
        else:
            bb.pop('previous_close')
        try:
            adapter.StableBullBypassRange(ParameterSet(pp))
            policy.decisions(pp, ss, bb)
        except ValueError:
            refusals.append(name)
        else:
            raise AssertionError('Illegal bypass input accepted: ' + name)
    output = {'status': 'PASS', 'synthetic_only': True, 'real_inputs_read': 0, 'real_inputs': 0,
        'accounts': 0, 'experiments_allocated': 0,
        'checks': ['48-row causal scope truth table', 'Scope differs from all score pass and allbull scoped-off',
                   'Other range/ACF/momentum/BODY eligibility unchanged', 'Original five exit priorities and no exit-day reentry',
                   'TIME original transaction anchor and BELOW recovery preserved', 'Score equality and held-signal bypass diagnostic',
                   'All30 prefixes and future changes preserve past', 'Calendar-year continuity without reset',
                   'OFF exact complete parent table', 'ON original input/execution/decision contracts', 'Six parent sources byte exact',
                   'Typed switch/enum/unknown-field and finite aligned input refusal'],
        'check_count': 12, 'truth_table': truth_table, 'priority_cases': priority_cases,
        'rejections': refusals, 'rejection_count': len(refusals), 'new_numeric_coordinates': [],
        'limitations': 'Causal stable rawbull/body is not final profitable-year oracle. Earlier actual entries alter later trade age/anchor/cash; no new information or account advantage established.',
        'strongest_counter': 'EX006/EX012 full confirmation relief raised frequency but reduced return; narrow scope may still turn thin2023 profit negative.',
        'source_sha256': {path.name: sha256(path.read_bytes()).hexdigest() for path in [Path(__file__), *sorted((WORK / 'strategy_runtime/strategies').glob('*.py'))]}}
    with (WORK / 'checks.json').open('w', encoding='utf-8') as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print({'status': 'PASS', 'checks': output['check_count'], 'truth_table_rows': 48, 'rejections': len(refusals), 'real_inputs': 0})


if __name__ == '__main__':
    run()
