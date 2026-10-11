"""Declare one segment-scoped category intervention before any native evaluation."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime, StrategyCandidate, implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, DEPENDENCIES, context, read, write, file_hash


def main():
    assert not (PROTOCOLS / 'plan_reference.json').exists()
    assert read(SRC.parent / 'experiment.json') == EXPERIMENT.to_dict()
    old = read(ROOT / 'research/S013/experiments/EX043_20261011/protocols/plan.json')
    original = deepcopy(next(row for row in old['controls'] if row['label'] == 'B0-TIME'))
    coupled = deepcopy(next(row for row in old['configurations'] if row['label'] == 'N0'))
    coupled.update(label='B0-COUPLED', reused=True, reuse_from='EX043_20261011', reuse_label='N0',
                   source_directory='../../EX043_20261011/src/strategy_runtime')
    files = ['strategies/' + name + '.py' for name in
             ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range', 'mechanism_range', '__init__')]
    payload = deepcopy(coupled['payload'])
    payload['parameters']['mechanism'] = 'MEAN_BEAR_TIME_BELOW_SEGMENT_CLOSE'
    payload['runtime'].update(module='strategy_runtime.strategies.mechanism_range', qualname='MechanismRange',
        source_files=files, source_sha256=implementation_sha256(files, source_root=SRC / 'strategy_runtime'))
    strategy = StrategyCandidate('S013', 'C5600', payload, SRC / 'strategy_runtime')
    identity = StrategyRuntime().identify(strategy, dependencies=DEPENDENCIES)
    expected = deepcopy(coupled['payload']['parameters'])
    expected['mechanism'] = 'MEAN_BEAR_TIME_BELOW_SEGMENT_CLOSE'
    assert payload['parameters'] == expected
    cfg = {'label': 'N0', 'index': 0, 'candidate_id': strategy.candidate_id, 'content_sha256': identity.content_sha256,
        'payload': payload, 'source_directory': 'strategy_runtime', 'background': 'COUPLED', 'mechanism': expected['mechanism'],
        'mode': 'M1', 'existing_identity': None, 'reused': False, 'parent_control': 'B0-COUPLED'}
    ctx = context(1)
    assert not (ctx.repository.research_registry_root / 'S013/candidates/C5600.json').exists()
    assert not (ROOT / 'research/S013/assets/candidates/C5600').exists()
    controls = [original, coupled]
    prior_refs = read(ROOT / 'research/S013/assets/runs/EX043_20261011/account_references.json')
    refs = {'B0-TIME': prior_refs['B0-TIME'], 'B0-COUPLED': prior_refs['N0']}
    for reference in refs.values():
        ref = EvidenceRef.from_dict(reference)
        assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
    diagnosis_refs = read(PROTOCOLS / 'context_diagnosis_references.json')
    for reference in diagnosis_refs.values():
        ref = EvidenceRef.from_dict(reference)
        assert ref.experiment == EXPERIMENT and file_hash(ref.resolve(ROOT)) == ref.sha256
    diagnosis = read(EvidenceRef.from_dict(diagnosis_refs['diagnosis']).resolve(ROOT))
    assert diagnosis['status'] == 'PASS' and diagnosis['new_account_evaluations'] == 0
    assert len(diagnosis['accounts']) == 66
    pure = read(ROOT / '.tmp/ex046-synthetic/focused.json')
    assert pure['status'] == 'PURE_PASS' and pure['new_account_evaluations'] == pure['new_account_preparations'] == 0
    for name, digest in pure['source_files'].items():
        assert file_hash(SRC / name) == digest
    plan = {'name': 'S013-EX046-bear-time-category-market-segment-context', 'controls': controls, 'configurations': [cfg],
        'cells': [{key: row[key] for key in ('label', 'candidate_id', 'content_sha256', 'mechanism', 'background')} for row in controls + [cfg]],
        'control_references': refs, 'mandate': old['mandate'], 'authorization': old['authorization'],
        'previous_delivery': read(ROOT / 'research/S013/experiments/EX045_20261011/protocols/delivery_reference.json'),
        'diagnosis_reference': diagnosis_refs['diagnosis'], 'diagnosis_source_reference': diagnosis_refs['source-history'],
        'hypothesis': 'A price-category gate tied to the last bear TIME episode can survive an intervening rawbull regime. Limiting only category memory to a continuous rawbear segment may reduce inherited state sensitivity without new entry/exit parameters. Existing66 paths show coupled135/fixed137 incremental refusals, each center3; no counterfactual profit inference.',
        'mechanism': 'Only MEAN_BEAR_TIME_BELOW_SEGMENT_CLOSE: flat current rawbull clears last_exit_category before decision metadata/eligibility; final held bear TIME on current rawbull keeps reason=time/route=bear but category=None. Both operations retain last_exit_reason/route/confirmation_exit_context. Any entry clears all3 as before. Coupled strictpast actual-L bear ACF baseline, original score, strictClose direction, original H/exit priorities and all13 coordinates unchanged.',
        'fixed_structural_choice': 'Category lifetime follows current causal rawregime segment; no dates/year exceptions/new threshold/window search/physical holding-age change. This is a categorical mechanism outside original13numeric domains, not removal or narrowing of coordinates.',
        'strongest_counterevidence': 'Expired context describes chronology, not economic harm. Original C2132 has no such added category memory and is still parameter-sensitive. Coupled center is weaker and absolute tails worse than original; fixed120 made both tails worse. New expiry introduces regime-threshold-driven memory changes and may remove profitable protection. Center affected only3 old-path refusals (2020 twice/2026 once), none direct2023/2024; this may leave broad sensitivity untouched. Shared66 paths are dependent and repeatedly selected on S013 development data.',
        'center_expectation': 'Same path-independent raw features/score/baseline and all numeric parameters as coupled center; state and complete economic accounts may differ and must be independently evaluated. New identity must not reuse prior center account.',
        'predeclared_selection': 'One new center business/two actual serial+spawn; reuse original/coupled2 exactnativecenters. Only if new center4originalgates pass, run32newbusiness/33actual at original13full domains/numeric centers/identical32 joint5%coordinates. Reuseoriginal32/coupled32 exactly. No point/coordinate removal/domain narrowing/replacement/diagnostic veto. Goal requires qualifying center and better absoluteQ10return/Q90DD AND both relative degradations vs original.',
        'parameter_candidate_reservation': 'C3900..C3931',
        'counts': {'new_business_configurations': 1, 'new_evaluations': 2, 'reused_controls': 2},
        'resources': {'max_workers': 8, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'required_warmup': 'Exactly coupled native requirements: actual confirmationL+21 and parent/causal regime feature history; no fixed120 baseline, fallback or shortened history.',
        'source_files': {p.relative_to(SRC).as_posix(): file_hash(p) for p in SRC.rglob('*.py')
                         if 'strategy_runtime' in p.parts or p.name in ('direction_oracle.py', 'synthetic_checks.py',
                            'declare.py', 'precheck.py', 'analyze.py', 'publish_accounts.py',
                            'common.py', 'account_reference.py', 'ledger_reference.py', 'analysis_reference.py')},
        'external_source_files': {f'research/S013/experiments/EX043_20261011/src/{name}': file_hash(ROOT / f'research/S013/experiments/EX043_20261011/src/{name}')
                                  for name in ('direction_oracle.py', 'strategy_runtime/strategies/mechanism_range.py', 'analysis_reference_v2.py')},
        'prospective_pure_verification': pure,
        'selection_history': 'Full EX04532 negative result and zero-new66 exact original-path context diagnosis completed before selection; no point/year profit search or independent market validation.',
        'boundaries': 'RSCH S013stage3; no adjacentbatch/newdata/dependencies/platform/freeze/PTE/prod/merge/tag/push.'}
    write(PROTOCOLS / 'plan.json', plan)
    reference = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-segment-context-plan',
        (PROTOCOLS / 'plan.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'plan_reference.json', reference.to_dict())
    print({'plan': 'DECLARED', 'new_centers': 1, 'actual_center_evaluations': 2}, flush=True)


if __name__ == '__main__':
    main()
