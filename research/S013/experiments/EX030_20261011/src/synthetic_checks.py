"""Pure synthetic exit-only checks; zero account preparation or evaluation."""
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


MODES = ('BULL_EXIT_BEAR3', 'BULL_EXIT_BEAR_MAJORITY3')


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


def expect_rejected(action, label):
    try:
        action()
    except ValueError:
        return
    raise AssertionError('Invalid input accepted: ' + label)


def temporary_plan(source):
    original = json.loads(Path('research/S013/experiments/EX020_20261011/protocols/plan.json')
                          .read_text(encoding='utf-8'))['controls'][0]['payload']
    files = ['strategies/' + name + '.py' for name in (
        'range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range',
        'exit_confirmed_range', '__init__')]
    configs = []
    for index, mode in enumerate(MODES):
        payload = deepcopy(original)
        payload['parameters']['mechanism'] = mode
        payload['runtime'] = {'module': 'strategy_runtime.strategies.exit_confirmed_range',
                              'qualname': 'ExitConfirmedRange', 'contract_version': 1,
                              'source_files': files,
                              'source_sha256': implementation_sha256(files, source_root=source)}
        configs.append({'label': 'N' + str(index), 'candidate_id': 'C' + str(6900 + index),
                        'payload': payload})
    return {'configurations': configs}


