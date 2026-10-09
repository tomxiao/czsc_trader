"""Causality, buy-only gate boundaries and all ten exact parent controls."""
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
    package = types.ModuleType('_s013_confirmation_test')
    package.__path__ = [str(SOURCE / 'strategies')]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location(package.__name__ + '.confirmed_range',
                                                 SOURCE / 'strategies/confirmed_range.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    strategy = module.ConfirmedRange
    p = read(PROTOCOLS / 'initial_plan.json')['configurations'][0]['parameters']
    dates = pd.bdate_range('2019-01-01', periods=520)
    t = np.arange(len(dates))
    close = 100 * np.exp(.0002 * t + .04 * np.sin(t / 11) + .005 * np.sin(t / 2.7))
    volume = 10000 * np.exp(.1 * np.sin(t / 7) + .03 * np.cos(t / 3))
    bars = pd.DataFrame({'Date': dates, 'Open': close * .998, 'High': close * 1.1,
                         'Low': close * .9, 'Close': close, 'Volume': volume, 'Amount': close * volume})
    sessions = dates[200:]
    base = {k: v for k, v in p.items() if k != 'confirmation'}
    original = module.AdaptiveRange(ParameterSet(base)).calculate_history({'daily': bars}, sessions)
    disabled = strategy(ParameterSet(p)).calculate_history({'daily': bars}, sessions)
    pd.testing.assert_frame_equal(original, disabled, check_exact=True)
    case = deepcopy(p)
    case['confirmation']['enabled'] = True
    enabled = strategy(ParameterSet(case)).calculate_history({'daily': bars}, sessions)
    pd.testing.assert_frame_equal(original, enabled.loc[:, original.columns], check_exact=True)
    cutoff = dates[360]
    changed = bars.copy()
    changed.loc[changed.Date > cutoff, ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']] *= 1.8
    for profile in module.PROFILES:
        for orientation in (-1, 1):
            case['confirmation'].update(profile=profile, threshold=.0, orientation=orientation)
            model = strategy(ParameterSet(case))
            history = model.calculate_history({'daily': bars}, sessions)
            future = model.calculate_history({'daily': changed}, sessions)
            prefix = model.calculate_history({'daily': bars.loc[bars.Date <= cutoff]}, sessions[sessions <= cutoff])
            pd.testing.assert_frame_equal(history.loc[:cutoff], future.loc[:cutoff], check_exact=True)
            pd.testing.assert_frame_equal(history.loc[:cutoff], prefix, check_exact=True)
            assert history.confirmation_score.between(-.5, .5).all()
    assert module.causal_rank(pd.Series([1., 2., 2., 4.]), 4).iloc[-1] == .375
    assert module.causal_rank(pd.Series([1., 2., 4., 2.]), 4).iloc[-1] == 0.
    for key, value in (('enabled', 1), ('threshold', float('nan')), ('threshold', 1.),
                       ('orientation', True), ('orientation', 0), ('lookback', 39), ('profile', 'unknown')):
        invalid = deepcopy(p)
        invalid['confirmation'][key] = value
        try:
            strategy(ParameterSet(invalid))
        except (TypeError, ValueError):
            pass
        else:
            raise AssertionError((key, value))
    invalid = deepcopy(p)
    invalid['bull']['cooldown'] = 1
    try:
        strategy(ParameterSet(invalid))
    except ValueError:
        pass
    else:
        raise AssertionError('fixed cooldown accepted')
    actual_function = module.confirmation_features
    case = deepcopy(p)
    case['confirmation'].update(enabled=True, threshold=.1, profile='all')
    case['exit_on_regime_change'] = False
    for route in ('bull', 'bear'):
        case[route].update(entry=.99, exit=1., acf_min=None, momentum_min=None, max_hold=5)
    panel = pd.DataFrame(.1, index=dates, columns=['acf', 'turnover', 'volume'])
    panel.loc[sessions[0]] = -.1
    panel.loc[sessions[2:6]] = -.1
    module.confirmation_features = lambda *args: (panel, panel)
    boundary = strategy(ParameterSet(case)).calculate_history({'daily': bars}, sessions)
    assert list(boundary.target_position.iloc[:3]) == [0., 1., 1.]
    assert boundary.signal_reason.iloc[0] == 'confirmation_rejected'
    assert boundary.signal_reason.iloc[1] == 'entry'  # equality passes, no extra waiting
    assert boundary.signal_reason.iloc[2] == 'hold'  # weak score cannot force an exit
    assert boundary.signal_reason.iloc[6] == 'time'
    module.confirmation_features = actual_function
    write(RUNS / 'synthetic_check.json', {'status': 'PASS', 'checks': [
        'disabled exact history', 'unrestricted gate exact old columns', '14 profile-direction prefix/future invariances',
        'midrank and ties', 'parameter boundaries', 'fixed cooldown rejected',
        'threshold equality enters', 'rejected day immediately reconsidered', 'weak confirmation cannot exit']})


def main():
    synthetic()
    configs = read(PROTOCOLS / 'initial_plan.json')['configurations'][:10]
    research = context(4)
    proofs, shared = [], None
    for offset in range(0, 10, 4):
        selected = configs[offset:offset + 4]
        bounds = [research.evaluation.prepare(request(f'C{2000 + offset + i:04}', row['parameters'], shared))
                  for i, row in enumerate(selected)]
        shared = bounds[0].execution_data
        outcomes = research.evaluation.evaluate_many(tuple(bounds))
        for row, bound, outcome in zip(selected, bounds, outcomes, strict=True):
            assert outcome.status.value == 'SUCCEEDED', outcome
            record = read(ROOT / f'research/registrations/S013/candidates/{row["parent"]}.json')['record']
            old = read(ROOT / 'research/S013' / record['origin']['evidence'][0]['path'])
            proof = compare_evidence(old, serialize_evaluation_evidence(bound, outcome.result))
            cache_write(CACHE / f'{bound.strategy.candidate_id}.pkl.gz', (bound, outcome.result))
            proofs.append({'parent': row['parent'], 'control': bound.strategy.candidate_id,
                           'comparison': proof, 'metrics': summarize(outcome.result)})
        print({'exact_parent_controls': len(proofs)}, flush=True)
    first, baseline = bounds[0], outcomes[0].result
    repeated = research.evaluation.evaluate(first)
    compare_evidence(serialize_evaluation_evidence(first, baseline), serialize_evaluation_evidence(first, repeated))
    write(RUNS / 'precheck.json', {'status': 'PASS', 'controls': proofs, 'single_spawn_consistency': 'EXACT_EQUAL',
                                 'external_provider_access': False})
    print({'status': 'PASS', 'ten_parent_accounts': 'EXACT_EQUAL', 'single_spawn': 'EXACT_EQUAL'}, flush=True)


if __name__ == '__main__':
    main()
