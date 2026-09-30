"""Fixed balanced, paired perturbation design; no response-adaptive search."""
import json
from itertools import combinations
import numpy as np
import optuna

SEED=2026093028
FIELDS=('tail_weight','spx_weight','entry','exit','lookback','premium','max_days')
STEPS=(.025,.025,.005,.025,10,.0005,1)
CENTERS={
 'S011-CFG-000618':dict(tail_weight=.575,spx_weight=.05,entry=.325,exit=.025,max_days=2,lookback=130,premium=.003),
 'S011-CFG-000624':dict(tail_weight=.575,spx_weight=.05,entry=.330,exit=.025,max_days=2,lookback=130,premium=.003),
 'S011-CFG-000621':dict(tail_weight=.575,spx_weight=.05,entry=.325,exit=.175,max_days=2,lookback=130,premium=.003),
 'S011-CFG-000628':dict(tail_weight=.575,spx_weight=.05,entry=.330,exit=.175,max_days=2,lookback=130,premium=.003)}

def signs():
    # Seven distinct odd-parity Walsh columns of H16: balanced marginals,
    # balanced pairs, and explicit opposite-sign partners. Higher interactions alias.
    return np.array([[1 if (row&column).bit_count()%2==0 else -1 for column in (1,2,4,8,7,11,13)] for row in range(16)])

def design():
    slots=[]; unique=[dict(p) for p in CENTERS.values()]
    lookup={json.dumps(p,sort_keys=True):i for i,p in enumerate(unique)}
    offsets=[('CENTER','center',np.zeros(7,dtype=int))]
    for i,field in enumerate(FIELDS):
        for direction in (-1,1):
            v=np.zeros(7,dtype=int);v[i]=direction;offsets.append(('AXIS',field+('+' if direction==1 else '-'),v))
    for i,v in enumerate(signs()):
        fixed=v.copy();fixed[-1]=0
        offsets.append(('JOINT_HOLD2',f'J{i:02}',fixed))
        offsets.append(('JOINT_HOLD13',f'J{i:02}',v))
    for cid,center in CENTERS.items():
        for kind,label,offset in offsets:
            p={k:round(center[k]+int(v)*step,10) for k,v,step in zip(FIELDS,offset,STEPS)}
            for k in ('lookback','max_days'):p[k]=int(p[k])
            key=json.dumps(p,sort_keys=True)
            if key not in lookup:lookup[key]=len(unique);unique.append(p)
            slots.append({'center_config_id':cid,'kind':kind,'probe':label,'design_id':lookup[key],
                          'offset':list(map(int,offset)),'parameters':p})
    return slots,unique

def study():
    _,points=design()
    result=optuna.create_study(storage=optuna.storages.InMemoryStorage(),sampler=optuna.samplers.RandomSampler(seed=SEED),directions=['maximize','maximize'])
    for i in range(len(points)):result.enqueue_trial({'design_id':i})
    return result

def synthetic():
    a=signs();assert a.shape==(16,7) and np.all(a.sum(axis=0)==0)
    for i,j in combinations(range(7),2):
        assert all(sum((a[:,i]==x)&(a[:,j]==y))==4 for x in (-1,1) for y in (-1,1))
    assert {tuple(v) for v in a}=={tuple(-v) for v in a}
    slots,points=design();assert len(slots)==188 and len({json.dumps(p,sort_keys=True) for p in points})==len(points)
    assert all(-.5<=p['exit']<p['entry']<=.5 and 1<=p['max_days']<=3 and p['spx_weight']>=0 for p in points)
    s=study();seen=[]
    def objective(t):
        i=t.suggest_int('design_id',0,len(points)-1);seen.append(i);return 0.,0.
    s.optimize(objective,n_trials=len(points),n_jobs=8)
    assert sorted(seen)==list(range(len(points))) and all(t.state.name=='COMPLETE' for t in s.trials)
