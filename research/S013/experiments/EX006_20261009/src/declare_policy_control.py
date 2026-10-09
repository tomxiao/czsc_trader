"""Final matched scope contrast and local threshold checks for the best center."""
from copy import deepcopy
from hashlib import sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import PROTOCOLS, RUNS, EXPERIMENT, read, write, context
from diagnose import rows


def main():
    assert read(RUNS / 'confirmation_best_margin.json')['status'] == 'COMPLETE'
    path = PROTOCOLS / 'policy_control_plan.json'
    assert not path.exists()
    best = max((r for r in rows() if r['qualified'] and r['parameters']['confirmation']['enabled']),
               key=lambda r: r['negative_year_min_profit'])
    configs = []
    for gate, threshold in (('all', -.175), ('regime_reentry', -.185), ('regime_reentry', -.165)):
        p = deepcopy(best['parameters'])
        p['confirmation']['threshold'] = threshold
        p['context']['entry_gate'] = gate
        configs.append({'parent': best['parent'], 'parameters': p,
            'label': f"{best['parent']}-policy-control-{gate}-{threshold}"})
    plan = {'name': 'confirmation_policy_control', 'precheck_file': 'context_precheck.json',
        'observed_center': best['candidate_id'],
        'basis': 'Matched all-entry versus state-exit-reentry gate at the new best parent; nearest threshold neighbors. Stop this mechanism round after these controls and full account/cost attribution, with remaining directions explicit.',
        'seen_best_margin_sha256': sha256((RUNS / 'confirmation_best_margin.json').read_bytes()).hexdigest(),
        'source_files': read(PROTOCOLS / 'context_plan.json')['source_files'],
        'configurations': configs}
    write(path, plan)
    ref = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT,
        'buy-confirmation-policy-control-plan', path.read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'policy_control_plan_reference.json', ref.to_dict())
    print({'published': True, 'center': best['candidate_id'], 'controls': len(configs)}, flush=True)


if __name__ == '__main__':
    main()
