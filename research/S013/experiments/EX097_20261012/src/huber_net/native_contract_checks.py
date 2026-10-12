"""Huber adapter metadata and pure mock checks; no market ingestion or phases."""
from copy import deepcopy
from datetime import date
from hashlib import sha256
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import types
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet, TradableWindow

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[2]
PACKAGE = '_s013_huber_native_contract'


def run():
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(WORK / 'strategy_runtime')]
    sys.modules[PACKAGE] = package
    adapter = importlib.import_module(PACKAGE + '.strategies.huber_net')
    parent = importlib.import_module(PACKAGE + '.strategies.confirm_net')
    p = {'confirmation_lookback': 120, 'holding_sessions': 4, 'ridge_alpha': 10.0, 'huber_multiple': 1.345}
    strategy = adapter.HuberNet(ParameterSet(p))
    old = parent.ConfirmNet(ParameterSet({key: value for key, value in p.items() if key != 'huber_multiple'}))
    for field in ('inputs', 'decision', 'execution', 'monitoring', 'capabilities', 'tradable_symbol', 'observation'):
        assert getattr(strategy.definition, field) == getattr(old.definition, field)
    assert strategy.definition.parameters.values == ParameterSet(p).values
    window = TradableWindow(date(2021, 1, 4), date(2021, 1, 8))
    calendar = tuple(day.date() for day in pd.bdate_range('2019-12-01', '2021-01-08'))
    assert strategy.calendar_request(window) == old.calendar_request(window)
    assert strategy.derive_calculation_scope(window, calendar) == old.derive_calculation_scope(window, calendar)
    checks = ['inherited exact original80 InputContract/Scope/decision/execution, no market ingestion']
    for lookback in (40, 120):
        for horizon in (1, 60):
            for alpha in (1.0, 100.0):
                for multiple in (.5, 3.0):
                    adapter.HuberNet(ParameterSet({'confirmation_lookback': lookback, 'holding_sessions': horizon,
                                                   'ridge_alpha': alpha, 'huber_multiple': multiple}))
    checks.append('all four original/new parameter domain endpoints are legal')
    pure = importlib.import_module(PACKAGE + '.strategies.confirm_kernel')
    spec = importlib.util.spec_from_file_location('huber_original_scalar_labels', ROOT / 'research/S013/experiments/EX080_20261012/src/reproduction/82670d42c540_audit.py')
    audit80 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit80)
    axis = pd.bdate_range('2021-01-01', periods=100).as_unit('ns')
    prices = pd.DataFrame({'Open': 100 * np.exp(.001 * np.arange(100)),
                           'Close': 100 * np.exp(.001 * np.arange(100))}, index=axis)
    pd.testing.assert_frame_equal(adapter.net_labels(prices, axis, 4), audit80.net_labels(prices, axis), check_exact=True)
    for horizon in (1, 4, 60):
        labels = adapter.net_labels(prices, axis, horizon)
        for i in range(100):
            if i + horizon + 1 < 100:
                assert labels.iloc[i, 0] == prices.Open.iloc[i + horizon + 1] / prices.Open.iloc[i + 1] * (.999 / 1.001) - 1
                assert labels.iloc[i, 1] == axis[i + horizon + 1]
            else:
                assert np.isnan(labels.iloc[i, 0]) and pd.isna(labels.iloc[i, 1])
    checks.append('centreH4 independent old labels exact; H endpoints use actual dynamic maturity and missing tail')
    forecast = pd.Series(np.where(np.arange(100) % 7 == 0, .01, -.001), index=axis, name='net_forecast')
    for horizon in (1, 4, 60):
        actual = pure.episode_history(forecast, axis, horizon)
        expected = audit80.episodes(forecast, horizon)
        for column in expected:
            a, e = actual[column], expected[column]
            assert a.isna().equals(e.isna())
            good = e.notna()
            assert a[good].tolist() == e[good].tolist()
    checks.append('strictpositive entry/expiry priority/no sameT reentry matches independent old clock')
    original = adapter.prepare_history
    seen = []
    dummy = pd.DataFrame({'target_position': [0., 1.]}, index=axis[:2])

    def mocked(parameters, inputs, sessions):
        seen.append((parameters, inputs, sessions))
        return {'history': dummy}

    adapter.prepare_history = mocked
    try:
        assert strategy.calculate_history('synthetic sentinel', axis[:2]) is dummy
        assert seen[0][0] == ParameterSet(p).values and seen[0][1] == 'synthetic sentinel'
        assert seen[0][2].equals(axis[:2])
    finally:
        adapter.prepare_history = original
    checks.append('adaptercalculate dispatch signature exercised with explicit mock; no OHLC/provider consumed')
    refused = []
    for kind in ('extra_key', 'lookback39', 'lookback121', 'lookback_float', 'holding0', 'holding61',
                 'alpha0', 'alpha101', 'alpha_int', 'multiple_low', 'multiple_high', 'multiple_nan', 'multiple_int'):
        bad = deepcopy(p)
        if kind == 'extra_key':
            bad['fallback'] = True
        elif kind.startswith('lookback'):
            bad['confirmation_lookback'] = {'lookback39': 39, 'lookback121': 121, 'lookback_float': 120.0}[kind]
        elif kind.startswith('holding'):
            bad['holding_sessions'] = 0 if kind == 'holding0' else 61
        elif kind.startswith('alpha'):
            bad['ridge_alpha'] = {'alpha0': 0., 'alpha101': 101., 'alpha_int': 10}[kind]
        else:
            bad['huber_multiple'] = {'multiple_low': .499, 'multiple_high': 3.001, 'multiple_nan': np.nan, 'multiple_int': 1}[kind]
        try:
            adapter.HuberNet(ParameterSet(bad))
        except ValueError:
            refused.append(kind)
        else:
            raise AssertionError('Bad contract accepted: ' + kind)
    for name in ('confirm_kernel.py', 'confirm_net.py'):
        old_source = ROOT / 'research/S013/experiments/EX080_20261012/src/adapter_revision2/strategy_runtime/strategies' / name
        assert old_source.read_bytes() == (WORK / 'strategy_runtime/strategies' / name).read_bytes()
    assert (WORK / 'huber_kernel.py').read_bytes() == (WORK / 'strategy_runtime/strategies/huber_kernel.py').read_bytes()
    checks.append('original80 source bytes and pure/runtime Huber arithmetic bytes exact')
    result = {'status': 'PASS', 'synthetic_only': True, 'metadata_and_mock_only': True,
              'real_inputs_read': 0, 'accounts': 0, 'experiments_allocated': 0,
              'provider_calls': 0, 'checks': checks, 'check_count': len(checks),
              'rejections': refused, 'rejection_count': len(refused),
              'source_sha256': {name: sha256((WORK / 'strategy_runtime/strategies' / name).read_bytes()).hexdigest()
                                for name in ('confirm_kernel.py', 'confirm_net.py', 'huber_kernel.py', 'huber_net.py')},
              'native_market_calculate_path_executed': False,
              'hubernetscore_is_conditional_expected_payoff': False}
    (WORK / 'native_contract_checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({'status': 'PASS', 'checks': len(checks), 'refusals': len(refused), 'real_inputs': 0})


if __name__ == '__main__':
    run()
