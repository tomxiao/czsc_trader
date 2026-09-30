"""Independent geometry, trial coverage and evidence checks for the EX28 report."""
from pathlib import Path
from hashlib import sha256
from itertools import combinations
import argparse
import json
import numpy as np
import pandas as pd

REPO=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').is_file())
EX=REPO/'experiments/S011/20260930_S011_EX28'

def read(path):return json.loads(path.read_text(encoding='utf-8'))

def verify(package):
    artifact=EX/'artifacts';slots=read(artifact/'design_slots.json');points=read(artifact/'unique_parameters.json')
    protocol=read(artifact/'protocol.json');fields=list(protocol['steps']);steps=np.array(list(protocol['steps'].values()))
    assert len(slots)==188 and len(points)==184
    assert len({json.dumps(p,sort_keys=True) for p in points})==184
    for cid in protocol['center_ids']:
        subset=[s for s in slots if s['center_config_id']==cid]
        assert len(subset)==47
        center=next(s['parameters'] for s in subset if s['kind']=='CENTER')
        for s in subset:
            assert s['parameters']==points[s['design_id']]
            np.testing.assert_allclose([s['parameters'][k]-center[k] for k in fields],steps*s['offset'],atol=1e-12,rtol=0)
        axis=[s for s in subset if s['kind']=='AXIS'];assert len(axis)==14
        assert {tuple(s['offset']) for s in axis}=={tuple(v*sign) for v in np.eye(7,dtype=int) for sign in (-1,1)}
        for kind,n in [('JOINT_HOLD2',6),('JOINT_HOLD13',7)]:
            a=np.array([s['offset'] for s in subset if s['kind']==kind])[:,:n]
            assert a.shape==(16,n) and np.all(a.sum(axis=0)==0)
            assert {tuple(r) for r in a}=={tuple(-r) for r in a}
            for i,j in combinations(range(n),2):
                assert all(np.count_nonzero((a[:,i]==x)&(a[:,j]==y))==4 for x in (-1,1) for y in (-1,1))
    states=read(artifact/'trial_states.json')
    assert len(states)==184 and all(t['state']=='COMPLETE' for t in states)
    assert sorted(t['params']['design_id'] for t in states)==list(range(184))
    assert sorted(read(artifact/'completion_order.json'))==list(range(184))
    for i in range(4):assert read(artifact/f'trials/T{i:03}/anchor_check.json')['five_economic_ledgers_equal']
    workers=read(artifact/'worker_execution.json');assert len(workers)==184
    events=sorted([(r['started'],1) for r in workers.values()]+[(r['finished'],-1) for r in workers.values()])
    active=peak=0
    for _,change in events:active+=change;peak=max(peak,active)
    assert active==0 and 1<=peak<=8
    evaluation=pd.read_parquet(package/'evaluations.parquet')
    assert len(evaluation)==368
    stats=pd.read_parquet(package/'diagnostics.parquet')
    checked=0
    for s in stats.itertuples():
        ids=[p['design_id'] for p in slots if p['center_config_id']==s.center_config_id and p['kind']==s.kind
             and (s.holding_stratum=='ALL' or p['parameters']['max_days']==int(s.holding_stratum))]
        results=[evaluation[evaluation.design_id.eq(i)&evaluation.scenario.eq(s.scenario)].iloc[0] for i in ids]
        assert len(results)==s.positions
        assert sum(r.qualified for r in results)==s.qualified
        assert sum(r.return_pass for r in results)==s.return_pass_count
        assert sum(r.frequency>6 for r in results)==s.frequency_above6
        checked+=1
    old=read(REPO/'research/S011/configurations.json')['configurations']
    new=read(package/'configurations.json')['configurations'];assert new[:len(old)]==old
    assert (package/'pareto.json').read_bytes()==(REPO/'research/S011/stage4/iteration_03/pareto.json').read_bytes()
    return {'status':'PASS','manifest_sha256':sha256((package/'manifest.json').read_bytes()).hexdigest(),
            'geometry_checked_positions':188,'unique_complete_trials':184,'complete_accounts':368,
            'reconciled_summary_rows':checked,'actual_worker_pids':sorted({r['pid'] for r in workers.values()}),
            'peak_overlapping_public_evaluations':peak,'old_registry_prefix_unchanged':len(old),
            'new_registry_entries':len(new),'old_pareto_unchanged':True,
            'scope':'Evidence, balanced geometry and numerical accounting only; no independent out-of-sample validation'}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('package',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=verify(args.package.resolve());text=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text,encoding='utf-8',newline='\n')
    print(text)
