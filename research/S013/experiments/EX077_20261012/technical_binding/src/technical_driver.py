"""Technical request-identity revision; reuse frozen original account driver."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
from strategy_runtime import StrategyCandidate
from czsc_trader.research_tools.context import ExperimentRef

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / '.tmp/s013-price-event-policy'
WORK = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('price_event_original_driver', ORIGINAL / 'centre_driver.py')
d = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = d
spec.loader.exec_module(d)
d.WORK = WORK
d.CANDIDATE = 'C9078'

def stage():
    exp = ExperimentRef.from_dict(d.read(WORK / 'experiment.json'))
    path = exp.resolve(ROOT) / 'technical_binding'
    plan = d.read(path / 'protocols/plan.json')
    if d.read(d.public(d.read(path / 'protocols/plan_reference.json'))) != plan:
        raise ValueError('technical actual/public plan mismatch')
    return exp, plan, path

d.stage = stage

def declare(authority_path):
    authority = d.authorize('declare', authority_path)
    exp = ExperimentRef.from_dict(d.read(ORIGINAL / 'experiment.json'))
    assert exp.experiment_id == 'EX077_20261012'
    original_plan = d.read(exp.resolve(ROOT) / 'protocols/plan.json')
    original_ref = d.read(exp.resolve(ROOT) / 'protocols/plan_reference.json')
    assert original_ref['sha256'] == '41aa5b6aa3ec796b0b285d01bf91bfbc9dd173e97e52158a6de2e0c2c7fd9ff2'
    assert d.read(d.public(original_ref)) == original_plan
    assert not (ORIGINAL / 'centre_prepared.pkl.gz').exists()
    assert not (ORIGINAL / 'centre_account.pkl.gz').exists()
    for path in (ROOT / 'research/S013/assets/candidates/C9078', ROOT / 'research/registrations/S013/candidates/C9078.json'):
        assert not path.exists(), 'new technical identity already occupied'
    (baseline, _), _, cache = d.native()
    assert d.digest(cache) == original_plan['baseline_cache_sha256']
    c = d.common()
    ctx = c.context(1)
    path = exp.resolve(ROOT) / 'technical_binding'
    for relative, source in (
        ('src/strategy_runtime/strategies/policy.py', ORIGINAL / 'policy.py'),
        ('src/strategy_runtime/strategies/price_event.py', WORK / 'adapter.py'),
        ('src/centre_audit.py', ORIGINAL / 'centre_audit.py'),
        ('src/technical_driver.py', Path(__file__)),
    ):
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(source.read_bytes())
    source = path / 'src/strategy_runtime'
    strategy = StrategyCandidate('S013', 'C9078', d.payload(source), source)
    identity = ctx.runtime.identify(strategy, dependencies=baseline.dependencies)
    plan = original_plan | {
        'status': 'TECHNICAL_EXISTING_REQUEST_REUSE_DECLARED_ZERO_ACCOUNTS',
        'candidate_id': 'C9078',
        'content_sha256': identity.content_sha256,
        'payload': json.loads(json.dumps(dict(strategy.payload), default=dict)),
        'source_freeze': d.read(WORK / 'centre_source_freeze.json'),
        'synthetic_precheck': d.read(WORK / 'proof.json'),
        'root_authority': authority,
        'technical_revision': {
            'original_plan': original_ref,
            'prior_candidate_id': 'C9077',
            'failure': d.read(ORIGINAL / 'prepare_failure.json'),
            'change': 'Calendar and daily exact requests reuse authenticated C8880 original assets; definition minimum121 and full L2..120 unchanged. Extra original warm observations do not initialize policy state or alter any decision.',
            'original_scientific_policy_sha256': d.digest(ORIGINAL / 'policy.py'),
            'new_accounts_before_revision': 0,
            'new_policy_signals_before_revision': 0,
        },
    }
    plan_path = path / 'protocols/plan.json'
    d.write(plan_path, plan)
    refs = {'plan': d.put(ctx, exp, plan_path), 'original_plan': original_ref, 'baseline_native': original_plan['baseline_native']}
    for file in (WORK / 'adapter.py', WORK / 'proof.json', WORK / 'centre_source_freeze.json', Path(__file__), ORIGINAL / 'prepare_failure.json', ORIGINAL / 'reuse_r2_checks.py', ORIGINAL / 'reuse_r2_freeze.json', Path(authority_path)):
        refs[file.name] = d.put(ctx, exp, file)
    for file in (path / 'src').rglob('*.py'):
        refs[file.relative_to(path / 'src').as_posix()] = d.put(ctx, exp, file)
    d.write(path / 'protocols/plan_reference.json', refs['plan'])
    d.write(path / 'protocols/prospective_references.json', refs)
    d.write(WORK / 'experiment.json', exp.to_dict())
    assert not c.SOURCE_CALLS
    return {'status': 'TECHNICAL_DECLARED_SAME_EXPERIMENT', 'plan_reference': refs['plan'], 'new_accounts': 0, 'experiment': exp.experiment_id}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('declare', 'prepare', 'execute', 'verify'))
    parser.add_argument('--authority', required=True)
    args = parser.parse_args()
    action = declare if args.phase == 'declare' else getattr(d, args.phase)
    print(json.dumps(action(Path(args.authority)), ensure_ascii=False, indent=2, allow_nan=False))
