"""Five-round, prospectively specified funding diagnostics; no strategy account."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
import argparse
from dataclasses import fields, is_dataclass
from collections.abc import Mapping
from datetime import date
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from uuid import UUID
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context, create_experiment, ExperimentRequest, publish_evidence
from czsc_trader.research_tools import ResearchBatchRef, ExecutionResources, ExperimentRef, EvidenceRef, MaterialEvidenceWrite
from dataflows import DataRequest, Dataset, DataCoverageRequirement, PreparedDataRef

ROOT=Path(__file__).resolve().parents[5]
BASE=ROOT/'research/S015/experiments'
HOME=BASE/'EX027_20261023'
SEGMENTS=((0,100),(100,184),(184,268),(268,352),(352,434))
FEATURES=['f1','f5','f20','persist5']
CONTROLS=['r1','r5','vol20','pressure','range20']
def read(p):return json.loads(p.read_bytes())
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def ctx():return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
def material(ex,p):return publish_evidence(ctx(),MaterialEvidenceWrite(ex,p.stem,p.read_bytes(),{'.json':'application/json','.py':'text/x-python','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))
def folder(n):return BASE/f'EX{26+n:03d}_20261023'

def allocate():
    assert not (HOME/'others/round_refs.json').exists()
    p=EvidenceRef.from_dict(read(HOME/'others/protocol_ref.json'));p.resolve(ROOT)
    own=ExperimentRef('S015',HOME.name)
    source=material(own,Path(__file__))
    refs={'protocol':p.to_dict(),'source':source.to_dict(),'rounds':{'1':own.to_dict()}}
    titles=['份额持续需求与竞争解释','份额与价格的机制四格','资金相对量价预测增量','信息延迟和盈利遗漏反证']
    protocol=read(p.resolve(ROOT))
    for n,title in enumerate(titles,2):
        ex=create_experiment(ctx(),ExperimentRequest(title,protocol['rounds'][n-1]['question'],date(2026,10,23)))
        assert ex.experiment_id==folder(n).name
        save(folder(n)/'protocols/round.json',{'parent':p.to_dict(),'source':source.to_dict(),'round':protocol['rounds'][n-1]})
        rr=material(ex,folder(n)/'protocols/round.json')
        refs['rounds'][str(n)]=ex.to_dict();refs[f'round{n}_protocol']=rr.to_dict()
    save(HOME/'others/round_refs.json',refs)
    print('Allocated EX028..EX031; fixed source and protocol published',flush=True)

def load_inputs():
    published=read(HOME/'others/round_refs.json')
    source=EvidenceRef.from_dict(published['source']);source.resolve(ROOT)
    assert sha256(Path(__file__).read_bytes()).hexdigest()==source.sha256
    spec=importlib.util.spec_from_file_location('ex026',BASE/'EX026_20261023/src/study.py')
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    refs=old.sources();adj,raw,bars,rules,ids=old.inputs(refs)
    for frame in (adj,raw,bars):frame.attrs={}
    record=read(HOME/'others/own_share_preparation_resolved.json')
    p=record['reference']; prep=PreparedDataRef(UUID(p['space_id']),UUID(p['preparation_id']),p['manifest_sha256'])
    req=DataRequest(Dataset.ETF_SHARE_SIZE,'159326.SZ','2024-09-10','2026-10-21','2026-10-21',coverage=DataCoverageRequirement(0,508,508))
    got=ctx().data.fetch(req,prepared=prep);assert got.ready,got.error
    assert got.identity.content_sha256==read(HOME/'others/own_share_identity.json')['content_sha256']
    shares=got.dataframe.copy();shares.attrs={}
    shares.Date=pd.to_datetime(shares.Date);raw.Date=pd.to_datetime(raw.Date)
    assert len(shares)==508 and not shares.Date.duplicated().any()
    assert set(shares.Date)==set(raw.Date.iloc[1:])
    assert shares.TotalShare.gt(0).all() and np.isfinite(shares.TotalShare).all()
    vals=shares.set_index('Date').TotalShare.reindex(raw.Date).reset_index(drop=True).astype(float)
    assert vals.isna().sum()==1 and pd.isna(vals.iloc[0])
    e_ref=EvidenceRef.from_dict(read(BASE/'EX026_20261023/others/delivery_validation.json')['materials']['events.csv'])
    events=pd.read_csv(e_ref.resolve(ROOT))
    # Recompute controls from authenticated raw prices; discard duplicated old controls.
    events=events.drop(columns=[k for k in CONTROLS if k in events.columns])
    assert len(events)==1302 and len(events[events.status=='CLOSED'])==1269
    save(HOME/'others/input_refs.json',{'prior':{k:v.to_dict() for k,v in refs.items()},'events':e_ref.to_dict(),'funding_identity':read(HOME/'others/own_share_identity.json'),'preparation':record})
    x0=pd.DataFrame({'date':raw.Date.dt.strftime('%Y-%m-%d'),'r1':raw.Close.pct_change(fill_method=None),'r5':raw.Close.pct_change(5,fill_method=None),'vol20':raw.Close.pct_change(fill_method=None).rolling(20).std(),'pressure':raw.Close/(raw.Amount/raw.Volume)-1,'range20':((raw.High-raw.Low)/raw.Close).rolling(20).mean()})
    frames={}
    for lag in (1,2,3):
        x=x0.copy()
        for k in (1,5,20):x[f'f{k}']=vals.shift(lag)/vals.shift(lag+k)-1
        change=vals.diff();up=change.gt(0).astype(float).where(change.notna())
        x['persist5']=up.rolling(5,min_periods=5).mean().shift(lag)-.5
        x=x.iloc[75:].reset_index(drop=True);x['position']=np.arange(434);x['lag']=lag
        assert len(x)==434 and np.isfinite(x[FEATURES+CONTROLS]).all().all()
        x.to_csv(HOME/f'others/features_lag{lag}.csv',index=False)
        frames[lag]=x
    facts={'rows':508,'warmup_rows':74,'development_rows':434,'missing_source_dates':['2024-09-09'],'missing_development_features':0,'units':'10,000 ETF shares; growth is dimensionless, not cash flow','share_min':float(vals.min()),'share_max':float(vals.max()),'unchanged_transitions':int(vals.diff().eq(0).sum()),'nonzero_transitions':int(vals.diff().ne(0).where(vals.diff().notna(),False).sum()),'largest_absolute_daily_growth':float(vals.pct_change(fill_method=None).abs().max()),'availability':'D+1 08:30 assumption; historical revision/publication timestamps not authenticated','same_index_peer':'current directory only own listed ETF and 562720.SH status P with null listing date; no usable historical comparison basket','financing':'fixed start-date probe empty; endpoint probe nonempty; no formal DFLS margin binding; not admitted'}
    # Independent scalar reconstruction at every date for every lag and definition.
    count=0
    for lag,x in frames.items():
        for j in range(434):
            t=j+75-lag
            for k in (1,5,20):
                assert abs(x.iloc[j][f'f{k}']-(float(vals.iloc[t])/float(vals.iloc[t-k])-1))<1e-12
                count+=1
            expect=sum(float(vals.iloc[q])>float(vals.iloc[q-1]) for q in range(t-4,t+1))/5-.5
            assert abs(x.iloc[j].persist5-expect)<1e-12;count+=1
    # Development decision features never depend on D=T or later shares.
    facts['scalar_feature_checks']=count
    facts['maximum_source_position_relative_to_decision']=-1
    save(HOME/'others/survey_results.json',facts)
    return frames,events

def stats(g,label='net'):
    z=g[label].dropna().astype(float);pos=float(z[z>0].sum());neg=float(-z[z<0].sum())
    return {'n':len(z),'mean_return':float(z.mean()/100000) if len(z) else None,'median_return':float(z.median()/100000) if len(z) else None,'positive_n':int((z>0).sum()),'negative_n':int((z<0).sum()),'positive_yuan':pos,'negative_yuan':neg,'net_yuan':float(z.sum())}
def grouping(g,name):
    allstats=stats(g);out={'all':allstats,'groups':{}}
    for tag,mask in [('positive',g[name]>0),('negative',g[name]<0),('zero',g[name]==0)]:
        sub=g[mask];s=stats(sub)
        s.update(captured_positive_fraction=s['positive_yuan']/allstats['positive_yuan'] if allstats['positive_yuan'] else None,borne_negative_fraction=s['negative_yuan']/allstats['negative_yuan'] if allstats['negative_yuan'] else None,entry_net=stats(sub,'entry_net'),entry_gross_yuan=float(sub.entry_gross.sum()),subsequent_gross_yuan=float(sub.subsequent_gross.sum()))
        out['groups'][tag]=s
    return out
def joined(x,e,h):
    g=e[e.horizon==h].merge(x[['date',*FEATURES,*CONTROLS]],on='date',validate='one_to_one')
    return g[g.status=='CLOSED'].copy()
def bootstrap(g,name):
    # Full calendar sampling, then conditioning. Missing/nonclosed calendar days remain NaN.
    a=g.set_index('position').reindex(range(434)); y=a.net.to_numpy(float)/100000;v=a[name].to_numpy(float)
    rng=np.random.default_rng(13);values=[]
    for _ in range(499):
        starts=rng.integers(0,434-20+1,size=22);idx=np.concatenate([np.arange(s,s+20) for s in starts])[:434]
        valid=np.isfinite(y[idx]);p=y[idx][valid&(v[idx]>0)];n=y[idx][valid&(v[idx]<0)]
        if len(p) and len(n):values.append(float(p.mean()-n.mean()))
    return {'valid_draws':len(values),'positive_minus_negative_ci95':np.quantile(values,[.025,.975]).tolist() if values else None}
def round2(frames,e,lag=1):
    out={}
    for h in (1,3,5):
        g=joined(frames[lag],e,h);out[str(h)]={}
        for f in FEATURES:
            a=grouping(g,f);a['periods']={f'{lo}:{hi}':grouping(g[(g.position>=lo)&(g.position<hi)],f) for lo,hi in SEGMENTS}
            a['bootstrap']=bootstrap(g,f)
            ids=g.net.abs().nlargest(5).index
            a['omit_largest5_absolute_net']=grouping(g.drop(ids),f)
            out[str(h)][f]=a
    return out
def round3(frames,e):
    out={}
    for h in (1,3,5):
        g=joined(frames[1],e,h);cells={}
        for fs in ('positive','negative','zero'):
            fm={'positive':g.f5>0,'negative':g.f5<0,'zero':g.f5==0}[fs]
            for ps in ('up','down','flat'):
                pm={'up':g.r5>0,'down':g.r5<0,'flat':g.r5==0}[ps]
                sub=g[fm&pm];s=stats(sub);s['entry_net']=stats(sub,'entry_net')
                s['periods']={f'{lo}:{hi}':stats(sub[(sub.position>=lo)&(sub.position<hi)]) for lo,hi in SEGMENTS}
                cells[f'{fs}_{ps}']=s
        out[str(h)]={'cells':cells,'all':stats(g),'sum_cell_n':sum(v['n'] for v in cells.values())}
        assert out[str(h)]['sum_cell_n']==len(g)
    out['interpretation']='price/flow quadrants are descriptive competition, not causality or cash amount; current peer catalog cannot resolve substitution'
    return out
def ridge(train,test,columns,label):
    a=train[columns].to_numpy(float);b=test[columns].to_numpy(float);y=train[label].to_numpy(float)/100000
    mean=a.mean(axis=0);std=a.std(axis=0);std[std==0]=1
    a=np.column_stack([np.ones(len(a)),(a-mean)/std]);b=np.column_stack([np.ones(len(b)),(b-mean)/std])
    penalty=np.eye(a.shape[1])*10;penalty[0,0]=0
    beta=np.linalg.solve(a.T@a+penalty,a.T@y)
    return b@beta
def predstats(g):
    y=g.y.to_numpy(float);base=(g.base.to_numpy(float)-y)**2;fund=(g.fund.to_numpy(float)-y)**2
    out={'n':len(g),'base_mse':float(base.mean()),'fund_mse':float(fund.mean()),'relative_mse_gain':float(1-fund.mean()/base.mean()) if base.mean() else None,'filters':{}}
    for model in ('base','fund'):
        reject=g[model]<0;positive=np.maximum(y,0);negative=np.maximum(-y,0)
        out['filters'][model]={'reject_n':int(reject.sum()),'rejected_negative_n':int(((y<0)&reject).sum()),'rejected_positive_n':int(((y>0)&reject).sum()),'caught_negative_yuan':float(negative[reject].sum()*100000),'missed_positive_yuan':float(positive[reject].sum()*100000),'caught_negative_fraction':float(negative[reject].sum()/negative.sum()) if negative.sum() else None,'missed_positive_fraction':float(positive[reject].sum()/positive.sum()) if positive.sum() else None}
    return out
def round4(frames,e,lag):
    summaries={};predictions=[]
    for target,h in [('net',1),('net',3),('net',5),('entry_net',1)]:
        x=frames[lag];g=e[e.horizon==h].merge(x[['date',*FEATURES,*CONTROLS]],on='date',validate='one_to_one')
        if target=='net':g=g[g.status=='CLOSED'].copy();g['known_date']=g.actual_exit_date
        else:g=g[g.entry_net.notna()].copy();g['known_date']=g.entry_date
        key=f'{target}_h{h}';parts=[];folds={}
        for lo,hi in SEGMENTS[1:]:
            cutoff=x.date.iloc[lo];tr=g[(g.position<lo)&(g.known_date<cutoff)];te=g[(g.position>=lo)&(g.position<hi)]
            assert len(tr)>=80 and len(te)>0
            assert (tr.known_date<cutoff).all() and set(tr.position).isdisjoint(te.position)
            p=te[['date','position',target]].rename(columns={target:'observed_yuan'}).copy()
            p['y']=p.observed_yuan/100000;p['base']=ridge(tr,te,CONTROLS,target);p['fund']=ridge(tr,te,CONTROLS+FEATURES,target)
            p['target']=key;p['lag']=lag;p['fold']=f'{lo}:{hi}';parts.append(p)
            folds[f'{lo}:{hi}']={**predstats(p),'train_n':len(tr),'max_train_label_date':tr.known_date.max(),'first_test_decision':cutoff}
        both=pd.concat(parts,ignore_index=True);predictions.append(both)
        out=predstats(both);out['folds']=folds
        out['omit_largest5_absolute_label']=predstats(both.drop(both.y.abs().nlargest(5).index))
        a=both.set_index('position').reindex(range(434));loss=(a.base-a.y)**2-(a.fund-a.y)**2
        rng=np.random.default_rng(13);means=[]
        for _ in range(499):
            starts=rng.integers(0,415,size=22);ix=np.concatenate([np.arange(s,s+20) for s in starts])[:434]
            z=loss.to_numpy(float)[ix];z=z[np.isfinite(z)]
            if len(z):means.append(float(z.mean()))
        out['paired_mse_improvement_block20_ci95']=np.quantile(means,[.025,.975]).tolist()
        summaries[key]=out
    return summaries,pd.concat(predictions,ignore_index=True)

def execute():
    frames,e=load_inputs();print('R1 admission+causal scalar audit PASS',flush=True)
    if not (folder(2)/'others/results.json').exists():save(folder(2)/'others/results.json',round2(frames,e))
    print('R2 complete',flush=True)
    if not (folder(3)/'others/results.json').exists():save(folder(3)/'others/results.json',round3(frames,e))
    print('R3 complete',flush=True)
    r,p=round4(frames,e,1);save(folder(4)/'others/results.json',r);p.to_csv(folder(4)/'others/predictions.csv',index=False);print('R4 complete',flush=True)
    sensitivity={}
    for lag in (2,3):
        r,p=round4(frames,e,lag);p.to_csv(folder(5)/f'others/predictions_lag{lag}.csv',index=False)
        sensitivity[str(lag)]={'conditions':round2(frames,e,lag),'models':r}
    save(folder(5)/'others/results.json',sensitivity);print('R5 complete',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['allocate','execute']);{'allocate':allocate,'execute':execute}[p.parse_args().mode]()
