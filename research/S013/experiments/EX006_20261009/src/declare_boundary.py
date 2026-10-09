"""Prospective refinement of observed information-gate boundary improvements."""
from copy import deepcopy
from hashlib import sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import PROTOCOLS, RUNS, EXPERIMENT, read, write, context, config_hash
from diagnose import rows


def main():
    prior = read(RUNS / 'confirmation_context.json')
    assert prior['status'] == 'COMPLETE'
    plan_path = PROTOCOLS / 'boundary_plan.json'
    assert not plan_path.exists()
    indexed = {row['candidate_id']: row for row in rows()}
    seen = {row['config_hash'] for row in rows()}
    configurations = []

    def append(origin, threshold, *, parent=None, volume_basis=None):
        row = indexed[origin]
        p = deepcopy(row['parameters'])
        if parent is not None:
            control = next(r for r in rows() if r['parent'] == parent and not r['parameters']['confirmation']['enabled'])
            p = {**deepcopy(control['parameters']), 'confirmation': deepcopy(p['confirmation']),
                 'context': deepcopy(p['context'])}
        p['confirmation']['threshold'] = threshold
        if volume_basis:
            p['context']['volume_basis'] = volume_basis
        digest = config_hash(p)
        if digest in seen:
            return
        seen.add(digest)
        configurations.append({'parent': parent or row['parent'], 'parameters': p,
            'label': f"{parent or row['parent']}-boundary-{p['confirmation']['profile']}-{threshold}-{p['context']['volume_basis']}"})

    for threshold in (-.3, -.25, -.225, -.175, -.15, -.125, -.1):
        append('C2127', threshold)
    for threshold in (-.25, -.175, -.15):
        append('C2127', threshold, volume_basis='ADJUSTED')
    for parent in ('C9018', 'C9020', 'C9025', 'C9026', 'C9029', 'C9030'):
        append('C2127', -.2, parent=parent)
    for threshold in (-.175, -.15, -.125, -.1, -.05):
        append('C2111', threshold)
    plan = {'name': 'confirmation_boundary', 'precheck_file': 'context_precheck.json',
        'basis': 'Observed C2126/C2127 volume-gated state reentry improves annual headroom with exactly 110 closes; refine both sides and reuse six original parent centers. Turnover state gate has nearby frequency/headroom tradeoff.',
        'seen_context_sha256': sha256((RUNS / 'confirmation_context.json').read_bytes()).hexdigest(),
        'source_files': read(PROTOCOLS / 'context_plan.json')['source_files'],
        'scope': 'same approved developer pool, costs and four gates; no source change or fixed cooldown',
        'volume_comparison': 'RAW40 versus identical ADJUSTED40 only',
        'stopping': 'mechanism-boundary evidence, not a fixed trial count or all-components impossibility claim',
        'configurations': configurations}
    write(plan_path, plan)
    ref = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT,
        'buy-confirmation-boundary-plan', plan_path.read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'boundary_plan_reference.json', ref.to_dict())
    print({'published': True, 'boundary_configurations': len(configurations)}, flush=True)


if __name__ == '__main__':
    main()
