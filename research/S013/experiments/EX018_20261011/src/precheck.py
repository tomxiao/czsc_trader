"""Synthetic virtual-vote checks and exact public serial/spawn account preflight."""
# ruff: noqa: E402
import os

for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

from copy import deepcopy
from itertools import product
import importlib.util
import sys
import types

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from common import (
    SRC, PROTOCOLS, RUNS, CACHE, SOURCE_CALLS, read, write, request, context, cache_write, file_hash,
)


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


def declared_members(parameters):
    """Independent reference construction, without calling the implementation factory."""
    base = deepcopy(parameters)
    mode = base.pop('mechanism')
    offsets = (0.,) if mode == 'VOTE9' else (-.012, 0., .012)
    triples = list(product((-.033, 0., .033), (-1, 0, 1), offsets))
    triples.remove((0., 0, 0.))
    triples.insert(0, (0., 0, 0.))
    result = []
    for acf, age, regime in triples:
        member = deepcopy(base)
        member['bear']['acf_min'] = base['bear']['acf_min'] + acf
        member['bear']['max_hold'] = min(60, max(1, base['bear']['max_hold'] + age))
        member['regime_threshold'] = min(.2, max(-.2, base['regime_threshold'] + regime))
        result.append(member)
    return result


def check_factory(implementation, parameters):
    expected = declared_members(parameters)
    actual = implementation.members()
    assert len(actual) == len(expected) == (9 if parameters['mechanism'] == 'VOTE9' else 27)
    for member, values in zip(actual, expected, strict=True):
        assert member._parameters.values == values
    return expected


def check_majority(frame, targets):
    assert np.isin(targets, (0., 1.)).all()
    count = targets.shape[1]
    quorum = 5 if count == 9 else 14
    votes = targets.sum(axis=1).astype(int)
    positions, reasons, prior = [], [], False
    for vote in votes:
        held = bool(vote >= quorum)
        reasons.append('entry' if held and not prior else 'hold' if held else 'vote' if prior else 'flat')
        positions.append(float(held))
        prior = held
    assert np.array_equal(frame.target_position.to_numpy(), positions)
    assert np.array_equal(frame.signal_reason.to_numpy(), reasons)
    assert np.array_equal(frame.ensemble_votes.to_numpy(), votes)
    assert frame.ensemble_members.eq(count).all() and frame.ensemble_quorum.eq(quorum).all()
    assert frame.regime.eq('ensemble').all(), 'Actual regime must not masquerade as a center route'
    assert np.isin(frame.target_position.to_numpy(), (0., 1.)).all()


class StubMember:
    def __init__(self, history):
        self.history = history

    def calculate_history(self, inputs, sessions):
        return self.history.reindex(sessions).copy()


def check_quorum(implementation, inputs, template):
    count = len(implementation.members())
    quorum = count // 2 + 1
    sessions = template.index[:5]
    votes = np.array((quorum - 1, quorum, count, quorum - 1, 0))
    matrix = (np.arange(count)[None, :] < votes[:, None]).astype(float)
    histories = []
    for index in range(count):
        history = template.loc[sessions].copy()
        history['target_position'] = matrix[:, index]
        histories.append(history)
    implementation.members = lambda: [StubMember(history) for history in histories]
    try:
        result = implementation.calculate_history(inputs, sessions)
        check_majority(result, matrix)
        assert result.signal_reason.tolist() == ['flat', 'entry', 'hold', 'vote', 'flat']
        assert result.ensemble_votes.tolist() == votes.tolist()
        histories[0].loc[sessions[0], 'target_position'] = .5
        try:
            implementation.calculate_history(inputs, sessions)
        except ValueError:
            pass
        else:
            raise AssertionError('Non-binary virtual target accepted')
    finally:
        del implementation.members


