"""Pure synthetic EX027 checks; contains no account preparation or evaluation."""
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


MODES = ('BEAR_ACF_MEDIAN3', 'BEAR_ACF_MEAN3')


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
        configs.append({'label': 'N' + str(index), 'candidate_id': 'C' + str(8900 + index),
                        'payload': payload})
    return {'configurations': configs}


def synthetic(plan, source_root=None):
    """Reusable by the formal helper: synthetic(plan, SRC / 'strategy_runtime')."""
    source = Path(source_root) if source_root is not None else Path(__file__).parent / 'strategy_runtime'
    new = module(source, '_ex027_acf', 'acf_range')
    original = module(source, '_ex027_original', 'reentry_confirmed_range')
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
        independently = []
        for session in sessions:
            last = raw.loc[:session].iloc[-3:].to_numpy()
            assert len(last) == 3 and np.isfinite(last).all()
            independently.append(float(np.median(last) if p['mechanism'] == MODES[0] else np.sum(last) / 3))
        np.testing.assert_allclose(history.bear_acf_filtered, independently, rtol=0, atol=1e-12)
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
                   position=None, prices=None, score_threshold=-.2, compare_original=False):
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
            result = new.AcfRange(ParameterSet(p)).calculate_history({'daily': frame}, index[5:])
        if compare_original:
            oldp = {key: value for key, value in p.items() if key != 'mechanism'}
            with patch.object(original, 'components', feature), patch.object(original, 'confirmation_features', normalized):
                baseline = original.ReentryConfirmedRange(ParameterSet(oldp)).calculate_history({'daily': frame}, index[5:])
            pd.testing.assert_frame_equal(result[baseline.columns], baseline)
        counts['controlled_histories'] += 1
        return result

    # Fixed outlier direction gives opposite median and mean decisions.
    for values, expected in (([.25, .25, -1.], ('entry', 'flat')),
                             ([-.25, -.25, 1.], ('flat', 'entry'))):
        sequence = [.25] * 3 + values
        for mode, reason in zip(MODES, expected, strict=True):
            result = controlled(mode, sequence)
            assert result.iloc[0].signal_reason == reason
    for mode in MODES:
        # Exercise real bull entries, holds, time exits, and score denial rather than flat-only routes.
        bull = controlled(mode, [.25] * 24, regime='bull', compare_original=True)
        assert {'entry', 'hold', 'time'} <= set(bull.signal_reason)
        bull_denied = controlled(mode, [.25] * 8, regime='bull', score_threshold=.1, compare_original=True)
        assert set(bull_denied.signal_reason) == {'confirmation_rejected'}
        unchanged_bear = controlled(mode, [.25] * 12, compare_original=True)
        assert 'time' in set(unchanged_bear.signal_reason)
        equality = controlled(mode, [.25] * 6, threshold=.25)
        assert equality.iloc[0].entry_acf_pass and equality.iloc[0].signal_reason == 'entry'
        denied = controlled(mode, [.25] * 6, score_threshold=.1)
        assert denied.iloc[0].signal_reason == 'confirmation_rejected'
        held = controlled(mode, [.25] * 6 + [-1.] * 5)
        assert held.signal_reason.tolist()[:5] == ['entry', 'hold', 'hold', 'hold', 'time']
        assert not held.iloc[3].entry_acf_pass
        for invalid in (np.nan, np.inf, -np.inf):
            # Selected raw value is finite; a missing preceding raw member must still reject.
            reject(lambda v=invalid, m=mode: controlled(m, [.25] * 3 + [v, .25, .25]),
                   'incomplete preceding ACF')

    # Real feature dependencies: the 23rd price is the first with three valid ACF20 values.
    smallp = deepcopy(base)
    smallp['confirmation']['lookback'] = 40
    smallp['bull']['range_window'] = smallp['bear']['range_window'] = 21
    smallp['regime_window'] = 5
    for mode in MODES:
        smallp['mechanism'] = mode
        impl = new.AcfRange(ParameterSet(smallp))
        with patch.object(new, 'confirmation_features', normalized):
            reject(lambda: impl.calculate_history({'daily': bars.iloc[:22]}, dates[21:22]), '22-price ACF')
            first = impl.calculate_history({'daily': bars.iloc[:23]}, dates[22:23])
            assert np.isfinite(first.bear_acf_filtered).all()
        assert next(r.lookback_sessions for r in impl.definition.inputs.requirements if r.name == 'daily') == 60
        impl.calculate_history({'daily': bars.iloc[:60]}, dates[59:60])
        reject(lambda: impl.calculate_history({'daily': bars.iloc[:59]}, dates[58:59]), 'confirmation warmup')
        wide = deepcopy(smallp)
        wide['regime_window'] = 60
        impl = new.AcfRange(ParameterSet(wide))
        assert next(r.lookback_sessions for r in impl.definition.inputs.requirements if r.name == 'daily') == 61
        impl.calculate_history({'daily': bars.iloc[:61]}, dates[60:61])
        reject(lambda: impl.calculate_history({'daily': bars.iloc[:60]}, dates[59:60]), 'W60 warmup')
        counts['warmup_cases'] += 6

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
            'cases': counts, 'acf_dependency_prices': 23, 'minimum_contract_warmup': 60,
            'W60_minimum_contract_warmup': 61}


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
