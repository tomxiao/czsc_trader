"""Prospectively declare one bear-only rank correlation filter at original center."""
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
        ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range', 'bear_rank_range', '__init__')]
    payload = deepcopy(original['payload'])
    payload['parameters']['mechanism'] = 'BEAR_RANK_ACF20'
    payload['runtime'].update(module='strategy_runtime.strategies.bear_rank_range', qualname='BearRankRange',
        source_files=files, source_sha256=implementation_sha256(files, source_root=SRC / 'strategy_runtime'))
    strategy = StrategyCandidate('S013', 'C6680', payload, SRC / 'strategy_runtime')
    identity = StrategyRuntime().identify(strategy, dependencies=DEPENDENCIES)
    cfg = {'label': 'N0', 'index': 0, 'candidate_id': strategy.candidate_id, 'content_sha256': identity.content_sha256,
        'payload': payload, 'source_directory': 'strategy_runtime', 'background': 'ORIGINAL', 'mechanism': 'BEAR_RANK_ACF20',
        'mode': 'M1', 'existing_identity': None, 'reused': False, 'parent_control': 'B0-TIME'}
    ctx = context(1)
    for identifier in ['C6680', *(f'C{number:04d}' for number in range(6640, 6672))]:
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
    for label, folder in (('runtime', ROOT / '.tmp/ex050-rank-acf-prototype'),
                          ('oracle', ROOT / '.tmp/ex050-rank-acf-oracle'),
                          ('parameter-checks', ROOT / '.tmp/ex050-param-checks')):
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
    plan = {'name': 'S013-EX050-bear-rank-acf20', 'controls': controls, 'configurations': [cfg],
        'control_references': old['control_references'], 'mandate': old['mandate'], 'authorization': old['authorization'],
        'previous_delivery': read(ROOT / 'research/S013/experiments/EX049_20261011/protocols/delivery_reference.json'),
        'effect_reference': effect_ref, 'effect_method_reference': read(PROTOCOLS / 'effect_method_reference.json'),
        'pure_prototype_references': prototypes,
        'hypothesis': 'Rank ordering may reduce amplitude domination of a few returns in bear entry filtering, while preserving original confirmation and other state/path mechanisms. This is a testable estimator replacement, not a claim of smoother paths or equal filter strength.',
        'mechanism': 'Fixed20 original simple daily returns; first19 and last19 separately average-tie ranked. rho=dot(centered ranks)/sqrt(sum squares product); legal negatives retained, threshold equality passes. Zero rank variance/nonfinite required values reject; no abs/clipping/filling/fallback/threshold scaling. Full history before reindex; only eligible bear entry ACF uses rho. Original rawacf1 and all old schema/confirmation/state/ranges/H/exit priorities remain exact.',
        'strongest_counterevidence': 'EX013 removing bear ACF weakened negative-year protection, while EX027 time aggregation and EX028 centering raw ACF failed economic constraints. Spearman removes amplitude and rank can jump; same numeric .1 is not same filtering strength. Original center112 barely passes110. Original regime/H sensitivity untouched; repeated development pool not independent validation.',
        'selection_history': 'After FULL45 mean-momentum center failed. S013 bounded1582 source/metadata duplicate search found no exact rank19-pair entry implementation. EX002 future-label Spearman diagnostic is not used in runtime. One fixed20 mechanism, original numeric center, no rank-window/threshold optimization or units mapping/domain contraction/date exception.',
        'current_authorization': 'User: 授权你可以自主完成目标，无需评审. Existing RSCH S013 stage3 only; no stage4/freeze/PTE/production/newdata/platform/push.',
        'predeclared_selection': 'One new business center/two actual serial-spawn evaluations and2exact old centers. Only if center passes original4economic gates, run32newbusiness/33actual original13full-domain same32joint5% points, reuse original32/coupled32; otherwisezero parameter accounts. Success requires qualifying center and improvement in absolute Q10CAGR/Q90DD AND both center-relative degradations versus originalC2132. No all32qualification veto.',
        'parameter_candidate_reservation': {'first': 6640, 'last': 6671},
        'required_warmup': 'Original parent unchanged; fixed20 original returns require21 closes already covered by original ACF20. Zero required rank variance explicitly refuses. Fixed20 is structural, not searched coordinate.',
        'source_files': {path.relative_to(SRC).as_posix(): file_hash(path) for path in SRC.rglob('*.py')},
        'external_source_files': external,
        'counts': {'new_business_configurations': 1, 'new_evaluations': 2, 'reused_controls': 2},
        'resources': {'max_workers': 8, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'boundaries': 'RSCH S013stage3; no adjacentbatch/newdata/dependency/platform/production/PTE/freeze/stageadvance/merge/tag/push'}
    plan['prospective_pure_verification'] = synthetic(plan, SRC / 'strategy_runtime')
    write(PROTOCOLS / 'plan.json', plan)
    reference = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-bear-rank-acf-plan',
        (PROTOCOLS / 'plan.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'plan_reference.json', reference.to_dict())
    print({'plan': 'DECLARED', 'new_center': 'C6680', 'actual_center_evaluations': 2}, flush=True)


if __name__ == '__main__':
    main()
