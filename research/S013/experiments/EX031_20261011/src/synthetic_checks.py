"""Pure synthetic volatility-clock validation; no account preparation or evaluation."""
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


MODES = ('BEAR_VOLATILITY_TIME', 'ALL_VOLATILITY_TIME')


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
        'volatility_time_range', '__init__')]
    configs = []
    for index, mode in enumerate(MODES):
        payload = deepcopy(original)
        payload['parameters']['mechanism'] = mode
        payload['runtime'] = {'module': 'strategy_runtime.strategies.volatility_time_range',
                              'qualname': 'VolatilityTimeRange', 'contract_version': 1,
                              'source_files': files,
                              'source_sha256': implementation_sha256(files, source_root=source)}
        configs.append({'label': 'N' + str(index), 'candidate_id': 'C' + str(6400 + index),
                        'payload': payload})
    return {'configurations': configs}


def synthetic(plan, source_root=None):
    source = Path(source_root) if source_root is not None else Path(__file__).parent / 'strategy_runtime'
    new = module(source, '_ex031_volatility', 'volatility_time_range')
    original = module(source, '_ex031_original', 'reentry_confirmed_range')
    configs = plan['configurations']
    assert len(configs) == 2 and {cfg['payload']['parameters']['mechanism'] for cfg in configs} == set(MODES)
    counts = {'authenticated_configurations': 0, 'causal_configurations': 0,
              'independent_volatility_rows': 0, 'controlled_histories': 0,
              'constant_increment_exact_cases': 0, 'warmup_cases': 0, 'rejected_cases': 0}
    rng = np.random.default_rng(13)
    dates = pd.bdate_range('2018-01-01', periods=640)
    close = 6 * np.exp(np.cumsum(rng.normal(.0004, .02, len(dates))))
    bars = pd.DataFrame({'Date': dates, 'Open': close * .999, 'High': close * 1.02,
                         'Low': close * .98, 'Close': close,
                         'Volume': np.exp(rng.normal(15, .2, len(dates))),
                         'Amount': np.exp(rng.normal(18, .2, len(dates)))})
    sessions = dates[400:]

    def audit_clock(history):
        holding = False
        clock = 0.
        age = 0
        for row in history.itertuples():
            if holding:
                clock += row.volatility_clock_increment
                age += 1
            elif row.signal_reason == 'entry':
                clock = 0.
                age = 0
            assert row.holding_clock == clock and row.holding_age == age
            assert row.time_exit_trigger == (row.signal_reason == 'time')
            if not holding:
                assert not row.time_exit_condition and not row.time_exit_trigger
            holding = row.target_position == 1.

    for cfg in configs:
        p = deepcopy(cfg['payload']['parameters'])
        bound = StrategyRuntime().describe(StrategyCandidate('S013', cfg['candidate_id'], cfg['payload'], source))
        assert bound.parameters.sha256 == ParameterSet(p).sha256
        counts['authenticated_configurations'] += 1
        impl = new.VolatilityTimeRange(ParameterSet(p))
        history = impl.calculate_history({'daily': bars}, sessions)
        baseline = original.ReentryConfirmedRange(ParameterSet(
            {key: value for key, value in p.items() if key != 'mechanism'})).calculate_history({'daily': bars}, sessions)
        volatility = [np.nan] + [max(float(bars.High.iloc[i] - bars.Low.iloc[i]),
                                     abs(float(bars.High.iloc[i] - close[i - 1])),
                                     abs(float(bars.Low.iloc[i] - close[i - 1]))) / close[i - 1]
                                for i in range(1, len(bars))]
        independent_reference = [float(np.sum(volatility[i - 20:i]) / 20) for i in range(400, len(bars))]
        np.testing.assert_allclose(history.volatility_range_pct, volatility[400:], rtol=0, atol=1e-14)
        np.testing.assert_allclose(history.volatility_reference_mean20, independent_reference, rtol=0, atol=1e-14)
        np.testing.assert_allclose(history.volatility_clock_increment,
                                   np.asarray(volatility[400:]) / independent_reference, rtol=0, atol=1e-12)
        counts['independent_volatility_rows'] += len(sessions)
        for column in ('acf1', 'close', 'momentum20', 'regime', 'regime_momentum',
                       'bull_range_position', 'bear_range_position', 'confirmation_score',
                       'confirmation_acf', 'confirmation_turnover', 'confirmation_volume'):
            pd.testing.assert_series_equal(history[column], baseline[column])
        audit_clock(history)
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
    for value in ('TIME', 'ALL_VOLATILITY_TIME2', None):
        p = deepcopy(base)
        p['mechanism'] = value
        reject(lambda: new.VolatilityTimeRange(ParameterSet(p)), 'fixed enum')
    p = deepcopy(base)
    p['confirmation']['enabled'] = False
    reject(lambda: new.VolatilityTimeRange(ParameterSet(p)), 'disabled original confirmation')

    def normalized(frame, acf, window):
        index = pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
        result = pd.DataFrame(0., index=index, columns=('acf', 'turnover', 'volume'))
        return result, result

    def controlled(mode, widths, route='bear', horizon=4, compare_original=False,
                   score_threshold=-.2, positions=None, close_values=None, stop=None, trail=None,
                   threshold=None, prior_width=1., start=40):
        size = start + len(widths)
        frame = bars.iloc[:size].copy()
        close_array = np.full(size, 10.) if close_values is None else np.asarray(close_values, dtype=float)
        half_width = np.asarray([prior_width] * start + widths, dtype=float)
        frame['Close'] = close_array
        frame['High'] = close_array + half_width
        frame['Low'] = close_array - half_width
        frame['Open'] = close_array
        p = deepcopy(base)
        p['mechanism'] = mode
        p['regime_threshold'] = (.2 if route == 'bear' else -.2) if threshold is None else float(threshold)
        p['regime_window'] = 5
        p['confirmation']['threshold'] = score_threshold
        p['bull']['max_hold'] = p['bear']['max_hold'] = horizon
        p['bull']['stop_loss'] = p['bear']['stop_loss'] = stop
        p['bull']['trailing_stop'] = p['bear']['trailing_stop'] = trail
        index = pd.DatetimeIndex(frame.Date)

        def features(input_frame, window):
            return pd.DataFrame({'range_position': .5 if positions is None else positions,
                                 'acf1': .25, 'close': input_frame.Close.to_numpy(),
                                 'momentum20': 0.}, index=index)

        with patch.object(new, 'components', features), patch.object(new, 'confirmation_features', normalized):
            history = new.VolatilityTimeRange(ParameterSet(p)).calculate_history({'daily': frame}, index[start:])
        if compare_original:
            oldp = {key: value for key, value in p.items() if key != 'mechanism'}
            with patch.object(original, 'components', features), patch.object(original, 'confirmation_features', normalized):
                baseline = original.ReentryConfirmedRange(ParameterSet(oldp)).calculate_history({'daily': frame}, index[start:])
            pd.testing.assert_frame_equal(history[baseline.columns], baseline)
        audit_clock(history)
        counts['controlled_histories'] += 1
        return history

    for mode in MODES:
        for route in ('bull', 'bear'):
            for horizon in (1, 2, 4, 8, 60):
                history = controlled(mode, [1.] * (horizon + 2), route=route, horizon=horizon,
                                     compare_original=True)
                np.testing.assert_array_equal(history.volatility_clock_increment, np.ones(len(history)))
                assert history.iloc[horizon].signal_reason == 'time'
                counts['constant_increment_exact_cases'] += 1
        for width, expected in ((.5, 'hold'), (1., 'time'), (2., 'time')):
            history = controlled(mode, [1., width], horizon=1)
            assert history.iloc[1].signal_reason == expected
            assert history.iloc[1].holding_clock == width
        zero = controlled(mode, [1., 0., .25], horizon=1)
        assert zero.signal_reason.tolist() == ['entry', 'hold', 'hold']
        assert zero.iloc[1].holding_clock == 0. and zero.iloc[1].volatility_clock_increment == 0.
        slow = controlled(mode, [1.] + [.25] * 7, horizon=4)
        assert slow.iloc[-1].holding_age > 4 and slow.iloc[-1].target_position == 1.
        spike = controlled(mode, [1., 6., 1., 1.], horizon=4)
        assert spike.iloc[1].signal_reason == 'time'
        np.testing.assert_allclose(spike.iloc[1].holding_clock, 6., rtol=0, atol=1e-12)
        assert spike.iloc[2].signal_reason == 'entry' and spike.iloc[2].holding_clock == 0.
        pos = [.5] * 44
        pos[42:] = [.94, .94]  # Flat after expiry has no new bear opportunity, preserving its final clock.
        retained = controlled(mode, [1., 6., 1., 1.], horizon=4, positions=pos)
        assert retained.signal_reason.tolist() == ['entry', 'time', 'flat', 'flat']
        np.testing.assert_allclose(retained.holding_clock, [0., 6., 6., 6.], rtol=0, atol=1e-12)
        denied = controlled(mode, [1., 1.], score_threshold=.1)
        assert set(denied.signal_reason) == {'confirmation_rejected'}
        assert (denied.holding_clock == 0.).all()
        # Both-day time condition is true, but the original higher labels win.
        prices = [10.] * 40 + [10., 9.5]
        pos = [.5] * 42
        pos[41] = .99
        for stop, trail, use_range, expected in ((.01, .01, True, 'loss'),
                                               (None, .01, True, 'trailing'),
                                               (None, None, True, 'range'),
                                               (None, None, False, 'time')):
            priority = controlled(mode, [1., 6.], horizon=1, close_values=prices,
                                  positions=pos if use_range else None, stop=stop, trail=trail)
            assert priority.iloc[1].time_exit_condition
            assert priority.iloc[1].signal_reason == expected
            assert priority.iloc[1].time_exit_trigger == (expected == 'time')
        # Bear raw-bull transition remains immediate and time still wins on simultaneous expiry.
        prices = [10.] * 40 + [9., 11.]
        regime = controlled(mode, [1., 1.], close_values=prices, threshold=0., horizon=60)
        assert regime.signal_reason.tolist() == ['entry', 'regime']
        simultaneous = controlled(mode, [1., 1.], close_values=prices, threshold=0., horizon=1)
        assert simultaneous.iloc[1].signal_reason == 'time'
        # Unselected bull accumulates diagnostics but keeps the original actual-session expiry.
        if mode == MODES[0]:
            bull = controlled(mode, [1.] + [.25] * 5, route='bull', horizon=4, compare_original=True)
            assert bull.iloc[4].signal_reason == 'time' and bull.iloc[4].holding_clock < 4.

        reject(lambda: controlled(mode, [0., 0.], prior_width=0.), 'zero past20 reference')
        reject(lambda: controlled(mode, [1.], start=20), 'only 19 valid past true ranges')
        earliest = controlled(mode, [1.], start=21)
        assert np.isfinite(earliest.volatility_clock_increment).all()
        counts['warmup_cases'] += 2
        impl = new.VolatilityTimeRange(ParameterSet(base | {'mechanism': mode}))
        for column in ('High', 'Low', 'Close'):
            for value in (0., -1., np.nan, np.inf, -np.inf):
                invalid = bars.copy()
                invalid.loc[400, column] = value
                reject(lambda b=invalid: impl.calculate_history({'daily': b}, sessions), 'invalid signal price')
            reject(lambda c=column: impl.calculate_history({'daily': bars.drop(columns=c)}, sessions), 'missing signal price')
        invalid = bars.copy()
        invalid.loc[400, 'High'] = invalid.loc[400, 'Low'] * .9
        reject(lambda: impl.calculate_history({'daily': invalid}, sessions), 'High below Low')
        small = deepcopy(base)
        small['mechanism'] = mode
        small['confirmation']['lookback'] = 40
        small['bull']['range_window'] = small['bear']['range_window'] = 21
        small['regime_window'] = 5
        impl = new.VolatilityTimeRange(ParameterSet(small))
        assert next(r.lookback_sessions for r in impl.definition.inputs.requirements if r.name == 'daily') == 60
        impl.calculate_history({'daily': bars.iloc[:60]}, dates[59:60])
        small['regime_window'] = 60
        impl = new.VolatilityTimeRange(ParameterSet(small))
        assert next(r.lookback_sessions for r in impl.definition.inputs.requirements if r.name == 'daily') == 61
        impl.calculate_history({'daily': bars.iloc[:61]}, dates[60:61])
        counts['warmup_cases'] += 2

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
                assert new.VolatilityTimeRange(ParameterSet(p)).definition.parameters.values == ParameterSet(p).values
    counts['numeric_contract_boundary_cases'] = 52
    return {'status': 'PASS', 'scope': 'pure synthetic + public authenticated describe; zero accounts',
            'cases': counts, 'volatility_dependency_prices': 22,
            'minimum_contract_warmup': 60, 'W60_minimum_contract_warmup': 61,
            'clock_scope': 'every subsequent holding session; selected routes only use clock for expiry',
            'duration_contract': 'no actual-session cap on volatility-selected routes'}


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
