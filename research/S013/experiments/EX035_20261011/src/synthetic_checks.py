"""Pure EX035 latch checks; authenticated loading only, zero accounts."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
from unittest.mock import patch

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet, StrategyCandidate, StrategyRuntime, implementation_sha256


MODE = 'BEAR_TIME_ELIGIBILITY_REFRESH'
DIAGNOSTICS = ('refresh_pending_before', 'refresh_pending_after', 'refresh_opportunity',
               'refresh_blocked', 'refresh_released', 'refresh_armed', 'holding_age')


def module(folder, name, filename):
    package = types.ModuleType(name)
    package.__path__ = [str(folder / 'strategies')]
    sys.modules[name] = package
    spec = importlib.util.spec_from_file_location(name + '.' + filename,
                                                folder / 'strategies' / (filename + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def temporary_plan(source):
    payload = deepcopy(json.loads(Path('research/S013/experiments/EX020_20261011/protocols/plan.json')
                                  .read_text(encoding='utf-8'))['controls'][0]['payload'])
    payload['parameters']['mechanism'] = MODE
    files = ['strategies/' + name + '.py' for name in (
        'range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range',
        'eligibility_refresh_range', '__init__')]
    payload['runtime'] = {'module': 'strategy_runtime.strategies.eligibility_refresh_range',
                          'qualname': 'EligibilityRefreshRange', 'contract_version': 1,
                          'source_files': files,
                          'source_sha256': implementation_sha256(files, source_root=source)}
    return {'configurations': [{'label': 'N0', 'candidate_id': 'C6000', 'payload': payload}]}


def synthetic(plan, source_root=None):
    source = Path(source_root) if source_root is not None else Path(__file__).parent / 'strategy_runtime'
    new = module(source, '_ex035_refresh', 'eligibility_refresh_range')
    old = module(source, '_ex035_original', 'reentry_confirmed_range')
    previous_source = Path('research/S013/experiments/EX034_20261011/src/strategy_runtime')
    previous = module(previous_source, '_ex035_previous', 'entry_refresh_range')
    configs = plan['configurations']
    assert len(configs) == 1 and configs[0]['payload']['parameters']['mechanism'] == MODE
    cfg = configs[0]
    base = deepcopy(cfg['payload']['parameters'])
    counts = {'authenticated_configurations': 0, 'controlled_histories': 0,
              'real_feature_causal_checks': 0, 'audited_real_feature_rows': 0,
              'native_exact_histories': 0, 'previous_model_exact_histories': 0,
              'warmup_cases': 0, 'rejected_cases': 0}
    bound = StrategyRuntime().describe(StrategyCandidate('S013', cfg['candidate_id'], cfg['payload'], source))
    assert bound.parameters.sha256 == ParameterSet(base).sha256
    counts['authenticated_configurations'] += 1

    def reject(action, label):
        try:
            action()
        except ValueError:
            counts['rejected_cases'] += 1
            return
        raise AssertionError('Invalid input accepted: ' + label)

    def native_parameters(p):
        return {key: value for key, value in p.items() if key != 'mechanism'}

    def audit(history, p):
        """Independent state walk, using original feature/score columns."""
        holding, route, age, pending = False, None, 0, False
        anchor = peak = 0.
        last_exit = None
        for row in history.itertuples():
            assert row.refresh_pending_before == pending
            released = pending and not holding and (row.regime != 'bear' or
                row.bear_range_position > p['bear']['entry'] or
                (p['bear']['acf_min'] is not None and row.acf1 < p['bear']['acf_min']) or
                (p['bear']['momentum_min'] is not None and row.momentum20 < p['bear']['momentum_min']))
            if released:
                pending = False
            current_route = route if holding else row.regime
            rp = p[current_route]
            position = row.bull_range_position if current_route == 'bull' else row.bear_range_position
            # ACF and momentum are shared price-return features for both ranges.
            eligible = (position <= rp['entry'] and
                        (rp['acf_min'] is None or row.acf1 >= rp['acf_min']) and
                        (rp['momentum_min'] is None or row.momentum20 >= rp['momentum_min']))
            opportunity = not holding and eligible
            refresh_opportunity = opportunity and row.regime == 'bear'
            blocked = refresh_opportunity and pending
            c = p['confirmation']
            applies = c['scope'] in ('both', row.regime) and (p['context']['entry_gate'] == 'all' or last_exit == 'regime')
            passed = not applies or row.confirmation_score >= c['threshold']
            assert row.confirmation_opportunity == opportunity
            assert row.confirmation_pass == passed
            assert row.confirmation_exit_context == (last_exit or 'initial')
            assert row.refresh_released == released and row.refresh_opportunity == refresh_opportunity
            assert row.refresh_blocked == blocked
            armed = False
            if holding:
                age += 1
                peak = max(peak, row.close)
                predicates = (
                    ('loss', rp['stop_loss'] is not None and row.close / anchor - 1 <= -rp['stop_loss']),
                    ('trailing', rp['trailing_stop'] is not None and row.close / peak - 1 <= -rp['trailing_stop']),
                    ('range', position >= rp['exit']), ('time', age >= rp['max_hold']),
                    ('regime', p['exit_on_regime_change'] and row.regime != route))
                reason = next((name for name, value in predicates if value), 'hold')
                if reason != 'hold':
                    armed = route == 'bear' and reason == 'time' and row.regime == 'bear' and position <= rp['entry']
                    pending = pending or armed
                    holding, route, last_exit = False, None, reason
            elif not eligible:
                reason = 'flat'
            elif blocked:
                reason = 'entry_refresh_rejected'
            elif not passed:
                reason = 'confirmation_rejected'
            else:
                reason = 'entry'
                holding, route, age, last_exit = True, row.regime, 0, None
                anchor = peak = row.close
            assert row.signal_reason == reason and row.target_position == float(holding)
            assert row.refresh_armed == armed and row.refresh_pending_after == pending
            assert row.holding_age == age

    rng = np.random.default_rng(13)
    dates = pd.bdate_range('2018-01-01', periods=680)
    close = 6 * np.exp(np.cumsum(rng.normal(.0004, .02, len(dates))))
    bars = pd.DataFrame({'Date': dates, 'Open': close * .999, 'High': close * 1.02,
                         'Low': close * .98, 'Close': close,
                         'Volume': np.exp(rng.normal(15, .2, len(dates))),
                         'Amount': np.exp(rng.normal(18, .2, len(dates)))})
    sessions = dates[400:]
    impl = new.EligibilityRefreshRange(ParameterSet(base))
    history = impl.calculate_history({'daily': bars}, sessions)
    baseline = old.ReentryConfirmedRange(ParameterSet(native_parameters(base))).calculate_history({'daily': bars}, sessions)
    for column in ('acf1', 'close', 'momentum20', 'regime', 'regime_momentum',
                   'bull_range_position', 'bear_range_position', 'confirmation_score',
                   'confirmation_acf', 'confirmation_turnover', 'confirmation_volume'):
        pd.testing.assert_series_equal(history[column], baseline[column])
    audit(history, base)
    counts['audited_real_feature_rows'] = len(history)
    cutoff = sessions[119]
    prefix = impl.calculate_history({'daily': bars[bars.Date <= cutoff]}, sessions[:120])
    pd.testing.assert_frame_equal(prefix, history.iloc[:120])
    future = bars.copy()
    future.loc[future.Date > cutoff, ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']] *= 1.37
    changed = impl.calculate_history({'daily': future}, sessions)
    pd.testing.assert_frame_equal(changed.iloc[:120], history.iloc[:120])
    counts['real_feature_causal_checks'] = 2
    # No bear route implies no latch: all original output columns must match.
    no_bear = deepcopy(base)
    no_bear['regime_threshold'] = -.2
    no_bear['regime_window'] = 5
    safe = bars.copy()
    safe['Close'] = 10 * np.exp(np.cumsum(rng.uniform(-.002, .002, len(bars))))
    safe['Open'] = safe.Close * .999
    safe['High'], safe['Low'] = safe.Close * 1.02, safe.Close * .98
    native = old.ReentryConfirmedRange(ParameterSet(native_parameters(no_bear))).calculate_history({'daily': safe}, sessions)
    untouched = new.EligibilityRefreshRange(ParameterSet(no_bear)).calculate_history({'daily': safe}, sessions)
    assert set(untouched.regime) == {'bull'} and not untouched.refresh_pending_after.any()
    pd.testing.assert_frame_equal(untouched.loc[:, native.columns], native)
    counts['native_exact_histories'] += 1
    floor = deepcopy(base)
    floor['bear']['acf_min'] = -.6
    no_acf_refresh = new.EligibilityRefreshRange(ParameterSet(floor)).calculate_history({'daily': bars}, sessions)
    assert (no_acf_refresh.acf1 >= -.6).all()
    old_floor = deepcopy(floor)
    old_floor['mechanism'] = 'BEAR_TIME_ENTRY_REFRESH'
    prior_floor = previous.EntryRefreshRange(ParameterSet(old_floor)).calculate_history({'daily': bars}, sessions)
    pd.testing.assert_frame_equal(no_acf_refresh, prior_floor)
    counts['previous_model_exact_histories'] += 1

    def controlled(regimes, *, positions=None, bull_positions=None, scores=None, acfs=None,
                   horizon=1, prices=None, stop=None, trail=None, compare_original=False,
                   momentum_values=None, momentum_min=None, acf_min=.1, compare_previous=True):
        p = deepcopy(base)
        for route in ('bull', 'bear'):
            p[route]['max_hold'] = horizon
            p[route]['stop_loss'], p[route]['trailing_stop'] = stop, trail
        p['bear']['momentum_min'] = momentum_min
        p['bear']['acf_min'] = acf_min
        start, size = 80, 80 + len(regimes)
        frame = bars.iloc[:size].copy()
        values = np.full(size, 10.)
        for j, regime in enumerate(regimes):
            i = start + j
            values[i] = values[i - p['regime_window']] * (1.01 if regime == 'bull' else .99)
        if prices is not None:
            values[start:] = prices
        frame['Close'] = values
        index = dates[:size]
        signal_sessions = index[start:]
        pos = np.asarray([.2] * len(regimes) if positions is None else positions)
        bullpos = pos if bull_positions is None else np.asarray(bull_positions)
        raw_acf = np.asarray([.2] * len(regimes) if acfs is None else acfs)
        raw_score = np.asarray([0.] * len(regimes) if scores is None else scores)
        raw_momentum = np.asarray([0.] * len(regimes) if momentum_values is None else momentum_values)

        def features(input_frame, window):
            result = pd.DataFrame({'range_position': .2, 'acf1': .2, 'close': values, 'momentum20': 0.}, index=index)
            result.loc[signal_sessions, 'range_position'] = bullpos if window == p['bull']['range_window'] else pos
            result.loc[signal_sessions, 'acf1'] = raw_acf
            result.loc[signal_sessions, 'momentum20'] = raw_momentum
            return result

        def normalized(input_frame, acf, window):
            result = pd.DataFrame(0., index=index, columns=('acf', 'turnover', 'volume'))
            result.loc[signal_sessions, :] = raw_score[:, None]
            return result, result

        with patch.object(new, 'components', features), patch.object(new, 'confirmation_features', normalized):
            result = new.EligibilityRefreshRange(ParameterSet(p)).calculate_history({'daily': frame}, signal_sessions)
        assert result.regime.tolist() == list(regimes)
        audit(result, p)
        counts['controlled_histories'] += 1
        if compare_previous:
            oldp = deepcopy(p)
            oldp['mechanism'] = 'BEAR_TIME_ENTRY_REFRESH'
            with patch.object(previous, 'components', features), patch.object(previous, 'confirmation_features', normalized):
                prior = previous.EntryRefreshRange(ParameterSet(oldp)).calculate_history({'daily': frame}, signal_sessions)
            pd.testing.assert_frame_equal(result, prior)
            counts['previous_model_exact_histories'] += 1
        if compare_original:
            with patch.object(old, 'components', features), patch.object(old, 'confirmation_features', normalized):
                native = old.ReentryConfirmedRange(ParameterSet(native_parameters(p))).calculate_history({'daily': frame}, signal_sessions)
            pd.testing.assert_frame_equal(result.loc[:, native.columns], native)
            counts['native_exact_histories'] += 1
        return result

    # Strict entry equality remains pending; above entry releases but remains raw-ineligible.
    latch = controlled(['bear'] * 7, positions=[.9, .9, .9, .9001, .9, .9, .9])
    assert latch.signal_reason.tolist() == ['entry', 'time', 'entry_refresh_rejected', 'flat', 'entry', 'time', 'entry_refresh_rejected']
    assert latch.refresh_pending_after.tolist() == [False, True, True, False, False, True, True]
    assert latch.refresh_released.tolist() == [False, False, False, True, False, False, False]
    assert latch.iloc[2].confirmation_opportunity and latch.iloc[2].confirmation_pass
    # Refresh precedes score rejection, but original score diagnostics are retained.
    denied = controlled(['bear'] * 6, positions=[.2, .2, .2, .95, .2, .2], scores=[0., 0., -.3, 0., -.3, 0.])
    assert denied.signal_reason.tolist() == ['entry', 'time', 'entry_refresh_rejected', 'flat', 'confirmation_rejected', 'entry']
    assert not denied.iloc[2].confirmation_pass and denied.iloc[2].refresh_blocked
    acf_denied = controlled(['bear'] * 6, positions=[.2, .2, .2, .95, .2, .2], acfs=[.2, .2, .05, .2, .05, .2], compare_previous=False)
    assert acf_denied.signal_reason.tolist() == ['entry', 'time', 'flat', 'flat', 'flat', 'entry']
    assert not acf_denied.iloc[2].refresh_pending_after and acf_denied.iloc[2].refresh_released
    assert not acf_denied.iloc[2].refresh_blocked
    # Full eligibility refresh: exact ACF equality retains pending, strict lower releases.
    acf_refresh = controlled(['bear'] * 6, acfs=[.2, .2, .1, .0999, .1, .1], compare_previous=False)
    assert acf_refresh.signal_reason.tolist() == ['entry', 'time', 'entry_refresh_rejected', 'flat', 'entry', 'time']
    assert not acf_refresh.iloc[2].refresh_released and acf_refresh.iloc[3].refresh_released
    assert not acf_refresh.iloc[3].confirmation_opportunity
    # Arming still ignores ACF: a failed ACF on the held TIME bar sets pending.
    held_acf_failure = controlled(['bear'] * 4, acfs=[.2, .05, .05, .2], compare_previous=False)
    assert held_acf_failure.signal_reason.tolist() == ['entry', 'time', 'flat', 'entry']
    assert held_acf_failure.iloc[1].refresh_armed and held_acf_failure.iloc[1].refresh_pending_after
    assert not held_acf_failure.iloc[1].refresh_released and held_acf_failure.iloc[2].refresh_released
    # A below-threshold held ACF does not release early or suppress subsequent pending.
    controlled(['bear'] * 3, acfs=[.2, .05, .2])
    momentum_refresh = controlled(['bear'] * 6, momentum_min=.02,
                                 momentum_values=[.02, .02, .02, .0199, .02, .02], compare_previous=False)
    assert momentum_refresh.signal_reason.tolist() == ['entry', 'time', 'entry_refresh_rejected', 'flat', 'entry', 'time']
    assert not momentum_refresh.iloc[2].refresh_released and momentum_refresh.iloc[3].refresh_released
    held_momentum_failure = controlled(['bear'] * 4, momentum_min=.02,
                                      momentum_values=[.02, .0199, .0199, .02], compare_previous=False)
    assert held_momentum_failure.signal_reason.tolist() == ['entry', 'time', 'flat', 'entry']
    assert held_momentum_failure.iloc[1].refresh_armed and held_momentum_failure.iloc[2].refresh_released
    controlled(['bear'] * 3, momentum_min=.02, momentum_values=[.02, .0199, .02])
    controlled(['bear'] * 3, acfs=[.2, -.2, -.2], acf_min=None)
    controlled(['bear'] * 3, momentum_values=[0., -.1, -.1])
    # The unchanged score gate alone is never a refresh predicate.
    assert denied.iloc[2].refresh_pending_after and not denied.iloc[2].refresh_released
    # Raw bull releases first and is allowed to enter on that same flat signal bar.
    released = controlled(['bear', 'bear', 'bull', 'bull'])
    assert released.signal_reason.tolist() == ['entry', 'time', 'entry', 'time']
    assert released.iloc[2].refresh_released and released.iloc[2].confirmation_opportunity
    rejected_bull = controlled(['bear', 'bear', 'bull', 'bull'], scores=[0., 0., -.3, 0.])
    assert rejected_bull.iloc[2].refresh_released and rejected_bull.iloc[2].signal_reason == 'confirmation_rejected'
    # TIME exit above entry never arms, so subsequent raw bear opportunity is unchanged.
    above = controlled(['bear'] * 3, positions=[.2, .95, .2], compare_original=True)
    assert above.signal_reason.tolist() == ['entry', 'time', 'entry'] and not above.refresh_armed.any()
    # TIME wins at simultaneous regime exit but cannot arm if current raw regime is bull.
    crossed = controlled(['bear', 'bull', 'bull'], compare_original=True)
    assert crossed.signal_reason.tolist() == ['entry', 'time', 'entry'] and not crossed.refresh_armed.any()
    controlled(['bull'] * 8, horizon=4, compare_original=True)
    regime_exit = controlled(['bear', 'bull', 'bear'], horizon=4, compare_original=True)
    assert regime_exit.iloc[1].signal_reason == 'regime' and not regime_exit.refresh_armed.any()
    # Higher priority exits suppress arming, even on the original time deadline.
    for stop, trail, position, expected in ((.01, .01, .999, 'loss'),
                                           (None, .01, .999, 'trailing'),
                                           (None, None, .999, 'range'),
                                           (.01, .01, .2, 'loss'),
                                           (None, .01, .2, 'trailing')):
        priority = controlled(['bear', 'bear', 'bear'], positions=[.2, position, .2],
                              prices=[9., 8., 8.5], stop=stop, trail=trail, compare_original=True)
        assert priority.iloc[1].signal_reason == expected and not priority.refresh_armed.any()
    for horizon in (1, 4, 8, 60):
        timed = controlled(['bear'] * (horizon + 3), horizon=horizon)
        assert timed.iloc[horizon].signal_reason == 'time' and timed.iloc[horizon].refresh_armed
        assert timed.iloc[horizon + 1].signal_reason == 'entry_refresh_rejected'
        assert timed.iloc[horizon].holding_age == horizon

    for value in (None, 'TIME', 'BEAR_TIME_ELIGIBILITY_REFRESH2'):
        p = deepcopy(base)
        p['mechanism'] = value
        reject(lambda p=p: new.EligibilityRefreshRange(ParameterSet(p)), 'invalid enum')
    p = deepcopy(base)
    p['confirmation']['enabled'] = False
    reject(lambda: new.EligibilityRefreshRange(ParameterSet(p)), 'disabled original score')
    for column, value in (('Close', np.nan), ('Close', np.inf), ('Volume', 0.), ('Amount', -1.)):
        invalid = bars.copy()
        invalid.loc[400, column] = value
        reject(lambda b=invalid: impl.calculate_history({'daily': b}, sessions), 'nonfinite or invalid original input')
    duplicated = pd.concat([bars.iloc[:401], bars.iloc[400:]], ignore_index=True)
    reject(lambda: impl.calculate_history({'daily': duplicated}, sessions), 'duplicate dates')
    reject(lambda: impl.calculate_history({'daily': bars.iloc[400:]}, sessions), 'missing feature warmup')
    small = deepcopy(base)
    small['bull']['range_window'] = small['bear']['range_window'] = 21
    small['confirmation']['lookback'] = 40
    for window, depth in ((5, 60), (60, 61)):
        small['regime_window'] = window
        strategy = new.EligibilityRefreshRange(ParameterSet(small))
        original = old.ReentryConfirmedRange(ParameterSet(native_parameters(small)))
        assert strategy._warmup == original._warmup == depth
        assert next(r.lookback_sessions for r in strategy.definition.inputs.requirements if r.name == 'daily') == depth
        strategy.calculate_history({'daily': bars.iloc[:depth]}, dates[depth - 1:depth])
        reject(lambda s=strategy, d=depth: s.calculate_history({'daily': bars.iloc[:d - 1]}, dates[d - 2:d - 1]), 'one price short')
        counts['warmup_cases'] += 2
    paths = (('bull', 'range_window', 21, 360), ('bull', 'entry', 0., .9),
             ('bull', 'exit', .7, 1.), ('bull', 'max_hold', 1, 60),
             ('bear', 'range_window', 21, 360), ('bear', 'entry', 0., .95),
             ('bear', 'exit', .91, 1.), ('bear', 'max_hold', 1, 60),
             ('bear', 'acf_min', -.6, .5), (None, 'regime_window', 5, 60),
             (None, 'regime_threshold', -.2, .2), ('confirmation', 'lookback', 40, 120),
             ('confirmation', 'threshold', -.5, .5))
    for section, key, lower, upper in paths:
        for value in (lower, upper):
            p = deepcopy(base)
            (p if section is None else p[section])[key] = value
            if key == 'entry':
                p[section]['exit'] = 1.
            if key == 'exit':
                p[section]['entry'] = 0.
            strategy = new.EligibilityRefreshRange(ParameterSet(p))
            assert strategy.definition.parameters.values == ParameterSet(p).values
            strategy.calculate_history({'daily': bars}, sessions)
    counts['numeric_boundary_feature_histories'] = 26
    for section, key, value in (('bear', 'max_hold', 0), ('bull', 'max_hold', 61),
                                (None, 'regime_window', 4), (None, 'regime_threshold', .21),
                                ('confirmation', 'lookback', 39), ('confirmation', 'threshold', .51),
                                ('bear', 'acf_min', np.inf)):
        p = deepcopy(base)
        (p if section is None else p[section])[key] = value
        reject(lambda p=p: new.EligibilityRefreshRange(ParameterSet(p)), 'original invalid numeric contract')
    return {'status': 'PASS', 'scope': 'pure synthetic + authenticated public describe; zero accounts',
            'cases': counts, 'diagnostics': list(DIAGNOSTICS),
            'minimum_contract_warmup': 60, 'W60_minimum_contract_warmup': 61,
            'warmup_changes': 'none; exact original lookback contract',
            'pending_seed': 'final bear TIME signal exit, raw bear and bear range <= original entry',
            'release': 'flat raw not bear or any original bear range/ACF/momentum eligibility predicate false; score excluded; before original entry evaluation'}


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    source = Path(__file__).resolve().parent / 'strategy_runtime'
    plan = temporary_plan(source)
    result = synthetic(plan, source)
    result['source_sha256'] = plan['configurations'][0]['payload']['runtime']['source_sha256']
    result['file_sha256'] = {str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in source.rglob('*.py')}
    output = Path('.tmp/ex035_source/synthetic_result.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
