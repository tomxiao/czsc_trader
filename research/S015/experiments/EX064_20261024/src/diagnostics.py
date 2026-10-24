"""Descriptive interpretation of the frozen complete grid; no new acceptance rules."""
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from stage4 import OUT, read, save


def build():
    plans={x['candidate_id']:x for x in read(OUT/'plan_refs.json')}
    audit=read(OUT/'audit.json')
    assert audit['status']=='PASS'
    accounts={x['candidate_id']:x for x in audit['accounts']}
    projections=read(OUT/'assessment_request.json')['evidence']
    paths={x['candidate']['candidate_id'].removeprefix('S015-'):sha256(json.dumps(
        [(p['session'],p['equity']) for p in x['account']],separators=(',',':')).encode()).hexdigest()
        for x in projections if x['scenario_id']=='standard'}
    groups=[]
    points=[]
    for row in read(OUT/'comparison.json')['rows']:
        cid=row['candidate']['candidate_id'].removeprefix('S015-')
        plan=plans[cid]
        centers={x['name']:x['center'] for x in plan['design']['space']['axes']}
        group=next(x for x in row['target_checks'] if x['type']=='ParameterNeighborhoodCheck')
        local=[]
        for check in group['points']:
            values={x['name']:x['value'] for x in plan['design']['points'][check['point_index']]['values']}
            child=check['candidate']['candidate_id'].removeprefix('S015-')
            facts=accounts[child]['summary']
            joint=all(x['status'] in ('PASSED','NOT_APPLICABLE') for x in check['joint_checks'])
            risk=all(x['status'] in ('PASSED','NOT_APPLICABLE') for x in check['all_point_checks'])
            changed=[name for name,value in values.items() if value!=centers[name]]
            point={'center':cid,'child':child,'point_index':check['point_index'],**values,
                'changed_axes':','.join(changed),'changed_count':len(changed),'joint_pass':joint,'all_point_pass':risk,
                'net_return':facts['net_return'],'annual_return':(1+facts['net_return'])**(252/434)-1,
                'drawdown':facts['dd'],
                'failed_targets':','.join(x['target']['target_id'] for x in (*check['joint_checks'],*check['all_point_checks']) if x['status']=='FAILED')}
            local.append(point)
        assert len(local)==group['required_points']==group['valid_points']
        assert sum(x['joint_pass'] for x in local)==group['joint_passes']
        strata=[]
        for name in centers:
            for value in sorted({x[name] for x in local}):
                selected=[x for x in local if x[name]==value]
                strata.append({'axis':name,'value':value,'points':len(selected),'joint_passes':sum(x['joint_pass'] for x in selected),
                    'min_annual':min(x['annual_return'] for x in selected),'max_dd':max(x['drawdown'] for x in selected)})
        groups.append({'candidate_id':cid,'acceptance_status':row['acceptance_status'],'comparison_status':row['status'],
            'required_points':len(local),'joint_passes':group['joint_passes'],'minimum_joint_passes':group['minimum_joint_passes'],
            'parameter_status':group['status'],'all_point_failures':sum(not x['all_point_pass'] for x in local),
            'min_annual':min(x['annual_return'] for x in local),'max_annual':max(x['annual_return'] for x in local),
            'max_drawdown':max(x['drawdown'] for x in local),
            'distinct_neighbor_equity_paths':len({paths[x['child']] for x in local}),
            'single_axis_points':sum(x['changed_count']==1 for x in local),
            'single_axis_failures':sum(x['changed_count']==1 and not x['joint_pass'] for x in local),
            'multi_axis_failures':sum(x['changed_count']>1 and not x['joint_pass'] for x in local),
            'failed_targets':dict(Counter(t for x in local for t in x['failed_targets'].split(',') if t)),
            'axis_strata':strata})
        points.extend(local)
    assert len(points)==542
    fields=list(dict.fromkeys(k for p in points for k in p))
    with (OUT/'neighborhood_points.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        writer.writerows(points)
    behavior=defaultdict(list)
    for cid in accounts: behavior[paths[cid]].append(cid)
    save(OUT/'behavior_groups.json',{'grouping':'Exact full-window daily equity, without tolerance; economic path similarity is not proof of common mechanism.',
        'account_configurations':len(accounts),'distinct_equity_paths':len(behavior),
        'center_distinct_equity_paths':len({paths[cid] for cid in plans}),
        'groups':dict(behavior)})
    save(OUT/'neighborhood_diagnostics.json',{'interpretation':'Descriptive post-evaluation strata, not a new threshold or independent sample.',
        'points':542,'groups':groups,'acceptance_counts':dict(Counter(x['acceptance_status'] for x in groups)),
        'joint_passes':sum(x['joint_pass'] for x in points),'risk_failures':sum(not x['all_point_pass'] for x in points),
        'min_annual':min(x['annual_return'] for x in points),'max_drawdown':max(x['drawdown'] for x in points)})
    for g in groups:
        print(g['candidate_id'],g['joint_passes'],g['required_points'],g['minimum_joint_passes'],g['acceptance_status'],flush=True)


if __name__=='__main__':
    build()
