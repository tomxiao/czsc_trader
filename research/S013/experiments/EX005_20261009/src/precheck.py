"""Synthetic causal checks and exact public-TDR control replay."""
from copy import deepcopy
import importlib.util
import sys
import types

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from common import SOURCE, ROOT, RUNS, CACHE, PROTOCOLS, context, read, write, request, cache_write
from economic_equivalence import compare_evidence
from economics_r4 import summarize


def synthetic():
    package = types.ModuleType('_s013_stable_test')
    package.__path__ = [str(SOURCE / 'strategies')]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location(
        package.__name__ + '.stable_range', SOURCE / 'strategies/stable_range.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    stable, original = module.StableRange, module.AdaptiveRange
    p = read(PROTOCOLS / 'initial_plan.json')['configurations'][0]['parameters']
    dates = pd.bdate_range('2019-01-01', periods=520)
    t = np.arange(len(dates))
    close = 100 * np.exp(.0002 * t + .04 * np.sin(t / 11) + .005 * np.sin(t / 2.7))
    bars = pd.DataFrame({'Date': dates, 'Open': close * .998, 'High': close * 1.1,
                         'Low': close * .9, 'Close': close, 'Volume': 10000.,
                         'Amount': close * 10000})
    sessions = dates[200:]
    base = {k: v for k, v in p.items() if k in ('bull', 'bear', 'regime_window',
                                              'regime_threshold', 'exit_on_regime_change')}
    lhs = original(ParameterSet(base)).calculate_history({'daily': bars}, sessions)
    rhs = stable(ParameterSet(p)).calculate_history({'daily': bars}, sessions)
    pd.testing.assert_frame_equal(lhs, rhs, check_exact=True)
    assert list(stable.states([.0, -.001, .001, -.001, -.02, -.015, .002, .02, .03],
                              0., .01, 2)) == ['bull'] * 5 + ['bear'] * 3 + ['bull']
    cutoff = dates[360]
    changed = bars.copy()
    changed.loc[changed.Date > cutoff, ['Open', 'High', 'Low', 'Close']] *= 1.8
    for band, confirmation, exit_count, direction, cooldown in (
            (.002, 2, 3, 'both', 2), (.01, 3, 1, 'bull_to_bear', 1),
            (0., 1, 2, 'bear_to_bull', 0)):
        case = deepcopy(p)
        case.update(regime_band=band, regime_confirmation=confirmation,
                    exit_confirmation=exit_count, exit_direction=direction, regime_cooldown=cooldown)
        strategy = stable(ParameterSet(case))
        before = strategy.calculate_history({'daily': bars}, sessions)
        after = strategy.calculate_history({'daily': changed}, sessions)
        pd.testing.assert_frame_equal(before.loc[:cutoff], after.loc[:cutoff], check_exact=True)
        assert set(before.target_position) <= {0., 1.}
    for key, value in (('regime_band', float('nan')), ('regime_band', -.001),
                       ('regime_band', 0), ('regime_confirmation', True),
                       ('regime_confirmation', 0), ('exit_confirmation', 11),
                       ('exit_direction', 'unknown'), ('regime_cooldown', -1)):
        case = deepcopy(p)
        case[key] = value
        try:
            stable(ParameterSet(case))
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError((key, value))
    write(RUNS / 'synthetic_check.json', {'status': 'PASS', 'checks': [
        'disabled-mechanism exact signals', 'state boundary and consecutive reset',
        'future OHLC invariance', 'position bounds', 'illegal parameter rejection']})


def main():
    synthetic()
    research = context(4)
    configs = read(PROTOCOLS / 'initial_plan.json')['configurations']
    control = research.evaluation.prepare(request('C1000', configs[0]['parameters']))
    result = research.evaluation.evaluate(control)
    record = read(ROOT / 'research/registrations/S013/candidates/C9023.json')['record']
    old = read(ROOT / 'research/S013' / record['origin']['evidence'][0]['path'])
    proof = compare_evidence(old, serialize_evaluation_evidence(control, result))
    cache_write(CACHE / 'C1000.pkl.gz', (control, result))
    second = research.evaluation.prepare(request('C1001', configs[1]['parameters'], control.execution_data))
    outcomes = research.evaluation.evaluate_many((control, second))
    assert all(o.status.value == 'SUCCEEDED' for o in outcomes), outcomes
    compare_evidence(serialize_evaluation_evidence(control, result),
                     serialize_evaluation_evidence(control, outcomes[0].result))
    for bound, outcome in zip((control, second), outcomes, strict=True):
        cache_write(CACHE / f'{bound.strategy.candidate_id}.pkl.gz', (bound, outcome.result))
    write(RUNS / 'precheck.json', {
        'status': 'PASS', 'parent': 'C9023', 'control': 'C1000', 'exact_control': proof,
        'spawn_consistency': 'EXACT_EQUAL', 'public_batch_items': 2,
        'control_metrics': summarize(result), 'external_provider_access': False})
    print({'status': 'PASS', 'exact_control': True, 'spawn_items': 2}, flush=True)


if __name__ == '__main__':
    main()
