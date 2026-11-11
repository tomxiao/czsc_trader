"""Summarize each complete equal-weight neighborhood and reused center/stress evidence."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import numpy as np

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
WORK = Path(__file__).resolve().parents[1]
if WORK.parent != ROOT/'research/S019/experiments':
    WORK = ROOT/'research/S019/experiments/EX050_20261111'
COUNTS = {'C0966':242,'C1010':728,'C0909':728}


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def joint_pass(row):
    # The all-point absolute-MDD target is independent of the joint proportion.
    return all(row['selfcheck_gates'][key] for key in ('nar','calmar','relative_dd'))


def distribution(rows):
    output = {}
    for key in ('nar','drawdown','calmar'):
        values = np.asarray([r['candidate'][key] for r in rows],dtype=float)
        assert np.isfinite(values).all(), ('Missing/nonfinite metric requires explicit review',key)
        output[key] = {name:float(np.quantile(values,q)) for name,q in
            (('min',0),('q10',.1),('median',.5),('q90',.9),('max',1))}
    return output


def main():
    source = read(WORK/'others/account_results.json')
    scope = read(WORK/'protocols/scope.json')
    assert set(scope['selected']) == set(COUNTS)
    expected = {f'{cid}_P{i:03}' for cid,n in COUNTS.items() for i in range(n)} | {
        f'{cid}_{label}' for cid in COUNTS for label in ('CENTER','STRESS')}
    assert source['status'] == 'COMPLETE' and set(source['accounts']) == expected
    output = {'criterion':'Each full neighborhood jointly passes >=80%; every point MDD <=25%',
        'equal_weight':True,'groups':{},'workload':source['workload'],
        'account_seconds':source['elapsed_seconds'],'new_search_trials':0,
        'standard_center_replays':0,'reused_original_centers':3,'reused_stress_accounts':3,
        'replay_statistics_complete':source['replay_statistics_complete'],
        'account_results_sha256':digest(WORK/'others/account_results.json'),
        'scope_sha256':digest(WORK/'protocols/scope.json'),
        'parameter_level_interpretation':'Conditional slices within the complete joint grid; dependent observations, descriptive association rather than independent causal experiments.',
        'geometry_comparison':'Five active axes for C0966; six for C1010/C0909. Each full grid is accepted independently; cross-design quantiles are descriptive.'}
    for cid,n in COUNTS.items():
        points = {k:r for k,r in source['accounts'].items() if r['parent']==cid and r['label'].startswith('P')}
        assert set(points) == {f'{cid}_P{i:03}' for i in range(n)}
        rows = list(points.values())
        assert all(all(r['selfcheck_gates'].values())==r['selfcheck_pass'] for r in rows)
        assert all(r['role']=='SELF_CHECK' for r in rows)
        passed = sum(joint_pass(r) for r in rows)
        risks = all(r['candidate']['drawdown']<=.25 for r in rows)
        levels = {}
        for key in rows[0]['parameters']:
            values = sorted({r['parameters'][key] for r in rows})
            if len(values)<=1:
                continue
            levels[key] = []
            for value in values:
                group = [r for r in rows if r['parameters'][key]==value]
                levels[key].append({'value':value,'n':len(group),
                    'joint_pass_rate':sum(joint_pass(r) for r in group)/len(group),
                    'distribution':distribution(group)})
        output['groups'][cid] = {'points':n,'valid_points':len(points),'passed_points':passed,
            'required_passes':(4*n+4)//5,'joint_pass_rate':passed/n,'all_risk_limits_pass':risks,
            'parameter_acceptance':passed*5>=n*4 and risks,
            'failed_gates':dict(Counter(k for r in rows for k,ok in r['selfcheck_gates'].items() if not ok)),
            'distribution':distribution(rows),'parameter_level_diagnostics':levels,
            'lowest_calmar':min(points,key=lambda k:(points[k]['candidate']['calmar'],k)),
            'highest_mdd':min(points,key=lambda k:(-points[k]['candidate']['drawdown'],k)),
            'center':source['accounts'][f'{cid}_CENTER'],'stress':source['accounts'][f'{cid}_STRESS']}
    (WORK/'others/account_summary.json').write_bytes((json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
    print('ACCOUNT_SUMMARY_COMPLETE',{cid:output['groups'][cid]['joint_pass_rate'] for cid in COUNTS},flush=True)


if __name__ == '__main__':
    main()
