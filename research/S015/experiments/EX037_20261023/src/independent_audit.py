"""Independent train-only categorical expansion and nested incremental-model audit."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[3];BASE=HERE.parent
def read(p):return json.loads(p.read_bytes())
def mod(p,n):
    s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def compare(a,b):
    if isinstance(b,dict):
        assert set(a)==set(b),(set(a)-set(b),set(b)-set(a))
        for k,v in b.items():compare(a[k],v)
    elif isinstance(b,list):
        assert len(a)==len(b)
        for u,v in zip(a,b):compare(u,v)
    else:audit.eq(a,b)
def least_squares(train,test,columns):
    if not columns:return np.repeat(train.y.mean(),len(test))
    a=train[columns].to_numpy();b=test[columns].to_numpy();mu=a.mean(0);sd=a.std(0);sd[sd==0]=1
    a=np.c_[np.ones(len(a)),(a-mu)/sd];b=np.c_[np.ones(len(b)),(b-mu)/sd]
    aug=np.vstack([a,np.diag([0.]+[np.sqrt(10)]*len(columns))]);rhs=np.r_[train.y,np.zeros(len(columns)+1)]
    return b@np.linalg.lstsq(aug,rhs,rcond=None)[0]

def main():
    global audit
    fr=read(HERE/'others/protocol_refs.json')
    for name,sub in [('followup.py','src'),('expression_checks.json','protocols')]:assert EvidenceRef.from_dict(fr[name]).resolve(ROOT).read_bytes()==(HERE/sub/name).read_bytes()
    prior=read(HERE/'protocols/expression_checks.json')['sources']['materials']
    p=BASE/'EX036_20261023/src/independent_audit.py';assert EvidenceRef.from_dict(prior['src/independent_audit.py']).resolve(ROOT).read_bytes()==p.read_bytes();audit=mod(p,'verified_independent_audit')
    p=BASE/'EX036_20261023/src/validate.py';assert EvidenceRef.from_dict(prior['src/validate.py']).resolve(ROOT).read_bytes()==p.read_bytes();metrics=mod(p,'verified_metrics').metrics
    x=pd.read_csv(EvidenceRef.from_dict(prior['others/model_features.csv']).resolve(ROOT));labels=pd.read_csv(EvidenceRef.from_dict(prior['others/labels.csv']).resolve(ROOT));before=pd.read_csv(EvidenceRef.from_dict(prior['others/predictions.csv']).resolve(ROOT))
    families=read(EvidenceRef.from_dict(read(BASE/'EX035_20261023/others/published_refs.json')['materials']['protocols/signal_dictionary.json']).resolve(ROOT))['families'];families['all']=sum(families.values(),[])
    cuts=read(HERE/'others/cutpoints.json');lookup={(r['target'],r['fold'],r['signal']):r for r in cuts};assert len(lookup)==len(cuts)==864
    preds=pd.read_csv(HERE/'others/predictions.csv');results=read(HERE/'others/results.json');fit_n=0;baseline_n=0
    for target,res in results.items():
        g=x.merge(labels[labels.target==target].drop(columns='date'),on='position',validate='one_to_one');p=preds[preds.target==target].reset_index(drop=True)
        controls=['r1','r5','vol20','range20']+(['held_unreal'] if target in ('hold1','hold3') else []);legacy=controls+['pressure']
        for fold,(lo,hi) in enumerate(((100,184),(184,268),(268,352),(352,434))):
            tr=g[(g.position<lo)&g.y.notna()&(g.known_date<g.date.iloc[lo])].copy();te=g[(g.position>=lo)&(g.position<hi)&g.y.notna()].copy();pp=p[p.fold==fold];bp=before[(before.target==target)&(before.fold==fold)]
            audit.eq(pp.position.tolist(),te.position.tolist());audit.eq(pp.y,te.y);assert tr.known_date.max()<g.date.iloc[lo]
            for name,columns in [('constant',[]),('price',controls),('legacy',legacy)]:
                values=least_squares(tr,te,columns)
                if target=='fill':values=np.clip(values,0,1)
                audit.eq(values,pp[name]);audit.eq(pp[name].to_numpy(),bp[name].to_numpy());baseline_n+=1
            for signal in families['all']:
                # Compute boundaries using sorted interpolation through numpy, independently of pandas quantile/searchsorted.
                boundaries=np.quantile(tr[signal].to_numpy(),[1/3,2/3]);a=np.sum(tr[signal].to_numpy()[:,None]>=boundaries,axis=1);b=np.sum(te[signal].to_numpy()[:,None]>=boundaries,axis=1)
                row=lookup[target,fold,signal];audit.eq([row['cut1'],row['cut2']],boundaries);audit.eq(row['train_counts'],[sum(a==i) for i in range(3)])
                for group in (1,2):tr[f'{signal}_bin{group}']=(a==group).astype(float);te[f'{signal}_bin{group}']=(b==group).astype(float)
            for family,signals in families.items():
                for expression in ('linear','binned'):
                    columns=signals if expression=='linear' else [f'{s}_bin{i}' for s in signals for i in (1,2)]
                    values=least_squares(tr,te,legacy+columns)
                    if target=='fill':values=np.clip(values,0,1)
                    audit.eq(values,pp[f'{expression}/{family}']);fit_n+=1
        for name,out in res.items():
            # Metric implementation was independently verified in EX036; inputs and predictions are independently reconstructed here.
            calculated=metrics(p,name,target)
            for fold,z in p.groupby('fold'):
                den=((z.legacy-z.y)**2).mean();calculated['folds'][str(fold)]['mse_gain_vs_legacy']=float(1-((z[name]-z.y)**2).mean()/den) if den>0 else None
            compare(out,calculated)
            # Independent utility algebra is reused, not the main implementation.
            audit.utility(out['utility'],p,name,target)
            for fold,z in p.groupby('fold'):audit.utility(out['folds'][str(fold)]['utility'],z,name,target)
    assert fit_n==504 and baseline_n==108
    paths=[Path(__file__),HERE/'src/followup.py',HERE/'protocols/expression_checks.json',*[HERE/'others'/f for f in ('predictions.csv','cutpoints.json','results.json','design_counts.json')]]
    output={'status':'PASS','checks':audit.CHECKS,'added_fits':fit_n,'baseline_refits':baseline_n,'added_specifications':126,'targets':9,'cutpoint_records':len(cuts),'prediction_rows':len(preds),'sha256':{str(p.relative_to(HERE)).replace('\\','/'):sha256(p.read_bytes()).hexdigest() for p in paths},'method':'Authenticated EX036 labels/features/previous independent audit. Rebuilt train-only tertiles, onehot reference group, nested legacy design, training-only normalization and augmented least-squares Ridge. All outputs recomputed with previously independently verified metrics; utilities rechecked by independent amount/count logic.','limitations':['Seen development samples and unadjusted exploratory intervals.','Per-fold equal-count utility is retrospective.','Incremental predictive evidence does not establish continuous-account qualification.']}
    (HERE/'others/independent_audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(output,ensure_ascii=False))
if __name__=='__main__':main()
