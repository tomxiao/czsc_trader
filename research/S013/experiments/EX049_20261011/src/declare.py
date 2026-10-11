"""Prospectively declare one three-original-momentum mean classifier at original center."""
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
    old = read(ROOT / 'research/S013/experiments/EX046_20261011/protocols/plan.json')
    controls = deepcopy(old['controls'])
    original = next(row for row in controls if row['label'] == 'B0-TIME')
    files = ['strategies/' + name + '.py' for name in
        ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range', 'mean_momentum_range', '__init__')]
    payload = deepcopy(original['payload'])
    payload['parameters']['mechanism'] = 'MEAN_MOMENTUM3'
    payload['runtime'].update(module='strategy_runtime.strategies.mean_momentum_range', qualname='MeanMomentumRange',
        source_files=files, source_sha256=implementation_sha256(files, source_root=SRC / 'strategy_runtime'))
    strategy = StrategyCandidate('S013', 'C6480', payload, SRC / 'strategy_runtime')
    identity = StrategyRuntime().identify(strategy, dependencies=DEPENDENCIES)
    cfg = {'label': 'N0', 'index': 0, 'candidate_id': strategy.candidate_id, 'content_sha256': identity.content_sha256,
        'payload': payload, 'source_directory': 'strategy_runtime', 'background': 'ORIGINAL', 'mechanism': 'MEAN_MOMENTUM3',
        'mode': 'M1', 'existing_identity': None, 'reused': False, 'parent_control': 'B0-TIME'}
    ctx = context(1)
    for identifier in ['C6480', *(f'C{number:04d}' for number in range(6440, 6472))]:
        assert not (ctx.repository.research_registry_root / 'S013/candidates' / (identifier + '.json')).exists()
        assert not (ROOT / 'research/S013/assets/candidates' / identifier).exists()
    for label, reference in old['control_references'].items():
        ref = EvidenceRef.from_dict(reference)
        assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
        assert label in ('B0-TIME', 'B0-COUPLED')
    effect_ref = read(PROTOCOLS / 'effect_reference.json')
    ref = EvidenceRef.from_dict(effect_ref)
    assert ref.experiment == EXPERIMENT and file_hash(ref.resolve(ROOT)) == ref.sha256
    effect = read(ref.resolve(ROOT))
    assert effect['status'] == 'PASS' and len(effect['accounts']) == 33
    assert effect['summary']['new_account_evaluations'] == 0
    prototypes = {}
    for label, folder in (('runtime', ROOT / '.tmp/ex049-mean-momentum-prototype'),
                          ('oracle', ROOT / '.tmp/ex049-mean-momentum-oracle'),
                          ('parameter-checks', ROOT / '.tmp/ex049-param-checks')):
        files_history = {path.relative_to(folder).as_posix(): {'sha256': file_hash(path), 'source': path.read_text(encoding='utf-8')}
            for path in folder.rglob('*') if path.is_file() and path.suffix in ('.py', '.json')}
        assert read(folder / 'focused.json')['status'] == 'PURE_PASS'
        write(PROTOCOLS / (label + '_prototype.json'), {'files': files_history,
            'retention': 'Pure synthetic source/evidence only; original .tmp location retained. No financial native account evaluation.'})
        prototypes[label] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, label + '-pure-prototype',
            (PROTOCOLS / (label + '_prototype.json')).read_bytes(), 'application/json', 'json')).to_dict()
    external = {f'research/S013/experiments/EX043_20261011/src/{name}': file_hash(ROOT / f'research/S013/experiments/EX043_20261011/src/{name}')
                for name in ('direction_oracle.py', 'strategy_runtime/strategies/mechanism_range.py')}
    external.update({f'research/S013/experiments/EX012_20261011/src/strategy_runtime/strategies/{name}.py':
        file_hash(ROOT / f'research/S013/experiments/EX012_20261011/src/strategy_runtime/strategies/{name}.py')
        for name in ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range')})
    for name in ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range'):
        assert (SRC / f'strategy_runtime/strategies/{name}.py').read_bytes() == (ROOT / f'research/S013/experiments/EX012_20261011/src/strategy_runtime/strategies/{name}.py').read_bytes()
    plan = {'name': 'S013-EX049-three-original-momentum-mean-state', 'controls': controls, 'configurations': [cfg],
        'control_references': old['control_references'], 'mandate': old['mandate'], 'authorization': old['authorization'],
        'previous_delivery': read(ROOT / 'research/S013/experiments/EX048_20261011/protocols/delivery_reference.json'),
        'effect_reference': effect_ref, 'effect_method_reference': read(PROTOCOLS / 'effect_method_reference.json'),
        'pure_prototype_references': prototypes,
        'hypothesis': 'Use the arithmetic magnitude of three original momenta rather than a single near-threshold daily value, while keeping both entry route and immediate state exit consistent. This may reduce state-boundary path sensitivity without an extra waiting rule. It is not a majority of thresholded states or smoothing the reference prices.',
        'mechanism': 'm_t=Close_t/Close_t-W-1, mbar=(m_t+m_t-1+m_t-2)/3, then bull if mbar>=theta, equality bull. Compute predecessors on full daily history before reindex. Both flat route and instantaneous regime exit use mean state; held route stays locked. Original H in1..60 held-session units, range/rawACF20/score/L/gates/stop/trail/cooldown and exit priorities remain unchanged.',
        'strongest_counterevidence': 'EX021 smoothing reference prices and EX024 majority vote failed economic centers; EX005 band/confirmation reduced frequency/price returns, and EX048 delayed bear exit reduced112 to107 complete trades. Neither raw route stability nor a conditional observed-state count proves profitability or new trade frequency. Original13 diagnosis also identifies H/ACF sensitivity untouched here. Original center112 barely exceeds110. Mean magnitude may delay downside exits or magnify an outlier; repeated S013 development pool is not independent validation.',
        'selection_history': 'After FULL44 and independently authenticated post-publication112-to107 interval diagnosis. Exact-prior-duplicate search covered all S013 experiment sources/metadata and found no mean of three original momenta. One fixed3 structure at original numeric center; no day/window/threshold search, unit transformation, coordinate drop, economic relaxation or date/year exception.',
        'current_authorization': 'User: 授权你可以自主完成目标，无需评审. Existing RSCH S013 stage3 only; no stage4/freeze/PTE/production/newdata/platform/push.',
        'predeclared_selection': 'One new business center/two actual serial-spawn evaluations and2exact old centers. Only if new center passes original4economic gates, run32newbusiness/33actual original13full-domain same32joint5% points, reuse original32/coupled32; otherwisezero parameter accounts. Success requires qualifying center and improvement in absolute Q10CAGR/Q90DD AND both center-relative degradations versus originalC2132. No all32qualification veto.',
        'parameter_candidate_reservation': {'first': 6440, 'last': 6471},
        'required_warmup': 'max(original parent, W+3), complete current plus two preceding original daily momenta with no history fill. Fixed3 is a structural choice, not a searched numerical coordinate.',
        'source_files': {path.relative_to(SRC).as_posix(): file_hash(path) for path in SRC.rglob('*.py')},
        'external_source_files': external,
        'counts': {'new_business_configurations': 1, 'new_evaluations': 2, 'reused_controls': 2},
        'resources': {'max_workers': 8, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'boundaries': 'RSCH S013stage3; no adjacentbatch/newdata/dependency/platform/production/PTE/freeze/stageadvance/merge/tag/push'}
    plan['prospective_pure_verification'] = synthetic(plan, SRC / 'strategy_runtime')
    write(PROTOCOLS / 'plan.json', plan)
    reference = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-mean-momentum-state-plan',
        (PROTOCOLS / 'plan.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'plan_reference.json', reference.to_dict())
    print({'plan': 'DECLARED', 'new_center': 'C6480', 'actual_center_evaluations': 2}, flush=True)


if __name__ == '__main__':
    main()
