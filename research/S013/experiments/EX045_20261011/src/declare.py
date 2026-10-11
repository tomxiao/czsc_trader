"""Prospective fixed120 baseline split, same active13 numeric coordinates."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime, StrategyCandidate, implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, DEPENDENCIES, context, read, write, file_hash


def main():
    assert not (PROTOCOLS / 'plan_reference.json').exists()
    old = read(ROOT / 'research/S013/experiments/EX043_20261011/protocols/plan.json')
    original = deepcopy(next(row for row in old['controls'] if row['label'] == 'B0-TIME'))
    coupled = deepcopy(next(row for row in old['configurations'] if row['label'] == 'N0'))
    coupled.update(label='B0-COUPLED', reused=True, reuse_from='EX043_20261011', reuse_label='N0',
                   source_directory='../../EX043_20261011/src/strategy_runtime')
    files = ['strategies/' + name + '.py' for name in
             ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range', 'mechanism_range', '__init__')]
    payload = deepcopy(coupled['payload'])
    payload['parameters']['mechanism'] = 'MEAN_FIXED120_BEAR_TIME_BELOW_CLOSE'
    payload['runtime'].update(module='strategy_runtime.strategies.mechanism_range', qualname='MechanismRange',
        source_files=files, source_sha256=implementation_sha256(files, source_root=SRC / 'strategy_runtime'))
    strategy = StrategyCandidate('S013', 'C5300', payload, SRC / 'strategy_runtime')
    identity = StrategyRuntime().identify(strategy, dependencies=DEPENDENCIES)
    expected = deepcopy(coupled['payload']['parameters'])
    expected['mechanism'] = 'MEAN_FIXED120_BEAR_TIME_BELOW_CLOSE'
    assert payload['parameters'] == expected
    cfg = {'label': 'N0', 'index': 0, 'candidate_id': strategy.candidate_id, 'content_sha256': identity.content_sha256,
        'payload': payload, 'source_directory': 'strategy_runtime', 'background': 'COUPLED', 'mechanism': expected['mechanism'],
        'mode': 'M1', 'existing_identity': None, 'reused': False, 'parent_control': 'B0-COUPLED'}
    ctx = context(1)
    assert not (ctx.repository.research_registry_root / 'S013/candidates/C5300.json').exists()
    assert not (ROOT / 'research/S013/assets/candidates/C5300').exists()
    controls = [original, coupled]
    prior_refs = read(ROOT / 'research/S013/assets/runs/EX043_20261011/account_references.json')
    refs = {'B0-TIME': prior_refs['B0-TIME'], 'B0-COUPLED': prior_refs['N0']}
    for reference in refs.values():
        ref = EvidenceRef.from_dict(reference)
        assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
    diagnosis = read(ROOT / 'research/S013/assets/deliveries/CANDIDATES/40/delivery.json')
    evidence = next(ref for ref in diagnosis['content']['evidence'] if ref['name'] == 'complete-native-input-state')
    ref = EvidenceRef.from_dict(evidence)
    assert file_hash(ref.resolve(ROOT)) == ref.sha256
    pure = read(ROOT / '.tmp/ex045-synthetic/focused.json')
    assert pure['status'] == 'PURE_PASS' and pure['new_account_evaluations'] == 0
    plan = {'name': 'S013-EX045-fixed120-bear-acf-baseline-split', 'controls': controls, 'configurations': [cfg],
        'cells': [{key: row[key] for key in ('label', 'candidate_id', 'content_sha256', 'mechanism', 'background')} for row in controls + [cfg]],
        'control_references': refs, 'mandate': old['mandate'], 'authorization': old['authorization'],
        'previous_delivery': read(ROOT / 'research/S013/experiments/EX044_20261011/protocols/delivery_reference.json'),
        'diagnosis_reference': evidence,
        'hypothesis': 'Original confirmationL also moves strictpast bearACF mean. Splitting that baseline to original-center120 may reduce extra sensitivity while original scoreL remains active. EX044 one-step probe changed36fullstates/14of33native paths, so mechanism is testable but no profit implication.',
        'mechanism': 'Only new MEAN_FIXED120_BEAR_TIME_BELOW_CLOSE uses strictpast120mean raw20ACF; original confirmation score uses actual confirmation.lookback and all13coordinates active. Original eligible rawbear after retained BELOW-category finalbearTIME gets strictClose>previousClose gate exactly as EX043N0. Original holding H/range/regime priority and entry/exit context retained.',
        'fixed_structural_choice': '120 is original center L, predeclared, no grid or year exception. Fixed baseline window outside13 numeric domain; scoreL remains original coordinate and threshold units remain centered ACF. This is distinct structural mechanism, not a narrowed old coordinate domain.',
        'strongest_counterevidence': 'EX043 N0 center qualifies4gates but Q10CAGR1.7843/Q90DD34.6163 worse original5.8974/30.5044. EX044 about50% actualnewtarget differences reproduced by priorstate alone and9397physical-resynced days retain differentmemory; fixed window may leave dominant state sensitivity untouched. Its36probe nextstates cannot predict new financial path.',
        'center_expectation': 'At actual center L120 both baseline formulas exact same. Authenticate new distinct runtime identity and own public native evaluation; compare full causal signal/features and economic ledgers to coupled center. Do not relabel prior account as new.',
        'predeclared_selection': 'One new center business/two actual serial+spawn; original/coupled2 exactnativecenter reuse. Only if center4originalgates pass then32newbusiness/33actual matched original13full-domain points. Reuseoriginal32/coupled32 exactly. No coordinate omission/domain narrowing/point replacement/diagnostic veto. Goal requires qualifying center and better absoluteQ10return/Q90DD AND both relative degradations vsoriginal.',
        'parameter_candidate_reservation': 'C3800..C3831',
        'counts': {'new_business_configurations': 1, 'new_evaluations': 2, 'reused_controls': 2},
        'resources': {'max_workers': 8, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'required_warmup': 'max(parent,141,regimeW+2); original actual score L needs own L+20 preserved. No shortened baseline or data fallback.',
        'source_files': {p.relative_to(SRC).as_posix(): file_hash(p) for p in SRC.rglob('*.py')
                         if 'strategy_runtime' in p.parts or p.name in ('direction_oracle.py', 'synthetic_checks.py',
                            'declare.py', 'precheck.py', 'analyze.py', 'publish_accounts.py',
                            'common.py', 'account_reference.py', 'ledger_reference.py', 'analysis_reference.py')},
        'external_source_files': {f'research/S013/experiments/EX043_20261011/src/{name}': file_hash(ROOT / f'research/S013/experiments/EX043_20261011/src/{name}')
                                  for name in ('direction_oracle.py', 'strategy_runtime/strategies/mechanism_range.py', 'analysis_reference_v2.py')},
        'prospective_pure_verification': pure,
        'selection_history': 'Repeated S013 development pool after zero-new66 fullstate diagnosis. No independent sample, actual economic control follow original complete panel, no selecting14changedpaths only.',
        'boundaries': 'RSCH S013stage3; no adjacentbatch/newdata/dependencies/platform/freeze/PTE/prod/merge/tag/push.'}
    write(SRC.parent / 'experiment.json', {'type': 'ExperimentRef', 'strategy_id': 'S013', 'experiment_id': EXPERIMENT.experiment_id})
    write(PROTOCOLS / 'plan.json', plan)
    reference = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-fixed120-baseline-plan',
        (PROTOCOLS / 'plan.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'plan_reference.json', reference.to_dict())
    print({'plan': 'DECLARED', 'new_centers': 1, 'actual_center_evaluations': 2}, flush=True)


if __name__ == '__main__':
    main()
