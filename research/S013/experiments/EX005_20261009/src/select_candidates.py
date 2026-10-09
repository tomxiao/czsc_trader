"""Researcher-owned stage-three retention; no SE ranking or extra eligibility gates."""
from common import RUNS, write
from diagnose import rows


def main():
    valid = [row for row in rows() if row['status'] == 'SUCCEEDED']
    qualified = sorted(row['candidate_id'] for row in valid if row['qualified'])
    pool = [row for row in valid if row['gates']['annual_drawdown']
            and row['gates']['negative_buyhold_year_profit']]

    def metrics(row):
        return row['net_cagr'], row['negative_year_min_profit'], min(row['frequency60'], 4.)

    frontier = [row['candidate_id'] for row in pool if not any(
        all(a >= b for a, b in zip(metrics(other), metrics(row), strict=True))
        and any(a > b for a, b in zip(metrics(other), metrics(row), strict=True))
        for other in pool if other['candidate_id'] != row['candidate_id'])]
    counterexamples = ['C1001', 'C1014', 'C1015', 'C1016', 'C1017',
                       'C1103', 'C1105', 'C1109', 'C1111', 'C1200', 'C1201', 'C1202', 'C1203',
                       'C1314', 'C1315', 'C1316', 'C1317', 'C1318']
    retained = sorted(set(qualified + frontier + counterexamples))
    write(RUNS / 'selection.json', {'qualified': qualified, 'frontier': frontier,
        'counterexamples': counterexamples, 'retained': retained,
        'method': 'all exact four-gate configurations; stage-three CAGR/annual-profit/frequency-capped-at4 frontier; explicit mechanism counterexamples',
        'not_stage4': 'no assessment ranking or new economic gate',
        'counts': {'successful_configurations': len(valid), 'qualified': len(qualified),
                   'novel_qualified_excluding_disabled_control': len([x for x in qualified if x != 'C1000']),
                   'retained': len(retained)}})
    print({'counts': {'successful': len(valid), 'qualified': len(qualified),
                      'retained': len(retained)}, 'qualified': qualified, 'frontier': frontier})


if __name__ == '__main__':
    main()
