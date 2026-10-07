"""Stage-three return/frequency tradeoffs within the annual-DD constraint."""


def frontier(rows, extra_ids=()):
    valid = [r for r in rows if r['status'] == 'SUCCEEDED']
    feasible_dd = [r for r in valid if r['gates']['annual_drawdown']]
    points = []
    for row in feasible_dd:
        x, y = row['net_cagr'], min(row['frequency60'], 4.0)
        if not any(other['net_cagr'] >= x and min(other['frequency60'], 4.0) >= y
                   and (other['net_cagr'] > x or min(other['frequency60'], 4.0) > y)
                   for other in feasible_dd):
            points.append(row)
    # Preserve every qualified parameter configuration, even if dominated.
    selected = {r['candidate_id']: r for r in points}
    for row in valid:
        if row['qualified'] or row['candidate_id'] in extra_ids:
            selected[row['candidate_id']] = row
    # Keep the baseline and most informative counterexamples with full ledgers.
    for row in (valid[0], max(valid, key=lambda r: r['net_cagr']),
                min(valid, key=lambda r: r['deficit'])):
        selected[row['candidate_id']] = row
    return sorted(selected.values(), key=lambda r: r['candidate_id'])
