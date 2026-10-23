"""Independent attribution, causal risk threshold and interval-DP audit."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import importlib.util,json
from bisect import bisect_right
from hashlib import sha256
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[3];BASE=HERE.parent
def read(p):return json.loads(p.read_bytes())
def module(p,name):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def fit(train,test,cols):
    a=train[cols].to_numpy();b=test[cols].to_numpy();mu=a.mean(0);sd=a.std(0);sd[sd==0]=1
    a=np.c_[np.ones(len(a)),(a-mu)/sd];b=np.c_[np.ones(len(b)),(b-mu)/sd];pen=np.diag([0.]+[np.sqrt(10)]*len(cols))
    coef=np.linalg.lstsq(np.vstack([a,pen]),np.r_[train.y,np.zeros(len(cols)+1)],rcond=None)[0]
    return a@coef,b@coef,dict(zip(['intercept',*cols],coef))
def utility(actual,p,variant):
    y=p.payoff.to_numpy();keep=p[f'keep/{variant}'].to_numpy(bool)
    audit.check_amount(actual['selected'],y[keep]);audit.check_amount(actual['excluded'],y[~keep])
    audit.eq(actual['caught_loss_fraction'],audit.ratio(-sum(y[(~keep)&(y<0)]),-sum(y[y<0])))
    audit.eq(actual['missed_profit_fraction'],audit.ratio(sum(y[(~keep)&(y>0)]),sum(y[y>0])))
    audit.eq(actual['retained_risk_mean'],p.loc[keep,'y'].mean() if keep.any() else None);audit.eq(actual['retained_event_sum'],sum(y[keep]))
def frequency(events,positions,h,dates):
    lookup={d:i for i,d in enumerate(dates)};intervals=[]
    for row in events.itertuples():
        if row.horizon==h and row.position in positions and row.status=='CLOSED':intervals.append((lookup[row.entry_date],lookup[row.actual_exit_date]))
    intervals.sort(key=lambda t:(t[1],t[0]));counts=[]
    for end in range(159,434):
        window=[(s,e) for s,e in intervals if end-59<=e<=end];ends=[e for s,e in window];dp=[0]
        for j,(start,finish) in enumerate(window):
            # Maximum interval cardinality with equality allowed; earlier endpoints only.
            predecessor=bisect_right(ends,start,0,j);dp.append(max(dp[-1],1+dp[predecessor]))
        counts.append(dp[-1])
    return counts
def main():
    global audit
    refs=read(HERE/'others/protocol_refs.json')
    for name,sub in [('attribution.py','src'),('attribution.json','protocols')]:assert EvidenceRef.from_dict(refs[name]).resolve(ROOT).read_bytes()==(HERE/sub/name).read_bytes()
    inputs=read(HERE/'others/input_refs.json');src=read(BASE/'EX036_20261023/others/published_refs.json')['materials'];path=BASE/'EX036_20261023/src/independent_audit.py';assert EvidenceRef.from_dict(src['src/independent_audit.py']).resolve(ROOT).read_bytes()==path.read_bytes();audit=module(path,'confirmed_amount_auditor')
    x=pd.read_csv(EvidenceRef.from_dict(inputs['evidence']['others/model_features.csv']).resolve(ROOT));labels=pd.read_csv(EvidenceRef.from_dict(inputs['evidence']['others/labels.csv']).resolve(ROOT));families=read(EvidenceRef.from_dict(inputs['dictionary']).resolve(ROOT))['families'];events=pd.read_csv(EvidenceRef.from_dict(inputs['events']).resolve(ROOT));previous=pd.read_csv(EvidenceRef.from_dict(inputs['prior_predictions']).resolve(ROOT))
    pfull=pd.read_csv(HERE/'others/predictions.csv');results=read(HERE/'others/results.json');thresholds=read(HERE/'others/thresholds.json');lookup={(a['case'],a['fold'],a['variant']):a for a in thresholds};coefs=read(HERE/'others/coefficients.json');coeflookup={(a['case'],a['fold']):a for a in coefs};assert len(lookup)==320 and len(coeflookup)==32
    net3=labels[labels.target=='net3'].set_index('position').y;fits=0;dpwindows=0
    for case,res in results.items():
        target,family,mode=case.split('/');signals=families[family];variants={'baseline':[],'full':signals,**{f'only/{s}':[s] for s in signals},**{f'without/{s}':[t for t in signals if t!=s] for s in signals}};assert set(res)==set(variants)
        g=x.merge(labels[labels.target==target].drop(columns='date'),on='position',validate='one_to_one');g['payoff']=g.position.map(net3) if target in ('loss3','drawdown3') else g.y;p=pfull[pfull['case']==case].reset_index(drop=True)
        base=['r1','r5','vol20','range20','pressure']+(['held_unreal'] if target.startswith('hold') else [])
        for fold,(lo,hi) in enumerate(((100,184),(184,268),(268,352),(352,434))):
            train=g[(g.position<lo)&g.y.notna()&(g.known_date<g.date.iloc[lo])].copy();test=g[(g.position>=lo)&(g.position<hi)&g.y.notna()].copy();pp=p[p.fold==fold]
            audit.eq(pp.position.tolist(),test.position.tolist());audit.eq(pp.y,test.y);audit.eq(pp.payoff,test.payoff);audit.eq(pp.r5,test.r5);assert train.known_date.max()<g.date.iloc[lo]
            if mode=='binned':
                for s in signals:
                    q=np.quantile(train[s],[1/3,2/3]);a=np.sum(train[s].to_numpy()[:,None]>=q,axis=1);b=np.sum(test[s].to_numpy()[:,None]>=q,axis=1)
                    for i in (1,2):train[f'{s}_bin{i}']=(a==i).astype(float);test[f'{s}_bin{i}']=(b==i).astype(float)
            for variant,cs in variants.items():
                columns=base+(cs if mode=='linear' else [f'{s}_bin{i}' for s in cs for i in (1,2)]);training,values,coef=fit(train,test,columns);audit.eq(pp[variant],values);fits+=1
                threshold=float(np.median(training)) if target in ('loss3','drawdown3') else 0
                row=lookup[case,fold,variant]
                for k,v in [('threshold',threshold),('train_n',len(train)),('max_train_known_date',train.known_date.max()),('test_start',g.date.iloc[lo])]:audit.eq(row[k],v)
                keep=values<=threshold if target in ('loss3','drawdown3') else values>=threshold;audit.eq(pp[f'keep/{variant}'].to_numpy(bool),keep)
                if variant=='full':
                    expected=coeflookup[case,fold]['standardized_coefficients'];assert set(expected)==set(coef)
                    for k,v in coef.items():audit.eq(expected[k],v)
                if variant in ('baseline','full'):
                    ref='legacy' if variant=='baseline' else mode+'/'+family;prior=previous[(previous.target==target)&(previous.fold==fold)];audit.eq(pp[variant].to_numpy(),prior[ref].to_numpy())
        for variant,out in res.items():
            audit.eq(out['n'],len(p));audit.eq(out['mse_gain_vs_baseline'],1-((p[variant]-p.y)**2).mean()/((p.baseline-p.y)**2).mean());utility(out['utility'],p,variant)
            for fold,z in p.groupby('fold'):
                f=out['folds'][str(fold)];audit.eq(f['mse_gain'],1-((z[variant]-z.y)**2).mean()/((z.baseline-z.y)**2).mean());utility(f['utility'],z,variant)
            for state,z in p.groupby(p.r5>0):utility(out['states']['r5_positive' if state else 'r5_nonpositive'],z,variant)
            utility(out['omit_largest5_utility'],p.drop(p.payoff.abs().nlargest(5).index),variant)
            change=np.where(p[f'keep/{variant}'],p.payoff,0)-np.where(p['keep/baseline'],p.payoff,0);gain=out['retained_increment_vs_baseline'];audit.eq(gain['mean_per_event'],change.mean());delta=np.full(434,np.nan);delta[p.position.to_numpy(int)]=change;rng=np.random.default_rng(13);boot=[]
            for _ in range(499):
                starts=rng.integers(415,size=22);ix=(starts[:,None]+np.arange(20)).reshape(-1)[:434];boot.append(np.nanmean(delta[ix]))
            audit.eq(gain['ci95'],np.quantile(boot,[.025,.975]))
            if not target.startswith('hold'):
                counts=frequency(events,set(p.loc[p[f'keep/{variant}'],'position']),5 if target=='net5' else 3,x.date.tolist());f=out['frequency_upper_bound'];audit.eq(f['counts'],counts);audit.eq(f['median_max'],np.median(counts));audit.eq(f['at_least3_windows'],sum(n>=3 for n in counts));audit.eq(f['windows'],275);dpwindows+=275
    assert fits==320 and dpwindows==16500
    paths=[Path(__file__),HERE/'src/attribution.py',HERE/'protocols/attribution.json',*[HERE/'others'/f for f in ('predictions.csv','thresholds.json','coefficients.json','results.json')]]
    output={'status':'PASS','checks':audit.CHECKS,'fits':fits,'cases':8,'variants':80,'thresholds':320,'coefficient_sets':32,'frequency_windows_checked_by_dynamic_programming':dpwindows,'sha256':{str(p.relative_to(HERE)).replace('\\','/'):sha256(p.read_bytes()).hexdigest() for p in paths},'method':'Authenticated inputs; independent augmented-lstsq coefficients and predictions; train-only median fitted risk thresholds; actual net3 payoff for risk rules; all amounts, folds/states, omissions and block bootstrap; dynamic-programming nonoverlap bounds.','limitations':['Adaptive seen-development attribution, not independent validation.','Frequency is an optimistic bound on modeled-period event exits, not full-account frequency acceptance.','Event amounts and holding increments are not account returns.']}
    (HERE/'others/independent_audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(output,ensure_ascii=False))
if __name__=='__main__':main()
