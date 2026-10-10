"""Freeze four original-confirmation bear-entry direction contrasts."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime, StrategyCandidate, implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, DEPENDENCIES, context, read, write, file_hash


def main():
    assert not (PROTOCOLS / 'plan_references.json').exists()
    old = read(ROOT / 'research/S013/experiments/EX038_20261011/protocols/plan.json')
    controls = deepcopy(old['controls'][:2])
    assert [x['label'] for x in controls] == ['B0-TIME', 'B0-MEAN']
    files = ['strategies/' + name + '.py' for name in
             ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range', 'acf_range', '__init__')]
    source_sha = implementation_sha256(files, source_root=SRC / 'strategy_runtime')
    configurations = []
    for index, (background, mechanism) in enumerate((('RAW', 'RAW_BEAR_CLOSE'), ('RAW', 'RAW_BEAR_BODY'),
                                                    ('MEAN', 'MEAN_BEAR_CLOSE'), ('MEAN', 'MEAN_BEAR_BODY'))):
        parent = controls[0 if background == 'RAW' else 1]
        payload = deepcopy(parent['payload'])
        payload['parameters']['mechanism'] = mechanism
        payload['runtime'].update(module='strategy_runtime.strategies.acf_range', qualname='AcfRange',
                                  source_files=files, source_sha256=source_sha)
        strategy = StrategyCandidate('S013', f'C{5200 + index}', payload, SRC / 'strategy_runtime')
        identity = StrategyRuntime().identify(strategy, dependencies=DEPENDENCIES)
        expected = deepcopy(parent['payload']['parameters'])
        expected['mechanism'] = mechanism
        assert payload['parameters'] == expected
        configurations.append({'label': f'N{index}', 'index': index, 'background': background, 'mechanism': mechanism,
            'candidate_id': strategy.candidate_id, 'content_sha256': identity.content_sha256, 'payload': payload,
            'source_directory': 'strategy_runtime', 'mode': 'M1', 'existing_identity': None, 'reused': False,
            'parent_control': parent['label']})
    ctx = context(1)
    for cfg in configurations:
        assert not (ctx.repository.research_registry_root / f"S013/candidates/{cfg['candidate_id']}.json").exists()
        assert not (ROOT / f"research/S013/assets/candidates/{cfg['candidate_id']}").exists()
    previous = read(ROOT / 'research/S013/experiments/EX039_20261011/protocols/delivery_reference.json')
    delivery = read(ROOT / 'research/S013/assets/deliveries/CANDIDATES/35/delivery.json')
    names = {'native-direction', 'research-decision'}
    diagnosis = {r['name']: r for r in delivery['content']['evidence'] if r['name'] in names}
    assert set(diagnosis) == names
    for ref_value in diagnosis.values():
        ref = EvidenceRef.from_dict(ref_value)
        assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
    plan = {'name': 'S013-EX040-bear-entry-direction-minimal-factorial', 'controls': controls,
        'configurations': configurations,
        'cells': [{k: cfg[k] for k in ('background', 'mechanism', 'label', 'candidate_id', 'content_sha256')}
                  for cfg in controls + configurations],
        'mandate': old['mandate'], 'authorization': old['authorization'], 'previous_delivery': previous,
        'diagnosis_references': diagnosis,
        'hypothesis': 'Existing bear ACF+confirmation often permits entry before a visible same-day bounce. Require a strict close direction only at original flat eligible bear entries; compare raw and mean-centered ACF backgrounds without changing held exits.',
        'mechanism': 'T raw regime=bear AND flat-before AND original range/ACF/momentum eligible. Additional gate is Close_T>Close_previous_actual_daily_session or Close_T>Open_T. Equal and lower prices reject as entry_direction_rejected before original score refusal. Bull entries and all held loss/trail/range/time/regime exits preserve original semantics. No wait, stop, risk exit, boundary-only exception or date rule. Original confirmation preserved.',
        'preserved': 'All13 original numeric center values and full domains active; RAW uses original rawACF20, MEAN strictpast existing confirmation-lookback mean centering from EX028. Original H8/H4 signal-session units, binary target/T+1 execution/data/cost/benchmark unchanged. No extra bullish BODY background.',
        'fixed_new_choices': 'Two categorical strict direction predicates are new structure outside original13 numeric coordinates; no magnitude threshold introduced. Previous-regime diagnostic needs W+2 history but does not affect these rawbear gates; actual existing full-domain32 points retain adequate original warmup. MEAN L+21 baseline need preserved. No stability claim for untested categorical alternatives.',
        'strongest_counterevidence': 'Original112 closed trades have only2 above110 requirement;2023 profit+.2841%. Native original57bear entries have only23CloseUP/22BodyUP, MEAN68have29/28. Restriction can remove recoveries, alter future opportunity/state/cash and destroy frequency. Prior bull-price gates failed110 requirement. Old-path refusal counts are not new profits.',
        'selection_history': 'Repeatedly seen S013 development pool; all EX039 years and counts seen before this selection. EX037/38 six exit centers failed, stop width calibration. Four fixed bear direction rules had no exact prior native accounts in S013 metadata/source duplicate review. No independent validation.',
        'predeclared_selection': 'Four new business accounts with5actual evaluations (N0 exact serial/spawn duplicate),2old controls exact reuse. Only new centers satisfying all4original gates receive32business/33actual complete original13-domain points each; original EX01532 native points exact reuse once. No unqualified expansion/replacement/extra gate. Center qualification plus absoluteQ10CAGR/Q90DD and relative degradation jointly improve before claiming goal achieved.',
        'counts': {'new_business_configurations': 4, 'new_evaluations': 5, 'reused_controls': 2},
        'resources': {'max_workers': 8, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'boundaries': 'RSCH S013 stage3 only; no adjacent batch bytes/newdata/dependency/platform/freeze/PTE/prod/merge/tag/push.',
        'source_files': {p.relative_to(SRC).as_posix(): file_hash(p) for p in SRC.rglob('*.py')
                         if 'strategy_runtime' in p.parts or p.name in ('direction_oracle.py', 'synthetic_checks.py')}}
    write(SRC.parent / 'experiment.json', {'type': 'ExperimentRef', 'strategy_id': 'S013', 'experiment_id': EXPERIMENT.experiment_id})
    write(PROTOCOLS / 'plan.json', plan)
    write(PROTOCOLS / 'authorization.json', old['authorization'])
    write(PROTOCOLS / 'plan_references.json', {p.stem: publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT,
        'mechanism-' + p.stem, p.read_bytes(), 'application/json', 'json')).to_dict()
        for p in (PROTOCOLS / 'plan.json', PROTOCOLS / 'authorization.json')})
    print({'declared': EXPERIMENT.experiment_id, 'new_configurations': 4}, flush=True)


if __name__ == '__main__':
    main()
