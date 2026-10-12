"""EX095 one native stable raw-bull score-bypass centre; phases invoked explicitly by root.

Definition and metadata inspection do not read actual market/account contents.
Preparation authenticates existing cached inputs; execution is one public full
account with no automatic repeat. A centre pass requires a later frozen32/fee
followup and never completes the current research goal on its own.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import importlib
from pathlib import Path
import sys
import types

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet, StrategyCandidate, canonical_sha256, implementation_sha256
from strategy_evaluator import CandidateAssessmentRequest, QuantileMethod, SelfCheckProtocol, assess_candidates
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite, build_assessment_evidence
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp/s013-new-goal'))
import governance as g  # noqa: E402

WORK = Path(__file__).resolve().parent
OUT = ROOT / '.tmp/s013-new-goal/result095'
CANDIDATE = 'C9095'
MECHANISM = 'STABLE_RAW_BULL_BODY_CONFIRMATION_BYPASS'
PACKAGE = WORK / 'strategy_runtime'
RUNTIME_FILES = ['strategies/' + name for name in (
    '__init__.py', 'range_reversion.py', 'adaptive_range.py', 'confirmed_range.py',
    'reentry_confirmed_range.py', 'boundary_bear_recovery_range.py',
    'policy_kernel.py', 'stable_bull_bypass_range.py')]
HELPERS = ROOT / 'research/S013/experiments/EX074_20261011/src'


def candidate_unoccupied():
    occupied = (ROOT / 'research/S013/assets/candidates' / CANDIDATE,
                ROOT / 'research/registrations/S013/candidates' / (CANDIDATE + '.json'))
    if any(path.exists() for path in occupied):
        raise ValueError('Reserved candidate identity is occupied; never overwrite or register implicitly')


def definition():
    candidate_unoccupied()
    for filename in ('checks.json', 'audit_checks.json'):
        checked = g.read(WORK / filename)
        if checked['status'] != 'PASS' or checked['real_inputs_read'] != 0 or not checked['synthetic_only']:
            raise ValueError('Primary and independent pure synthetic checks required')
    for filename, expected in g.read(WORK / 'checks.json')['source_sha256'].items():
        source = WORK / filename if filename == 'checks.py' else PACKAGE / 'strategies' / filename
        if g.digest(source) != expected:
            raise ValueError('Checked source changed before declaration: ' + filename)
    old = g.read(ROOT / 'research/S013/experiments/EX058_20261011/protocols/plan.json')
    centre = next(row for row in old['configurations'] if row['label'] == 'N0')
    if centre['candidate_id'] != 'C8880':
        raise ValueError('Exact C8880 N0 parameter metadata required')
    parameters = deepcopy(centre['payload']['parameters'])
    parameters.update({'mechanism': MECHANISM, 'bypass_enabled': True})
    geometry_ref = g.read(ROOT / 'research/S013/experiments/EX058_20261011/protocols/parameter_plans.json')['geometry']
    geometry = g.read(g.public(geometry_ref))
    if len(geometry['coordinates']) != 13 or geometry['protocol'] != {'radius': .05, 'point_count': 32, 'seed': 13}:
        raise ValueError('Original full13 domains and standard32 protocol must be retained')
    for name, lower, upper, kind in geometry['coordinates']:
        value = parameters
        for part in name.split('.'):
            value = value[part]
        if not lower <= value <= upper or (kind == 'INTEGER' and type(value) is not int):
            raise ValueError('Original centre/domain mapping differs: ' + name)
    payload = {'parameters': parameters, 'runtime': {'contract_version': 1,
        'module': 'strategy_runtime.strategies.stable_bull_bypass_range', 'qualname': 'StableBullBypassRange',
        'source_files': RUNTIME_FILES, 'source_sha256': implementation_sha256(RUNTIME_FILES, source_root=PACKAGE)}}
    own = [path.relative_to(ROOT).as_posix() for path in WORK.rglob('*') if path.is_file() and path.suffix in ('.py', '.json')]
    source_files = own + [
        '.tmp/s013-new-goal/governance.py', '.tmp/s013-new-goal/gates_v2.py',
        '.tmp/s013-new-goal/prospective_expression_review.json', '.tmp/s013_confirm_execution.py',
        'research/S013/experiments/EX058_20261011/src/common.py',
        'research/S013/experiments/EX080_20261012/src/reproduction/02c394b35938_s013_confirm_execution_v3.py',
        'research/S013/experiments/EX080_20261012/src/reproduction/f78efbb0b1da_audit_driver.py',
        *[(HELPERS / (name + '.py')).relative_to(ROOT).as_posix() for name in ('economics_reference', 'account_reference', 'execution_links')]]
    baseline_ref = g.read(ROOT / 'research/S013/experiments/EX071_20261011/protocols/plan.json')['native_ref']
    baseline_sha = g.read(ROOT / 'research/S013/experiments/EX092_20261012/protocols/plan.json')['native_cache_sha256']
    return {
        'question': '保留C8880其他规则，仅对当前及前日rawbull且当T严格正BODY豁免score，能否恢复有效参与并满足新版四门？',
        'basis': 'EX006/012全面解除确认增加频率但损害收益，当前窄scope与全面或bull单侧Off有合成差异；固定stable rawbull及严格正BODY条件检验恢复参与，没有新增信息。',
        'strongest_counter': '窄豁免仍可能引入低质量买入，早入场改变后续交易年龄、价格锚和资金，可能使2023薄净盈利转负；因果上行近似不是最终buyhold盈利年预知。',
        'role_of_component': '原0/1策略的稳定上行参与窄score豁免；其他入场、全部退出、持仓H和锚保持原职责',
        'label': '真实连续原生账户净收益/年度回撤/实际退出闭合次数，不以价格代理代替',
        'horizon': '原bull H8、bear H4仍是实际被接受的交易信号年龄；合法1..60域及原13参数完整保留，无新数值参数',
        'controls': '同源C8880原完整参数及父策略；bypass_enabled=False父全部history与旧native决策逐字段精确核验',
        'availability': '仅当T和完整前日rawbull且Close>Open可免score；原opportunity/scorepassed仍保留诊断；不使用当年最终盈利标签，T决策T+1执行',
        'price_basis': '原510500HFQ固定锚、不叠加现金分红、100万元整手100、单侧10bp、固定1% LimitBuyHold及原数据',
        'limitations': '同开发池反复研究；原13数值语义完整保持，固定结构豁免仍改变路径；旧扰动账户不能作为新策略扰动，中心通过不代表32/32',
        'payload': payload, 'candidate_id': CANDIDATE,
        'parameter_geometry': {'source': geometry_ref, 'coordinates': geometry['coordinates'],
            'protocol': {**geometry['protocol'], 'random_generator': 'PCG64', 'integer_rounding': 'HALF_EVEN',
                         'quantile_method': 'LINEAR', 'distance_tolerance': 1e-10, 'max_attempts': 100000},
            'feasibility': 'bull.entry<bull.exit and bear.entry<bear.exit; original domain/type constraints',
            'new_numeric_coordinates': [], 'fixed_structure': {'bypass_enabled': True, 'mechanism': MECHANISM},
            'semantic_change': 'No numeric business semantic change; max_hold remains accepted-trade age; all13 original full domains retained; only fixed categorical bypass scope changes',
            'not_done_before_centre': 'No new parameter points or account results; centre pass requires a separately frozen sameEX32/independentfee plan'},
        'new_goal': 'MANDATE/7; centre and all32 pass new4, pooled positiveBHyear actual exit frequency replaces whole-period frequency; realised BHyears ex-post only',
        'stop_or_followup': 'Fail any v2 centre gate: stop this fixed policy, no32/fee/windowrescue. Pass centre: freeze sameEX32 and independentfee; do not finalize as robust achieved.',
        'resources': {'maximum_native_centres': 1, 'new_accounts': 1, 'provider_calls': 0, 'automatic_repeat': False},
        'input_references': {'baseline_native.json': baseline_ref, 'parameter_geometry.json': geometry_ref},
        'native_cache_sha256': baseline_sha,
        'source_files': {name: g.digest(ROOT / name) for name in source_files},
        'objective_achieved': False,
    }


def candidate(exp, plan):
    return StrategyCandidate('S013', CANDIDATE, plan['payload'], exp.resolve(ROOT) / 'src/stable_bull_bypass/strategy_runtime')


def local_runtime(source):
    """Private source namespace; never shadow installed strategy_runtime."""
    prefix = '_s013_episode_preaccount'
    for name in tuple(sys.modules):
        if name == prefix or name.startswith(prefix + '.'):
            del sys.modules[name]
    for name, directory in ((prefix, source), (prefix + '.strategies', source / 'strategies')):
        module = types.ModuleType(name)
        module.__path__ = [str(directory)]
        sys.modules[name] = module
    adapter = importlib.import_module(prefix + '.strategies.stable_bull_bypass_range')
    parent = importlib.import_module(prefix + '.strategies.boundary_bear_recovery_range')
    core = importlib.import_module(prefix + '.strategies.policy_kernel')
    return adapter, parent, core


def compare_history(actual, expected):
    """Compare every expected field, preserving missingness and strict numbers."""
    if not actual.index.equals(expected.index) or any(name not in actual for name in expected):
        raise ValueError('Full policy axis or fields differ')
    for name in expected:
        wanted, supplied = expected[name], actual[name]
        if not wanted.isna().equals(supplied.isna()):
            raise ValueError('Policy missingness differs: ' + name)
        good = wanted.notna()
        if pd.api.types.is_numeric_dtype(wanted.dtype):
            left = pd.to_numeric(supplied[good], errors='raise').to_numpy(float)
            right = wanted[good].to_numpy(float)
            if not np.array_equal(left, right):
                raise ValueError('Policy numeric field differs: ' + name)
        elif supplied[good].tolist() != wanted[good].tolist():
            raise ValueError('Policy categorical field differs: ' + name)


def native(plan, common):
    cache = ROOT / '.tmp/s013-mechanism-EX058/N0.pkl.gz'
    if g.digest(cache) != plan['native_cache_sha256']:
        raise ValueError('Original native cache drift')
    pair, reference = g.base.native(common)
    if reference != plan['input_references']['baseline_native.json']:
        raise ValueError('Baseline public reference drift')
    return pair, reference


def frame(reference):
    value = pd.read_csv(g.public(reference), index_col='signal_date', float_precision='round_trip')
    value.index = pd.to_datetime(value.index).as_unit('ns')
    return value


def declare():
    plan = definition()
    checked = g.read(WORK / 'checks.json')
    checks = {**checked, 'real_inputs': checked['real_inputs_read']}
    exp, plan, refs = g.allocate(95, title='稳定rawbull正BODY窄确认豁免的原生中心反证', question=plan['question'], plan=plan, checks=checks)
    OUT.mkdir(parents=True, exist_ok=True)
    g.write(OUT / 'declaration.json', {'experiment': exp.to_dict(), 'candidate_id': CANDIDATE, 'quota_slot': 7, 'new_accounts': 0})
    print({'experiment': exp.experiment_id, 'candidate': CANDIDATE, 'stage': 'DECLARED', 'new_accounts': 0}, flush=True)


def prepare():
    exp, path, plan, refs = g.stage(95)
    g.write(OUT / 'prepare_attempt.json', {'status': 'STARTED', 'new_accounts': 0, 'automatic_repeat': False})
    c = g.base.common()
    (old, baseline), baseline_ref = native(plan, c)
    ctx = c.context(1)
    strategy = candidate(exp, plan)
    request = replace(old, experiment_id=exp.experiment_id, strategy=strategy,
        runtime_binding={'candidate_id': strategy.reference_id, 'source_files': list(strategy.payload['runtime']['source_files']),
                         'implementation_sha256': strategy.payload['runtime']['source_sha256']}, input_bindings={}, lineage=None)
    bound = ctx.evaluation.prepare(request)
    if bound.execution_data.fingerprint != old.execution_data.fingerprint or bound.benchmark.to_dict() != old.benchmark.to_dict() or bound.execution_data.pricing.to_dict() != old.execution_data.pricing.to_dict():
        raise ValueError('Original execution/benchmark/HFQ pricing contract changed')
    b, original = bound.input_bindings['full'], old.input_bindings['full']
    if set(b.plan.requests) != set(original.plan.requests):
        raise ValueError('Original complete runtime request names changed')
    for name in b.plan.requests:
        if b.plan.requests[name] != original.plan.requests[name]:
            raise ValueError('Original exact prepared request changed: ' + name)
    inputs, identities = {}, {}
    for name, query in b.plan.requests.items():
        fetched = ctx.data.fetch(query, prepared=b.prepared)
        if not fetched.ready:
            raise ValueError('Exact existing prepared input unavailable: ' + name)
        inputs[name] = fetched.dataframe
        identities[name] = fetched.identity.content_sha256
    if c.SOURCE_CALLS:
        raise ValueError('Provider access prohibited')
    sessions = pd.DatetimeIndex(pd.to_datetime(tuple(b.plan.signal_dates.values()))).as_unit('ns')
    if len(sessions) != 1636 or sessions[0] != pd.Timestamp('2019-12-31') or sessions[-1] != pd.Timestamp('2026-09-29'):
        raise ValueError('Original1636 signal prefix required')
    identity = ctx.runtime.identify(strategy, dependencies=bound.dependencies)
    adapter, parent, core = local_runtime(strategy.source_root)
    parameters = deepcopy(plan['payload']['parameters'])
    disabled_parameters = {**parameters, 'bypass_enabled': False}
    parent_parameters = {key: value for key, value in parameters.items() if key != 'bypass_enabled'}
    parent_parameters['mechanism'] = adapter.PARENT_MECHANISM
    disabled = adapter.StableBullBypassRange(ParameterSet(disabled_parameters)).calculate_history(inputs, sessions)
    original_history = parent.BoundaryBearRecoveryRange(ParameterSet(parent_parameters)).calculate_history(inputs, sessions)
    pd.testing.assert_frame_equal(disabled, original_history, check_exact=True)
    old_decisions = baseline.runs[0].execution.decisions.copy()
    old_decisions.index = pd.DatetimeIndex(pd.to_datetime(old_decisions.signal_date)).as_unit('ns')
    compare_history(old_decisions, original_history)
    base = core.prepare(parameters, inputs, sessions)
    history = adapter.StableBullBypassRange(ParameterSet(parameters)).calculate_history(inputs, sessions)
    independent = g.base.load('episode_independent_preaccount', path / 'src/stable_bull_bypass/audit_core.py').verify(sessions, parameters, base, history)
    if independent['status'] != 'PASS':
        raise ValueError('Independent complete policy preaccount proof required')
    for name, table in (('policy.csv', history), ('disabled_policy.csv', disabled)):
        with (OUT / name).open('x', encoding='utf-8', newline='\n') as stream:
            table.to_csv(stream, index_label='signal_date', float_format='%.17g')
    g.write(OUT / 'independent_preaccount.json', independent)
    c.cache_write(OUT / 'prepared.pkl.gz', bound)
    proof = {'status': 'PASS', 'new_accounts': 0, 'disabled_parent_history': 'EXACT', 'baseline_original_columns': 'EXACT',
        'original_requests_exact': True, 'input_bindings': {key: value.to_dict() for key, value in bound.input_bindings.items()},
        'input_identities': identities, 'execution_fingerprint': bound.execution_data.fingerprint,
        'content_sha256': identity.content_sha256, 'prepared_cache_sha256': g.digest(OUT / 'prepared.pkl.gz'),
        'signal_sessions': 1636, 'provider_calls': 0, 'baseline_reference': baseline_ref}
    g.write(OUT / 'prepare.json', proof)
    prepared_refs = {name: g.put(ctx, exp, OUT / name) for name in ('prepare.json', 'policy.csv', 'disabled_policy.csv', 'independent_preaccount.json')}
    g.write(path / 'protocols/prepare_references.json', prepared_refs)
    assert not c.SOURCE_CALLS
    print({'experiment': exp.experiment_id, 'stage': 'PREPARED', 'preaccount': 'PASS', 'new_accounts': 0}, flush=True)


def prepared(exp, path, plan):
    references = g.read(path / 'protocols/prepare_references.json')
    proof = g.read(g.public(references['prepare.json']))
    independent = g.read(g.public(references['independent_preaccount.json']))
    if proof['status'] != 'PASS' or independent['status'] != 'PASS' or g.digest(OUT / 'prepared.pkl.gz') != proof['prepared_cache_sha256']:
        raise ValueError('Authenticated immutable preaccount preparation required')
    c = g.base.common()
    bound = c.cache_read(OUT / 'prepared.pkl.gz')
    if canonical_sha256(bound.strategy.payload) != canonical_sha256(plan['payload']) or bound.strategy.candidate_id != CANDIDATE or bound.experiment_id != exp.experiment_id:
        raise ValueError('Prepared candidate/request differs from frozen plan')
    if {key: value.to_dict() for key, value in bound.input_bindings.items()} != proof['input_bindings']:
        raise ValueError('Prepared input binding drift')
    history = frame(references['policy.csv'])
    return c, bound, proof, independent, history


def execute():
    exp, path, plan, refs = g.stage(95)
    c, bound, proof, independent, history = prepared(exp, path, plan)
    g.write(OUT / 'execute_attempt.json', {'status': 'STARTED', 'maximum_accounts': 1, 'automatic_repeat': False})
    ctx = c.context(1)
    result = ctx.evaluation.evaluate(bound)
    c.cache_write(OUT / 'account.pkl.gz', (bound, result))
    reference = publish_evidence(ctx, EvaluationEvidenceWrite(exp, 'stable-bull-bypass-fixed-centre-native', bound, result)).to_dict()
    if g.read(g.public(reference)) != serialize_evaluation_evidence(bound, result) or c.SOURCE_CALLS:
        raise ValueError('Complete public native mismatch or forbidden provider access')
    receipt = {'status': 'COMPLETE', 'new_accounts': 1, 'native_ref': reference, 'cache_sha256': g.digest(OUT / 'account.pkl.gz'),
               'request_hash': result.request_hash, 'result_hash': result.result_hash}
    g.write(OUT / 'execution.json', receipt)
    g.write(path / 'protocols/centre_reference.json', reference)
    print({'experiment': exp.experiment_id, 'candidate': CANDIDATE, 'stage': 'COMPLETE', 'new_accounts': 1}, flush=True)


def audit():
    exp, path, plan, refs = g.stage(95)
    c, prepared_bound, proof, independent, history = prepared(exp, path, plan)
    receipt = g.read(OUT / 'execution.json')
    if receipt['status'] != 'COMPLETE' or receipt['new_accounts'] != 1 or g.digest(OUT / 'account.pkl.gz') != receipt['cache_sha256']:
        raise ValueError('One authenticated complete account required')
    bound, result = c.cache_read(OUT / 'account.pkl.gz')
    formal = g.read(g.public(receipt['native_ref']))
    validate_evaluation_evidence(formal)
    if serialize_evaluation_evidence(bound, result) != formal or bound.strategy.payload != prepared_bound.strategy.payload or bound.runtime_binding != prepared_bound.runtime_binding:
        raise ValueError('Prepared request/full public native differs')
    if {key: value.to_dict() for key, value in bound.input_bindings.items()} != proof['input_bindings']:
        raise ValueError('Native complete input bindings differ from preparation')
    ctx = c.context(1)
    identity = ctx.runtime.identify(bound.strategy, dependencies=bound.dependencies)
    if identity.content_sha256 != proof['content_sha256'] or identity.content_sha256 != result.runs[0].identity.content_sha256 or result.data_identity != bound.execution_data.fingerprint or result.runtime_binding_hash != canonical_sha256(bound.runtime_binding):
        raise ValueError('Native runtime/data/payload identity differs')
    if len(result.runs) != 1 or bound.execution_mode != 'FULL' or bound.initial_cash != 1_000_000:
        raise ValueError('One full unlevered original-capital account required')
    decisions = result.runs[0].execution.decisions.copy()
    decisions.index = pd.DatetimeIndex(pd.to_datetime(decisions.signal_date)).as_unit('ns')
    compare_history(decisions, history)
    helpers = {name: g.base.load('episode_' + name, HELPERS / (name + '.py')) for name in ('economics_reference', 'account_reference', 'execution_links')}
    facts = build_assessment_evidence(bound, result)
    economics = helpers['economics_reference'].economics(facts[0])
    cash_account = helpers['account_reference'].verify_account(bound, result)
    links = helpers['execution_links'].verify(bound, result)
    for year, values in economics['annual'].items():
        if abs(values['return'] - cash_account['annual'][year]['net_return']) > 1e-12 or abs(values['drawdown'] - cash_account['annual'][year]['drawdown_magnitude']) > 1e-12:
            raise ValueError('Independent continuous annual accounting mismatch')
    account = result.runs[0].execution.account_daily
    if not np.isfinite(account.equity).all() or (account.quantity < 0).any() or (account.cash < -1e-6).any():
        raise ValueError('Finite cash-only long/no leverage required')
    (old, old_result), baseline_ref = native(plan, c)
    if bound.execution_data.fingerprint != old.execution_data.fingerprint or bound.benchmark.to_dict() != old.benchmark.to_dict() or bound.execution_data.pricing.to_dict() != old.execution_data.pricing.to_dict():
        raise ValueError('Original data/benchmark/price contract changed')
    baseline = helpers['economics_reference'].economics(build_assessment_evidence(old, old_result)[0])
    gates = g.base.load('episode_current_gates', ROOT / '.tmp/s013-new-goal/gates_v2.py')
    review, baseline_review = gates.from_economics(economics), gates.from_economics(baseline)
    protocol = SelfCheckProtocol(version='S013-EX062-three-ledger-checks-missing32-fee-v1', baseline_window='full',
        standard_scenario='baseline', stress_scenario='stress_20bp_per_side', rolling_window_days=126, rolling_step_days=21,
        quantile_method=QuantileMethod.LINEAR, minimum_perturbations=32, minimum_rolling_windows=20,
        bootstrap_repetitions=2000, bootstrap_block_length=20, seed=13, reconciliation_tolerance=1e-6, pbo_blocks=10)
    partial = assess_candidates(CandidateAssessmentRequest((facts[0].candidate,), protocol, (), facts)).to_dict()
    report = {'status': 'PASS', 'new_accounts': 1, 'technical_financial_repeats': 0,
        'independent_signal': independent, 'native_policy_and_metadata': 'EXACT', 'economics': economics,
        'gates_v2': {**asdict(review), 'qualified': review.qualified}, 'old_all_pool_gate_is_diagnostic_only': True,
        'cash_account': cash_account, 'orders_first_touch': links, 'baseline_economics': baseline,
        'baseline_gates_v2': {**asdict(baseline_review), 'qualified': baseline_review.qualified}, 'baseline_reference': baseline_ref,
        'three_ledger_checks': partial, 'full_five_checks_complete': False,
        'parameter32': {'status': 'NOT_RUN', 'Q10': None, 'Q90': None, 'individual_gate_rates': None, 'joint_gate_rate': None},
        'independent_double_fee': {'status': 'NOT_RUN'}, 'pbo': {'status': 'UNAVAILABLE', 'required_blocks': 10, 'reason': 'Complete search-family returns absent'},
        'qualified': review.qualified, 'provider_calls': 0, 'centre_reference': receipt['native_ref'],
        'stop': 'CENTRE_FAILED_STOP_32_FEE_NEIGHBORS' if not review.qualified else 'CENTRE_PASS_FROZEN_SAME_EX_32_FEE_REQUIRED',
        'objective_achieved': False}
    if c.SOURCE_CALLS:
        raise ValueError('Provider access prohibited')
    g.write(OUT / 'verification.json', report)
    published = {name: g.put(ctx, exp, file) for name, file in {'verification.json': OUT / 'verification.json', 'audit_driver.py': Path(__file__)}.items()}
    g.write(path / 'protocols/audit_references.json', published)
    print({'experiment': exp.experiment_id, 'status': 'PASS', 'new_gates': review.gates, 'stop': report['stop']}, flush=True)


if __name__ == '__main__':
    {'declare': declare, 'prepare': prepare, 'execute': execute, 'audit': audit}[sys.argv[1]]()