def synthetic(plan, source_root=None):
    source = Path(source_root) if source_root is not None else Path(__file__).parent / 'strategy_runtime'
    new = module(source, '_ex030_exit', 'exit_confirmed_range')
    original = module(source, '_ex030_original', 'reentry_confirmed_range')
    configs = plan['configurations']
    assert len(configs) == 2 and {cfg['payload']['parameters']['mechanism'] for cfg in configs} == set(MODES)
    counts = {'authenticated_configurations': 0, 'causal_configurations': 0,
              'independent_raw_windows': 0, 'controlled_histories': 0,
              'stable_route_exact_cases': 0, 'warmup_cases': 0, 'rejected_cases': 0}
    rng = np.random.default_rng(13)
    dates = pd.bdate_range('2018-01-01', periods=640)
    close = 6 * np.exp(np.cumsum(rng.normal(.0004, .02, len(dates))))
    bars = pd.DataFrame({'Date': dates, 'Open': close * .999, 'High': close * 1.02,
                         'Low': close * .98, 'Close': close,
                         'Volume': np.exp(rng.normal(15, .2, len(dates))),
                         'Amount': np.exp(rng.normal(18, .2, len(dates)))})
    sessions = dates[400:]
    for cfg in configs:
        p = deepcopy(cfg['payload']['parameters'])
        bound = StrategyRuntime().describe(StrategyCandidate('S013', cfg['candidate_id'], cfg['payload'], source))
        assert bound.parameters.sha256 == ParameterSet(p).sha256
        counts['authenticated_configurations'] += 1
        impl = new.ExitConfirmedRange(ParameterSet(p))
        history = impl.calculate_history({'daily': bars}, sessions)
        oldp = {key: value for key, value in p.items() if key != 'mechanism'}
        baseline = original.ReentryConfirmedRange(ParameterSet(oldp)).calculate_history({'daily': bars}, sessions)
        price_series = pd.Series(close, index=dates)
        raw = price_series / price_series.shift(p['regime_window']) - 1
        windows = [int(np.count_nonzero(raw.loc[:day].iloc[-3:].to_numpy() < p['regime_threshold']))
                   for day in sessions]
        np.testing.assert_array_equal(history.raw_bear_count3, windows)
        counts['independent_raw_windows'] += len(sessions)
        for column in ('acf1', 'close', 'momentum20', 'regime', 'regime_momentum',
                       'bull_range_position', 'bear_range_position', 'confirmation_score',
                       'confirmation_acf', 'confirmation_turnover', 'confirmation_volume'):
            pd.testing.assert_series_equal(history[column], baseline[column])
        np.testing.assert_array_equal(history.regime_exit_trigger, history.signal_reason == 'regime')
        cutoff = sessions[79]
        prefix = impl.calculate_history({'daily': bars[bars.Date <= cutoff]}, sessions[:80])
        pd.testing.assert_frame_equal(prefix, history.iloc[:80])
        future = bars.copy()
        future.loc[future.Date > cutoff, ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']] *= 1.37
        changed = impl.calculate_history({'daily': future}, sessions)
        pd.testing.assert_frame_equal(changed.iloc[:80], history.iloc[:80])
        counts['causal_configurations'] += 1

    def reject(action, label):
        expect_rejected(action, label)
        counts['rejected_cases'] += 1

    base = deepcopy(configs[0]['payload']['parameters'])
    for value in ('EXIT_CONFIRM', 'REGIME_MAJORITY3', None):
        p = deepcopy(base)
        p['mechanism'] = value
        reject(lambda: new.ExitConfirmedRange(ParameterSet(p)), 'fixed new enum')
    p = deepcopy(base)
    p['confirmation']['enabled'] = False
    reject(lambda: new.ExitConfirmedRange(ParameterSet(p)), 'disabled original confirmation')

    def normalized(frame, acf, window):
        index = pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
        result = pd.DataFrame(0., index=index, columns=('acf', 'turnover', 'volume'))
        return result, result

    def controlled(mode, states, previous=('bull', 'bull'), horizon=60, score_threshold=-.2,
                   stop=None, trail=None, positions=None, price_step=.05,
                   exit_enabled=True, compare_original=False, threshold=0., close_override=None):
        start = 30
        size = start + len(states)
        frame = bars.iloc[:size].copy()
        full_states = ['bull'] * size
        full_states[start - 2:start] = previous
        full_states[start:] = states
        prices = np.full(size, 10.)
        for i in range(5, size):
            prices[i] = prices[i - 5] * (1 + threshold + (price_step if full_states[i] == 'bull' else -price_step))
        if close_override is not None:
            prices = np.asarray(close_override, dtype=float)
        frame['Close'] = prices
        index = pd.DatetimeIndex(frame.Date)
        p = deepcopy(base)
        p['mechanism'] = mode
        p['regime_window'] = 5
        p['regime_threshold'] = float(threshold)
        p['bull']['max_hold'] = p['bear']['max_hold'] = horizon
        p['bull']['stop_loss'] = p['bear']['stop_loss'] = stop
        p['bull']['trailing_stop'] = p['bear']['trailing_stop'] = trail
        p['confirmation']['threshold'] = score_threshold
        p['exit_on_regime_change'] = exit_enabled

        def features(input_frame, window):
            return pd.DataFrame({'range_position': .5 if positions is None else positions,
                                 'acf1': .25, 'close': input_frame.Close.to_numpy(),
                                 'momentum20': 0.}, index=index)

        with patch.object(new, 'components', features), patch.object(new, 'confirmation_features', normalized):
            history = new.ExitConfirmedRange(ParameterSet(p)).calculate_history({'daily': frame}, index[start:])
        if compare_original:
            oldp = {key: value for key, value in p.items() if key != 'mechanism'}
            with patch.object(original, 'components', features), patch.object(original, 'confirmation_features', normalized):
                baseline = original.ReentryConfirmedRange(ParameterSet(oldp)).calculate_history({'daily': frame}, index[start:])
            pd.testing.assert_frame_equal(history[baseline.columns], baseline)
        raw_momentum = prices / np.concatenate((np.full(5, np.nan), prices[:-5])) - 1
        expected = [np.count_nonzero(raw_momentum[i - 2:i + 1] < threshold) for i in range(start, size)]
        np.testing.assert_array_equal(history.raw_bear_count3, expected)
        if price_step > 0.:
            np.testing.assert_array_equal(history.regime, states)
        np.testing.assert_array_equal(history.regime_exit_trigger, history.signal_reason == 'regime')
        counts['controlled_histories'] += 1
        return history

    for mode in MODES:
        # Past states are market evidence, not an entry restriction or a post-exit waiting lock.
        entered = controlled(mode, ['bull', 'bull'], previous=('bear', 'bear'))
        assert entered.iloc[0].raw_bear_count3 == 2. and entered.iloc[0].signal_reason == 'entry'
        assert not entered.iloc[0].regime_exit_condition
        assert entered.iloc[1].signal_reason == 'hold'
        contiguous = controlled(mode, ['bull', 'bear', 'bear', 'bear', 'bull'])
        required = 3 if mode == MODES[0] else 2
        assert contiguous.signal_reason.tolist()[:required + 1] == ['entry'] + ['hold'] * (required - 1) + ['regime']
        spaced = controlled(mode, ['bull', 'bear', 'bull', 'bear'])
        assert spaced.iloc[-1].signal_reason == ('hold' if mode == MODES[0] else 'regime')
        # Bear holding still exits on the first raw bull, with no same-day reverse entry.
        bear = controlled(mode, ['bear', 'bull', 'bull'])
        assert bear.signal_reason.tolist() == ['entry', 'regime', 'entry']
        assert bear.iloc[2].confirmation_exit_context == 'regime'
        denied = controlled(mode, ['bull', 'bear'], score_threshold=.1)
        assert set(denied.signal_reason) == {'confirmation_rejected'}
        for route in ('bull', 'bear'):
            stable = controlled(mode, [route] * 12, horizon=4, compare_original=True)
            assert {'entry', 'hold', 'time'} <= set(stable.signal_reason)
            counts['stable_route_exact_cases'] += 1
        disabled = controlled(mode, ['bull'] + ['bear'] * 4, exit_enabled=False, horizon=4,
                              compare_original=True)
        assert disabled.iloc[-1].signal_reason == 'time' and not disabled.regime_exit_condition.any()
        # Every original fixed horizon remains a hard cap, including H1 and simultaneous conditions.
        for horizon in (1, 2, 3, 4, 8, 60):
            history = controlled(mode, ['bull'] + ['bear'] * (required + 1), horizon=horizon)
            first_exit = min(horizon, required)
            assert history.iloc[first_exit].signal_reason == ('time' if horizon <= required else 'regime')
        # Loss, trailing, range, and time all outrank regime even if its market evidence is sufficient.
        positions = [.5] * (31 + required)
        positions[30 + required] = .99
        simultaneous_prices = [10.] * (31 + required)
        simultaneous_prices[25] = 9.5
        simultaneous_prices[26:30] = [12.] * 4
        simultaneous_prices[30 + required] = 9.
        for stop, trail, use_range, expected in ((.05, .05, True, 'loss'),
                                               (None, .05, True, 'trailing'),
                                               (None, None, True, 'range'),
                                               (None, None, False, 'time')):
            history = controlled(mode, ['bull'] + ['bear'] * required, horizon=required,
                                 stop=stop, trail=trail, positions=positions if use_range else None,
                                 close_override=simultaneous_prices)
            assert history.iloc[required].regime_exit_condition
            assert history.iloc[required].signal_reason == expected
            assert not history.iloc[required].regime_exit_trigger
        # Threshold equality is bull; it cannot be silently counted as a bear vote.
        equality = controlled(mode, ['bull'] * 3, price_step=0.)
        assert (equality.regime == 'bull').all() and (equality.raw_bear_count3 == 0.).all()

        small = deepcopy(base)
        small['mechanism'] = mode
        small['confirmation']['lookback'] = 40
        small['bull']['range_window'] = small['bear']['range_window'] = 21
        small['regime_window'] = 60
        impl = new.ExitConfirmedRange(ParameterSet(small))
        assert next(r.lookback_sessions for r in impl.definition.inputs.requirements if r.name == 'daily') == 63
        impl.calculate_history({'daily': bars.iloc[:63]}, dates[62:63])
        reject(lambda: impl.calculate_history({'daily': bars.iloc[:62]}, dates[61:62]), 'only 2 raw states')
        reject(lambda: impl.calculate_history({'daily': bars.iloc[:61]}, dates[60:61]), 'only 1 raw state')
        small['regime_window'] = 5
        impl = new.ExitConfirmedRange(ParameterSet(small))
        assert next(r.lookback_sessions for r in impl.definition.inputs.requirements if r.name == 'daily') == 60
        impl.calculate_history({'daily': bars.iloc[:60]}, dates[59:60])
        counts['warmup_cases'] += 4
        impl = new.ExitConfirmedRange(ParameterSet(configs[0]['payload']['parameters'] | {'mechanism': mode}))
        for value in (0., -1., np.nan, np.inf, -np.inf):
            invalid = bars.copy()
            invalid.loc[400, 'Close'] = value
            reject(lambda b=invalid: impl.calculate_history({'daily': b}, sessions), 'invalid Close')
        reject(lambda: impl.calculate_history({'daily': bars.drop(columns='Close')}, sessions), 'missing Close')

    # Inherited coordinate contracts remain variable and unchanged.
    paths = (('bull', 'range_window', 21, 360), ('bull', 'entry', 0., .9),
             ('bull', 'exit', .7, 1.), ('bull', 'max_hold', 1, 60),
             ('bear', 'range_window', 21, 360), ('bear', 'entry', 0., .95),
             ('bear', 'exit', .91, 1.), ('bear', 'max_hold', 1, 60),
             ('bear', 'acf_min', -.6, .5), (None, 'regime_window', 5, 60),
             (None, 'regime_threshold', -.2, .2), ('confirmation', 'lookback', 40, 120),
             ('confirmation', 'threshold', -.5, .5))
    for mode in MODES:
        for section, key, lower, upper in paths:
            for value in (lower, upper):
                p = deepcopy(base)
                p['mechanism'] = mode
                (p if section is None else p[section])[key] = value
                if key == 'entry':
                    p[section]['exit'] = 1.
                if key == 'exit':
                    p[section]['entry'] = 0.
                assert new.ExitConfirmedRange(ParameterSet(p)).definition.parameters.values == ParameterSet(p).values
    counts['numeric_contract_boundary_cases'] = 52
    return {'status': 'PASS', 'scope': 'pure synthetic + public authenticated describe; zero accounts',
            'cases': counts, 'warmup': 'max(parent, regime_window+3)',
            'minimum_contract_warmup': 60, 'W60_minimum_contract_warmup': 63,
            'vote_scope': 'full daily, includes states before entry; raw regime remains entry route'}


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    root = Path(__file__).resolve().parent
    source = root / 'strategy_runtime'
    plan = temporary_plan(source)
    result = synthetic(plan, source)
    result['source_sha256'] = plan['configurations'][0]['payload']['runtime']['source_sha256']
    result['file_sha256'] = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in source.rglob('*.py')}
    (root / 'synthetic_result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
