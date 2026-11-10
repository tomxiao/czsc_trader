"""Summarize all 240 equal-weight parameter points and three separate stresses."""
from collections import Counter
import json
from pathlib import Path
import numpy as np

WORK = Path(__file__).resolve().parents[1]
IDS = ('C0367', 'C0355', 'C0264')


def distribution(rows):
    return {key: {name: float(np.quantile([r['candidate'][key] for r in rows], q))
            for name, q in (('min', 0), ('q10', .1), ('median', .5), ('q90', .9), ('max', 1))}
            for key in ('nar', 'drawdown', 'calmar')}


def main():
    source = json.loads((WORK / 'others/account_results.json').read_bytes())
    assert source['status'] == 'COMPLETE' and len(source['accounts']) == 244
    output = {'criterion': 'joint passing proportion >= 0.8; all 80 points MDD <= 0.25 per center',
        'equal_weight': True, 'groups': {}, 'workload': source['workload'],
        'account_seconds': source['elapsed_seconds'], 'new_search_trials': 0,
        'remaining_optimization_rounds': 6, 'standard_center_replays': 1,
        'reused_original_centers': 2, 'replay_statistics_complete': source['replay_statistics_complete']}
    for cid in IDS:
        points = {key: row for key, row in source['accounts'].items()
                  if row['parent'] == cid and row['label'].startswith('P')}
        assert set(points) == {f'{cid}_P{i:03}' for i in range(80)}
        rows = list(points.values())
        assert all(all(r['selfcheck_gates'].values()) == r['selfcheck_pass'] for r in rows)
        passed = sum(r['selfcheck_pass'] for r in rows)
        risks = all(r['candidate']['drawdown'] <= .25 for r in rows)
        levels = {}
        for key in rows[0]['parameters']:
            values = sorted({r['parameters'][key] for r in rows})
            if len(values) <= 1:
                continue
            levels[key] = []
            for value in values:
                group = [r for r in rows if r['parameters'][key] == value]
                levels[key].append({'value': value, 'n': len(group),
                    'joint_pass_rate': sum(r['selfcheck_pass'] for r in group)/len(group),
                    'distribution': distribution(group)})
        output['groups'][cid] = {'points': 80, 'valid_points': len(points), 'passed_points': passed,
            'required_passes': 64, 'joint_pass_rate': passed/80, 'all_risk_limits_pass': risks,
            'parameter_acceptance': passed*5 >= 80*4 and risks,
            'failed_gates': dict(Counter(k for r in rows for k, ok in r['selfcheck_gates'].items() if not ok)),
            'distribution': distribution(rows), 'parameter_level_diagnostics': levels,
            'lowest_calmar': min(points, key=lambda k: points[k]['candidate']['calmar']),
            'highest_mdd': max(points, key=lambda k: points[k]['candidate']['drawdown']),
            'stress': source['accounts'][f'{cid}_STRESS']}
    (WORK / 'others/account_summary.json').write_bytes(
        (json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())
    print('ACCOUNT_SUMMARY_COMPLETE', {cid: output['groups'][cid]['joint_pass_rate'] for cid in IDS}, flush=True)


if __name__ == '__main__':
    main()
