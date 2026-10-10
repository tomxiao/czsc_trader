"""Pure EX040 prototype checks; no prepared/evaluated account or publication."""
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


MODES = ('RAW_BEAR_CLOSE', 'RAW_BEAR_BODY', 'MEAN_BEAR_CLOSE', 'MEAN_BEAR_BODY')
FILES = ['strategies/' + name + '.py' for name in (
    'range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range', 'acf_range', '__init__')]


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
    raw = json.loads(Path('research/S013/experiments/EX020_20261011/protocols/plan.json').read_text(encoding='utf-8'))['controls'][0]['payload']
    mean = next(cfg for cfg in json.loads(Path('research/S013/experiments/EX028_20261011/protocols/plan.json').read_text(encoding='utf-8'))['configurations'] if cfg['label'] == 'N1')['payload']
    configurations = []
    for index, mode in enumerate(MODES):
        payload = deepcopy(raw if mode.startswith('RAW_') else mean)
        payload['parameters']['mechanism'] = mode
        payload['runtime'] = {'module': 'strategy_runtime.strategies.acf_range', 'qualname': 'AcfRange',
                              'contract_version': 1, 'source_files': FILES,
                              'source_sha256': implementation_sha256(FILES, source_root=source)}
        configurations.append({'label': f'N{index}', 'candidate_id': f'C{5200 + index}', 'payload': payload})
    return {'configurations': configurations}


