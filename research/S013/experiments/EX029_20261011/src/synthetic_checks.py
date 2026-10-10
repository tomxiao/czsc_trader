"""Pure synthetic EX029 checks; contains no account preparation or evaluation."""
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


MODES = ('MEAN_ACF_NEW_BULL_CLOSE', 'MEAN_ACF_NEW_BULL_BODY')


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
        'acf_range', '__init__')]
    configs = []
    for index, mode in enumerate(MODES):
        payload = deepcopy(original)
        payload['parameters']['mechanism'] = mode
        payload['runtime'] = {'module': 'strategy_runtime.strategies.acf_range',
                              'qualname': 'AcfRange', 'contract_version': 1,
                              'source_files': files,
                              'source_sha256': implementation_sha256(files, source_root=source)}
        configs.append({'label': 'N' + str(index), 'candidate_id': 'C' + str(8480 + index),
                        'payload': payload})
    return {'configurations': configs}


def synthetic(plan, source_root=None):
    """Reusable by the formal helper: synthetic(plan, SRC / 'strategy_runtime')."""
    source = Path(source_root) if source_root is not None else Path(__file__).parent / 'strategy_runtime'
    new = module(source, '_ex029_acf', 'acf_range')
    original = module(source, '_ex029_original', 'reentry_confirmed_range')
    configs = plan['configurations']
    assert len(configs) == 2
    assert {cfg['payload']['parameters']['mechanism'] for cfg in configs} == set(MODES)
    counts = {'authenticated_configurations': 0, 'causal_configurations': 0,
              'independent_aggregation_rows': 0, 'bull_exact_configurations': 0,
              'controlled_histories': 0, 'rejected_cases': 0, 'warmup_cases': 0}
    rng = np.random.default_rng(13)
    dates = pd.bdate_range('2018-01-01', periods=640)
    close = 6 * np.exp(np.cumsum(rng.normal(.0004, .02, len(dates))))
    bars = pd.DataFrame({'Date': dates, 'Open': close * .999, 'High': close * 1.02,
                         'Low': close * .98, 'Close': close,
                         'Volume': np.exp(rng.normal(15, .2, len(dates))),
                         'Amount': np.exp(rng.normal(18, .2, len(dates)))})
    sessions = dates[400:]

    for cfg in configs:
        # Public authenticated loading of each real enum/parameter payload, without an account.
        bound = StrategyRuntime().describe(StrategyCandidate('S013', cfg['candidate_id'], cfg['payload'], source))
        assert bound.parameters.sha256 == ParameterSet(cfg['payload']['parameters']).sha256
        counts['authenticated_configurations'] += 1
        p = deepcopy(cfg['payload']['parameters'])
        oldp = {key: value for key, value in p.items() if key != 'mechanism'}
        impl = new.AcfRange(ParameterSet(p))
        history = impl.calculate_history({'daily': bars}, sessions)
        baseline = original.ReentryConfirmedRange(ParameterSet(oldp)).calculate_history({'daily': bars}, sessions)
        raw = original.components(bars, p['bear']['range_window']).acf1
        independent_baseline, independent_centered = [], []
        for session in sessions:
            past = raw.loc[raw.index < session].iloc[-p['confirmation']['lookback']:].to_numpy()
            assert len(past) == p['confirmation']['lookback'] and np.isfinite(past).all()
            baseline_value = float(np.sum(past) / len(past))
            independent_baseline.append(baseline_value)
            independent_centered.append(float(raw.loc[session] - baseline_value))
        np.testing.assert_allclose(history.bear_acf_baseline, independent_baseline, rtol=0, atol=1e-12)
        np.testing.assert_allclose(history.bear_acf_centered, independent_centered, rtol=0, atol=1e-12)
        pd.testing.assert_series_equal(history.bear_acf_raw, raw.reindex(sessions), check_names=False)
        counts['independent_aggregation_rows'] += len(sessions)
        for column in ('acf1', 'close', 'momentum20', 'regime', 'regime_momentum',
                       'bull_range_position', 'bear_range_position', 'confirmation_score',
                       'confirmation_acf', 'confirmation_turnover', 'confirmation_volume'):
            pd.testing.assert_series_equal(history[column], baseline[column])
        cutoff = sessions[79]
        prefix = impl.calculate_history({'daily': bars[bars.Date <= cutoff]}, sessions[:80])
        pd.testing.assert_frame_equal(prefix, history.iloc[:80])
        future = bars.copy()
        mask = future.Date > cutoff
        future.loc[mask, ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']] *= 1.37
        changed = impl.calculate_history({'daily': future}, sessions)
        pd.testing.assert_frame_equal(changed.iloc[:80], history.iloc[:80])
        counts['causal_configurations'] += 1

        # All-bull paths must preserve every original column, including holdings and exits.
        bull_bars = bars.copy()
        bull_close = 6 * np.exp(np.cumsum(rng.uniform(.002, .025, len(dates))))
        for column, multiplier in (('Close', 1.), ('Open', .999), ('High', 1.02), ('Low', .98)):
            bull_bars[column] = bull_close * multiplier
        bullp = deepcopy(p)
        bullp['regime_threshold'] = -.2
        oldbull = {key: value for key, value in bullp.items() if key != 'mechanism'}
        bullnew = new.AcfRange(ParameterSet(bullp)).calculate_history({'daily': bull_bars}, sessions)
        bullold = original.ReentryConfirmedRange(ParameterSet(oldbull)).calculate_history({'daily': bull_bars}, sessions)
        assert (bullnew.regime == 'bull').all()
        pd.testing.assert_frame_equal(bullnew[bullold.columns], bullold)
        counts['bull_exact_configurations'] += 1

    def reject(action, label):
        expect_rejected(action, label)
        counts['rejected_cases'] += 1

    base = deepcopy(configs[0]['payload']['parameters'])
    for key, value in (('mechanism', 'SMOOTH'), ('mechanism', None)):
        bad = deepcopy(base)
        bad[key] = value
        reject(lambda: new.AcfRange(ParameterSet(bad)), 'mechanism')
    bad = deepcopy(base)
    bad['confirmation']['enabled'] = False
    reject(lambda: new.AcfRange(ParameterSet(bad)), 'disabled confirmation')

    def normalized(frame, acf, window):
        index = pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
        feature = pd.DataFrame(0., index=index, columns=('acf', 'turnover', 'volume'))
        return feature, feature

    def controlled(mode, values, threshold=.1, regime='bear', horizon=4,
                   position=None, prices=None, score_threshold=-.2, compare_original=False,
                   session_start=40):
        size = len(values)
        frame = bars.iloc[:size].copy()
        frame['Close'] = np.linspace(12, 6, size) if regime == 'bear' else np.linspace(6, 12, size)
        if prices is not None:
            frame['Close'] = prices
        p = deepcopy(base)
        p['mechanism'] = mode
        p['regime_window'] = 5
        p['regime_threshold'] = .2 if regime == 'bear' else -.2
        p['exit_on_regime_change'] = False
        p['bear']['acf_min'] = threshold
        p['bear']['max_hold'] = horizon
        p['confirmation']['threshold'] = score_threshold
        p['confirmation']['lookback'] = 40
        p['bull']['range_window'] = 21
        p['bear']['range_window'] = 22
        index = pd.DatetimeIndex(frame.Date)

        def feature(input_frame, window):
            result = pd.DataFrame({'range_position': .5, 'acf1': .25,
                                   'close': input_frame.Close.to_numpy(), 'momentum20': 0.}, index=index)
            if window == 22:
                result['acf1'] = values
            if position is not None:
                result['range_position'] = position
            return result

        with patch.object(new, 'components', feature), patch.object(new, 'confirmation_features', normalized):
            result = new.AcfRange(ParameterSet(p)).calculate_history({'daily': frame}, index[session_start:])
        if compare_original:
            oldp = {key: value for key, value in p.items() if key != 'mechanism'}
            with patch.object(original, 'components', feature), patch.object(original, 'confirmation_features', normalized):
                baseline = original.ReentryConfirmedRange(ParameterSet(oldp)).calculate_history({'daily': frame}, index[session_start:])
            pd.testing.assert_frame_equal(result[baseline.columns], baseline)
        counts['controlled_histories'] += 1
        return result

    # Both new categories preserve EX028 mean centering exactly, including outlier response.
    for sequence, reason in (([.25] * 30 + [1.] * 10 + [.5], 'flat'),
                             ([.5] * 30 + [-1.] * 10 + [.5], 'entry')):
        for mode in MODES:
            result = controlled(mode, sequence)
            assert result.iloc[0].signal_reason == reason
    for mode in MODES:
        # Exercise real bull entries, holds, time exits, and score denial rather than flat-only routes.
        bull = controlled(mode, [.25] * 64, regime='bull', compare_original=True)
        assert {'entry', 'hold', 'time'} <= set(bull.signal_reason)
        bull_denied = controlled(mode, [.25] * 48, regime='bull', score_threshold=.1, compare_original=True)
        assert set(bull_denied.signal_reason) == {'confirmation_rejected'}
        unchanged_bear = controlled(mode, [0.] * 40 + [.25] * 12, compare_original=True)
        assert 'time' in set(unchanged_bear.signal_reason)
        equality = controlled(mode, [.25] * 40 + [.5], threshold=.25)
        assert equality.iloc[0].entry_acf_pass and equality.iloc[0].signal_reason == 'entry'
        denied = controlled(mode, [.25] * 40 + [.5], score_threshold=.1)
        assert denied.iloc[0].signal_reason == 'confirmation_rejected'
        held = controlled(mode, [.25] * 40 + [.5] + [-1.] * 5)
        assert held.signal_reason.tolist()[:5] == ['entry', 'hold', 'hold', 'hold', 'time']
        assert not held.iloc[3].entry_acf_pass
        # At the first session the baseline excludes the current .5, and at the next includes it.
        shifted = controlled(mode, [0.] * 40 + [.5, -.25])
        assert shifted.iloc[0].bear_acf_baseline == 0.
        assert shifted.iloc[0].bear_acf_centered == .5
        assert shifted.iloc[1].bear_acf_baseline == .0125
        # Identical current ACF can pass or fail as its actual past level changes.
        low = controlled(mode, [0.] * 40 + [.25])
        high = controlled(mode, [.25] * 41)
        assert low.iloc[0].signal_reason == 'entry' and high.iloc[0].signal_reason == 'flat'
        for invalid in (np.nan, np.inf, -np.inf):
            # Selected raw value is finite; even the oldest required prior value cannot be skipped.
            reject(lambda v=invalid, m=mode: controlled(m, [v] + [.25] * 39 + [.5]),
                   'incomplete preceding ACF')
            reject(lambda v=invalid, m=mode: controlled(m, [.25] * 40 + [v]), 'invalid current ACF')
        reject(lambda m=mode: controlled(m, [.25] * 39 + [.5], session_start=39), 'only 39 preceding estimates')

    # Real feature dependency: L past ACF20 estimates plus current require L+21 prices.
    smallp = deepcopy(base)
    smallp['confirmation']['lookback'] = 40
    smallp['bull']['range_window'] = smallp['bear']['range_window'] = 21
    smallp['regime_window'] = 5
    for mode in MODES:
        smallp['mechanism'] = mode
        impl = new.AcfRange(ParameterSet(smallp))
        assert next(r.lookback_sessions for r in impl.definition.inputs.requirements if r.name == 'daily') == 61
        impl.calculate_history({'daily': bars.iloc[:61]}, dates[60:61])
        reject(lambda: impl.calculate_history({'daily': bars.iloc[:60]}, dates[59:60]), '40 past estimates warmup')
        wide = deepcopy(smallp)
        wide['regime_window'] = 60
        impl = new.AcfRange(ParameterSet(wide))
        assert next(r.lookback_sessions for r in impl.definition.inputs.requirements if r.name == 'daily') == 62
        impl.calculate_history({'daily': bars.iloc[:62]}, dates[61:62])
        reject(lambda: impl.calculate_history({'daily': bars.iloc[:61]}, dates[60:61]), 'W60 previous regime warmup')
        longp = deepcopy(smallp)
        longp['confirmation']['lookback'] = 120
        impl = new.AcfRange(ParameterSet(longp))
        assert next(r.lookback_sessions for r in impl.definition.inputs.requirements if r.name == 'daily') == 141
        impl.calculate_history({'daily': bars.iloc[:141]}, dates[140:141])
        reject(lambda: impl.calculate_history({'daily': bars.iloc[:140]}, dates[139:140]), '120 past estimates warmup')
        counts['warmup_cases'] += 6

    # Explicit price sequences independently create the raw bear-to-bull boundary.
    def direction_case(mode, close_values=None, open_values=None, positions=None,
                       score_threshold=-.2, horizon=8, stop=None, trail=None,
                       threshold=0., entry_gate='all'):
        frame = bars.iloc[:44].copy()
        close_values = ([10.] * 34 + [12., 8., 8., 10., 10., 11., 10., 9.5, 9., 9.]
                        if close_values is None else close_values)
        frame['Close'] = close_values
        frame['Open'] = frame.Close * .99 if open_values is None else open_values
        p = deepcopy(base)
        p['mechanism'] = mode
        p['regime_window'] = 5
        p['regime_threshold'] = float(threshold)
        p['confirmation']['lookback'] = 40
        p['confirmation']['threshold'] = score_threshold
        p['context']['entry_gate'] = entry_gate
        p['bull']['range_window'] = 21
        p['bear']['range_window'] = 22
        p['bull']['max_hold'] = p['bear']['max_hold'] = horizon
        p['bull']['stop_loss'] = p['bear']['stop_loss'] = stop
        p['bull']['trailing_stop'] = p['bear']['trailing_stop'] = trail
        index = pd.DatetimeIndex(frame.Date)

        def features(input_frame, window):
            raw = np.zeros(len(index)) if window == 22 else np.full(len(index), .25)
            if window == 22:
                raw[40:] = .25
            return pd.DataFrame({'range_position': .5 if positions is None else positions,
                                 'acf1': raw, 'close': input_frame.Close.to_numpy(),
                                 'momentum20': 0.}, index=index)

        with patch.object(new, 'components', features), patch.object(new, 'confirmation_features', normalized):
            result = new.AcfRange(ParameterSet(p)).calculate_history({'daily': frame}, index[40:])
        # Audit the diagnostics from the actual synthetic price sequence, without strategy routing code.
        price_series = pd.Series(close_values, index=index)
        raw_momentum = price_series / price_series.shift(5) - 1
        expected_regime = np.where(raw_momentum.loc[index[40:]] >= threshold, 'bull', 'bear')
        expected_previous = np.where(raw_momentum.shift(1).loc[index[40:]] >= threshold, 'bull', 'bear')
        np.testing.assert_array_equal(result.regime, expected_regime)
        np.testing.assert_array_equal(result.previous_regime, expected_previous)
        np.testing.assert_array_equal(result.entry_direction_gate_applies,
                                      (expected_regime == 'bull') & (expected_previous == 'bear'))
        comparison = (frame.Close.shift(1) if mode == MODES[0] else frame.Open)
        np.testing.assert_array_equal(result.entry_direction_up, (frame.Close > comparison).iloc[40:])
        np.testing.assert_array_equal(result.previous_signal_close, frame.Close.shift(1).iloc[40:])
        np.testing.assert_array_equal(result.entry_signal_close, frame.Close.iloc[40:])
        np.testing.assert_array_equal(result.entry_signal_open, frame.Open.iloc[40:])
        counts['controlled_histories'] += 1
        return result, close_values

    first, sequence = direction_case(MODES[0])
    assert first.signal_reason.tolist()[:2] == ['entry_direction_rejected', 'entry']
    assert first.iloc[0].entry_direction_gate_applies and not first.iloc[1].entry_direction_gate_applies
    # After a refused boundary, the declining next stable-bull close is still permitted.
    body, _ = direction_case(MODES[1])
    assert body.signal_reason.tolist()[:2] == ['entry', 'hold']
    for mode in MODES:
        for relation in (-1, 0, 1):
            closing, opening = list(sequence), [9.] * len(sequence)
            if mode == MODES[0]:
                closing[40] = closing[39] + relation
            else:
                opening[40] = closing[40] - relation
            result, _ = direction_case(mode, closing, opening)
            assert result.iloc[0].signal_reason == ('entry' if relation == 1 else 'entry_direction_rejected')
        # Direction refusal has label priority when both direction and score fail.
        opens = [11.] * len(sequence)
        rejected, _ = direction_case(mode, sequence, opens, score_threshold=.1)
        assert rejected.iloc[0].signal_reason == 'entry_direction_rejected'
        good_close = list(sequence)
        good_close[40] = 12.
        denied, _ = direction_case(mode, good_close, [9.] * len(sequence), score_threshold=.1)
        assert denied.iloc[0].signal_reason == 'confirmation_rejected'
        # No eligible range opportunity means no direction refusal.
        positions = [.5] * len(sequence)
        positions[40] = .8
        absent, _ = direction_case(mode, sequence, opens, positions=positions)
        assert absent.iloc[0].signal_reason == 'flat'
        # Stable bull and bear do not gain a price direction constraint.
        stable_bull, _ = direction_case(mode, sequence, opens, threshold=-.2)
        assert stable_bull.iloc[0].signal_reason == 'entry'
        bear_sequence = list(sequence)
        bear_sequence[35] = 9.
        stable_bear, _ = direction_case(mode, bear_sequence, opens, threshold=.2)
        assert stable_bear.iloc[0].signal_reason == 'entry'
        assert not stable_bear.iloc[0].entry_direction_gate_applies
        # A held bear exits on the boundary; it cannot re-enter until the next stable bull day.
        held_sequence = list(sequence)
        held_sequence[35] = 12.
        held_sequence[41] = 9.
        held_sequence[42] = 8.5
        held_sequence[37] = 8.
        held_sequence[43] = 8.2
        held_sequence[38] = 8.
        held, _ = direction_case(mode, held_sequence, [12.] * len(sequence))
        assert held.signal_reason.tolist()[:3] == ['entry', 'regime', 'entry']
        assert held.iloc[1].entry_direction_gate_applies and not held.iloc[2].entry_direction_gate_applies
        assert held.iloc[2].confirmation_exit_context == 'regime'
        # Original exit labels retain loss > trailing > range > time > regime.
        pos = [.5] * len(sequence)
        pos[41] = .99
        for stop, trail, horizon, use_range, expected in ((.05, .05, 1, True, 'loss'),
                                                         (None, .05, 1, True, 'trailing'),
                                                         (None, None, 1, True, 'range'),
                                                         (None, None, 1, False, 'time'),
                                                         (None, None, 8, False, 'regime')):
            priority, _ = direction_case(mode, held_sequence, [12.] * len(sequence),
                                         positions=pos if use_range else None,
                                         horizon=horizon, stop=stop, trail=trail)
            assert priority.iloc[1].signal_reason == expected
        # Original context gate can suppress score on initial entry; direction still applies.
        context, _ = direction_case(mode, sequence, opens, score_threshold=.1, entry_gate='regime_reentry')
        assert context.iloc[0].confirmation_pass and context.iloc[0].signal_reason == 'entry_direction_rejected'
        validp = deepcopy(configs[0]['payload']['parameters'])
        validp['mechanism'] = mode
        impl = new.AcfRange(ParameterSet(validp))
        for column in ('Open', 'Close'):
            for value in (0., -1., np.nan, np.inf, -np.inf):
                invalid = bars.copy()
                invalid.loc[400, column] = value
                reject(lambda b=invalid: impl.calculate_history({'daily': b}, sessions), 'illegal signal price')
            invalid = bars.drop(columns=column)
            reject(lambda b=invalid: impl.calculate_history({'daily': b}, sessions), 'missing signal price')
    counts['direction_scope_and_priority_modes'] = 2

    # Both modes retain all parent numeric contracts and do not pin any of the 13 coordinates.
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
    counts['numeric_contract_boundary_cases'] = 52
    return {'status': 'PASS', 'scope': 'pure synthetic + public authenticated describe; zero accounts',
            'cases': counts, 'acf_dependency_prices': 'confirmation.lookback + 21',
            'minimum_contract_warmup': 61, 'W60_minimum_contract_warmup': 62,
            'L120_minimum_contract_warmup': 141}


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
