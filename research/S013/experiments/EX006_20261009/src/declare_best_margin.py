"""Follow the new best headroom center, rather than stop at the first success."""
from copy import deepcopy
from hashlib import sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import PROTOCOLS, RUNS, EXPERIMENT, read, write, context, config_hash
from diagnose import rows


def main():
    assert read(RUNS / 'confirmation_boundary.json')['status'] == 'COMPLETE'
    plan_path = PROTOCOLS / 'best_margin_plan.json'
    assert not plan_path.exists()
    best = max((r for r in rows() if r['qualified'] and r['parameters']['confirmation']['enabled']),
               key=lambda r: r['negative_year_min_profit'])
    assert best['parameters']['confirmation']['profile'] == 'turnover'
    seen = {row['config_hash'] for row in rows()}
    configurations = []
    def append(row, threshold, basis, parent=None):
        p = deepcopy(row['parameters'])
        if parent is not None:
            control = next(r for r in rows() if r['parent'] == parent and not r['parameters']['confirmation']['enabled'])
            p = {**deepcopy(control['parameters']), 'confirmation': deepcopy(p['confirmation']),
                 'context': deepcopy(p['context'])}
        p['confirmation']['threshold'] = threshold
        p['context']['volume_basis'] = basis
        digest = config_hash(p)
        if digest not in seen:
            seen.add(digest)
            configurations.append({'parent': parent or row['parent'], 'parameters': p,
                'label': f"{parent or row['parent']}-best-margin-{p['confirmation']['profile']}-{threshold}-{basis}"})
    for threshold in (-.19, -.185, -.18, -.17, -.165, -.16):
        append(best, threshold, 'ADJUSTED')
    for parent in ('C9018', 'C9025', 'C9029'):
        append(best, -.175, 'ADJUSTED', parent)
    volume = max((r for r in rows() if r['qualified']
                  and r['parameters'].get('context', {}).get('volume_basis') == 'RAW'),
                 key=lambda r: r['negative_year_min_profit'])
    for threshold, basis in ((-.225, 'RAW'), (-.175, 'RAW'), (-.15, 'RAW'), (-.2, 'ADJUSTED')):
        append(volume, threshold, basis)
    plan = {'name': 'confirmation_best_margin', 'precheck_file': 'context_precheck.json',
        'basis': 'New best C2216 turnover-state-reentry headroom boundary and cross-parent confirmation; also verify the best C2214 volume-state center neighborhood and same-window adjusted-volume counterpart.',
        'observed_center': best['candidate_id'],
        'seen_boundary_sha256': sha256((RUNS / 'confirmation_boundary.json').read_bytes()).hexdigest(),
        'source_files': read(PROTOCOLS / 'context_plan.json')['source_files'],
        'scope': 'same approved stage three, data, four gates and fees; no fixed cooldown',
        'configurations': configurations}
    write(plan_path, plan)
    ref = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT,
        'buy-confirmation-best-margin-plan', plan_path.read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'best_margin_plan_reference.json', ref.to_dict())
    print({'published': True, 'center': best['candidate_id'], 'configurations': len(configurations)}, flush=True)


if __name__ == '__main__':
    main()
