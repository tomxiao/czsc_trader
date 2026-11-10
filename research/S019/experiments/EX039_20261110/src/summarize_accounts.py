"""Summarize the complete preregistered neighborhoods without selecting new trials."""
from collections import Counter
import json
from pathlib import Path

import numpy as np

WORK = Path(__file__).resolve().parents[1]


def distribution(rows):
    return {
        key: {name: float(np.quantile([r['candidate'][key] for r in rows], q))
              for name, q in (('min', 0), ('q10', .1), ('median', .5), ('q90', .9), ('max', 1))}
        for key in ('nar', 'drawdown', 'calmar')
    }


def main():
    source = json.loads((WORK / 'others/account_results.json').read_bytes())
    assert source['status'] == 'COMPLETE' and len(source['accounts']) == 90
    output = {'criterion': 'joint passing proportion >= 0.8; all points MDD <= 0.25',
              'equal_weight': True, 'groups': {}, 'workload': source['workload'],
              'account_seconds': source['elapsed_seconds'], 'new_search_trials': 0,
              'remaining_optimization_rounds': 7}
    for cid, expected in (('C0135', 8), ('C0224', 80)):
        points = {k: r for k, r in source['accounts'].items()
                  if r['parent'] == cid and r['label'] != 'STRESS'}
        assert len(points) == expected
        rows = list(points.values())
        passed = sum(r['selfcheck_pass'] for r in rows)
        risks_pass = all(r['candidate']['drawdown'] <= .25 for r in rows)
        assert all(all(r['selfcheck_gates'].values()) == r['selfcheck_pass'] for r in rows)
        levels = {}
        for key in rows[0]['parameters']:
            values = sorted({r['parameters'][key] for r in rows})
            if len(values) <= 1:
                continue
            levels[key] = []
            for value in values:
                group = [r for r in rows if r['parameters'][key] == value]
                levels[key].append({'value': value, 'n': len(group),
                    'joint_pass_rate': sum(r['selfcheck_pass'] for r in group) / len(group),
                    'distribution': distribution(group)})
        output['groups'][cid] = {'points': expected, 'valid_points': len(points),
            'passed_points': passed, 'joint_pass_rate': passed / expected,
            'all_risk_limits_pass': risks_pass,
            'parameter_acceptance': passed * 5 >= expected * 4 and risks_pass,
            'failed_gates': dict(Counter(g for r in rows for g, ok in r['selfcheck_gates'].items() if not ok)),
            'distribution': distribution(rows), 'parameter_level_diagnostics': levels,
            'lowest_calmar': min(points, key=lambda k: points[k]['candidate']['calmar']),
            'highest_mdd': max(points, key=lambda k: points[k]['candidate']['drawdown']),
            'stress': source['accounts'][f'{cid}_STRESS']}
    (WORK / 'others/account_summary.json').write_bytes(
        (json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())
    print('ACCOUNT_SUMMARY_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
