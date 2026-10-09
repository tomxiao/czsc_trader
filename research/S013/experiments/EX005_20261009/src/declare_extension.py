"""Small boundary and interaction check before closing the turnover mechanism."""
from copy import deepcopy

from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import EXPERIMENT, PROTOCOLS, RUNS, context, read, write


def main():
    assert read(RUNS / 'state_hold_interaction.json')['status'] == 'COMPLETE'
    path = PROTOCOLS / 'extension_plan.json'
    if path.exists():
        raise RuntimeError('Published boundary checks may not be overwritten')
    indexed = {row['candidate_id']: row for row in read(RUNS / 'state_stability_initial.json')['rows']}
    configurations = []
    for direction, cooldown in (('both', 4), ('both', 5), ('bull_to_bear', 1), ('bull_to_bear', 2)):
        p = deepcopy(indexed['C1000']['parameters'])
        p.update(exit_direction=direction, regime_cooldown=cooldown)
        configurations.append({'label': f'final-{direction}-cooldown{cooldown}',
                               'parent': 'C9023', 'parameters': p})
    plan = {'name': 'state_cooldown_extension',
        'purpose': 'check the upper cooldown boundary and the untested direction-by-cooldown interaction',
        'basis': 'cooldown3 increased2023profit but lost2022profit/CAGR; cooldown2 is a frequency-limited frontier; risk-only exit remained qualified',
        'counterclaim': 'additional cooling loses protective/rebound timing and frequency; interaction may not combine individual benefits',
        'method': 'Optuna fixed queue, four distinct configurations, unchanged data/source/execution',
        'resources': {'max_workers': 4, 'native_threads_per_worker': 1, 'request_workers': 1, 'seed': 13},
        'initial_budget': 4, 'configurations': configurations}
    write(path, plan)
    ref = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT,
        'stage3-cooldown-boundary-plan', path.read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'extension_reference.json', ref.to_dict())
    print({'published': True, 'configurations': 4})


if __name__ == '__main__':
    main()
