"""Prospectively declare one bear-only rawbull exit confirmation at original center."""
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
        ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range', 'exit_confirmed_range', '__init__')]
    payload = deepcopy(original['payload'])
    payload['parameters']['mechanism'] = 'BEAR_EXIT_BULL2'
    payload['runtime'].update(module='strategy_runtime.strategies.exit_confirmed_range', qualname='ExitConfirmedRange',
        source_files=files, source_sha256=implementation_sha256(files, source_root=SRC / 'strategy_runtime'))
    strategy = StrategyCandidate('S013', 'C5980', payload, SRC / 'strategy_runtime')
    identity = StrategyRuntime().identify(strategy, dependencies=DEPENDENCIES)
    cfg = {'label': 'N0', 'index': 0, 'candidate_id': strategy.candidate_id, 'content_sha256': identity.content_sha256,
        'payload': payload, 'source_directory': 'strategy_runtime', 'background': 'ORIGINAL', 'mechanism': 'BEAR_EXIT_BULL2',
        'mode': 'M1', 'existing_identity': None, 'reused': False, 'parent_control': 'B0-TIME'}
    ctx = context(1)
    for identifier in ['C5980', *(f'C{number:04d}' for number in range(5940, 5972))]:
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
    for label, folder in (('runtime', ROOT / '.tmp/ex048-bear-exit-prototype'),
                          ('oracle', ROOT / '.tmp/ex048-bear-exit-oracle'),
                          ('parameter-checks', ROOT / '.tmp/ex048-param-checks')):
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
    plan = {'name': 'S013-EX048-bear-only-two-rawbull-regime-exit', 'controls': controls, 'configurations': [cfg],
        'control_references': old['control_references'], 'mandate': old['mandate'], 'authorization': old['authorization'],
        'previous_delivery': read(ROOT / 'research/S013/experiments/EX047_20261011/protocols/delivery_reference.json'),
        'effect_reference': effect_ref, 'effect_method_reference': read(PROTOCOLS / 'effect_method_reference.json'),
        'pure_prototype_references': prototypes,
        'hypothesis': 'Do not force a short bear rebound holding to exit on its first single rawbull, while retaining immediate bull-to-bear downside exit and original range/time maximum. This may reduce forced-exit timing differences under regimeW/threshold shifts. It is distinct from already failed bull-only2/3 exit delay and global3 majority.',
        'mechanism': 'Held bear regime exit requires current AND previous full-daily rawbull; held bull current rawbear remains immediate. Complete daily causal raw momentum Close_t/Close_t-W minus1 >= original return threshold, equality bull. Entry classification/range/ACF20/score and all13 numeric parameters unchanged. loss>trail>range>time>regime, maxhold original1..60 days. No entry-day forced exit; no state wait latch/filled-price anchor/category. switchFalse disables this regime exit as original.',
        'strongest_counterevidence': 'Original32 one-coordinate diagnostic shows H and ACF also matter, which this exit delay does not fix. Prior delayed bull exits/globalmajority failed frequency and negative-benchmark-year profit. Original center112 closed barely exceeds110; delay can reduce frequency or extend losses. Original heldbear cannot survive previous rawbull by design, so every old finalbear regime exit is a first-rawbull event; 17center/570pooled old conditional effects describe this endogenous rule, not a profit edge or revised policy trade count. The same repeated S013 development pool is not independent evidence.',
        'selection_history': 'After FULL43 original33 complete13coordinate forward/reverse conditional diagnosis and duplicate rawmedian3 rejection. One new fixed2 bear-only structure, original numeric center, no H/threshold/window/date selection; all negative experiments retained. Existing C4900 is historical multi-structure counterevidence, not an isolated fixed2 control; only versusC2132 isolates exit change.',
        'predeclared_selection': 'Only one new center1business/2actual serial-spawn,2oldcenters reused. If new four original economic gates pass, run32newbusiness/33actual at exact original13full domains/numeric centers/same32joint5% coordinates, reuseoriginal32/coupled32 exactly; otherwisezero params. Goal requires qualifying center and improvement in absolute Q10CAGR/Q90DD AND both center-relative degradations versusC2132. No all32qualification veto, dropped/narrowed coordinate or unit normalization.',
        'parameter_candidate_reservation': {'first': 5940, 'last': 5971},
        'required_warmup': 'max(original parent, regimeW+2), actual complete preceding daily momentum, no fill; center180. Fixed2 is a categorical structure, no new numeric coordinate.',
        'source_files': {path.relative_to(SRC).as_posix(): file_hash(path) for path in SRC.rglob('*.py')},
        'external_source_files': external,
        'counts': {'new_business_configurations': 1, 'new_evaluations': 2, 'reused_controls': 2},
        'resources': {'max_workers': 8, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'boundaries': 'RSCH S013stage3; no adjacentbatch/newdata/dependency/platform/production/PTE/freeze/stageadvance/merge/tag/push'}
    plan['prospective_pure_verification'] = synthetic(plan, SRC / 'strategy_runtime')
    write(PROTOCOLS / 'plan.json', plan)
    reference = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-bear-only-exit-plan',
        (PROTOCOLS / 'plan.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'plan_reference.json', reference.to_dict())
    print({'plan': 'DECLARED', 'new_center': 'C5980', 'actual_center_evaluations': 2}, flush=True)


if __name__ == '__main__':
    main()
