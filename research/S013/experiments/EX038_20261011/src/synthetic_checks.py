"""Focused EX038 pure checks for fixed2/3 cutoffs, without account evaluation."""
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


MODES = ('BEAR_MEAN_ACF_ADVERSE_TR2', 'BEAR_MEAN_ACF_ADVERSE_TR3',
         'BEAR_MEAN_ACF_BODY_ADVERSE_TR2', 'BEAR_MEAN_ACF_BODY_ADVERSE_TR3')
FILES = ['strategies/' + name + '.py' for name in (
    'range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range',
    'acf_background_range', 'acf_risk_one_range', 'acf_range', '__init__')]


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
    previous = json.loads(Path('research/S013/experiments/EX037_20261011/protocols/plan.json')
                          .read_text(encoding='utf-8'))['configurations']
    configurations = []
    for index, mode in enumerate(MODES):
        payload = deepcopy(previous[0 if index < 2 else 1]['payload'])
        payload['parameters']['mechanism'] = mode
        payload['runtime'] = {'module': 'strategy_runtime.strategies.acf_range',
                              'qualname': 'AcfRange', 'contract_version': 1, 'source_files': FILES,
                              'source_sha256': implementation_sha256(FILES, source_root=source)}
        configurations.append({'label': f'N{index}', 'candidate_id': f'C{5700 + index}', 'payload': payload})
    return {'configurations': configurations}


