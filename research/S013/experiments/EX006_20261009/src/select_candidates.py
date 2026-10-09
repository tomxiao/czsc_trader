"""Retain qualifications and informative controls without promoting a stage."""
from common import RUNS, write, read
from diagnose import rows


def main():
    searches = [read(path) for path in RUNS.glob('confirmation_*.json') if 'rows' in read(path)]
    assert all(value['status'] == 'COMPLETE' for value in searches)
    valid = rows()
    assert all(row['status'] == 'SUCCEEDED' for row in valid)
    qualified = sorted(row['candidate_id'] for row in valid if row['qualified'])
    enabled = [row for row in valid if row['parameters']['confirmation']['enabled']]
    pool = [row for row in enabled if row['gates']['annual_drawdown']
            and row['gates']['negative_buyhold_year_profit']]

    def metrics(row):
        return row['net_cagr'], row['negative_year_min_profit'], min(row['frequency60'], 4.)

    frontier_rows = [row for row in pool if not any(
        all(a >= b for a, b in zip(metrics(other), metrics(row), strict=True))
        and any(a > b for a, b in zip(metrics(other), metrics(row), strict=True))
        for other in pool if other['candidate_id'] != row['candidate_id'])]
    # All qualified identities remain. Identical frontier metrics need only one
    # full counterexample account; the complete search retains every row.
    frontier = list({metrics(row): row['candidate_id'] for row in frontier_rows}.values())
    counterexamples = []
    counterexamples.extend(row['candidate_id'] for row in valid if 'oldacf-off' in row['label'])
    counterexamples.extend(['C2110', 'C2111', 'C2112', 'C2113', 'C2400'])
    for subset in (enabled, [r for r in enabled if 'context' in r['parameters']]):
        counterexamples.extend([max(subset, key=lambda r: r['negative_year_min_profit'])['candidate_id'],
                                min(subset, key=lambda r: r['deficit'])['candidate_id']])
    for row in enabled:
        c, setting = row['parameters']['confirmation'], row['parameters'].get('context')
        if setting and setting['volume_basis'] == 'RAW':
            pairs = [other for other in enabled if other['parameters']['confirmation'] == c
                     and other['parent'] == row['parent']
                     and other['parameters'].get('context') == {**setting, 'volume_basis': 'ADJUSTED'}]
            if pairs:
                counterexamples.extend([row['candidate_id'], *(other['candidate_id'] for other in pairs)])
        if ('oldacf-off' in row['label'] or c['orientation'] == -1) and c['profile'] == 'all':
            counterexamples.append(row['candidate_id'])
        if setting and c['threshold'] == 0 and (setting['volume_basis'] == 'RAW'
                or setting['weighting'] == 'EQUAL_BLOCKS'):
            counterexamples.append(row['candidate_id'])
            pair = [other for other in enabled if other['parameters']['confirmation'] == c
                    and other['parent'] == row['parent']
                    and other['parameters'].get('context') == {
                        **setting, 'volume_basis': 'ADJUSTED', 'weighting': 'EQUAL_FEATURES'}]
            counterexamples.extend(other['candidate_id'] for other in pair)
    counterexamples = sorted(set(counterexamples))
    retained = sorted(set(qualified + frontier + counterexamples))
    controls = [r for r in valid if not r['parameters']['confirmation']['enabled'] and r['qualified']]
    parent_margin = {r['parent']: r['negative_year_min_profit'] for r in controls}
    improvements = [r['candidate_id'] for r in enabled if r['qualified']
                    and r['negative_year_min_profit'] > parent_margin[r['parent']]]
    write(RUNS / 'selection.json', {'qualified': qualified, 'frontier': frontier,
        'counterexamples': counterexamples, 'retained': retained,
        'qualified_margin_improvements_over_parent': improvements,
        'method': 'all four-gate identities; one account per identical frontier metric tuple; explicit reversed-score/old-ACF/raw-volume/block-weight controls',
        'not_stage4': 'no assessment ranking, extra gate, freeze or phase advancement',
        'counts': {'successful_configurations': len(valid), 'qualified': len(qualified),
                   'disabled_qualified_controls': len(controls),
                   'enabled_qualified': len(qualified) - len(controls), 'retained': len(retained)}})
    print({'counts': {'successful': len(valid), 'qualified': len(qualified),
                     'retained': len(retained)}, 'margin_improvements': improvements}, flush=True)


if __name__ == '__main__':
    main()