def synthetic(plan, source_root=None):
    source = Path(source_root) if source_root is not None else Path(__file__).parent / 'strategy_runtime'
    original_source = Path('research/S013/experiments/EX029_20261011/src/strategy_runtime')
    for name in ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range', '__init__'):
        assert (source / 'strategies' / (name + '.py')).read_bytes() == (original_source / 'strategies' / (name + '.py')).read_bytes()
    new = module(source, '_ex040_new', 'acf_range')
    raw = module(source, '_ex040_raw', 'reentry_confirmed_range')
    mean = module(Path('research/S013/experiments/EX028_20261011/src/strategy_runtime'), '_ex040_mean', 'acf_range')
    configs = plan['configurations']
    assert len(configs) == 4 and [cfg['payload']['parameters']['mechanism'] for cfg in configs] == list(MODES)
    counts = {'authenticated_configurations': 0, 'causal_configurations': 0,
              'background_exact_histories': 0, 'controlled_histories': 0,
              'invalid_inputs': 0, 'numeric_contract_boundaries': 0, 'warmup_cases': 0}
    rng = np.random.default_rng(13)
    dates = pd.bdate_range('2018-01-01', periods=640)
    close = 10 * np.exp(np.cumsum(rng.normal(.0004, .02, len(dates))))
    bars = pd.DataFrame({'Date': dates, 'Open': close * .999, 'High': close * 1.02,
                         'Low': close * .98, 'Close': close,
                         'Volume': np.exp(rng.normal(15, .2, len(dates))),
                         'Amount': np.exp(rng.normal(18, .2, len(dates)))})
    sessions = dates[400:]

    def baseline(p, frame, selected):
        original = deepcopy(p)
        if p['mechanism'].startswith('RAW_'):
            original.pop('mechanism')
            return raw.ReentryConfirmedRange(ParameterSet(original)).calculate_history({'daily': frame}, selected)
        original['mechanism'] = 'BEAR_ACF_CENTER_MEAN'
        return mean.AcfRange(ParameterSet(original)).calculate_history({'daily': frame}, selected)

    for cfg in configs:
        bound = StrategyRuntime().describe(StrategyCandidate('S013', cfg['candidate_id'], cfg['payload'], source))
        p = deepcopy(cfg['payload']['parameters'])
        assert bound.parameters.sha256 == ParameterSet(p).sha256
        counts['authenticated_configurations'] += 1
        impl = new.AcfRange(ParameterSet(p))
        result = impl.calculate_history({'daily': bars}, sessions)
        expected_direction = bars.Close.gt(bars.Close.shift(1) if p['mechanism'].endswith('_CLOSE') else bars.Open).iloc[400:]
        np.testing.assert_array_equal(result.entry_direction_up, expected_direction)
        expected_applies = result.confirmation_opportunity.to_numpy(dtype=bool) & result.regime.eq('bear').to_numpy()
        np.testing.assert_array_equal(result.entry_direction_gate_applies, expected_applies)
        assert ('bear_acf_baseline' in result) == p['mechanism'].startswith('MEAN_')
        assert ('bear_acf_centered' in result) == p['mechanism'].startswith('MEAN_')
        cutoff = sessions[79]
        prefix = impl.calculate_history({'daily': bars[bars.Date <= cutoff]}, sessions[:80])
        pd.testing.assert_frame_equal(prefix, result.iloc[:80])
        future = bars.copy()
        future.loc[future.Date > cutoff, ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']] *= 1.37
        mutated = impl.calculate_history({'daily': future}, sessions)
        pd.testing.assert_frame_equal(mutated.iloc[:80], result.iloc[:80])
        counts['causal_configurations'] += 1
        old = baseline(p, bars, sessions)
        for name in ('acf1', 'close', 'momentum20', 'regime', 'regime_momentum', 'bull_range_position',
                     'bear_range_position', 'confirmation_score', 'confirmation_acf',
                     'confirmation_turnover', 'confirmation_volume'):
            pd.testing.assert_series_equal(result[name], old[name])
        # Direction always passes in this increasing-price history; original bear paths are exercised.
        up = bars.copy()
        upclose = 10 * np.exp(np.cumsum(rng.uniform(.001, .004, len(dates))))
        for name, multiplier in (('Close', 1.), ('Open', .999), ('High', 1.02), ('Low', .98)):
            up[name] = upclose * multiplier
        up_p = deepcopy(p)
        up_p['regime_threshold'] = .2
        up_p['confirmation']['threshold'] = -.5
        up_p['bear'].update(entry=.95, exit=1., acf_min=-.6)
        unchanged = new.AcfRange(ParameterSet(up_p)).calculate_history({'daily': up}, sessions)
        old = baseline(up_p, up, sessions)
        assert unchanged.regime.eq('bear').all() and unchanged.entry_direction_up.all()
        assert unchanged.signal_reason.eq('entry').any()
        pd.testing.assert_frame_equal(unchanged[old.columns], old)
        counts['background_exact_histories'] += 1
        # All-bull histories preserve the original background even with failing price direction.
        bull_p = deepcopy(p)
        bull_p['regime_threshold'] = -.2
        down = bars.copy()
        downclose = 10 * np.exp(-np.cumsum(rng.uniform(.001, .004, len(dates))))
        for name, multiplier in (('Close', 1.), ('Open', 1.001), ('High', 1.02), ('Low', .98)):
            down[name] = downclose * multiplier
        bull = new.AcfRange(ParameterSet(bull_p)).calculate_history({'daily': down}, sessions)
        old = baseline(bull_p, down, sessions)
        assert bull.regime.eq('bull').all() and not bull.entry_direction_up.any()
        assert not bull.entry_direction_gate_applies.any()
        pd.testing.assert_frame_equal(bull[old.columns], old)
        counts['background_exact_histories'] += 1

    base = deepcopy(configs[0]['payload']['parameters'])

    def controlled(mode, post, opens=None, positions=None, score_threshold=-.2,
                   acf_threshold=.1, raw_acf=None, route='bear', horizon=4, stop=None,
                   trail=None, close_values=None, regime_threshold=None, regime_change=False):
        closing = [100.] * 40 + list(post) if close_values is None else close_values
        size = len(closing)
        frame = bars.iloc[:size].copy()
        frame['Close'] = closing
        frame['Open'] = frame.Close - .1 if opens is None else opens
        frame['High'], frame['Low'] = frame.Close * 1.02, frame.Close * .98
        p = deepcopy(base)
        p['mechanism'] = mode
        p['regime_window'] = 5
        p['regime_threshold'] = (.2 if route == 'bear' else -.2) if regime_threshold is None else regime_threshold
        p['exit_on_regime_change'] = regime_change
        p['confirmation']['lookback'], p['confirmation']['threshold'] = 40, score_threshold
        p['bull']['range_window'], p['bear']['range_window'] = 21, 22
        p['bear']['acf_min'] = acf_threshold
        for key in ('bull', 'bear'):
            p[key]['max_hold'], p[key]['stop_loss'], p[key]['trailing_stop'] = horizon, stop, trail
        index = pd.DatetimeIndex(frame.Date)
        acf = [0.] * 40 + [.25] * (size - 40) if raw_acf is None else raw_acf

        def components(input_frame, window):
            return pd.DataFrame({'range_position': .5 if positions is None else positions,
                                 'acf1': acf if window == 22 else .25,
                                 'close': input_frame.Close.to_numpy(), 'momentum20': 0.}, index=index)

        def normalized(input_frame, values, lookback):
            result = pd.DataFrame(0., index=index, columns=('acf', 'turnover', 'volume'))
            return result, result

        with patch.object(new, 'components', components), patch.object(new, 'confirmation_features', normalized):
            result = new.AcfRange(ParameterSet(p)).calculate_history({'daily': frame}, index[40:])
        counts['controlled_histories'] += 1
        return result

    for mode in MODES:
        for sign in (-1., 0., 1.):
            ending = 100. + sign if mode.endswith('_CLOSE') else 100.
            opening = [100.] * 40 + [ending - sign]
            result = controlled(mode, [ending], opens=opening)
            assert result.iloc[0].signal_reason == ('entry' if sign == 1 else 'entry_direction_rejected')
            assert result.iloc[0].entry_direction_gate_applies
        both_fail = controlled(mode, [100.], opens=[100.] * 41, score_threshold=.1)
        assert both_fail.iloc[0].signal_reason == 'entry_direction_rejected'
        score_fail = controlled(mode, [101.], opens=[100.] * 41, score_threshold=.1)
        assert score_fail.iloc[0].signal_reason == 'confirmation_rejected'
        absent = controlled(mode, [100.], acf_threshold=.5)
        assert absent.iloc[0].signal_reason == 'flat' and not absent.iloc[0].entry_direction_gate_applies
        bull = controlled(mode, [100.], opens=[100.] * 41, route='bull')
        assert bull.iloc[0].signal_reason == 'entry' and not bull.iloc[0].entry_direction_gate_applies
        # Once held, falling/equal prices never become a direction exit; original timer unchanged.
        held = controlled(mode, [101., 100., 100., 99., 99.], opens=[102.] * 40 + [100., 102., 102., 102., 102.])
        assert held.signal_reason.tolist() == ['entry', 'hold', 'hold', 'hold', 'time']
        assert not held.entry_direction_gate_applies.iloc[1:].any()
        positions = [.5] * 41 + [.99]
        for stop, trail, horizon, ranges, expected in ((.005, .005, 1, True, 'loss'),
                                                      (None, .005, 1, True, 'trailing'),
                                                      (None, None, 1, True, 'range'),
                                                      (None, None, 1, False, 'time')):
            result = controlled(mode, [101., 100.], positions=positions if ranges else None,
                                stop=stop, trail=trail, horizon=horizon)
            assert result.iloc[1].signal_reason == expected
        # Original raw bear->bull regime exit occurs before any possible next-day entry.
        sequence = [100.] * 35 + [102., 98.] + [100.] * 3 + [101., 100., 99.]
        reg = controlled(mode, [], close_values=sequence, regime_threshold=0., regime_change=True)
        assert reg.signal_reason.tolist()[:2] == ['entry', 'regime']
        if mode.startswith('MEAN_'):
            # Identical current raw ACF with different strict past levels changes only original MEAN eligibility.
            low = controlled(mode, [101.], raw_acf=[0.] * 40 + [.25])
            high = controlled(mode, [101.], raw_acf=[.25] * 41)
            assert low.iloc[0].signal_reason == 'entry' and high.iloc[0].signal_reason == 'flat'

    def rejected(action):
        try:
            action()
        except ValueError:
            counts['invalid_inputs'] += 1
            return
        raise AssertionError('Illegal input accepted')

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
                assert new.AcfRange(ParameterSet(p)).definition.parameters.values == ParameterSet(p).values
                counts['numeric_contract_boundaries'] += 1
        p = deepcopy(base)
        p['mechanism'] = mode
        p['confirmation']['lookback'] = 40
        p['bull']['range_window'] = p['bear']['range_window'] = 21
        for window in (5, 60):
            p['regime_window'] = window
            impl = new.AcfRange(ParameterSet(p))
            old = deepcopy(p)
            old.pop('mechanism')
            parent = raw.ReentryConfirmedRange(ParameterSet(old))
            expected = max(parent._warmup, window + 2, 61 if mode.startswith('MEAN_') else 0)
            assert impl._warmup == expected
            impl.calculate_history({'daily': bars.iloc[:expected]}, dates[expected - 1:expected])
            counts['warmup_cases'] += 1
        impl = new.AcfRange(ParameterSet({**base, 'mechanism': mode}))
        for name in ('Open', 'Close'):
            for invalid in (0., -1., np.nan, np.inf, -np.inf):
                bad = bars.copy()
                bad.loc[400, name] = invalid
                rejected(lambda b=bad: impl.calculate_history({'daily': b}, sessions))
            rejected(lambda n=name: impl.calculate_history({'daily': bars.drop(columns=n)}, sessions))
    for invalid in (None, 'MEAN_ACF_NEW_BULL_BODY', 'RAW_BEAR_CLOSE2'):
        rejected(lambda m=invalid: new.AcfRange(ParameterSet({**base, 'mechanism': m})))
    bad = deepcopy(base)
    bad['confirmation']['enabled'] = False
    rejected(lambda: new.AcfRange(ParameterSet(bad)))
    return {'status': 'PASS', 'new_account_evaluations': 0, 'scope': 'pure prototype + authenticated describe',
            'cases': counts, 'direction_scope': 'flat and original eligible and raw bear only',
            'warmup': 'RAW max(parent,W+2); MEAN max(parent,L+21,W+2); previous raw regime adds diagnostic dependency only',
            'limits': 'No native account result, deployment, profit effect or economic qualification tested.'}


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    source = Path(__file__).resolve().parent / 'strategy_runtime'
    plan = temporary_plan(source)
    result = synthetic(plan, source)
    result['source_sha256'] = plan['configurations'][0]['payload']['runtime']['source_sha256']
    result['file_sha256'] = {path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in source.rglob('*.py')}
    output = Path('.tmp/ex040-synthetic/result.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, allow_nan=False))
