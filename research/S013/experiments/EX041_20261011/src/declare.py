"""Freeze two targeted bear-TIME reentry direction controls before evaluation."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime, StrategyCandidate, implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, DEPENDENCIES, context, read, write, file_hash


def main():
    assert not (PROTOCOLS / 'plan_references.json').exists()
    prior = read(ROOT / 'research/S013/experiments/EX040_20261011/protocols/plan.json')
    controls = deepcopy(prior['controls'])
    assert [x['label'] for x in controls] == ['B0-TIME', 'B0-MEAN']
    files = ['strategies/' + name + '.py' for name in
             ('range_reversion', 'adaptive_range', 'confirmed_range', 'reentry_confirmed_range', 'acf_range', '__init__')]
    source_hash = implementation_sha256(files, source_root=SRC / 'strategy_runtime')
    configurations = []
    for index, mechanism in enumerate(('MEAN_BEAR_TIME_REENTRY_CLOSE', 'MEAN_BEAR_TIME_REENTRY_BODY')):
        payload = deepcopy(controls[1]['payload'])
        payload['parameters']['mechanism'] = mechanism
        payload['runtime'].update(module='strategy_runtime.strategies.acf_range', qualname='AcfRange',
                                  source_files=files, source_sha256=source_hash)
        strategy = StrategyCandidate('S013', f'C{4800 + index}', payload, SRC / 'strategy_runtime')
        identity = StrategyRuntime().identify(strategy, dependencies=DEPENDENCIES)
        expected = deepcopy(controls[1]['payload']['parameters'])
        expected['mechanism'] = mechanism
        assert payload['parameters'] == expected
        configurations.append({'label': f'N{index}', 'index': index, 'candidate_id': strategy.candidate_id,
            'content_sha256': identity.content_sha256, 'payload': payload, 'source_directory': 'strategy_runtime',
            'background': 'MEAN', 'mechanism': mechanism, 'mode': 'M1', 'existing_identity': None,
            'reused': False, 'parent_control': 'B0-MEAN'})
    ctx = context(1)
    for cfg in configurations:
        assert not (ctx.repository.research_registry_root / f"S013/candidates/{cfg['candidate_id']}.json").exists()
        assert not (ROOT / f"research/S013/assets/candidates/{cfg['candidate_id']}").exists()
    delivery = read(ROOT / 'research/S013/assets/deliveries/CANDIDATES/36/delivery.json')
    names = {'runs-analysis', 'runs-conclusion'}
    diagnosis = {r['name']: r for r in delivery['content']['evidence'] if r['name'] in names}
    assert set(diagnosis) == names
    diagnosis['original-reentry-diagnosis'] = read(ROOT / 'research/S013/experiments/EX033_20261011/protocols/diagnosis_reference.json')
    for value in diagnosis.values():
        ref = EvidenceRef.from_dict(value)
        assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
    plan = {'name': 'S013-EX041-mean-bear-time-reentry-direction', 'controls': controls,
        'configurations': configurations,
        'cells': [{k: cfg[k] for k in ('background', 'mechanism', 'label', 'candidate_id', 'content_sha256')}
                  for cfg in controls + configurations],
        'mandate': prior['mandate'], 'authorization': prior['authorization'],
        'previous_delivery': read(ROOT / 'research/S013/experiments/EX040_20261011/protocols/delivery_reference.json'),
        'diagnosis_references': diagnosis,
        'hypothesis': 'All-bear direction gates reduced frequency and made2023 negative. Apply the same strict price signal only to the already-diagnosed bear TIME exit/reentry context, keeping unrelated eligible entry opportunities. MEAN background has123closed trades and only2024annualDD failure before adding any gate.',
        'mechanism': 'At T gate only flat-before AND originaleligible AND rawregime=bear AND last signal exit reason=time AND last signal exit route=bear. Gate is strict Close_T>previous actual daily Close or Close_T>Open_T. Equality/lower refuses before original score. Every held signal exit remembers active exit route/reason; every successful signal entry on either route clears both. Direction refusal, eligibility failure or raw-regime change while flat does not clear. No waiting reset condition, date exception, price magnitude or new numeric threshold. These are signal-model states, not fills/closed-trade PnL.',
        'preserved': 'Other first/nonTIME/lastbullTIME bear and all bull eligible opportunities preserve original MEAN/confirmation entry; every held loss/trail/range/time/regime exit and H8/H4 original units preserved. All13 original numeric values/full domains active, original T+1 execution/data/cost/benchmark unchanged. Strictpast existing L ACF mean centering preserved.',
        'fixed_new_choices': 'Two fixed categorical direction predicates and last-exit-context scope are new structure outside13numeric coordinates; no numeric calibration. W+2 previous-regime diagnostic has no gate role. MEAN L+21 warmup unchanged; current32 original numeric points have adequate data. No categorical-scope robustness or independent-validation claim.',
        'strongest_counterevidence': 'EX034/35 bearTIME refresh waits destroyed original trade frequency and negative-year profits. EX040 four all-bear price gates had95..106closed (<110) and2023 -1.52%..-2.30%. Narrower scope can still reject profitable recoveries or delay/fail required trades; last-exit state can propagate path/cash effects. Native old-path counts and removed old trade PnL cannot predict profits.',
        'selection_history': 'Repeatedly seen S013 development pool. Choice follows EX033 full reentry diagnosis and all four EX040 failed accounts, not independent validation. Duplicate review of existing S013 plan/prototype metadata found no exact bearTIME last-route+reason scoped entry Close/Body gate; older refresh waits/conditionalTIME exits/bull direction scopes are different. All years and all failed results retained.',
        'predeclared_selection': 'Two new complete business configurations with3actual evaluations (N0 serial/spawn exact duplicate),2old complete backgrounds exact reuse. Only new centers satisfying all4original economic gates receive32business/33actual full13-domain points each, original EX01532 native accounts exact reuse once. No failed center expansion or point replacement. Improvement claim requires a qualifying center with absoluteQ10CAGR/Q90DD and relative degradation improving versus original same-domain baseline; neighbor gates report-only.',
        'counts': {'new_business_configurations': 2, 'new_evaluations': 3, 'reused_controls': 2},
        'resources': {'max_workers': 8, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'boundaries': 'RSCH S013 stage3 only; no adjacent batch bytes/newdata/dependency/platform/freeze/PTE/prod/merge/tag/push.',
        'source_files': {p.relative_to(SRC).as_posix(): file_hash(p) for p in SRC.rglob('*.py')
                         if 'strategy_runtime' in p.parts or p.name in ('direction_oracle.py', 'synthetic_checks.py')},
        'date_contract': 'Every native T-to-valid-session pair checked through same prepared public calendar, full plan.signal_dates, calendar hash and execution-date sequence; signal OHLC ends at final T, no future price for signal features or omitted terminal day.'}
    write(SRC.parent / 'experiment.json', {'type': 'ExperimentRef', 'strategy_id': 'S013', 'experiment_id': EXPERIMENT.experiment_id})
    write(PROTOCOLS / 'plan.json', plan)
    write(PROTOCOLS / 'authorization.json', prior['authorization'])
    write(PROTOCOLS / 'plan_references.json', {p.stem: publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT,
        'mechanism-' + p.stem, p.read_bytes(), 'application/json', 'json')).to_dict()
        for p in (PROTOCOLS / 'plan.json', PROTOCOLS / 'authorization.json')})
    print({'declared': EXPERIMENT.experiment_id, 'new_configurations': 2}, flush=True)


if __name__ == '__main__':
    main()
