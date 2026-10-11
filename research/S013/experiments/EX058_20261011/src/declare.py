"""Prospective joint boundary guard and recovery, one new center and four reuses."""
from copy import deepcopy
import subprocess
from strategy_runtime import StrategyRuntime, StrategyCandidate, implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, DEPENDENCIES, context, read, write, file_hash
from synthetic_checks import synthetic

def main():
    assert not (PROTOCOLS / 'plan_reference.json').exists()
    assert read(SRC.parent / 'experiment.json') == EXPERIMENT.to_dict()
    subprocess.run([str(ROOT / '.venv/Scripts/ruff.exe'), 'check', str(SRC)], check=True, cwd=ROOT)
    old = read(ROOT / 'research/S013/experiments/EX055_20261011/protocols/plan.json')
    controls = deepcopy(old['controls'])
    original = next(row for row in controls if row['label'] == 'B0-TIME')
    rawrecovery = deepcopy(old['configurations'][0])
    rawrecovery.update(label='B0-RAW-RECOVERY', reused=True, source_directory='../../EX055_20261011/src/strategy_runtime',
        reuse_from='EX055_20261011', reuse_label='N0', role='Diagnostic historical RAW BODY-only ACF eligibility recovery contrast')
    boundary = deepcopy(next(row for row in read(ROOT / 'research/S013/experiments/EX020_20261011/protocols/plan.json')['configurations'] if row['candidate_id'] == 'C9102'))
    boundary.update(label='B0-BULL-BOUNDARY', reused=True, source_directory='../../EX020_20261011/src/strategy_runtime',
        reuse_from='EX020_20261011', reuse_label='N2', role='Diagnostic exact original raw bull-boundary BODY guard alone')
    references = {key: deepcopy(old['control_references'][key]) for key in ('B0-TIME', 'B0-COUPLED')}
    references['B0-RAW-RECOVERY'] = read(ROOT / 'research/S013/assets/runs/EX055_20261011/account_references.json')['N0']
    references['B0-BULL-BOUNDARY'] = read(ROOT / 'research/S013/assets/runs/EX020_20261011/account_references.json')['N2']
    for reference in references.values():
        ref = EvidenceRef.from_dict(reference)
        assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
    files = ['strategies/' + name + '.py' for name in ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range', 'boundary_bear_recovery_range', '__init__')]
    payload = deepcopy(original['payload'])
    payload['parameters']['mechanism'] = 'RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY'
    payload['runtime'].update(module='strategy_runtime.strategies.boundary_bear_recovery_range', qualname='BoundaryBearRecoveryRange',
        source_files=files, source_sha256=implementation_sha256(files, source_root=SRC / 'strategy_runtime'))
    strategy = StrategyCandidate('S013', 'C8880', payload, SRC / 'strategy_runtime')
    identity = StrategyRuntime().identify(strategy, dependencies=DEPENDENCIES)
    cfg = {'label': 'N0', 'index': 0, 'candidate_id': strategy.candidate_id, 'content_sha256': identity.content_sha256,
        'payload': payload, 'source_directory': 'strategy_runtime', 'background': 'ORIGINAL', 'mechanism': 'RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY',
        'mode': 'M1', 'existing_identity': None, 'reused': False, 'parent_control': 'B0-TIME'}
    ctx = context(1)
    for identifier in ['C8880', *(f'C{n:04d}' for n in range(8840, 8872))]:
        assert not (ctx.repository.research_registry_root / 'S013/candidates' / (identifier + '.json')).exists()
        assert not (ROOT / 'research/S013/assets/candidates' / identifier).exists()
    method_reference = read(PROTOCOLS / 'method_reference.json')
    ref = EvidenceRef.from_dict(method_reference)
    assert ref.experiment == EXPERIMENT and file_hash(ref.resolve(ROOT)) == ref.sha256
    method = read(ref.resolve(ROOT))
    assert method['financial_evaluations_before_declaration'] == 0
    prototypes = {}
    for label, folder in (('runtime', ROOT / '.tmp/ex058-boundary-recovery-prototype'),
                          ('oracle', ROOT / '.tmp/ex058-boundary-recovery-oracle'),
                          ('parameter-checks', ROOT / '.tmp/ex058-param-checks-v2')):
        assert read(folder / 'focused.json')['status'] == {'runtime': 'PURE_PASS', 'oracle': 'PASS', 'parameter-checks': 'PURE_PASS'}[label]
        history = {p.relative_to(folder).as_posix(): {'sha256': file_hash(p), 'source': p.read_text(encoding='utf-8')}
            for p in folder.rglob('*') if p.is_file() and p.suffix in ('.json', '.py')}
        path = PROTOCOLS / (label + '_prototype.json')
        write(path, {'files': history, 'retention': 'Pure synthetic source/evidence including failed sources and corrected fixture history; no financial account inputs.'})
        prototypes[label] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, label + '-pure-prototype', path.read_bytes(), 'application/json', 'json')).to_dict()
    path = PROTOCOLS / 'parameter_v1_history.json'
    write(path, {'files': {folder + '/' + p.relative_to(ROOT / '.tmp' / folder).as_posix():
        {'sha256': file_hash(p), 'source': p.read_text(encoding='utf-8')}
        for folder in ('ex058-param-prototype', 'ex058-param-checks') for p in (ROOT / '.tmp' / folder).rglob('*')
        if p.is_file() and p.suffix in ('.py', '.json')},
        'reason': 'Immutable v1 sources and proofs; v2 only corrects two method-description strings before finance.'})
    prototypes['parameter-v1-history'] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'parameter-v1-source-proof-history', path.read_bytes(), 'application/json', 'json')).to_dict()
    path = PROTOCOLS / 'crosscheck.json'
    write(path, {'result': read(ROOT / '.tmp/ex058-crosschecks/result.json'),
        'source': (ROOT / '.tmp/ex058_crosscheck.py').read_text(encoding='utf-8'),
        'history': {folder + '/' + p.name: {'sha256': file_hash(p), 'source': p.read_text(encoding='utf-8')}
            for folder in ('ex058-crosschecks',) for p in (ROOT / '.tmp' / folder).glob('*.json')}})
    prototypes['crosscheck'] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'independent-runtime-oracle-33-synthetic-paths', path.read_bytes(), 'application/json', 'json')).to_dict()
    external_paths = ['research/S013/experiments/EX043_20261011/src/direction_oracle.py',
        'research/S013/experiments/EX043_20261011/src/strategy_runtime/strategies/mechanism_range.py',
        'research/S013/experiments/EX055_20261011/src/raw_recovery_oracle.py']
    external_paths += ['research/S013/experiments/EX055_20261011/src/strategy_runtime/' + name for name in rawrecovery['payload']['runtime']['source_files']]
    external_paths += [f'research/S013/experiments/EX012_20261011/src/strategy_runtime/strategies/{n}.py'
        for n in ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range')]
    external_paths += ['research/S013/experiments/EX020_20261011/src/strategy_runtime/' + name for name in boundary['payload']['runtime']['source_files']]
    for name in ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range'):
        assert (SRC / f'strategy_runtime/strategies/{name}.py').read_bytes() == (ROOT / f'research/S013/experiments/EX012_20261011/src/strategy_runtime/strategies/{name}.py').read_bytes()
    plan = {'name': 'S013-EX058-raw-boundary-body-local-bear-recovery', 'controls': controls, 'diagnostic_controls': [rawrecovery, boundary], 'configurations': [cfg],
        'control_references': references, 'mandate': old['mandate'], 'authorization': old['authorization'],
        'previous_delivery': method['previous_delivery'],
        'method_reference': method_reference, 'pure_prototype_references': prototypes, 'supplementary_evidence': method['supplementary_evidence'],
        'hypothesis': 'Preserve all original ACFpassing bear and stablebull entries; only recover an ACFfailing flatrawbear opportunity after finalbearTIME BELOW anchor and bodyup, still requiring original range/momentum and confirmation; only flat eligible rawbear-to-rawbull boundary adds exact20 BODY gate. No score0 floor or holding changes.',
        'mechanism': method['business_method'], 'selection_history': method['review']['bounded_duplicate_review'],
        'strongest_counterevidence': method['review']['strongest_seen_counterevidence'],
        'current_authorization': method['current_authorization'],
        'constraint_interpretation': method['constraint_interpretation'], 'selection_bias': method['selection_bias'],
        'predeclared_selection': method['economics'], 'parameter_candidate_reservation': {'first': 8840, 'last': 8871},
        'required_warmup': 'max(original parent,regime_window+2) causal previous-full-daily raw route; original center and same32 actual warmup exact, full13 extreme may require62 rather than61; no domain shrink. Bound Open causal input, no MEAN baseline.',
        'source_files': {p.relative_to(SRC).as_posix(): file_hash(p) for p in SRC.rglob('*.py')},
        'external_source_files': {name: file_hash(ROOT / name) for name in external_paths},
        'counts': {'new_business_configurations': 1, 'new_evaluations': 2, 'reused_controls': 4},
        'resources': {'max_workers': 8, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'boundaries': old['boundaries']}
    plan['prospective_pure_verification'] = synthetic(plan, SRC / 'strategy_runtime')
    write(PROTOCOLS / 'plan.json', plan)
    ref = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-raw-recovery-reentry-plan', (PROTOCOLS / 'plan.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'plan_reference.json', ref.to_dict())
    print({'status': 'DECLARED', 'new_center': 'C8880', 'planned_actual_center_evaluations': 2, 'completed_new_evaluations': 0, 'reused_centers': 4}, flush=True)

if __name__ == '__main__':
    main()