def synthetic(plan, source_root=None):
    source = Path(source_root) if source_root is not None else Path(__file__).parent / 'strategy_runtime'
    previous = Path('research/S013/experiments/EX037_20261011/src/strategy_runtime')
    for path in previous.rglob('*.py'):
        if '__pycache__' in path.parts:
            continue
        relative = path.relative_to(previous)
        retained = Path('strategies/acf_risk_one_range.py') if relative.as_posix() == 'strategies/acf_range.py' else relative
        assert path.read_bytes() == (source / retained).read_bytes(), str(relative)
    new = module(source, '_ex038_new', 'acf_range')
    one = module(source, '_ex038_one', 'acf_risk_one_range')
    body = module(source, '_ex038_body', 'acf_background_range')
    mean = module(Path('research/S013/experiments/EX028_20261011/src/strategy_runtime'),
                  '_ex038_mean', 'acf_range')
    configurations = plan['configurations']
    assert len(configurations) == 4
    assert [cfg['payload']['parameters']['mechanism'] for cfg in configurations] == list(MODES)
    counts = {'authenticated_configurations': 0, 'causal_configurations': 0,
              'exact_background_histories': 0, 'controlled_histories': 0, 'invalid_constants': 0,
              'original37_source_files_exact': 7}
    rng = np.random.default_rng(13)
    dates = pd.bdate_range('2018-01-01', periods=600)
    close = 10 * np.exp(np.cumsum(rng.normal(.0004, .02, len(dates))))
    bars = pd.DataFrame({'Date': dates, 'Open': close * .999, 'High': close * 1.02,
                         'Low': close * .98, 'Close': close,
                         'Volume': np.exp(rng.normal(15, .2, len(dates))),
                         'Amount': np.exp(rng.normal(18, .2, len(dates)))})
    sessions = dates[400:]
    for cfg in configurations:
        bound = StrategyRuntime().describe(StrategyCandidate('S013', cfg['candidate_id'], cfg['payload'], source))
        p = deepcopy(cfg['payload']['parameters'])
        assert bound.parameters.sha256 == ParameterSet(p).sha256
        counts['authenticated_configurations'] += 1
        multiplier = 2. if p['mechanism'].endswith('2') else 3.
        impl = new.AcfRange(ParameterSet(p))
        result = impl.calculate_history({'daily': bars}, sessions)
        assert result.risk_multiplier.eq(multiplier).all()
        pd.testing.assert_series_equal(result.risk_cutoff_hfq,
                                       multiplier * result.risk_reference_mean20_hfq, check_names=False)
        prior = deepcopy(p)
        prior['mechanism'] = 'BEAR_MEAN_ACF_BODY_ADVERSE_TR' if 'BODY' in p['mechanism'] else 'BEAR_MEAN_ACF_ADVERSE_TR'
        riskone = one.AcfRange(ParameterSet(prior)).calculate_history({'daily': bars}, sessions)
        for name in ('risk_true_range_hfq', 'risk_reference_mean20_hfq', 'bear_acf_raw',
                     'bear_acf_baseline', 'bear_acf_centered', 'confirmation_score', 'regime',
                     'entry_direction_up', 'entry_direction_gate_applies'):
            pd.testing.assert_series_equal(result[name], riskone[name])
        cutoff = sessions[79]
        prefix = impl.calculate_history({'daily': bars[bars.Date <= cutoff]}, sessions[:80])
        pd.testing.assert_frame_equal(prefix, result.iloc[:80])
        future = bars.copy()
        future.loc[future.Date > cutoff, ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']] *= 1.37
        mutated = impl.calculate_history({'daily': future}, sessions)
        pd.testing.assert_frame_equal(mutated.iloc[:80], result.iloc[:80])
        counts['causal_configurations'] += 1
        # Exact background decisions and columns when no protection event occurs.
        quiet = bars.copy()
        quiet['High'], quiet['Low'] = quiet.Close + 100., quiet.Close * .01
        unchanged = impl.calculate_history({'daily': quiet}, sessions)
        original = deepcopy(p)
        original['mechanism'] = 'MEAN_ACF_NEW_BULL_BODY' if 'BODY' in p['mechanism'] else 'BEAR_ACF_CENTER_MEAN'
        parent = body if 'BODY' in p['mechanism'] else mean
        background = parent.AcfRange(ParameterSet(original)).calculate_history({'daily': quiet}, sessions)
        assert not unchanged.bear_risk_hit.any()
        pd.testing.assert_frame_equal(unchanged[background.columns], background)
        counts['exact_background_histories'] += 1

    base = deepcopy(configurations[0]['payload']['parameters'])

    def controlled(mode, ending):
        frame = bars.iloc[:42].copy()
        frame['Close'] = [100.] * 41 + [ending]
        frame['Open'] = frame.Close
        frame['High'], frame['Low'] = frame.Close + 1., frame.Close - 1.
        index = pd.DatetimeIndex(frame.Date)
        p = deepcopy(base)
        p['mechanism'] = mode
        p['regime_window'], p['regime_threshold'] = 5, .2
        p['exit_on_regime_change'] = False
        p['confirmation']['lookback'], p['confirmation']['threshold'] = 40, -.2
        p['bull']['range_window'], p['bear']['range_window'] = 21, 22

        def components(input_frame, window):
            acf = [0.] * 40 + [.25] * 2 if window == 22 else .25
            return pd.DataFrame({'range_position': .5, 'acf1': acf,
                                 'close': input_frame.Close.to_numpy(), 'momentum20': 0.}, index=index)

        def normalized(input_frame, acf, window):
            value = pd.DataFrame(0., index=index, columns=('acf', 'turnover', 'volume'))
            return value, value

        with patch.object(new, 'components', components), patch.object(new, 'confirmation_features', normalized):
            result = new.AcfRange(ParameterSet(p)).calculate_history({'daily': frame}, index[40:])
        counts['controlled_histories'] += 1
        return result

    for mode in MODES:
        multiplier = 2. if mode.endswith('2') else 3.
        for delta, expected in ((.0001, 'hold'), (0., 'bear_risk'), (-.0001, 'bear_risk')):
            result = controlled(mode, 100. - multiplier * 2. + delta)
            assert result.signal_reason.tolist() == ['entry', expected]
            assert result.iloc[1].risk_reference_mean20_hfq == 2.
            assert result.iloc[1].risk_cutoff_hfq == multiplier * 2.
            assert not result.iloc[0].bear_risk_hit and result.iloc[0].holding_age == 0
            assert bool(result.iloc[1].bear_risk_hit) == (expected == 'bear_risk')
            assert not result.entry_direction_gate_applies.any()
    for two, three in ((MODES[0], MODES[1]), (MODES[2], MODES[3])):
        assert controlled(two, 95.).iloc[-1].signal_reason == 'bear_risk'
        assert controlled(three, 95.).iloc[-1].signal_reason == 'hold'
    for invalid in ('BEAR_MEAN_ACF_ADVERSE_TR', 'BEAR_MEAN_ACF_ADVERSE_TR1',
                    'BEAR_MEAN_ACF_ADVERSE_TR4', 'BEAR_MEAN_ACF_BODY_ADVERSE_TR0', None):
        try:
            new.AcfRange(ParameterSet({**base, 'mechanism': invalid}))
        except ValueError:
            counts['invalid_constants'] += 1
        else:
            raise AssertionError('unsupported fixed width accepted')
    return {'status': 'PASS', 'new_account_evaluations': 0, 'scope': 'focused pure synthetic and authenticated describe',
            'cases': counts, 'constants': {'widths': [2, 3], 'strictly_past_TR_sessions': 20},
            'limits': 'Outcome-informed fixed-width calibration; no claim of market profit or width robustness.'}


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    source = Path(__file__).resolve().parent / 'strategy_runtime'
    plan = temporary_plan(source)
    result = synthetic(plan, source)
    result['source_sha256'] = plan['configurations'][0]['payload']['runtime']['source_sha256']
    result['file_sha256'] = {path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in source.rglob('*.py')}
    output = Path('.tmp/ex038-synthetic/result.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, allow_nan=False))
