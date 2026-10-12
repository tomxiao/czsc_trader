"""Definition/metadata and mock wiring checks; no experiment, provider or account."""
from copy import deepcopy
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
    driver = load('profit_latch_metadata_driver', WORK / 'native_driver.py')
    plan = driver.definition()
    assert plan['candidate_id'] == driver.CANDIDATE == 'C9094'
    p = plan['payload']['parameters']
    assert p['mechanism'] == driver.MECHANISM
    assert p['profit_latch'] == {'enabled': True, 'volatility_window': 20, 'activation_multiple': 1.0}
    assert plan['payload']['runtime']['module'] == 'strategy_runtime.strategies.profit_latch_range'
    assert plan['payload']['runtime']['qualname'] == 'ProfitLatchRange'
    assert plan['payload']['runtime']['source_sha256'] == implementation_sha256(driver.RUNTIME_FILES, source_root=driver.PACKAGE)
    geometry = plan['parameter_geometry']
    original = json.loads((ROOT / 'research/S013/experiments/EX058_20261011/protocols/geometry.json').read_text('utf-8'))
    assert geometry['coordinates'][:13] == original['coordinates'] and len(geometry['coordinates']) == 15
    assert geometry['new_numeric_coordinates'] == [
        ['profit_latch.volatility_window', 10., 60., 'INTEGER'],
        ['profit_latch.activation_multiple', .5, 3., 'CONTINUOUS']]
    assert geometry['protocol']['radius'] == .05 and geometry['protocol']['point_count'] == 32 and geometry['protocol']['seed'] == 13
    assert geometry['protocol']['integer_rounding'] == 'HALF_EVEN' and geometry['protocol']['quantile_method'] == 'LINEAR'
    assert not any('floor' in row[0] for row in geometry['coordinates'])
    assert plan['resources'] == {'maximum_native_centres': 1, 'new_accounts': 1, 'provider_calls': 0, 'automatic_repeat': False}
    assert 'sameEX32' in plan['stop_or_followup'] and plan['objective_achieved'] is False
    checks = ['metadata C9094/new mechanism/strict nested settings/full source package',
              'old13 domain exact plus full2 new coordinates; radius32/rounding/quantiles',
              'no floor coordinate; centre pass requires sameEX32/independentfee']
    adapter, parent, core = driver.local_runtime(driver.PACKAGE)
    instance = adapter.ProfitLatchRange(ParameterSet(p))
    original_p = {key: deepcopy(value) for key, value in p.items() if key != 'profit_latch'}
    original_p['mechanism'] = adapter.PARENT_MECHANISM
    old = parent.BoundaryBearRecoveryRange(ParameterSet(original_p))
    assert instance.definition.decision == old.definition.decision
    assert instance.definition.execution == old.definition.execution
    assert instance.definition.inputs == old.definition.inputs
    assert instance.definition.tradable_symbol == '510500.SH'
    assert instance._warmup >= 21
    assert len(core.BASE_KEYS) == 12 and core.BASE_KEYS[-1] == 'sigma_knowncurrent'
    assert len(core.DIAGNOSTICS) == 10
    checks.append('private namespace and original public SRT decision/execution/input contracts')
    auditor = load('profit_latch_metadata_independent', WORK / 'audit_core.py')
    assert tuple(inspect.signature(auditor.verify).parameters) == ('sessions', 'parameters', 'baseinputs', 'primarytable')
    assert tuple(inspect.signature(auditor.verify_sigma).parameters) == ('close_full', 'sessions', 'length', 'reported_sigma')
    synthetic = load('profit_latch_metadata_pure_fixture', WORK / 'checks.py')
    axis = pd.bdate_range('2021-12-01', periods=30).as_unit('ns')
    base = synthetic.make_base(axis, [100., 102., 100.])
    table = core.decisions(p, axis, base)
    signal_proof = auditor.verify(axis, p, base, table)
    assert signal_proof['status'] == 'PASS'
    full_axis = pd.bdate_range('2021-01-01', periods=100).as_unit('ns')
    close = pd.Series(100 * np.exp(.01 * np.arange(len(full_axis))), index=full_axis)
    sigma_module = load('profit_latch_metadata_sigma', driver.PACKAGE / 'strategies/locked_sigma.py')
    sigma = sigma_module.sigma_known(close, full_axis[-30:], 20)
    sigma_proof = auditor.verify_sigma(close, full_axis[-30:], 20, sigma)
    assert sigma_proof['status'] == 'PASS'
    checks.append('new sigma/policy audit signatures exercised on pure synthetic inputs')
    original_factory = driver.StrategyCandidate

    def factory(strategy_id, candidate_id, payload, source_root):
        return SimpleNamespace(strategy_id=strategy_id, candidate_id=candidate_id, payload=payload, source_root=source_root)

    driver.StrategyCandidate = factory
    try:
        exp = SimpleNamespace(resolve=lambda root: root / 'research/S013/experiments/EX094_20261012')
        candidate = driver.candidate(exp, plan)
        assert candidate.candidate_id == 'C9094' and candidate.strategy_id == 'S013'
        assert candidate.source_root == ROOT / 'research/S013/experiments/EX094_20261012/src/profit_latch/strategy_runtime'
        assert candidate.source_root.name == 'strategy_runtime' and candidate.payload == plan['payload']
    finally:
        driver.StrategyCandidate = original_factory
    checks.append('mock candidate path keeps exact strategy_runtime package basename')
    assert not driver.g.base.common().SOURCE_CALLS
    files = ['native_driver.py', 'checks.json', 'audit_checks.json', 'audit_core.py']
    source_hashes = {name: sha256((WORK / name).read_bytes()).hexdigest() for name in files}
    source_hashes.update({name: sha256((driver.PACKAGE / name).read_bytes()).hexdigest() for name in driver.RUNTIME_FILES})
    result = {'status': 'PASS', 'synthetic_only': True, 'metadata_only': True,
              'real_inputs_read': 0, 'accounts': 0, 'experiments_allocated': 0,
              'provider_calls': 0, 'candidate_registered': False,
              'phase_functions_not_invoked': ['declare', 'prepare', 'execute', 'audit'],
              'checks': checks, 'check_count': len(checks), 'source_sha256': source_hashes,
              'candidate_id': 'C9094', 'planned_experiment': 'EX094_20261012',
              'effective_numeric_dimensions': 15, 'signal_audit': signal_proof,
              'known_sigma_audit': sigma_proof,
              'actual_request_or_account_equivalence': 'NOT_CLAIMED'}
    (WORK / 'native_driver_checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({'status': 'PASS', 'checks': len(checks), 'real_inputs': 0, 'accounts': 0,
           'experiments_allocated': 0, 'parameter_dimensions': 15})


if __name__ == '__main__':
    run()
