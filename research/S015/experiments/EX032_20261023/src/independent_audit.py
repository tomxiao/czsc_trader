"""Independent EX032 reconstruction; no imports from the study under review."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[key] = '1'
import json
from pathlib import Path
from hashlib import sha256
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parents[1]
refs = json.loads((HERE/'others/input_refs.json').read_bytes())
results = json.loads((HERE/'others/results.json').read_bytes())
predictions = pd.read_csv(HERE/'others/predictions.csv')
checks = 0
max_prediction_error = 0.0
def equal(a,b):
    global checks
    checks += 1
    if a is None or b is None:
        assert a is b, (a,b)
    elif isinstance(a,(int,float,np.number)):
        assert np.isclose(a,b,rtol=1e-8,atol=1e-10,equal_nan=True), (a,b)
    else:
        assert a == b, (a,b)
def frame(name):
    return pd.read_csv(EvidenceRef.from_dict(refs[name]).resolve(ROOT))
shares = frame('shares').sort_values('Date').reset_index(drop=True)
events = frame('events')
controls = ['r1','r5','vol20','pressure','range20']
labels = [('net',1),('net',3),('net',5),('entry_net',1)]
schemes = ['primary','price_sensitivity','local_time_sensitivity']
def money(y):
    v=np.asarray(y,dtype=float);v=v[np.isfinite(v)]
    return dict(n=len(v),positive_yuan=float(sum(v[v>0])*100000),negative_yuan=float(-sum(v[v<0])*100000),mean=float(v.mean()) if len(v) else None)
def check_money(actual,y):
    for k,v in money(y).items():equal(v,actual[k])
def estimate(y,state,cell):
    detail=[]
    for k in sorted(set(cell)):
        pos=y[(cell==k)&(state==1)&np.isfinite(y)]
        neg=y[(cell==k)&(state==-1)&np.isfinite(y)]
        if len(pos) and len(neg):
            weight=1.0/(1.0/len(pos)+1.0/len(neg))
            detail.append(dict(cell=int(k),positive_n=len(pos),negative_n=len(neg),positive_mean=float(pos.mean()),negative_mean=float(neg.mean()),weight=weight,delta=float(pos.mean()-neg.mean())))
    support=np.isin(cell,[r['cell'] for r in detail])&np.isfinite(y)&(state!=0)
    delta=sum(r['weight']*r['delta'] for r in detail)/sum(r['weight'] for r in detail) if detail else None
    return delta,support,detail
def score(y,p0,p1):
    mse0=float(np.mean(np.square(y-p0)));mse1=float(np.mean(np.square(y-p1)))
    value=dict(n=len(y),base_mse=mse0,state_mse=mse1,relative_mse_gain=1-mse1/mse0,filters={})
    for name,p in [('base',p0),('funded',p1)]:
        rejected=p<0;loss=-y[y<0].sum();profit=y[y>0].sum()
        caught=-y[(y<0)&rejected].sum();missed=y[(y>0)&rejected].sum()
        value['filters'][name]=dict(reject_n=int(rejected.sum()),negative_n=int(((y<0)&rejected).sum()),positive_n=int(((y>0)&rejected).sum()),caught_loss_yuan=float(caught*100000),missed_profit_yuan=float(missed*100000),caught_loss_fraction=float(caught/loss) if loss else None,missed_profit_fraction=float(missed/profit) if profit else None)
    return value
def check_score(expected,y,p0,p1):
    for k,v in score(y,p0,p1).items():
        if k=='filters':
            for model,values in v.items():
                for name,value in values.items():equal(value,expected[k][model][name])
        else:equal(v,expected[k])
def fit(trainx,trainy,testx):
    # Augmented least squares, independent of study normal-equation solver.
    mu=trainx.mean(axis=0);sd=trainx.std(axis=0);sd=np.where(sd==0,1,sd)
    a=np.column_stack((np.ones(len(trainy)),(trainx-mu)/sd))
    b=np.column_stack((np.ones(len(testx)),(testx-mu)/sd))
    regularizer=np.diag([0.0]+[10.0**0.5]*trainx.shape[1])
    coefficients=np.linalg.lstsq(np.vstack((a,regularizer)),np.r_[trainy,np.zeros(a.shape[1])],rcond=None)[0]
    return b@coefficients

audit=[];fold_audit=[];scalar=0;label_checks=0
date_index={str(v)[:10]:i for i,v in enumerate(shares.Date)}
event_by_day=events[events.horizon==1].set_index('date')
for row in events.itertuples():
    if np.isfinite(row.entry_net):
        equal(row.entry_net,row.entry_gross-row.buy_fee);label_checks+=1
        assert row.entry_date>row.date
        if row.entry_date in event_by_day.index:
            close=float(event_by_day.loc[row.entry_date,'close'])
            equal(row.entry_gross,row.quantity*(close-row.buy_price));label_checks+=1
    if row.status=='CLOSED':
        equal(row.net,row.quantity*(row.sell_price-row.buy_price)-row.buy_fee-row.sell_fee);label_checks+=1
        assert row.actual_exit_date>=row.planned_exit_date and row.actual_exit_date>row.entry_date

for lag in (1,3):
    f=frame('features_lag'+str(lag));state=np.sign(f.f20.to_numpy()).astype(int)
    for row in f.itertuples():
        j=date_index[row.date]-lag
        equal(row.f20,shares.TotalShare.iloc[j]/shares.TotalShare.iloc[j-20]-1)
        assert str(shares.Date.iloc[j])[:10]<row.date
        scalar+=1
    period=np.array([next(i for i,(lo,hi) in enumerate([(0,100),(100,184),(184,268),(268,352),(352,434)]) if lo<=p<hi) for p in f.position])
    sign=np.sign(f.r5.to_numpy()).astype(int);psign=np.sign(f.pressure.to_numpy()).astype(int)
    cellmap={'primary':period*3+sign+1,'price_sensitivity':(period*3+sign+1)*3+psign+1,'local_time_sensitivity':np.array(f.position//21)*3+sign+1}
    for label,h in labels:
        key=f'{label}_h{h}';ev=events[events.horizon==h].set_index('position').loc[f.position]
        y=ev[label].to_numpy(float)/100000
        if label=='net':y=np.where(ev.status.to_numpy()=='CLOSED',y,np.nan)
        known=ev.actual_exit_date.to_numpy() if label=='net' else ev.entry_date.to_numpy()
        for scheme,cell in cellmap.items():
            expected=results[str(lag)]['conditions'][key][scheme]
            delta,support,detail=estimate(y,state,cell);equal(delta,expected['delta'])
            equal(len(detail),expected['supported_cells']);equal(int(support.sum()),expected['support_n'])
            equal(int((support&(state==1)).sum()),expected['positive_support_n']);equal(int((support&(state==-1)).sum()),expected['negative_support_n'])
            equal(sum(r['weight'] for r in detail),expected['weight_sum'])
            eligible=np.isfinite(y)&(state!=0)
            equal(int(eligible.sum()),expected['eligible_n']);equal(support.sum()/eligible.sum(),expected['support_fraction'])
            equal(int((np.isfinite(y)&(state==0)).sum()),expected['zero_n'])
            for actual,want in zip(detail,expected['common_cells']):
                for k,v in actual.items():equal(v,want[k])
            equal(len(expected['cells']),len(set(cell)))
            for row in expected['cells']:
                mask=cell==row['cell'];equal(row['first_date'],f.date[mask].min());equal(row['last_date'],f.date[mask].max())
                for name,s in [('positive',1),('negative',-1),('zero',0)]:check_money(row[name],y[mask&(state==s)])
                equal(row['both_states'],bool(support[mask].any()))
            for name,s in [('positive',1),('negative',-1)]:
                check_money(expected[name+'_all'],y[state==s]);check_money(expected['outside_'+name],y[(state==s)&~support])
            equal(float(np.nanmean(y[state==1])-np.nanmean(y[state==-1])),expected['crude_delta'])
            for name in controls:
                v=f[name].to_numpy();diff=sum(r['weight']*(v[support&(cell==r['cell'])&(state==1)].mean()-v[support&(cell==r['cell'])&(state==-1)].mean()) for r in detail)/sum(r['weight'] for r in detail)
                sd=v[support].std(ddof=1)
                for k,value in [('weighted_difference',diff),('support_pooled_sd',sd),('standardized_difference',diff/sd)]:equal(value,expected['control_balance'][name][k])
            omit=y.copy();eligible_ix=np.flatnonzero(np.isfinite(y));rank=sorted(eligible_ix,key=lambda j:abs(y[j]))[-5:];omit[rank]=np.nan
            omitted,omitsupport,omitdetails=estimate(omit,state,cell)
            equal(omitted,expected['omit_largest5']['delta']);equal(int(omitsupport.sum()),expected['omit_largest5']['support_n'])
            rng=np.random.default_rng(13);draws=[];counts=[]
            for b in range(499):
                index=np.concatenate([np.arange(t,t+20) for t in rng.integers(0,415,22)])[:434]
                d,s,_=estimate(y[index],state[index],cell[index]);counts.append(int(s.sum()))
                if d is not None:draws.append(d)
            bs=expected['bootstrap'];equal(len(draws),bs['valid_draws']);equal(min(counts),bs['support_n_min']);equal(max(counts),bs['support_n_max']);equal(float(np.median(counts)),bs['support_n_median'])
            for actual,want in zip(np.quantile(draws,[.025,.975]),bs['ci95']):equal(actual,want)
            audit.append(dict(lag=lag,target=key,scheme=scheme,support_n=int(support.sum()),eligible_n=int(eligible.sum()),delta=delta))
        x0=f[controls].to_numpy();x1=np.column_stack((x0,state==1,state==0));all_y=[];all_base=[];all_state=[];all_positions=[]
        expected=results[str(lag)]['models'][key]
        for lo,hi in [(100,184),(184,268),(268,352),(352,434)]:
            boundary=f.date.iloc[lo];train=np.array([(i<lo and np.isfinite(y[i]) and isinstance(known[i],str) and known[i]<boundary) for i in range(434)])
            test=(f.position.to_numpy()>=lo)&(f.position.to_numpy()<hi)&np.isfinite(y)
            base=fit(x0[train],y[train],x0[test]);funded=fit(x1[train],y[train],x1[test])
            saved=predictions[(predictions.lag==lag)&(predictions.target==key)&(predictions.fold==f'{lo}:{hi}')].sort_values('position')
            equal(saved.position.tolist(),f.position[test].tolist())
            for col,v in [('y',y[test]),('base',base),('funded',funded)]:
                err=float(np.max(np.abs(saved[col].to_numpy()-v)));max_prediction_error=max(max_prediction_error,err);equal(err,0.0)
            fold=expected['folds'][f'{lo}:{hi}'];check_score(fold,y[test],base,funded)
            equal(int(train.sum()),fold['train_n']);equal(max(known[train]),fold['max_train_known_date']);equal(boundary,fold['first_test_decision'])
            fold_audit.append(dict(lag=lag,target=key,fold=f'{lo}:{hi}',train_n=int(train.sum()),test_n=int(test.sum()),max_train_known_date=max(known[train]),first_test_decision=boundary))
            all_y.extend(y[test]);all_base.extend(base);all_state.extend(funded);all_positions.extend(f.position[test])
        yy=np.array(all_y);bb=np.array(all_base);ss=np.array(all_state)
        check_score(expected,yy,bb,ss)
        keep=np.ones(len(yy),bool);keep[sorted(range(len(yy)),key=lambda i:-abs(yy[i]))[:5]]=False
        check_score(expected['omit_largest5'],yy[keep],bb[keep],ss[keep])
        axis=np.full(434,np.nan);axis[all_positions]=(yy-bb)**2-(yy-ss)**2
        rng=np.random.default_rng(13);draw=[]
        for b in range(499):
            idx=np.concatenate([np.arange(t,t+20) for t in rng.integers(0,415,22)])[:434];draw.append(float(np.nanmean(axis[idx])))
        for a,b in zip(np.quantile(draw,[.025,.975]),expected['paired_mse_improvement_ci95']):equal(a,b)

out={'status':'PASS','checks':checks,'scalar_state_checks':scalar,'label_arithmetic_checks':label_checks,'matched_conditions':len(audit),'paired_models':8,'folds':fold_audit,'matched':audit,'maximum_prediction_absolute_error':max_prediction_error,'input_hashes':{k:v['sha256'] for k,v in refs.items() if isinstance(v,dict) and 'sha256' in v},'study_source_sha256':sha256((HERE/'src/study.py').read_bytes()).hexdigest(),'interpretation_limits':['Fixed coarse strata do not equate all prices or eliminate confounding; covariance balance remains report-only.','Overlap support is restricted: all-positive time cells cannot identify positive-minus-negative effects.','Lagging shares ensures dated dependencies are prior to decision; it does not establish point-in-time revision history.','Labels are overlapping independent events; captured loss and missed profit are event sums rather than executable account effects.','Post-selection diagnostics on the previously observed development pool are not independent confirmation or strategy qualification.']}
(HERE/'others/independent_audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
print(json.dumps({k:out[k] for k in ('status','checks','scalar_state_checks','label_arithmetic_checks','matched_conditions','paired_models','maximum_prediction_absolute_error')}))
