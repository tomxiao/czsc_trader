"""Pure EX041 bear-TIME reentry checks; no account preparation/evaluation."""
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


MODES = ('MEAN_BEAR_TIME_REENTRY_CLOSE', 'MEAN_BEAR_TIME_REENTRY_BODY')
FILES = ['strategies/' + name + '.py' for name in (
    'range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range', 'acf_range', '__init__')]


def module(folder, name):
    package = types.ModuleType(name)
    package.__path__ = [str(folder / 'strategies')]
    sys.modules[name] = package
    spec = importlib.util.spec_from_file_location(name + '.acf_range', folder / 'strategies/acf_range.py')
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def temporary_plan(source):
    original = next(cfg for cfg in json.loads(Path('research/S013/experiments/EX028_20261011/protocols/plan.json').read_text(encoding='utf-8'))['configurations'] if cfg['label'] == 'N1')['payload']
    configurations = []
    for index, mode in enumerate(MODES):
        payload = deepcopy(original)
        payload['parameters']['mechanism'] = mode
        payload['runtime'] = {'module': 'strategy_runtime.strategies.acf_range', 'qualname': 'AcfRange',
                              'contract_version': 1, 'source_files': FILES,
                              'source_sha256': implementation_sha256(FILES, source_root=source)}
        configurations.append({'label': f'N{index}', 'candidate_id': f'C{4800 + index}', 'payload': payload})
    return {'configurations': configurations}


