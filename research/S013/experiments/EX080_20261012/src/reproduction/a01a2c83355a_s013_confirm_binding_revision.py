"""Same-EX pre-account input-contract repair; new sourced identity, unchanged math."""
from pathlib import Path
import sys
from strategy_runtime import StrategyCandidate, implementation_sha256

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_confirm_execution as old
import s013_confirm_execution_v3 as new

exp, path, prior = old.stage()
if (old.OUT / 'account.pkl.gz').exists() or (old.OUT / 'execution.json').exists():
    raise ValueError('Cannot repair or replay an existing financial account')
ctx = old.common().context(1)
(original, _), _ = old.native(old.common())
source = path / 'src/adapter_revision2/strategy_runtime'
for name in ('confirm_kernel.py', 'confirm_net.py'):
    target = source / 'strategies' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write((ROOT / '.tmp/s013-confirm-net-execution-v2' / name).read_bytes())
files = ['strategies/confirm_kernel.py', 'strategies/confirm_net.py']
payload = {'parameters': prior['parameters'], 'runtime': {'contract_version': 1, 'module': 'strategy_runtime.strategies.confirm_net', 'qualname': 'ConfirmNet', 'source_files': files, 'source_sha256': implementation_sha256(files, source_root=source)}}
strategy = StrategyCandidate('S013', 'C9080', payload, source)
identity = ctx.runtime.identify(strategy, dependencies=original.dependencies)
definition = ctx.runtime.describe(strategy)
reqs = definition.inputs.requirements
if len(reqs) != 4 or sum(x.dataset == 'etf.ohlcv' for x in reqs) != 1 or sum(x.dataset == 'etf.unadjusted_daily' for x in reqs) != 1:
    raise ValueError('Single adjusted/single execution four-input definition required')
if definition.parameters.values != prior['parameters']:
    raise ValueError('No parameter change')
new_names = ['.tmp/s013_confirm_execution_v3.py', '.tmp/s013_confirm_binding_revision.py', '.tmp/s013-confirm-net-execution-v2/confirm_kernel.py', '.tmp/s013-confirm-net-execution-v2/confirm_net.py']
repair = {
    'status': 'ROOT_REVIEWED_PRE_ACCOUNT_INPUT_CONTRACT_REPAIR', 'experiment': exp.to_dict(),
    'failed_candidate': 'C9079', 'successor_candidate': 'C9080',
    'failed_stage': 'StrategyInstance.prepare_data._pricing rejected duplicate raw daily input before signal replay and _evaluate_prepared; no execution account or complete native result',
    'error': 'RuntimeContractError: strategy input contract must declare one adjusted and one execution price',
    'actual_accounts_before': 0, 'failed_evaluate_invocations_before_account': 1, 'financial_repeats': 0,
    'fix': 'Remove redundant native_daily. Reconstruct HFQ native daily from the original execution input already covering every signal day. Keep original adjusted daily/execution/calendar requests and exact original30m promoted request. Only consume through latest signal.',
    'numeric_fix': 'Detached pandas containers drop nonnumerical attrs before pure math to avoid expensive metadata copies; source/input identity authentication remains before detachment. Every historical feature/forecast/positiveflag must reequal original EX079 and prior EX080 proof.',
    'unchanged': 'Three parameters/effective domains, original14 definitions, annual mature train/ECDF/ridge, threshold0, h4 clock/turnaround, all original hardgates and execution contract',
    'new_allocation': 0, 'new_provider': 0, 'new_scientific_hypothesis': 0,
    'input_contract_check': '4 inputs; exactly1 adjusted daily and1 raw daily',
    'retained_original_plan_reference': old.read(path / 'protocols/method_references.json')['plan.json'],
}
old.write(new.OUT / 'experiment.json', exp.to_dict())
old.write(new.OUT / 'binding_repair.json', repair)
plan = {**prior, 'payload': payload, 'content_sha256': identity.content_sha256,
        'source_files': {**prior['source_files'], **{p: old.digest(ROOT / p) for p in new_names}},
        'input_contract_revision': repair}
old.write(path / 'protocols/plan_v2.json', plan)
refs = {'plan.json': old.put(ctx, exp, path / 'protocols/plan_v2.json'),
        'binding_repair.json': old.put(ctx, exp, new.OUT / 'binding_repair.json'),
        'failed_execute_attempt.json': old.put(ctx, exp, old.OUT / 'execute_attempt.json')}
for name in plan['source_files']:
    refs[name] = old.put(ctx, exp, ROOT / name)
old.write(path / 'protocols/method_references_v2.json', refs)
print({'status': repair['status'], 'candidate': 'C9080', 'accounts': 0, 'experiment': exp.experiment_id}, flush=True)
