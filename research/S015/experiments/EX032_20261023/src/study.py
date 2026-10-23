"""Fixed state comparisons; observational support is not causal identification."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import argparse
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,ExecutionResources,EvidenceRef,ExperimentRef,MaterialEvidenceWrite
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent
EX=ExperimentRef('S015',HERE.name)
CONTROLS=['r1','r5','vol20','pressure','range20'];STATE=['state_positive','state_zero']
SEGMENTS=((0,100),(100,184),(184,268),(268,352),(352,434))
TARGETS=(('net',1),('net',3),('net',5),('entry_net',1))
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def context():return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
def material(p):return publish_evidence(context(),MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))
def prepare():
    assert not (HERE/'others/source_ref.json').exists()
    save(HERE/'others/source_ref.json',material(Path(__file__)).to_dict())
def inputs():
    source=EvidenceRef.from_dict(read(HERE/'others/source_ref.json'));source.resolve(ROOT)
    assert sha256(Path(__file__).read_bytes()).hexdigest()==source.sha256
    r=read(BASE/'EX027_20261023/others/published_refs.json')['materials'];refs={}
    frames={}
    for lag in (1,3):
        ref=EvidenceRef.from_dict(r[f'others/features_lag{lag}.csv']);x=pd.read_csv(ref.resolve(ROOT));refs[f'features_lag{lag}']=ref.to_dict()
        assert len(x)==434 and x.position.tolist()==list(range(434)) and x.date.is_unique
        x['state_positive']=(x.f20>0).astype(float);x['state_zero']=(x.f20==0).astype(float)
        x['state']=np.sign(x.f20).astype(int)
        x['period']=np.searchsorted([100,184,268,352],x.position,side='right')
        x['price_sign']=np.sign(x.r5).astype(int);x['pressure_sign']=np.sign(x.pressure).astype(int)
        x['primary']=x.period*3+x.price_sign+1
        x['price_sensitivity']=x.primary*3+x.pressure_sign+1
        x['local_time_sensitivity']=(x.position//21)*3+x.price_sign+1
        frames[lag]=x
    ownref=EvidenceRef.from_dict(r['others/own_shares.csv']);s=pd.read_csv(ownref.resolve(ROOT)).sort_values('Date').reset_index(drop=True);refs['shares']=ownref.to_dict()
    idx={v[:10]:i for i,v in enumerate(s.Date)};checks=0
    for lag,x in frames.items():
        for row in x.itertuples():
            t=idx[row.date]-lag
            z=float(s.TotalShare.iloc[t])/float(s.TotalShare.iloc[t-20])-1
            assert abs(z-row.f20)<1e-12 and np.sign(z)==row.state;checks+=1
            assert s.Date.iloc[t][:10]<row.date
    er=EvidenceRef.from_dict(read(BASE/'EX026_20261023/others/delivery_validation.json')['materials']['events.csv']);e=pd.read_csv(er.resolve(ROOT));refs['events']=er.to_dict()
    assert len(e)==1302 and sum(e.status=='CLOSED')==1269
    refs['prior_reports']=[read(BASE/f'EX{n:03d}_20261023/report_ref.json')['report'] for n in (28,30,31)]
    for r0 in refs['prior_reports']:EvidenceRef.from_dict(r0).resolve(ROOT)
    save(HERE/'others/input_refs.json',refs);save(HERE/'others/feature_checks.json',{'status':'PASS','scalar_state_checks':checks,'lag_values':[1,3],'new_data_queries':0})
    return frames,e
def dataset(x,e,target,h):
    old=e[e.horizon==h].drop(columns=[c for c in x.columns if c in e.columns and c not in ('date','position')])
    g=x.merge(old,on=['date','position'],validate='one_to_one')
    if target=='net':valid=g.status.eq('CLOSED');known=g.actual_exit_date
    else:valid=g.entry_net.notna();known=g.entry_date
    g['y']=g[target].where(valid)/100000;g['known_date']=known
    assert len(g)==434
    return g
def estimate(y,state,cells):
    valid=np.isfinite(y);p=valid&(state>0);n=valid&(state<0)
    size=int(cells.max())+1
    np_=np.bincount(cells[p],minlength=size);nn=np.bincount(cells[n],minlength=size)
    sp=np.bincount(cells[p],weights=y[p],minlength=size);sn=np.bincount(cells[n],weights=y[n],minlength=size)
    overlap=(np_>0)&(nn>0);ids=np.flatnonzero(overlap)
    if not len(ids):return {'delta':None,'support_n':0,'supported_cells':0},[]
    weights=np_[ids]*nn[ids]/(np_[ids]+nn[ids]);diff=sp[ids]/np_[ids]-sn[ids]/nn[ids]
    delta=float(np.average(diff,weights=weights));support=overlap[cells]&valid&(state!=0)
    rows=[{'cell':int(i),'positive_n':int(np_[i]),'negative_n':int(nn[i]),'positive_mean':float(sp[i]/np_[i]),'negative_mean':float(sn[i]/nn[i]),'weight':float(w),'delta':float(d)} for i,w,d in zip(ids,weights,diff)]
    return {'delta':delta,'support_n':int(support.sum()),'supported_cells':len(ids),'positive_support_n':int((support&p).sum()),'negative_support_n':int((support&n).sum()),'weight_sum':float(weights.sum())},rows
def amounts(g):
    v=g.y.dropna();return {'n':len(v),'positive_yuan':float(v.clip(lower=0).sum()*100000),'negative_yuan':float(-v.clip(upper=0).sum()*100000),'mean':float(v.mean()) if len(v) else None}
def matched(g,scheme):
    y=g.y.to_numpy(float);s=g.state.to_numpy(int);c=g[scheme].to_numpy(int)
    out,rows=estimate(y,s,c);used=[r['cell'] for r in rows]
    allrows=[]
    for cell,sub in g.groupby(scheme,sort=True):
        row={'cell':int(cell),'first_date':sub.date.min(),'last_date':sub.date.max()}
        for name,sign in [('positive',1),('negative',-1),('zero',0)]:row[name]=amounts(sub[sub.state==sign])
        row['both_states']=int(cell) in used;allrows.append(row)
    valid=g.y.notna()&g.state.ne(0);support=valid&g[scheme].isin(used)
    out['eligible_n']=int(valid.sum());out['support_fraction']=float(support.sum()/valid.sum()) if valid.sum() else None
    out['zero_n']=int((g.y.notna()&g.state.eq(0)).sum())
    out['positive_all']=amounts(g[g.state>0]);out['negative_all']=amounts(g[g.state<0])
    out['crude_delta']=out['positive_all']['mean']-out['negative_all']['mean']
    out['outside_positive']=amounts(g[(g.state>0)&~support]);out['outside_negative']=amounts(g[(g.state<0)&~support])
    out['cells']=allrows;out['common_cells']=rows;out['control_balance']={}
    for name in CONTROLS:
        diffs=[];weights=[]
        for row in rows:
            sub=g[support&g[scheme].eq(row['cell'])]
            diffs.append(float(sub.loc[sub.state>0,name].mean()-sub.loc[sub.state<0,name].mean()));weights.append(row['weight'])
        sd=float(g.loc[support,name].std(ddof=1)) if support.sum()>1 else None
        diff=float(np.average(diffs,weights=weights)) if weights else None
        out['control_balance'][name]={'weighted_difference':diff,'support_pooled_sd':sd,'standardized_difference':diff/sd if sd and diff is not None else None}
    rng=np.random.default_rng(13);draws=[];counts=[]
    for _ in range(499):
        starts=rng.integers(0,415,size=22);idx=np.concatenate([np.arange(t,t+20) for t in starts])[:434]
        b,_=estimate(y[idx],s[idx],c[idx]);counts.append(b['support_n'])
        if b['delta'] is not None:draws.append(b['delta'])
    out['bootstrap']={'valid_draws':len(draws),'ci95':np.quantile(draws,[.025,.975]).tolist() if draws else None,'support_n_min':min(counts),'support_n_median':float(np.median(counts)),'support_n_max':max(counts)}
    # Predeclared largest absolute target omission, retaining the unmodified estimate above.
    yy=y.copy();ix=np.flatnonzero(np.isfinite(yy));rank=ix[np.argsort(np.abs(yy[ix]),kind='stable')[-5:]];yy[rank]=np.nan
    out['omit_largest5']=estimate(yy,s,c)[0]
    return out
def ridge(train,test,cols):
    a=train[cols].to_numpy(float);b=test[cols].to_numpy(float);m=a.mean(0);sd=a.std(0);sd[sd==0]=1
    a=np.column_stack([np.ones(len(a)),(a-m)/sd]);b=np.column_stack([np.ones(len(b)),(b-m)/sd])
    penalty=np.eye(a.shape[1])*10;penalty[0,0]=0
    return b@np.linalg.solve(a.T@a+penalty,a.T@train.y.to_numpy(float))
def metrics(g):
    y=g.y.to_numpy(float);be=(g.base-y)**2;se=(g.funded-y)**2
    out={'n':len(g),'base_mse':float(be.mean()),'state_mse':float(se.mean()),'relative_mse_gain':float(1-se.mean()/be.mean()),'filters':{}}
    for k in ('base','funded'):
        rejected=g[k]<0;pos=np.maximum(y,0);neg=np.maximum(-y,0)
        out['filters'][k]={'reject_n':int(rejected.sum()),'negative_n':int(((y<0)&rejected).sum()),'positive_n':int(((y>0)&rejected).sum()),'caught_loss_yuan':float(neg[rejected].sum()*100000),'missed_profit_yuan':float(pos[rejected].sum()*100000),'caught_loss_fraction':float(neg[rejected].sum()/neg.sum()) if neg.sum() else None,'missed_profit_fraction':float(pos[rejected].sum()/pos.sum()) if pos.sum() else None}
    return out
def models(g,lag,target):
    preds=[];folds={}
    for lo,hi in SEGMENTS[1:]:
        date=g.date.iloc[lo];train=g[(g.position<lo)&g.y.notna()&(g.known_date<date)];test=g[(g.position>=lo)&(g.position<hi)&g.y.notna()]
        assert len(train)>=80 and (train.known_date<date).all()
        p=test[['date','position','y','state']].copy();p['base']=ridge(train,test,CONTROLS);p['funded']=ridge(train,test,CONTROLS+STATE)
        p['fold']=f'{lo}:{hi}';p['lag']=lag;p['target']=target;preds.append(p)
        folds[f'{lo}:{hi}']={**metrics(p),'train_n':len(train),'max_train_known_date':train.known_date.max(),'first_test_decision':date}
    p=pd.concat(preds,ignore_index=True);out=metrics(p);out['folds']=folds
    out['omit_largest5']=metrics(p.drop(p.y.abs().nlargest(5).index))
    a=p.set_index('position').reindex(range(434));loss=((a.base-a.y)**2-(a.funded-a.y)**2).to_numpy(float)
    rng=np.random.default_rng(13);draws=[]
    for _ in range(499):
        ix=np.concatenate([np.arange(t,t+20) for t in rng.integers(0,415,size=22)])[:434];z=loss[ix];z=z[np.isfinite(z)]
        if len(z):draws.append(float(z.mean()))
    out['paired_mse_improvement_ci95']=np.quantile(draws,[.025,.975]).tolist()
    return out,p
def run():
    assert not (HERE/'others/results.json').exists()
    frames,e=inputs();out={};preds=[]
    for lag,x in frames.items():
        z={'conditions':{},'models':{}};runs=[];start=0
        for end in range(1,435):
            if end==434 or x.state.iloc[end]!=x.state.iloc[start]:
                runs.append({'start':start,'end_exclusive':end,'state':int(x.state.iloc[start]),'length':end-start,'left_censored':start==0,'right_censored':end==434});start=end
        z['runs']=runs
        for label,h in TARGETS:
            key=f'{label}_h{h}';g=dataset(x,e,label,h)
            z['conditions'][key]={scheme:matched(g,scheme) for scheme in ('primary','price_sensitivity','local_time_sensitivity')}
            z['models'][key],p=models(g,lag,key);preds.append(p)
        out[str(lag)]=z;print('lag',lag,'complete',flush=True)
    pd.concat(preds,ignore_index=True).to_csv(HERE/'others/predictions.csv',index=False)
    save(HERE/'others/results.json',out)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run']);{'prepare':prepare,'run':run}[p.parse_args().mode]()