def synthetic(plan):
    new = module(SRC / 'strategy_runtime', '_ex018_mechanism', 'mechanism_range')
    rng = np.random.default_rng(13)
    dates = pd.bdate_range('2018-01-01', periods=480)
    close = 6 * np.exp(np.cumsum(rng.normal(.0004, .02, len(dates))))
    bars = pd.DataFrame({'Date': dates, 'Open': close, 'High': close * 1.01,
        'Low': close * .99, 'Close': close, 'Volume': np.exp(rng.normal(15, .2, len(dates))),
        'Amount': np.exp(rng.normal(18, .2, len(dates)))})
    sessions = dates[240:]
    inputs = {'daily': bars}
    configurations = plan['configurations']
    assert len(configurations) == 2
    assert {cfg['payload']['parameters']['mechanism'] for cfg in configurations} == {'VOTE9', 'VOTE27'}
    independent_histories = {}
    member_count = 0
    for config in configurations:
        parameters = deepcopy(config['payload']['parameters'])
        implementation = new.MechanismRange(ParameterSet(parameters))
        expected = check_factory(implementation, parameters)
        full = implementation.calculate_history(inputs, sessions)
        cutoff = sessions[80]
        prefix = implementation.calculate_history({'daily': bars[bars.Date <= cutoff]}, sessions[:81])
        pd.testing.assert_frame_equal(full.loc[:cutoff], prefix, check_exact=True)
        changed = bars.copy()
        changed.loc[changed.Date > cutoff, ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']] *= 1.2
        mutated = implementation.calculate_history({'daily': changed}, sessions)
        pd.testing.assert_frame_equal(full.loc[:cutoff], mutated.loc[:cutoff], check_exact=True)
        histories = [new.ReentryConfirmedRange(ParameterSet(values)).calculate_history(inputs, sessions)
                     for values in expected]
        targets = np.column_stack([history.target_position.to_numpy() for history in histories])
        for index, history in enumerate(histories):
            assert np.array_equal(full[f'member_{index}_target'].to_numpy(), history.target_position.to_numpy())
            assert np.array_equal(full[f'member_{index}_reason'].to_numpy(), history.signal_reason.to_numpy())
            assert np.array_equal(full[f'member_{index}_regime'].to_numpy(), history.regime.to_numpy())
        check_majority(full, targets)
        assert np.array_equal(full.center_target.to_numpy(), histories[0].target_position.to_numpy())
        assert np.array_equal(full.center_signal_reason.to_numpy(), histories[0].signal_reason.to_numpy())
        assert np.array_equal(full.center_regime.to_numpy(), histories[0].regime.to_numpy())
        independent_histories[parameters['mechanism']] = (expected, histories)
        member_count += len(histories)
        check_quorum(implementation, inputs, histories[0])
        implementation.members = lambda frames=histories: [StubMember(frames[0])] * len(frames)
        try:
            same = implementation.calculate_history(inputs, sessions)
            assert np.array_equal(same.target_position.to_numpy(), histories[0].target_position.to_numpy())
        finally:
            del implementation.members
    nine_values, nine_histories = independent_histories['VOTE9']
    all_values, all_histories = independent_histories['VOTE27']
    for values, history in zip(nine_values, nine_histories, strict=True):
        counterpart = next(frame for member, frame in zip(all_values, all_histories, strict=True)
                           if member == values)
        pd.testing.assert_frame_equal(history, counterpart, check_exact=True)
    base = deepcopy(configurations[0]['payload']['parameters'])
    boundary_cases = 0
    for mode, age, regime in product(('VOTE9', 'VOTE27'), (1, 60), (-.2, .2)):
        parameters = deepcopy(base)
        parameters['mechanism'] = mode
        parameters['bear']['max_hold'] = age
        parameters['regime_threshold'] = regime
        expected = check_factory(new.MechanismRange(ParameterSet(parameters)), parameters)
        tuples = [(member['bear']['acf_min'], member['bear']['max_hold'], member['regime_threshold'])
                  for member in expected]
        assert all(1 <= member[1] <= 60 and -.2 <= member[2] <= .2 for member in tuples)
        assert len(set(tuples)) < len(tuples), 'Boundary duplicates must retain their original vote slots'
        assert sum(member[1] == age for member in tuples) == 2 * len(tuples) // 3
        if mode == 'VOTE27':
            assert sum(member[2] == regime for member in tuples) == 2 * len(tuples) // 3
        boundary_cases += 1
    for mode, acf in product(('VOTE9', 'VOTE27'), (-.6, .5)):
        parameters = deepcopy(base)
        parameters['mechanism'] = mode
        parameters['bear']['acf_min'] = acf
        expected = check_factory(new.MechanismRange(ParameterSet(parameters)), parameters)
        values = [member['bear']['acf_min'] for member in expected]
        assert min(values) == acf - .033 and max(values) == acf + .033
    invalid = []
    for name in ('mechanism', 'disabled_confirmation', 'null_acf', 'nonfinite_acf'):
        parameters = deepcopy(base)
        if name == 'mechanism':
            parameters['mechanism'] = 'INVALID'
        elif name == 'disabled_confirmation':
            parameters['confirmation']['enabled'] = False
        else:
            parameters['bear']['acf_min'] = None if name == 'null_acf' else float('nan')
        try:
            new.MechanismRange(ParameterSet(parameters))
        except ValueError:
            invalid.append(name)
        else:
            raise AssertionError('Invalid configuration accepted: ' + name)
    return {'status': 'PASS', 'causal_configurations': 2, 'independently_reproduced_members': member_count,
        'member_majority_and_reasons': 'EXACT_EQUAL', 'nested_nine_member_histories': 'EXACT_EQUAL',
        'quorum_cases': {'VOTE9': [4, 5, 9, 4, 0], 'VOTE27': [13, 14, 27, 13, 0]},
        'target_transitions': ['flat', 'entry', 'hold', 'vote', 'flat'], 'boundary_cases': boundary_cases,
        'boundary_duplicates': 'RETAINED original vote multiplicity', 'acf_boundary_cases': 4,
        'invalid_configurations_rejected': invalid, 'nonbinary_member_rejected': True,
        'equal_members_reproduce_original_target': 'EXACT_EQUAL', 'actual_route_label': 'ensemble',
        'scope': 'Synthetic signals only; no funded virtual accounts or account evaluation.'}


def main():
    assert not (RUNS / 'precheck.json').exists()
    plan = read(PROTOCOLS / 'plan.json')
    for path, digest in plan['source_files'].items():
        assert file_hash(SRC / path) == digest
    write(RUNS / 'synthetic_check.json', synthetic(plan))
    config = plan['configurations'][0]
    assert config['label'] == 'N0'
    bound = context(1).evaluation.prepare(request(config))
    print({'prepared': config['label']}, flush=True)
    serial = context(1).evaluation.evaluate(bound)
    cache_write(CACHE / 'preflight-serial.pkl.gz', (bound, serial))
    print({'serial': 'SUCCEEDED'}, flush=True)
    outcome = context(2).evaluation.evaluate_many((bound,))[0]
    assert outcome.status.value == 'SUCCEEDED', outcome.error
    parallel = outcome.result
    cache_write(CACHE / 'preflight-spawn.pkl.gz', (bound, parallel))
    a, b = serial.runs[0], parallel.runs[0]
    pd.testing.assert_frame_equal(a.signals.decisions, b.signals.decisions, check_exact=True)
    for kind in ('execution', 'buyhold'):
        left, right = getattr(a, kind), getattr(b, kind)
        if kind == 'buyhold':
            left, right = left.execution, right.execution
        for field in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
            pd.testing.assert_frame_equal(getattr(left, field), getattr(right, field), check_exact=True)
    assert serial.result_hash == parallel.result_hash and not SOURCE_CALLS
    cache_write(CACHE / 'N0.pkl.gz', (bound, serial))
    write(RUNS / 'precheck.json', {'status': 'PASS',
        'serial_spawn': 'EXACT_EQUAL signals and 5 ledgers on both accounts',
        'result_hash': serial.result_hash, 'configuration': 'N0',
        'account_evaluations': 2, 'provider_calls': SOURCE_CALLS})
    print({'precheck': 'PASS'}, flush=True)


if __name__ == '__main__':
    main()
