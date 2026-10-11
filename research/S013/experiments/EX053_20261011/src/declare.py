"""Prospective raw-ACF BELOW reentry contrast, one new center and three native reuses."""
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
    old = read(ROOT / 'research/S013/experiments/EX052_20261011/protocols/plan.json')
    controls = deepcopy(old['controls'])
    original = next(row for row in controls if row['label'] == 'B0-TIME')
    mean = deepcopy(next(row for row in read(ROOT / 'research/S013/experiments/EX028_20261011/protocols/plan.json')['configurations'] if row['label'] == 'N1'))
    mean.update(label='B0-MEAN', reused=True, source_directory='../../EX028_20261011/src/strategy_runtime',
        reuse_from='EX028_20261011', reuse_label='N1', role='Diagnostic mean background without price gate; original four-gate failure remains explicit')
    references = deepcopy(old['control_references'])
    references['B0-MEAN'] = read(ROOT / 'research/S013/assets/runs/EX028_20261011/account_references.json')['N1']
    for reference in references.values():
        ref = EvidenceRef.from_dict(reference)
        assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
    files = ['strategies/' + name + '.py' for name in ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range', 'bear_time_below_range', '__init__')]
    payload = deepcopy(original['payload'])
    payload['parameters']['mechanism'] = 'RAW_BEAR_TIME_BELOW_CLOSE'
    payload['runtime'].update(module='strategy_runtime.strategies.bear_time_below_range', qualname='BearTimeBelowRange',
        source_files=files, source_sha256=implementation_sha256(files, source_root=SRC / 'strategy_runtime'))
    strategy = StrategyCandidate('S013', 'C7580', payload, SRC / 'strategy_runtime')
    identity = StrategyRuntime().identify(strategy, dependencies=DEPENDENCIES)
    cfg = {'label': 'N0', 'index': 0, 'candidate_id': strategy.candidate_id, 'content_sha256': identity.content_sha256,
        'payload': payload, 'source_directory': 'strategy_runtime', 'background': 'ORIGINAL', 'mechanism': 'RAW_BEAR_TIME_BELOW_CLOSE',
        'mode': 'M1', 'existing_identity': None, 'reused': False, 'parent_control': 'B0-TIME'}
    ctx = context(1)
    for identifier in ['C7580', *(f'C{n:04d}' for n in range(7540, 7572))]:
        assert not (ctx.repository.research_registry_root / 'S013/candidates' / (identifier + '.json')).exists()
        assert not (ROOT / 'research/S013/assets/candidates' / identifier).exists()
    method_reference = read(PROTOCOLS / 'method_reference.json')
    ref = EvidenceRef.from_dict(method_reference)
    assert ref.experiment == EXPERIMENT and file_hash(ref.resolve(ROOT)) == ref.sha256
    method = read(ref.resolve(ROOT))
    assert method['financial_evaluations_before_declaration'] == 0
    prototypes = {}
    for label, folder in (('runtime', ROOT / '.tmp/ex053-raw-below-prototype'),
                          ('oracle', ROOT / '.tmp/ex053-raw-below-oracle'),
                          ('parameter-checks', ROOT / '.tmp/ex053-param-checks')):
        assert read(folder / 'focused.json')['status'] == ('PASS' if label == 'oracle' else 'PURE_PASS')
        history = {p.relative_to(folder).as_posix(): {'sha256': file_hash(p), 'source': p.read_text(encoding='utf-8')}
            for p in folder.rglob('*') if p.is_file() and p.suffix in ('.json', '.py')}
        path = PROTOCOLS / (label + '_prototype.json')
        write(path, {'files': history, 'retention': 'Pure synthetic source/evidence including failed sources and corrected fixture history; no financial account inputs.'})
        prototypes[label] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, label + '-pure-prototype', path.read_bytes(), 'application/json', 'json')).to_dict()
    path = PROTOCOLS / 'crosscheck.json'
    write(path, {'result': read(ROOT / '.tmp/ex053-crosschecks/result.json'),
        'source': (ROOT / '.tmp/ex053_crosscheck.py').read_text(encoding='utf-8'),
        'history': {p.name: {'sha256': file_hash(p), 'source': p.read_text(encoding='utf-8')}
            for p in (ROOT / '.tmp/ex053-crosschecks').glob('*.json')}})
    prototypes['crosscheck'] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'independent-runtime-oracle-33-synthetic-paths', path.read_bytes(), 'application/json', 'json')).to_dict()
    external_paths = ['research/S013/experiments/EX043_20261011/src/direction_oracle.py',
        'research/S013/experiments/EX043_20261011/src/strategy_runtime/strategies/mechanism_range.py',
        'research/S013/experiments/EX028_20261011/src/analyze.py',
        'research/S013/experiments/EX028_20261011/src/strategy_runtime/strategies/acf_range.py']
    external_paths += [f'research/S013/experiments/EX012_20261011/src/strategy_runtime/strategies/{n}.py'
        for n in ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range')]
    for name in ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range'):
        assert (SRC / f'strategy_runtime/strategies/{name}.py').read_bytes() == (ROOT / f'research/S013/experiments/EX012_20261011/src/strategy_runtime/strategies/{name}.py').read_bytes()
    plan = {'name': 'S013-EX053-raw-bear-time-below-close', 'controls': controls, 'diagnostic_controls': [mean], 'configurations': [cfg],
        'control_references': references, 'mandate': old['mandate'], 'authorization': old['authorization'],
        'previous_delivery': read(ROOT / 'research/S013/experiments/EX052_20261011/protocols/delivery_reference.json'),
        'method_reference': method_reference, 'pure_prototype_references': prototypes,
        'hypothesis': 'Preserve original rawACF protective entries; only require an observed price rise on bear reentry after final bear TIME exit below its own signal-entry anchor. Isolate price-category gate on RAW from known MEAN background interaction.',
        'mechanism': method['business_method'], 'selection_history': method['review']['bounded_duplicate_review'],
        'strongest_counterevidence': method['review']['strongest_existing_counterevidence'],
        'current_authorization': method['current_authorization'],
        'predeclared_selection': method['economics'], 'parameter_candidate_reservation': {'first': 7540, 'last': 7571},
        'required_warmup': 'Exact original parent unchanged across full13 domain; extra previousClose already covered. No previous-regime diagnostics, no W+2 or MEAN baseline requirement.',
        'source_files': {p.relative_to(SRC).as_posix(): file_hash(p) for p in SRC.rglob('*.py')},
        'external_source_files': {name: file_hash(ROOT / name) for name in external_paths},
        'counts': {'new_business_configurations': 1, 'new_evaluations': 2, 'reused_controls': 3},
        'resources': {'max_workers': 8, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'boundaries': old['boundaries']}
    plan['prospective_pure_verification'] = synthetic(plan, SRC / 'strategy_runtime')
    write(PROTOCOLS / 'plan.json', plan)
    ref = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-raw-below-reentry-plan', (PROTOCOLS / 'plan.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'plan_reference.json', ref.to_dict())
    print({'status': 'DECLARED', 'new_center': 'C7580', 'actual_center_evaluations': 2, 'reused_centers': 3}, flush=True)

if __name__ == '__main__':
    main()
