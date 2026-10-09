"""Prospective follow-up for the stronger cooldown-five annual-profit frontier."""
from copy import deepcopy

from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import EXPERIMENT, PROTOCOLS, context, write, config_hash
from diagnose import rows


def main():
    target = PROTOCOLS / 'recovery_plan.json'
    if target.exists():
        raise RuntimeError('Existing prospective recovery plan may not be overwritten')
    existing = rows()
    indexed = {row['candidate_id']: row for row in existing}
    assert indexed['C1201']['gates']['return'] and indexed['C1201']['gates']['negative_buyhold_year_profit']
    seen = {row['config_hash'] for row in existing}
    configurations = []

    def add(bull, bear, cooldown):
        p = deepcopy(indexed['C1000']['parameters'])
        p['bull']['max_hold'], p['bear']['max_hold'] = bull, bear
        p['regime_cooldown'] = cooldown
        digest = config_hash(p)
        if digest not in seen:
            seen.add(digest)
            configurations.append({'label': f'recovery-hold-{bull}-{bear}-cooldown{cooldown}',
                                   'parent': 'C9023', 'parameters': p})

    for bull in (4, 6, 8):
        for bear in (2, 3):
            for cooldown in (0, 2, 5):
                add(bull, bear, cooldown)
    for bull in (4, 6, 7):
        add(bull, 4, 5)
    for cooldown in (6, 8):
        add(8, 4, cooldown)
    plan = {'name': 'state_frequency_recovery',
        'basis': {key: indexed['C1201'][key] for key in ('net_cagr', 'annual', 'closed_trades', 'gates', 'result_hash')},
        'hypothesis': 'cooldown5 improved both negative-BuyHold-year margins; shorter route holding may recover missing turnover without losing that margin',
        'counterclaim': 'cooldown2/short-hold interactions failed; gains may come from skipping specific market paths and disappear on timing changes',
        'attribution': 'same hold cells with cooldown0/2/5; cooldown6/8 independently checks the new upper boundary',
        'selection_bias': 'same seen developer pool, adaptively extended after observed results, no holdout',
        'resources': {'max_workers': 4, 'native_threads_per_worker': 1, 'request_workers': 1, 'seed': 13},
        'initial_budget': len(configurations), 'configurations': configurations}
    write(target, plan)
    ref = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT,
        'stage3-cooldown-five-recovery-plan', target.read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'recovery_reference.json', ref.to_dict())
    print({'published': True, 'configurations': len(configurations)})


if __name__ == '__main__':
    main()
