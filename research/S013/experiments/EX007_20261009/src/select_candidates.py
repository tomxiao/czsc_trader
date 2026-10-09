"""Retain every new qualified content plus explicit mechanism counterexamples."""
from common import ROOT, RUNS, read, write
from diagnose import rows


def main():
    searches = [read(path) for path in RUNS.glob('cost_confirmation_*.json') if 'rows' in read(path)]
    assert all(value['status'] == 'COMPLETE' for value in searches)
    valid = rows()
    assert all(row['status'] == 'SUCCEEDED' for row in valid)
    assert len({row['config_hash'] for row in valid}) == len(valid)
    controls = ['C3000', 'C3001', 'C3200']
    known = {read(path)['record']['content_sha256']: path.stem
             for path in (ROOT / 'research/registrations/S013/candidates').glob('*.json')}
    aliases = {row['candidate_id']: known[row['content_sha256']] for row in valid
               if row['content_sha256'] in known}
    additions = [row for row in valid if row['candidate_id'] not in controls]
    qualified = sorted(row['candidate_id'] for row in additions if row['qualified']
                       and row['candidate_id'] not in aliases)
    pressure = read(RUNS / 'cost_diagnostics.json')
    assert pressure['status'] == 'COMPLETE'
    counterexamples = {item['candidate_id'] for item in pressure['rows']} - set(controls)
    counterexamples.update(('C3011', 'C3019', 'C3201', 'C3203'))  # gate, holding and price-amplitude contrasts
    counterexamples.update(row['candidate_id'] for row in additions if row['label'].startswith('isolated-'))
    for subset in ([row for row in additions if '-bull-raw-acf-' in row['label']],
                   [row for row in additions if 'hold-' in row['label'] and not row['label'].startswith('isolated-')],
                   [row for row in additions if row['parameters'].get('opportunity_confirmation', {}).get('profile') == 'acf_volume']):
        if subset:
            counterexamples.add(max(subset, key=lambda row: row['negative_year_min_profit'])['candidate_id'])
    counterexamples = sorted(counterexamples - set(aliases))
    retained = sorted(set(qualified + counterexamples))
    parent = {row['parent']: row for row in valid if row['candidate_id'] in ('C3000', 'C3001')}
    improvements = [row['candidate_id'] for row in additions if row['qualified'] and
                    row['negative_year_min_profit'] > parent[row['parent']]['negative_year_min_profit']]
    write(RUNS / 'selection.json', {'qualified': qualified, 'counterexamples': counterexamples,
        'retained': retained, 'controls_material_only': controls, 'existing_content_aliases': aliases,
        'qualified_margin_improvements_over_parent': improvements,
        'method': 'all unique new qualified identities; cost representatives, isolated holding and informative raw-ACF/compound-holding/acf-volume contrasts; exact disabled parent controls material-only; no duplicate existing content registration',
        'not_stage4': 'no ranking, extra eligibility gate, freeze or phase advancement',
        'counts': {'successful_configurations': len(valid), 'qualified_including_controls': sum(row['qualified'] for row in valid),
                   'new_qualified': len(qualified), 'exact_parent_controls': 2, 'price_floor_control': 1,
                   'existing_content_aliases': len(aliases), 'retained': len(retained)}})
    print({'selection': {'successful': len(valid), 'new_qualified': len(qualified), 'retained': len(retained)},
           'margin_improvements': improvements}, flush=True)


if __name__ == '__main__':
    main()
