"""Deterministic buy-gate branch checks; mocked panels are signal-state only."""
from copy import deepcopy
import ast
import importlib.util
import sys
import types
from unittest.mock import patch

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet

from common import PROTOCOLS, RUNS, SOURCE, read, write


def load_module():
    package = types.ModuleType('_s013_complement_contract')
    package.__path__ = [str(SOURCE / 'strategies')]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location(
        package.__name__ + '.complement_confirmed_range',
        SOURCE / 'strategies/complement_confirmed_range.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_panel(module, parameters, current_close, turnover, volume, acf=None):
    """Inject date-local values to isolate state/AND/route boundary semantics."""
    dates = pd.bdate_range('2020-01-01', periods=20 + len(current_close))
    close = np.r_[np.full(20, 100.), np.asarray(current_close, dtype=float)]
    bars = pd.DataFrame({'Date': dates, 'Open': close, 'High': close * 1.01,
                         'Low': close * .99, 'Close': close,
                         'Volume': 100., 'Amount': 10000.})
    features = pd.DataFrame({'close': close, 'range_position': .5,
                             'acf1': .2, 'momentum20': 0.}, index=dates)
    normalized = pd.DataFrame({
        'acf': np.r_[np.zeros(20), np.asarray(acf if acf is not None
                                             else np.zeros(len(current_close)))],
        'turnover': np.r_[np.zeros(20), np.asarray(turnover)],
        'volume': np.r_[np.zeros(20), np.asarray(volume)]}, index=dates)
    with patch.object(module, 'components', side_effect=lambda _bars, _window: features.copy()), \
            patch.object(module, 'confirmation_features',
                         side_effect=lambda _bars, _acf, _window: (normalized.copy(), normalized.copy())):
        return module.ComplementConfirmedRange(ParameterSet(parameters)).calculate_history(
            {'daily': bars}, dates[20:])


def holding_branch(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == 'holding':
            return [ast.dump(item, include_attributes=False) for item in node.body]
    raise AssertionError('holding branch missing')


def main():
    module = load_module()
    parameters = deepcopy(read(PROTOCOLS / 'initial_plan.json')['configurations'][0]['parameters'])
    parameters['bull']['max_hold'] = parameters['bear']['max_hold'] = 2
    parameters['opportunity_confirmation'].update(
        enabled=True, profile='volume', threshold=-.2,
        weighting='EQUAL_FEATURES', application='ordinary_entries', route_scope='bull')
    closes = [101., 101., 100., 101., 101., 101., 101., 101., 101.]
    amounts = [.1, .1, .1, -.3, .1, -.3, -.3, .1, .1]
    volumes = [-.3, -.2, -.3, -.3, -.3, -.3, -.3, -.3, -.2]
    history = run_panel(module, parameters, closes, amounts, volumes)
    expected = ['confirmation_rejected', 'entry', 'regime', 'confirmation_rejected',
                'entry', 'hold', 'time', 'confirmation_rejected', 'entry']
    assert history.signal_reason.tolist() == expected
    assert history.opportunity_confirmation_applies.tolist() == [
        True, True, False, False, False, True, True, True, True]
    assert history.confirmation_exit_context.tolist() == [
        'initial', 'initial', 'initial', 'regime', 'regime', 'initial',
        'initial', 'time', 'time']
    assert not bool(history.confirmation_pass.iloc[3])  # Original amount gate independently rejects.
    assert bool(history.confirmation_pass.iloc[4])  # Extra weak score exempt on regime reentry.
    assert not bool(history.confirmation_pass.iloc[5]) and history.signal_reason.iloc[5] == 'hold'
    assert history.opportunity_confirmation_score.iloc[1] == -.2
    assert history.opportunity_confirmation_score.iloc[8] == -.2

    all_entries = deepcopy(parameters)
    all_entries['opportunity_confirmation']['application'] = 'all_entries'
    all_history = run_panel(module, all_entries, closes, amounts, volumes)
    assert all_history.signal_reason.iloc[3] == 'confirmation_rejected'
    assert all_history.signal_reason.iloc[4] == 'confirmation_rejected'
    assert bool(all_history.opportunity_confirmation_applies.iloc[4])

    route_results = {}
    for scope in ('bull', 'bear', 'both'):
        route_case = deepcopy(parameters)
        route_case['opportunity_confirmation']['route_scope'] = scope
        route_history = run_panel(module, route_case, [100.], [.1], [-.3])
        route_results[scope] = route_history.signal_reason.iloc[0]
        assert route_results[scope] == ('entry' if scope == 'bull' else 'confirmation_rejected')

    block_case = deepcopy(parameters)
    block_case['opportunity_confirmation'].update(profile='all', weighting='EQUAL_BLOCKS')
    block_history = run_panel(module, block_case, [101.], [-.1], [.4], [.2])
    expected_block = .5 * .2 + .25 * -.1 + .25 * .4
    assert np.isclose(block_history.opportunity_confirmation_score.iloc[0], expected_block,
                      rtol=0., atol=1e-15)
    features_case = deepcopy(block_case)
    features_case['opportunity_confirmation'].update(profile='acf_volume', weighting='EQUAL_FEATURES')
    features_history = run_panel(module, features_case, [101.], [-.1], [.4], [.2])
    assert np.isclose(features_history.opportunity_confirmation_score.iloc[0], .3,
                      rtol=0., atol=1e-15)

    before = ast.parse((SOURCE / 'strategies/reentry_confirmed_range.py').read_text(encoding='utf-8'))
    after = ast.parse((SOURCE / 'strategies/complement_confirmed_range.py').read_text(encoding='utf-8'))
    assert holding_branch(before) == holding_branch(after)
    result = {'status': 'PASS', 'scope': 'deterministic signal-state branch contract; mocked panels',
              'state_semantics': 'last_exit_reason records internal signal exits, not actual fills; '
                                 'regime context persists through rejected flat opportunities until signal entry',
              'checks': ['ordinary weak-score rejection', 'threshold equality accepted',
                         'regime reentry extra-gate exemption', 'original gate independently rejects',
                         'all-entry gates combine with AND', 'weak buy score does not exit held signal position',
                         'non-regime exit restores ordinary-entry gate', 'bull/bear/both route scopes',
                         'equal blocks and equal selected-feature values', 'holding-exit AST exact equality'],
              'expected_signal_reasons': expected,
              'observed_signal_reasons': history.signal_reason.tolist(),
              'bear_opportunity_by_route_scope': route_results,
              'block_score': float(block_history.opportunity_confirmation_score.iloc[0]),
              'equal_acf_volume_score': float(features_history.opportunity_confirmation_score.iloc[0]),
              'causality_limit': 'Mocked branches do not prove rolling-feature causality; actual-feature '
                                 'prefix and future-invariance checks are in precheck.py.'}
    write(RUNS / 'complement_synthetic_check.json', result)
    print({'status': result['status'], 'checks': len(result['checks'])}, flush=True)


if __name__ == '__main__':
    main()
