"""Huber driver definition/mock wiring only; no native phases or providers."""
from hashlib import sha256
import importlib.util
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet, implementation_sha256

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run():
    driver = load('huber_native_metadata_driver', WORK / 'native_driver.py')
    plan = driver.definition()
    assert plan['candidate_id'] == driver.CANDIDATE == 'C9097'
    p = plan['payload']['parameters']
    assert p == {'confirmation_lookback': 120, 'holding_sessions': 4, 'ridge_alpha': 10.0, 'huber_multiple': 1.345}
    assert plan['payload']['runtime']['module'] == 'strategy_runtime.strategies.huber_net'
    assert plan['payload']['runtime']['qualname'] == 'HuberNet'
    assert plan['payload']['runtime']['source_sha256'] == implementation_sha256(driver.RUNTIME_FILES, source_root=driver.PACKAGE)
    assert plan['parameter_geometry']['coordinates'] == [
        ('confirmation_lookback', 40, 120, 'INTEGER'), ('holding_sessions', 1, 60, 'INTEGER'),
        ('ridge_alpha', 1., 100., 'CONTINUOUS'), ('huber_multiple', .5, 3., 'CONTINUOUS')]
    protocol = plan['parameter_geometry']['protocol']
    assert protocol['radius'] == .05 and protocol['point_count'] == 32 and protocol['seed'] == 13
    assert protocol['integer_rounding'] == 'HALF_EVEN' and protocol['quantile_method'] == 'LINEAR'
    assert 'sameEX32' in plan['stop_or_followup'] and plan['objective_achieved'] is False
    assert set(plan['original14_and_label_oracle']['function_sha256']) == {'original14', 'net_labels', 'episodes'}
    checks = ['definition four full effective domains/source hash and fixed32 geometry',
              'centre stop/pass followup explicit; old oracle funcs and no OFF=C8880 claim']
    adapter = driver.local_runtime(driver.PACKAGE)
    instance = adapter.HuberNet(ParameterSet(p))
    assert instance.definition.tradable_symbol == '510500.SH'
    assert tuple(inspect.signature(adapter.prepare_history).parameters) == ('p', 'inputs', 'sessions')
    auditor = load('huber_metadata_auditor', WORK / 'audit_huber.py')
    assert tuple(inspect.signature(auditor.verify).parameters) == ('features', 'labels', 'scores', 'fit_trace', 'ridge_alpha', 'huber_multiple')
    original_factory = driver.StrategyCandidate

    def factory(strategy_id, candidate_id, payload, source_root):
        return SimpleNamespace(strategy_id=strategy_id, candidate_id=candidate_id, payload=payload, source_root=source_root)

    driver.StrategyCandidate = factory
    try:
        exp = SimpleNamespace(resolve=lambda root: root / 'research/S013/experiments/EX097_20261012')
        candidate = driver.candidate(exp, plan)
        assert candidate.source_root == ROOT / 'research/S013/experiments/EX097_20261012/src/huber_net/strategy_runtime'
        assert candidate.source_root.name == 'strategy_runtime' and candidate.payload == plan['payload']
    finally:
        driver.StrategyCandidate = original_factory
    checks.append('adapter/auditor signatures and mocked exact strategy_runtime source basename')
    axis = pd.bdate_range('2021-01-01', periods=50).as_unit('ns')
    features = pd.DataFrame(.1, index=axis, columns=adapter.rebuild.__globals__['FEATURES'])
    scores = pd.DataFrame({'training_mean': .003,
                           'huber_net': np.where(np.arange(50) % 7 == 0, .01, -.001)}, index=axis)
    trace = [{'year': 2021, 'train_n': 55, 'max_maturity': '2020-12-30T00:00:00',
              'available': True, 'reason': None,
              'fit': {'training_mad': .01, 'delta': .01345, 'iterations': 20,
                      'max_abs_gradient': 1e-11, 'max_coefficient_change': 1e-13}}]
    inputs = {'daily': pd.DataFrame({'Date': axis, 'Close': np.full(len(axis), 100.)})}
    policy = driver.independent_policy(scores, features, trace, inputs, 4)
    oracle = load('huber_metadata_original_clock', driver.ORACLE)
    driver.compare_history(policy, oracle.episodes(scores.huber_net, 4))
    assert policy.huber_available.all() and policy.huber_delta.eq(.01345).all()
    assert policy.huber_reason.isna().all()
    for horizon in (1, 4, 60):
        driver.compare_history(driver.independent_policy(scores, features, trace, inputs, horizon),
                               oracle.episodes(scores.huber_net, horizon))
    prices = pd.DataFrame({'Open': np.arange(50) + 100., 'Close': np.arange(50) + 100.}, index=axis)
    for horizon in (1, 4, 60):
        actual = driver.independent_labels(prices, axis, horizon, oracle)
        expected = adapter.net_labels(prices, axis, horizon)
        np.testing.assert_allclose(actual.return_4, expected.return_4, atol=2e-13, rtol=2e-11, equal_nan=True)
        pd.testing.assert_series_equal(actual.label_end_return_4, expected.label_end_return_4, check_exact=True)
    checks.append('full known-time metadata and independent original clock/labels exercised on synthetic arrays')
    inspected = (WORK / 'native_driver.py').read_text('utf-8')
    assert "g.stage(97)" in inspected and "g.allocate(97," in inspected
    assert "result097" in inspected and "quota_slot': 9" in inspected
    assert 'existing_execution30m_promoted' in inspected and 'no_OFF_parent_equivalence' in inspected
    assert 'all_year_huber_and_positive_flags' in inspected
    assert 'CENTRE_PASS_FROZEN_SAME_EX_32_FEE_REQUIRED' in inspected
    assert not driver.g.base.common().SOURCE_CALLS
    files = ['native_driver.py', 'native_contract_checks.json', 'checks.json', 'audit_checks.json', 'audit_huber.py']
    hashes = {name: sha256((WORK / name).read_bytes()).hexdigest() for name in files}
    hashes.update({name: sha256((driver.PACKAGE / name).read_bytes()).hexdigest() for name in driver.RUNTIME_FILES})
    result = {'status': 'PASS', 'synthetic_only': True, 'metadata_and_mock_only': True,
              'real_inputs_read': 0, 'accounts': 0, 'experiments_allocated': 0, 'provider_calls': 0,
              'checks': checks, 'check_count': len(checks), 'source_sha256': hashes,
              'phase_functions_not_invoked': ['declare', 'prepare', 'execute', 'audit'],
              'candidate_registered': False, 'effective_numeric_dimensions': 4,
              'Huber_score_not_conditional_expectation': True}
    (WORK / 'native_driver_checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({'status': 'PASS', 'checks': len(checks), 'real_inputs': 0, 'accounts': 0, 'experiments_allocated': 0})


if __name__ == '__main__':
    run()
