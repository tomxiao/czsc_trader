"""EX037 pure synthetic model checks; no account preparation/evaluation."""
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


MODES = ('BEAR_MEAN_ACF_ADVERSE_TR', 'BEAR_MEAN_ACF_BODY_ADVERSE_TR')
FILES = ['strategies/' + name + '.py' for name in (
    'range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range',
    'acf_background_range', 'acf_range', '__init__')]


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
    original = json.loads(Path('research/S013/experiments/EX029_20261011/protocols/plan.json')
                          .read_text(encoding='utf-8'))['configurations'][0]['payload']
    configs = []
    for index, mode in enumerate(MODES):
        payload = deepcopy(original)
        payload['parameters']['mechanism'] = mode
        payload['runtime'] = {'module': 'strategy_runtime.strategies.acf_range',
                              'qualname': 'AcfRange', 'contract_version': 1,
                              'source_files': FILES,
                              'source_sha256': implementation_sha256(FILES, source_root=source)}
        configs.append({'label': 'N' + str(index), 'candidate_id': 'C' + str(5900 + index),
                        'payload': payload})
    return {'configurations': configs}


def synthetic(plan, source_root=None):
    source = Path(source_root) if source_root is not None else Path(__file__).parent / 'strategy_runtime'
    new = module(source, '_ex037_new', 'acf_range')
    body = module(source, '_ex037_body', 'acf_background_range')
    mean = module(Path('research/S013/experiments/EX028_20261011/src/strategy_runtime'),
                  '_ex037_mean', 'acf_range')
    counts = {'authenticated_configurations': 0, 'causal_configurations': 0,
              'independent_TR_rows': 0, 'background_exact_histories': 0,
              'controlled_histories': 0, 'rejected_cases': 0,
              'numeric_contract_boundaries': 0, 'warmup_cases': 0}
    configs = plan['configurations']
    assert len(configs) == 2 and {cfg['payload']['parameters']['mechanism'] for cfg in configs} == set(MODES)
    base = deepcopy(configs[0]['payload']['parameters'])
    rng = np.random.default_rng(13)
    dates = pd.bdate_range('2018-01-01', periods=640)
    close = 10 * np.exp(np.cumsum(rng.normal(.0004, .02, len(dates))))
    bars = pd.DataFrame({'Date': dates, 'Open': close * .999, 'High': close * 1.02,
                         'Low': close * .98, 'Close': close,
                         'Volume': np.exp(rng.normal(15, .2, len(dates))),
                         'Amount': np.exp(rng.normal(18, .2, len(dates)))})
    sessions = dates[400:]

    def background(parameters, inputs, selected):
        p = deepcopy(parameters)
        is_body = p['mechanism'] == MODES[1]
        p['mechanism'] = 'MEAN_ACF_NEW_BULL_BODY' if is_body else 'BEAR_ACF_CENTER_MEAN'
        implementation = body if is_body else mean
        return implementation.AcfRange(ParameterSet(p)).calculate_history(inputs, selected)

    for cfg in configs:
        bound = StrategyRuntime().describe(StrategyCandidate('S013', cfg['candidate_id'], cfg['payload'], source))
        assert bound.parameters.sha256 == ParameterSet(cfg['payload']['parameters']).sha256
        counts['authenticated_configurations'] += 1
        p = deepcopy(cfg['payload']['parameters'])
        impl = new.AcfRange(ParameterSet(p))
        result = impl.calculate_history({'daily': bars}, sessions)
        # Independent scalar TR formula and strictly prior twenty estimates.
        tr = [float('nan')]
        for i in range(1, len(bars)):
            row = bars.iloc[i]
            tr.append(max(row.High - row.Low, abs(row.High - bars.Close.iloc[i - 1]),
                          abs(row.Low - bars.Close.iloc[i - 1])))
        expected = [sum(tr[i - 20:i]) / 20 for i in range(400, len(bars))]
        np.testing.assert_allclose(result.risk_true_range_hfq, tr[400:], rtol=0, atol=1e-12)
        np.testing.assert_allclose(result.risk_reference_mean20_hfq, expected, rtol=0, atol=1e-12)
        counts['independent_TR_rows'] += len(sessions)
        cutoff = sessions[79]
        prefix = impl.calculate_history({'daily': bars[bars.Date <= cutoff]}, sessions[:80])
        pd.testing.assert_frame_equal(prefix, result.iloc[:80])
        future = bars.copy()
        future.loc[future.Date > cutoff, ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']] *= 1.37
        mutated = impl.calculate_history({'daily': future}, sessions)
        pd.testing.assert_frame_equal(mutated.iloc[:80], result.iloc[:80])
        counts['causal_configurations'] += 1
        # Wide positive OHLC prevents the protection; compare actual complete parent histories.
        quiet = bars.copy()
        quiet['High'], quiet['Low'] = quiet.Close + 100., quiet.Close * .01
        unchanged = impl.calculate_history({'daily': quiet}, sessions)
        old = background(p, {'daily': quiet}, sessions)
        assert not unchanged.bear_risk_hit.any()
        pd.testing.assert_frame_equal(unchanged[old.columns], old)
        counts['background_exact_histories'] += 1
        # All-bull complete paths, including the BODY gate, never gain bear protection.
        bullp = deepcopy(p)
        bullp['regime_threshold'] = -.2
        bullbars = bars.copy()
        bullclose = 10 * np.exp(np.cumsum(rng.uniform(.002, .025, len(dates))))
        for name, multiplier in (('Close', 1.), ('Open', .999), ('High', 1.02), ('Low', .98)):
            bullbars[name] = bullclose * multiplier
        bullnew = new.AcfRange(ParameterSet(bullp)).calculate_history({'daily': bullbars}, sessions)
        bullold = background(bullp, {'daily': bullbars}, sessions)
        assert bullnew.regime.eq('bull').all() and not bullnew.bear_risk_hit.any()
        pd.testing.assert_frame_equal(bullnew[bullold.columns], bullold)
        counts['background_exact_histories'] += 1
        # All data features/confirmation calculations are unchanged even when paths diverge.
        old = background(p, {'daily': bars}, sessions)
        for name in ('acf1', 'close', 'momentum20', 'regime', 'regime_momentum',
                     'bull_range_position', 'bear_range_position', 'confirmation_score',
                     'confirmation_acf', 'confirmation_turnover', 'confirmation_volume',
                     'bear_acf_raw', 'bear_acf_baseline', 'bear_acf_centered'):
            pd.testing.assert_series_equal(result[name], old[name])

    def reject(action, label):
        try:
            action()
        except ValueError:
            counts['rejected_cases'] += 1
            return
        raise AssertionError('invalid accepted: ' + label)

    def normalized(frame, acf, window):
        index = pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
        features = pd.DataFrame(0., index=index, columns=('acf', 'turnover', 'volume'))
        return features, features

    def controlled(mode, post, route='bear', horizon=4, positions=None, stop=None, trail=None,
                   score_threshold=-.2, acf_threshold=.1, raw_acf=None, closes=None,
                   opens=None, regime_threshold=None, regime_change=False, wide=False):
        close_values = [100.] * 40 + list(post) if closes is None else closes
        size = len(close_values)
        frame = bars.iloc[:size].copy()
        frame['Close'] = close_values
        frame['Open'] = frame.Close if opens is None else opens
        frame['High'] = np.maximum(frame.Close, frame.Open) + (100. if wide else 1.)
        frame['Low'] = np.minimum(frame.Close, frame.Open) - (50. if wide else 1.)
        p = deepcopy(base)
        p['mechanism'] = mode
        p['regime_window'] = 5
        p['regime_threshold'] = (.2 if route == 'bear' else -.2) if regime_threshold is None else regime_threshold
        p['exit_on_regime_change'] = regime_change
        p['confirmation']['lookback'] = 40
        p['confirmation']['threshold'] = score_threshold
        p['bull']['range_window'], p['bear']['range_window'] = 21, 22
        for route_name in ('bull', 'bear'):
            p[route_name]['max_hold'] = horizon
            p[route_name]['stop_loss'], p[route_name]['trailing_stop'] = stop, trail
        p['bear']['acf_min'] = acf_threshold
        index = pd.DatetimeIndex(frame.Date)
        acf = [0.] * 40 + [.25] * (size - 40) if raw_acf is None else raw_acf

        def components(input_frame, window):
            return pd.DataFrame({'range_position': .5 if positions is None else positions,
                                 'acf1': acf if window == 22 else .25,
                                 'close': input_frame.Close.to_numpy(), 'momentum20': 0.}, index=index)

        with patch.object(new, 'components', components), patch.object(new, 'confirmation_features', normalized):
            result = new.AcfRange(ParameterSet(p)).calculate_history({'daily': frame}, index[40:])
        counts['controlled_histories'] += 1
        return result, frame, p

    for mode in MODES:
        for end, expected in ((98.0001, 'hold'), (98., 'bear_risk'), (97.9999, 'bear_risk')):
            result, _, _ = controlled(mode, [100., end])
            assert result.signal_reason.tolist() == ['entry', expected]
            assert result.iloc[1].risk_reference_mean20_hfq == 2.
            assert not result.iloc[0].bear_risk_hit and result.iloc[0].holding_age == 0
            assert bool(result.iloc[1].bear_risk_hit) == (expected == 'bear_risk')
        # Current TR is excluded, and the unit updates daily rather than freezing at entry.
        evolving, frame, _ = controlled(mode, [100., 101., 99., 98.])
        tr = [max(frame.High.iloc[i] - frame.Low.iloc[i],
                  abs(frame.High.iloc[i] - frame.Close.iloc[i - 1]),
                  abs(frame.Low.iloc[i] - frame.Close.iloc[i - 1])) for i in range(1, len(frame))]
        for i, row in enumerate(evolving.itertuples(), start=40):
            assert abs(row.risk_reference_mean20_hfq - sum(tr[i - 21:i - 1]) / 20) < 1e-12
        # Exit does not install an entry lock; next eligible day enters with a fresh anchor.
        reentry, _, _ = controlled(mode, [100., 98., 97., 96.])
        assert reentry.signal_reason.tolist() == ['entry', 'bear_risk', 'entry', 'hold']
        assert reentry.entry_anchor_signal_close.tolist() == [100., 100., 97., 97.]
        assert reentry.holding_age.tolist() == [0, 1, 0, 1]
        bull, _, _ = controlled(mode, [100., 97., 96.], route='bull')
        assert bull.signal_reason.tolist() == ['entry', 'hold', 'hold'] and not bull.bear_risk_hit.any()
        denied, _, _ = controlled(mode, [100., 97.], score_threshold=.1)
        assert denied.signal_reason.eq('confirmation_rejected').all() and not denied.bear_risk_hit.any()
        absent, _, _ = controlled(mode, [100., 97.], acf_threshold=.5)
        assert absent.signal_reason.eq('flat').all() and not absent.bear_risk_hit.any()
        # Higher loss/trailing and lower range/time preserve complete priority.
        positions = [.5] * 41 + [.99]
        for stop, trail, expected in ((.01, .01, 'loss'), (None, .01, 'trailing'),
                                      (None, None, 'bear_risk')):
            priority, _, _ = controlled(mode, [100., 98.], horizon=1, positions=positions, stop=stop, trail=trail)
            assert priority.iloc[1].signal_reason == expected and priority.iloc[1].bear_risk_hit
            assert bool(priority.iloc[1].bear_risk_trigger) == (expected == 'bear_risk')
        for horizon in (1, 2, 4, 8, 60):
            time, _, _ = controlled(mode, [100.] * (horizon + 1), horizon=horizon,
                                    acf_threshold=None)
            assert time.iloc[-1].signal_reason == 'time' and time.iloc[-1].holding_age == horizon
            assert not time.bear_risk_hit.any()
        ranged, _, _ = controlled(mode, [100., 99.], horizon=1, positions=positions)
        assert ranged.iloc[1].signal_reason == 'range' and not ranged.iloc[1].bear_risk_hit
        # Boundary BODY refusal precedes the original score; stable bull has no direction filter.
        seq = [100.] * 34 + [120., 80., 80., 100., 100., 110., 100., 95., 90., 90.]
        opens = [max(value, 101.) for value in seq]
        boundary, _, _ = controlled(mode, [], closes=seq, opens=opens, regime_threshold=0., wide=True)
        assert boundary.iloc[0].previous_regime == 'bear' and boundary.iloc[0].regime == 'bull'
        assert boundary.iloc[0].signal_reason == ('entry_direction_rejected' if mode == MODES[1] else 'entry')
        if mode == MODES[1]:
            assert boundary.iloc[1].signal_reason == 'entry' and not boundary.iloc[1].entry_direction_gate_applies
        heldseq = [100.] * 34 + [120., 120., 80., 80., 80., 110., 100., 95., 90., 90.]
        rawexit, _, _ = controlled(mode, [], closes=heldseq, regime_threshold=0., regime_change=True, wide=True)
        assert rawexit.signal_reason.tolist()[:3] == ['entry', 'regime', 'entry']
        assert not rawexit.bear_risk_hit.any()
        # A rolling reference can turn raw regime bull despite a falling close;
        # the same held bear risk signal takes priority over that regime exit.
        simultaneous = [100.] * 35 + [101., 97.] + [100.] * 3 + [100., 97.]
        risk_regime, _, _ = controlled(mode, [], closes=simultaneous,
                                       regime_threshold=0., regime_change=True)
        assert risk_regime.regime.tolist() == ['bear', 'bull']
        assert risk_regime.signal_reason.tolist() == ['entry', 'bear_risk']
        assert risk_regime.iloc[1].bear_risk_trigger

    # Parent contracts remain unchanged for all thirteen coordinates.
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
        small = deepcopy(base)
        small['mechanism'] = mode
        small['confirmation']['lookback'] = 40
        small['bull']['range_window'] = small['bear']['range_window'] = 21
        for window, required in ((5, 61), (60, 62)):
            small['regime_window'] = window
            impl = new.AcfRange(ParameterSet(small))
            assert next(item.lookback_sessions for item in impl.definition.inputs.requirements if item.name == 'daily') == required
            impl.calculate_history({'daily': bars.iloc[:required]}, dates[required - 1:required])
            reject(lambda: impl.calculate_history({'daily': bars.iloc[:required - 1]}, dates[required - 2:required - 1]), 'insufficient warmup')
            counts['warmup_cases'] += 2
        impl = new.AcfRange(ParameterSet({**base, 'mechanism': mode}))
        for column in ('Open', 'High', 'Low', 'Close'):
            for value in (0., -1., np.nan, np.inf, -np.inf):
                invalid = bars.copy()
                invalid.loc[400, column] = value
                reject(lambda b=invalid: impl.calculate_history({'daily': b}, sessions), 'invalid OHLC')
            reject(lambda c=column: impl.calculate_history({'daily': bars.drop(columns=c)}, sessions), 'missing OHLC')
        invalid = bars.copy()
        invalid.loc[400, 'High'] = invalid.loc[400, 'Low'] / 2
        reject(lambda: impl.calculate_history({'daily': invalid}, sessions), 'High<Low')
        for column in ('High', 'Low'):
            invalid = bars.copy()
            invalid.loc[400, column] = invalid.loc[400, 'Close'] * (.99 if column == 'High' else 1.01)
            reject(lambda b=invalid: impl.calculate_history({'daily': b}, sessions), 'OHLC interval')
        invalid = bars.copy()
        invalid.loc[400, 'Date'] = invalid.loc[399, 'Date']
        reject(lambda: impl.calculate_history({'daily': invalid}, sessions), 'duplicate dates')
        zero = bars.copy()
        zero[['Open', 'High', 'Low', 'Close']] = 100.
        reject(lambda: impl.calculate_history({'daily': zero}, sessions), 'zero past20 unit')
        zero_current = bars.copy()
        zero_current.loc[400, ['Open', 'High', 'Low', 'Close']] = zero_current.Close.iloc[399]
        assert impl.calculate_history({'daily': zero_current}, sessions).iloc[0].risk_true_range_hfq == 0.
    for mode in ('INVALID', None):
        reject(lambda m=mode: new.AcfRange(ParameterSet({**base, 'mechanism': m})), 'mechanism')
    invalid = deepcopy(base)
    invalid['confirmation']['enabled'] = False
    reject(lambda: new.AcfRange(ParameterSet(invalid)), 'disabled original confirmation')
    return {'status': 'PASS', 'new_account_evaluations': 0, 'scope': 'pure synthetic + authenticated describe',
            'cases': counts, 'risk_constants': {'past_TR_sessions': 20, 'adverse_multiple': 1},
            'warmup': 'max(parent, confirmation.lookback+21, regime_window+2, 22)',
            'risk_unit': 'HFQ absolute prices; signal anchor is not actual-fill profitability'}


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    source = Path(__file__).resolve().parent / 'strategy_runtime'
    plan = temporary_plan(source)
    result = synthetic(plan, source)
    result['source_sha256'] = plan['configurations'][0]['payload']['runtime']['source_sha256']
    result['file_sha256'] = {str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in source.rglob('*.py')}
    output = Path('.tmp/ex037-synthetic/result.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, allow_nan=False))
