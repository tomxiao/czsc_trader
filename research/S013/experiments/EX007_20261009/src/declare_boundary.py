"""Adaptive complementary-score boundary and isolated holding contrasts."""
from copy import deepcopy
from hashlib import sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import SOURCE, PROTOCOLS, RUNS, EXPERIMENT, context, parent_parameters, write, read, config_hash


def main():
    initial = read(RUNS / 'cost_confirmation_initial.json')
    assert initial['status'] == 'COMPLETE'
    path = PROTOCOLS / 'boundary_plan.json'
    assert not path.exists(), 'published plans are immutable'
    base = read(PROTOCOLS / 'initial_plan.json')['configurations'][0]['parameters']
    seen = {config_hash(row['parameters']) for row in initial['rows']}
    configs = []

    def add(parameters, label):
        digest = config_hash(parameters)
        assert digest not in seen
        seen.add(digest)
        configs.append({'parent': 'C2308', 'parameters': parameters, 'label': label})

    for threshold in (-.45, -.4, -.35, -.325, -.275, -.25):
        for application in ('all_entries', 'ordinary_entries'):
            p = deepcopy(base)
            p['opportunity_confirmation'].update(enabled=True, threshold=threshold, application=application)
            add(p, f'all-bull-{threshold}-{application}-boundary')
    for threshold in (-.4, -.35):
        p = deepcopy(base)
        p['opportunity_confirmation'].update(enabled=True, profile='acf_volume',
            weighting='EQUAL_FEATURES', threshold=threshold)
        add(p, f'acf-volume-bull-{threshold}-ordinary-boundary')
    for route, hold in (('bull', 7), ('bear', 3)):
        p = deepcopy(parent_parameters('C2308'))
        p[route]['max_hold'] = hold
        add(p, f'isolated-{route}-max-hold-{hold}-without-extra-score')
    plan = {'name': 'cost_confirmation_boundary', 'configurations': configs,
        'observed_basis': [{'candidate_id': row['candidate_id'], 'net_cagr': row['net_cagr'],
            'closed_trades': row['closed_trades'], 'negative_year_min_profit': row['negative_year_min_profit'],
            'qualified': row['qualified']} for row in initial['rows']],
        'basis': 'all-feature bull confirmation at -0.3 raises CAGR with exactly 110 closed cycles but does not thicken the weakest negative-year margin; raw ACF overfilters. Expand the loose threshold edge and inspect its neighborhood; acf-volume -0.3 ordinary misses frequency by one; isolate the two initial holding controls.',
        'source_files': {p.relative_to(SOURCE).as_posix(): sha256(p.read_bytes()).hexdigest()
                         for p in SOURCE.rglob('*.py')},
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'known_information': 'adaptive continuation after viewing all initial S013 results; entire developer pool previously seen',
        'eligibility': 'unchanged four gates at 10bp; neighborhoods and costs diagnostic only',
        'exit_control': 'all entries retain original exits except two explicitly isolated max-hold contrasts; no fixed cooldown',
        'limits': 'these bounded contrasts do not exhaust possible score weights, normalization windows or mechanisms'}
    write(path, plan)
    ref = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT,
        'cost-confirmation-boundary-plan', path.read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'boundary_plan_reference.json', ref.to_dict())
    print({'published': True, 'configurations': len(configs)}, flush=True)


if __name__ == '__main__':
    main()
