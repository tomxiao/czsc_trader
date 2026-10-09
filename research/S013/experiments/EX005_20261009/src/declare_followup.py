"""Prospective factorial controls for the observed cooldown/frequency trade-off."""
from copy import deepcopy
from hashlib import sha256

from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import EXPERIMENT, PROTOCOLS, RUNS, context, read, write, config_hash


def main():
    initial = read(RUNS / 'state_stability_initial.json')
    assert initial['status'] == 'COMPLETE'
    target = PROTOCOLS / 'followup_plan.json'
    if target.exists():
        raise RuntimeError('Published follow-up may not be overwritten')
    indexed = {row['candidate_id']: row for row in initial['rows']}
    assert indexed['C1016']['gates']['negative_buyhold_year_profit']
    assert indexed['C1016']['gates']['return']
    assert not indexed['C1016']['gates']['frequency']
    seen = {row['config_hash'] for row in initial['rows']}
    configurations = []

    def add(bull, bear, direction='both', cooldown=0):
        p = deepcopy(indexed['C1000']['parameters'])
        p['bull']['max_hold'], p['bear']['max_hold'] = bull, bear
        p.update(exit_direction=direction, regime_cooldown=cooldown)
        digest = config_hash(p)
        if digest not in seen:
            seen.add(digest)
            configurations.append({'label': f'hold-{bull}-{bear}-{direction}-cooldown{cooldown}',
                                   'parent': 'C9023', 'parameters': p})

    # Full paired cells for the cooldown hypothesis; baseline cells authenticate opportunity costs.
    for bull in (6, 7, 8):
        for bear in (3, 4):
            for cooldown in (0, 1, 2):
                add(bull, bear, cooldown=cooldown)
    # Independently compare the asymmetric exit at the same hold parameters.
    for bull in (7, 8, 9):
        for bear in (3, 4, 5):
            for direction in ('both', 'bull_to_bear'):
                add(bull, bear, direction=direction)
    plan = {
        'name': 'state_hold_interaction', 'selection_basis': {
            key: {field: indexed[key][field] for field in ('net_cagr', 'closed_trades',
                'annual', 'gates', 'result_hash')} for key in ('C1013', 'C1015', 'C1016', 'C1017')},
        'observed': 'cooldown2 retains 2022/2023 profits and CAGR but misses frequency; shorter signal holding may restore entries',
        'counterclaim': 'shorter holding previously lost 2023 profits; higher frequency may consume fee-saving advantage',
        'attribution': 'paired cooldown0/1/2 cells and both/bull_to_bear cells; full continuous accounts',
        'provisional_boundaries': 'bull hold6..9, bear3..5; expand if useful improvements reach a boundary',
        'method': 'Optuna fixed queue, parameter hash dedup against all initial configurations',
        'initial_result_sha256': sha256((RUNS / 'state_stability_initial.json').read_bytes()).hexdigest(),
        'resources': {'max_workers': 4, 'native_threads_per_worker': 1, 'request_workers': 1, 'seed': 13},
        'known_information': 'same repeatedly reused developer pool; adaptive design disclosed; no holdout',
        'initial_budget': len(configurations), 'configurations': configurations,
    }
    write(target, plan)
    ref = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT,
        'stage3-state-hold-followup-plan', target.read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'followup_reference.json', ref.to_dict())
    print({'published': True, 'configurations': len(configurations)})


if __name__ == '__main__':
    main()