def synthetic(plan, source_root=None):
    source = Path(source_root) if source_root is not None else Path(__file__).parent / 'strategy_runtime'
    original_source = Path('research/S013/experiments/EX040_20261011/src/strategy_runtime')
    for name in ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range', '__init__'):
        assert (source / 'strategies' / (name + '.py')).read_bytes() == (original_source / 'strategies' / (name + '.py')).read_bytes()
    new = module(source, '_ex041_new')
    mean = module(Path('research/S013/experiments/EX028_20261011/src/strategy_runtime'), '_ex041_mean')
    configs = plan['configurations']
    assert len(configs) == 2 and [cfg['payload']['parameters']['mechanism'] for cfg in configs] == list(MODES)
    counts = {'authenticated_configurations': 0, 'causal_configurations': 0,
              'mean_background_exact_histories': 0, 'controlled_histories': 0,
              'numeric_contract_boundaries': 0, 'invalid_inputs': 0}
    rng = np.random.default_rng(13)
    dates = pd.bdate_range('2018-01-01', periods=640)
    close = 10 * np.exp(np.cumsum(rng.normal(.0004, .02, len(dates))))
    bars = pd.DataFrame({'Date': dates, 'Open': close * .999, 'High': close * 1.02,
                         'Low': close * .98, 'Close': close,
                         'Volume': np.exp(rng.normal(15, .2, len(dates))),
                         'Amount': np.exp(rng.normal(18, .2, len(dates)))})
    sessions = dates[400:]
    for cfg in configs:
        p = deepcopy(cfg['payload']['parameters'])
        described = StrategyRuntime().describe(StrategyCandidate('S013', cfg['candidate_id'], cfg['payload'], source))
        assert described.parameters.sha256 == ParameterSet(p).sha256
        counts['authenticated_configurations'] += 1
        impl = new.AcfRange(ParameterSet(p))
        result = impl.calculate_history({'daily': bars}, sessions)
        applies = (result.confirmation_opportunity.astype(bool) & result.regime.eq('bear') &
                   result.last_exit_reason.eq('time') & result.last_exit_route.eq('bear'))
        np.testing.assert_array_equal(result.entry_direction_gate_applies, applies)
        assert result.iloc[0].last_exit_reason is None and result.iloc[0].last_exit_route is None
        cutoff = sessions[79]
        prefix = impl.calculate_history({'daily': bars[bars.Date <= cutoff]}, sessions[:80])
        pd.testing.assert_frame_equal(prefix, result.iloc[:80])
        future = bars.copy()
        future.loc[future.Date > cutoff, ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']] *= 1.37
        mutated = impl.calculate_history({'daily': future}, sessions)
        pd.testing.assert_frame_equal(mutated.iloc[:80], result.iloc[:80])
        counts['causal_configurations'] += 1
        oldp = deepcopy(p)
        oldp['mechanism'] = 'BEAR_ACF_CENTER_MEAN'
        baseline = mean.AcfRange(ParameterSet(oldp)).calculate_history({'daily': bars}, sessions)
        for name in ('acf1', 'close', 'momentum20', 'regime', 'regime_momentum', 'bear_acf_raw',
                     'bear_acf_baseline', 'bear_acf_centered', 'confirmation_score',
                     'confirmation_acf', 'confirmation_turnover', 'confirmation_volume'):
            pd.testing.assert_series_equal(result[name], baseline[name])
        # Complete bear native histories equal MEAN when every directional predicate passes.
        up = bars.copy()
        upclose = 10 * np.exp(np.cumsum(rng.uniform(.001, .004, len(dates))))
        for name, multiplier in (('Close', 1.), ('Open', .999), ('High', 1.02), ('Low', .98)):
            up[name] = upclose * multiplier
        testp = deepcopy(p)
        testp['regime_threshold'] = .2
        testp['confirmation']['threshold'] = -.5
        testp['bear'].update(entry=.95, exit=1., acf_min=-.6)
        history = new.AcfRange(ParameterSet(testp)).calculate_history({'daily': up}, sessions)
        original = deepcopy(testp)
        original['mechanism'] = 'BEAR_ACF_CENTER_MEAN'
        old = mean.AcfRange(ParameterSet(original)).calculate_history({'daily': up}, sessions)
        assert history.regime.eq('bear').all() and history.signal_reason.eq('time').any()
        assert history.entry_direction_gate_applies.any()
        pd.testing.assert_frame_equal(history[old.columns], old)
        counts['mean_background_exact_histories'] += 1

    base = deepcopy(configs[0]['payload']['parameters'])

    def controlled(mode, post, opening=None, horizon=1, positions=None, score_values=None,
                   threshold=-.2, route='bear', stop=None, trail=None, full_close=None,
                   regime_threshold=None, regime_change=False):
        closing = [100.] * 40 + list(post) if full_close is None else full_close
        size = len(closing)
        frame = bars.iloc[:size].copy()
        frame['Close'] = closing
        frame['Open'] = closing if opening is None else opening
        frame['High'], frame['Low'] = frame.Close * 1.02, frame.Close * .98
        index = pd.DatetimeIndex(frame.Date)
        p = deepcopy(base)
        p['mechanism'] = mode
        p['confirmation']['lookback'], p['confirmation']['threshold'] = 40, threshold
        p['bull']['range_window'], p['bear']['range_window'] = 21, 22
        p['regime_window'] = 5
        p['regime_threshold'] = (.2 if route == 'bear' else -.2) if regime_threshold is None else regime_threshold
        p['exit_on_regime_change'] = regime_change
        for key in ('bull', 'bear'):
            p[key]['max_hold'], p[key]['stop_loss'], p[key]['trailing_stop'] = horizon, stop, trail

        def components(input_frame, window):
            return pd.DataFrame({'range_position': .5 if positions is None else positions,
                                 'acf1': [0.] * 40 + [.25] * (size - 40) if window == 22 else .25,
                                 'close': input_frame.Close.to_numpy(), 'momentum20': 0.}, index=index)

        def normalized(input_frame, acf, lookback):
            value = pd.DataFrame({name: 0. if score_values is None else score_values
                                  for name in ('acf', 'turnover', 'volume')}, index=index)
            return value, value

        with patch.object(new, 'components', components), patch.object(new, 'confirmation_features', normalized):
            result = new.AcfRange(ParameterSet(p)).calculate_history({'daily': frame}, index[40:])
        counts['controlled_histories'] += 1
        return result

    for mode in MODES:
        # Initial bear entry ignores direction, even when both direction comparisons fail.
        initial = controlled(mode, [99., 99., 99.])
        assert initial.signal_reason.tolist() == ['entry', 'time', 'entry_direction_rejected']
        assert initial.last_exit_route.tolist() == [None, None, 'bear']
        assert initial.last_exit_reason.tolist() == [None, None, 'time']
        for sign in (-1., 0., 1.):
            price = 100. + sign if mode.endswith('_CLOSE') else 100.
            opens = [100.] * 42 + [price - sign]
            result = controlled(mode, [100., 100., price], opening=opens)
            assert result.signal_reason.tolist()[:2] == ['entry', 'time']
            assert result.iloc[2].signal_reason == ('entry' if sign == 1 else 'entry_direction_rejected')
            assert result.iloc[2].entry_direction_gate_applies
        # Refused opportunities preserve both markers; a new entry clears them for the next decision.
        sequence = [100., 100., 100., 99., 100., 100.]
        opens = [100.] * 40 + sequence[:-2] + [99., 100.]
        retained = controlled(mode, sequence, opening=opens, horizon=1)
        assert retained.signal_reason.tolist() == ['entry', 'time', 'entry_direction_rejected',
                                                  'entry_direction_rejected', 'entry', 'time']
        assert retained.last_exit_reason.tolist() == [None, None, 'time', 'time', 'time', None]
        assert retained.last_exit_route.tolist() == [None, None, 'bear', 'bear', 'bear', None]
        assert retained.confirmation_exit_context.tolist() == ['initial', 'initial', 'time', 'time', 'time', 'initial']
        scores = [0.] * 42 + [-.5]
        both_fail = controlled(mode, [100., 100., 100.], score_values=scores)
        assert not both_fail.iloc[2].confirmation_pass and both_fail.iloc[2].signal_reason == 'entry_direction_rejected'
        score_fail = controlled(mode, [100., 100., 101.], opening=[100.] * 43, score_values=scores)
        assert score_fail.iloc[2].signal_reason == 'confirmation_rejected' and score_fail.iloc[2].entry_direction_gate_applies
        # A range exit, loss or trail does not arm the TIME-only entry predicate.
        pos = [.5] * 41 + [.99, .5]
        ranged = controlled(mode, [100., 100., 100.], positions=pos, horizon=8)
        assert ranged.signal_reason.tolist() == ['entry', 'range', 'entry']
        assert ranged.iloc[2].last_exit_reason == 'range' and not ranged.iloc[2].entry_direction_gate_applies
        for stop, trail, expected in ((.005, .005, 'loss'), (None, .005, 'trailing')):
            exited = controlled(mode, [100., 99., 99.], stop=stop, trail=trail, horizon=8)
            assert exited.signal_reason.tolist() == ['entry', expected, 'entry']
            assert not exited.iloc[2].entry_direction_gate_applies
        # A bull TIME remembers bull and therefore never gates the next bear entry.
        bull_time_prices = [100.] * 35 + [80., 120., 120.] + [100.] * 2 + [100., 100., 99.]
        bull_time = controlled(mode, [], full_close=bull_time_prices, regime_threshold=0., regime_change=True)
        assert bull_time.signal_reason.tolist() == ['entry', 'time', 'entry']
        assert bull_time.iloc[2].last_exit_route == 'bull' and not bull_time.iloc[2].entry_direction_gate_applies
        # Flat ineligible raw-bull day does not clear a saved bear TIME mark.
        preserved_prices = [100.] * 35 + [120., 120., 80., 120., 120.] + [100., 100., 100., 100., 101., 101.]
        pos = [.5] * len(preserved_prices)
        pos[42] = .99
        opening = list(preserved_prices)
        opening[44] = 100.
        preserved = controlled(mode, [], full_close=preserved_prices, opening=opening,
                               positions=pos, regime_threshold=0., regime_change=True)
        assert preserved.regime.tolist()[:5] == ['bear', 'bear', 'bull', 'bear', 'bear']
        assert preserved.signal_reason.tolist()[:5] == ['entry', 'time', 'flat', 'entry_direction_rejected', 'entry']
        assert preserved.iloc[2].last_exit_reason == preserved.iloc[3].last_exit_reason == 'time'
        assert preserved.iloc[2].last_exit_route == preserved.iloc[3].last_exit_route == 'bear'
        # Held direction failures do not change H or trigger entry gates.
        for horizon in (1, 2, 4, 8, 60):
            held = controlled(mode, [100.] * (horizon + 1), horizon=horizon)
            assert held.signal_reason.tolist() == ['entry'] + ['hold'] * (horizon - 1) + ['time']
            assert not held.entry_direction_gate_applies.any()

    def reject(action):
        try:
            action()
        except ValueError:
            counts['invalid_inputs'] += 1
            return
        raise AssertionError('Invalid input accepted')

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
        impl = new.AcfRange(ParameterSet({**base, 'mechanism': mode}))
        for column in ('Open', 'Close'):
            for value in (0., -1., np.nan, np.inf, -np.inf):
                bad = bars.copy()
                bad.loc[400, column] = value
                reject(lambda b=bad: impl.calculate_history({'daily': b}, sessions))
    for invalid in (None, 'MEAN_BEAR_CLOSE', 'RAW_BEAR_TIME_REENTRY_BODY'):
        reject(lambda m=invalid: new.AcfRange(ParameterSet({**base, 'mechanism': m})))
    bad = deepcopy(base)
    bad['confirmation']['enabled'] = False
    reject(lambda: new.AcfRange(ParameterSet(bad)))
    return {'status': 'PASS', 'new_account_evaluations': 0, 'scope': 'pure synthetic + authenticated describe',
            'cases': counts, 'state_contract': 'last_exit_route/reason are BEFORE decision; signal exits set, entries clear, all flat/refusal/raw-regime changes preserve.',
            'limits': 'No actual fill profitability, new native account, economic qualification or parameter robustness tested.'}


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    source = Path(__file__).resolve().parent / 'strategy_runtime'
    plan = temporary_plan(source)
    result = synthetic(plan, source)
    result['source_sha256'] = plan['configurations'][0]['payload']['runtime']['source_sha256']
    result['file_sha256'] = {path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in source.rglob('*.py')}
    output = Path('.tmp/ex041-synthetic/result.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, allow_nan=False))
