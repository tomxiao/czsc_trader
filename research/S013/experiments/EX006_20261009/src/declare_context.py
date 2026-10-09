"""Declare targeted reentry, lower-threshold, raw-unit and block-weight contrasts."""
from copy import deepcopy
from hashlib import sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import SOURCE, EXPERIMENT, PROTOCOLS, RUNS, context, parent_parameters, read, write, config_hash


def main():
    initial_path = RUNS / 'confirmation_initial.json'
    initial = read(initial_path)
    if initial['status'] != 'COMPLETE':
        raise RuntimeError('initial search must be complete before this adaptive declaration')
    if (PROTOCOLS / 'context_plan.json').exists():
        raise RuntimeError('prospective context plan already exists')
    assert read(RUNS / 'context_synthetic_check.json')['status'] == 'PASS'
    assert read(RUNS / 'raw_volume_scope_preparation.json')['status'] == 'PASS'
    configs, seen = [], set()

    def add(parent='C9023', profile='all', threshold=-.2, gate='all', basis='ADJUSTED',
            lookback=120, weighting='EQUAL_FEATURES', scope='both'):
        p = deepcopy(parent_parameters(parent))
        p['confirmation'] = {'enabled': True, 'profile': profile, 'threshold': float(threshold),
                             'orientation': 1, 'scope': scope, 'lookback': lookback}
        p['context'] = {'entry_gate': gate, 'volume_basis': basis, 'weighting': weighting}
        digest = config_hash(p)
        if digest not in seen:
            seen.add(digest)
            configs.append({'parent': parent, 'parameters': p,
                'label': f'{parent}-{gate}-{profile}-{threshold}-{basis}-n{lookback}-{weighting}-{scope}'})
    add()  # C2100 must exactly reproduce old-source C2018.
    for profile in ('all', 'turnover'):
        for threshold in (-.3, -.2, 0., .1):
            for gate in ('all', 'regime_reentry'):
                add(profile=profile, threshold=threshold, gate=gate)
    for profile in ('all', 'volume'):
        for threshold in (-.2, 0.):
            for gate in ('all', 'regime_reentry'):
                for basis in ('ADJUSTED', 'RAW'):
                    add(profile=profile, threshold=threshold, gate=gate, basis=basis, lookback=40)
    for threshold in (-.2, 0.):
        for gate in ('all', 'regime_reentry'):
            add(threshold=threshold, gate=gate, weighting='EQUAL_BLOCKS')
    for profile in ('all', 'turnover'):
        for threshold in (-.2, 0., .1):
            add(parent='C9018', profile=profile, threshold=threshold, gate='regime_reentry')
    for scope in ('bull', 'bear'):
        for threshold in (-.2, 0.):
            add(threshold=threshold, gate='regime_reentry', scope=scope)
    rows = initial['rows']
    basis_ids = ('C2018', 'C2055', 'C2059', 'C2076')
    plan = {'name': 'confirmation_context',
        'selection_basis': [row for row in rows if row['candidate_id'] in basis_ids],
        'initial_results_sha256': sha256(initial_path.read_bytes()).hexdigest(),
        'observed': 'loose composite gates qualify but margin remains thin; stronger amount confirmation raises margin and loses frequency',
        'mechanism_basis': 'prior S013 state-exit churn attribution; target only state reentry, without calendar waiting',
        'context_semantics': 'last exit reason==regime persists until next signal entry; score reevaluated daily; all other entries preserve original rules',
        'raw_units': '40-session paired normalization, existing raw asset has 60 warmup days; daily HFQ-volume*HFQ-close/raw-close must equal raw Volume',
        'raw_preparation': read(RUNS / 'raw_volume_scope_preparation.json'),
        'local_preparation': 'exact scope from existing authenticated S013 asset through existing offline preparation pattern; no new external provider/data',
        'block_weighting': 'ACF .5, amount .25, volume .25; compare equal-feature thirds without fitting weights',
        'bounds': 'threshold-.3 lower extension; source semantic domains remain fixed; inspect useful boundary improvements',
        'controls': 'C2100 full account exact vs C2018; all-entry/state-reentry pairs, raw/adjusted-volume pairs, block weights, route-specific gates',
        'prechecked_controls': ['C2100'], 'precheck_file': 'context_precheck.json',
        'configurations': configs, 'original_four_gates_unchanged': True,
        'scope': 'stage3 only; 0 fixed cooldown; no platform/PTE/release action',
        'known_information': 'adaptive same-pool extension; no independent validation; S007 expression only used as structure',
        'source_files': {p.relative_to(SOURCE).as_posix(): sha256(p.read_bytes()).hexdigest() for p in SOURCE.rglob('*.py')},
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1, 'seed': 13}}
    write(PROTOCOLS / 'context_plan.json', plan)
    ref = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT, 'buy-confirmation-context-plan',
        (PROTOCOLS / 'context_plan.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'context_plan_reference.json', ref.to_dict())
    print({'context_plan_published': True, 'configurations': len(configs)}, flush=True)


if __name__ == '__main__':
    main()
