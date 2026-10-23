"""Adaptive, disclosed stage-two attribution and causal opportunity tradeoffs."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import argparse,importlib.util,json
from pathlib import Path
from hashlib import sha256
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent;EX=ExperimentRef('S015',HERE.name)
CASES=[('net3','temporal_order','linear'),('net5','volatility_transition','linear'),('loss3','volatility_transition','linear'),('drawdown3','volatility_transition','linear'),('loss3','scale_relationship','binned'),('drawdown3','scale_relationship','binned'),('hold1','volatility_transition','linear'),('hold3','volatility_transition','linear')]
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def module(p,name):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def context():return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
def material(p):return publish_evidence(context(),MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))
def prepare():
    assert not (HERE/'others/protocol_refs.json').exists()
    proto={'authorization':'用户批准不限轮数阶段二；依EX036/37全结果选择八个值得归因的用途，选择历史公开，不声称新独立验证。',
      'cases':CASES,'source':read(BASE/'EX037_20261023/others/published_refs.json'),
      'attribution':'Each family full, each of four alone, each of four omitted, plus same legacy baseline. Keep EXACT old nine target definitions/folds/labels. Fixed Ridge10 and train-only bins. No selection of best submodel for deployment.',
      'policy':'Net and holding predictions>=0 mean participate/continue. Risk target predictions<=median of SAME MODEL training predictions mean lower-risk participate; train median fixed each fold, no test rank calibration. Evaluate all risk rules on actual net3 outcomes as well as risk labels. Train fitted values used for observable calibration, not out-of-sample calibration.',
      'cost_tradeoff':'Report selected/excluded counts, sums, means, loss caught/profit missed; differences vs same baseline retained event amounts. All are overlapping independent-event diagnostics, never portfolio PnL. Hold payoff is continuation increment, not full trade return.',
      'counterevidence':'All variants, four fold utilities, known r5 positive/nonpositive backgrounds, omit top5 absolute payoffs; 499 block20 seed13 paired retained event increments vs baseline. No multiple-selection correction/no statistical gate.',
      'frequency':'Only net/risk roles: maximum non-overlapping recorded CLOSED event intervals with same-day switch allowed, exit-day windows wholly within modeled positions100:434 (275 windows). No statement about full434 frequency acceptance; first100 not predicted. No optimization of entry sequence or strategy accounts.',
      'stop':'After attribution and causal utility tradeoffs, close stage2 if components and missing roles can be assessed; otherwise only pursue clearly decision-changing questions. No permission needed for further stage2 rounds, no automatic stage3.'}
    save(HERE/'protocols/attribution.json',proto);save(HERE/'others/protocol_refs.json',{p.name:material(p).to_dict() for p in (HERE/'protocols/attribution.json',Path(__file__))});print('ATTRIBUTION_FROZEN',flush=True)
def inputs():
    frozen=read(HERE/'others/protocol_refs.json')
    for name,sub in [('attribution.py','src'),('attribution.json','protocols')]:assert EvidenceRef.from_dict(frozen[name]).resolve(ROOT).read_bytes()==(HERE/sub/name).read_bytes()
    refs=read(BASE/'EX036_20261023/others/published_refs.json')['materials'];auth={}
    for k in ('src/validate.py','others/model_features.csv','others/labels.csv'):
        auth[k]=EvidenceRef.from_dict(refs[k]);auth[k].resolve(ROOT)
    path=BASE/'EX036_20261023/src/validate.py';assert path.read_bytes()==auth['src/validate.py'].resolve(ROOT).read_bytes();old=module(path,'validated_role_helpers')
    f=pd.read_csv(auth['others/model_features.csv'].resolve(ROOT));labels=pd.read_csv(auth['others/labels.csv'].resolve(ROOT))
    dr=EvidenceRef.from_dict(read(BASE/'EX035_20261023/others/published_refs.json')['materials']['protocols/signal_dictionary.json']);families=read(dr.resolve(ROOT))['families']
    er=EvidenceRef.from_dict(read(BASE/'EX026_20261023/others/delivery_validation.json')['materials']['events.csv']);events=pd.read_csv(er.resolve(ROOT))
    pr=EvidenceRef.from_dict(read(HERE/'protocols/attribution.json')['source']['materials']['others/predictions.csv']);prior=pd.read_csv(pr.resolve(ROOT))
    save(HERE/'others/input_refs.json',{'evidence':{k:v.to_dict() for k,v in auth.items()},'dictionary':dr.to_dict(),'events':er.to_dict(),'prior_predictions':pr.to_dict()})
    return old,f,labels,families,events,prior
def matrix_columns(train,test,cols,mode):
    if mode=='linear':return cols
    names=[]
    for c in cols:
        q=train[c].quantile([1/3,2/3]).to_numpy();a=np.searchsorted(q,train[c].to_numpy(),side='right');b=np.searchsorted(q,test[c].to_numpy(),side='right')
        for i in (1,2):
            n=f'{c}_bin{i}';train[n]=(a==i).astype(float);test[n]=(b==i).astype(float);names.append(n)
    return names
def coefficients(train,cols):
    a=train[cols].to_numpy(float);m=a.mean(0);s=a.std(0);s[s==0]=1;a=np.column_stack([np.ones(len(a)),(a-m)/s]);reg=np.eye(a.shape[1])*10;reg[0,0]=0
    beta=np.linalg.solve(a.T@a+reg,a.T@train.y.to_numpy(float));return {c:float(v) for c,v in zip(['intercept',*cols],beta)}
def utility(p,variant,old):
    y=p.payoff.to_numpy(float);keep=p[f'keep/{variant}'].to_numpy(bool);a=old.amount(y[keep]);b=old.amount(y[~keep]);pos=np.maximum(y,0);neg=np.maximum(-y,0)
    return {'selected':a,'excluded':b,'caught_loss_fraction':old.ratio(neg[~keep].sum(),neg.sum()),'missed_profit_fraction':old.ratio(pos[~keep].sum(),pos.sum()),
      'retained_risk_mean':float(p.loc[keep,'y'].mean()) if keep.any() else None,'retained_event_sum':float(y[keep].sum())}
def bound(p,variant,events,h,dates):
    selected=set(p.loc[p[f'keep/{variant}'],'position'].astype(int));lookup={d:i for i,d in enumerate(dates)}
    intervals=sorted([(lookup[r.entry_date],lookup[r.actual_exit_date]) for r in events[events.horizon.eq(h)&events.position.isin(selected)&events.status.eq('CLOSED')].itertuples()],key=lambda t:(t[1],t[0]))
    counts=[]
    for end in range(159,434):
        stop=-1;n=0
        for start,exitday in intervals:
            if end-59<=exitday<=end and start>=stop:n+=1;stop=exitday
        counts.append(n)
    return {'scope':'275 windows wholly within modeled decision period; not original434 acceptance','median_max':float(np.median(counts)),'at_least3_windows':sum(v>=3 for v in counts),'windows':275,'counts':counts}
def run():
    assert not (HERE/'others/results.json').exists()
    old,x,labels,families,events,prior=inputs();allpred=[];results={};meta=[];coef=[]
    net3=labels[labels.target.eq('net3')].set_index('position').y
    for target,family,mode in CASES:
        key=f'{target}/{family}/{mode}';cols=families[family];variants={'baseline':[],'full':cols,**{f'only/{c}':[c] for c in cols},**{f'without/{c}':[v for v in cols if v!=c] for c in cols}}
        g=x.merge(labels[labels.target.eq(target)].drop(columns=['date']),on='position',validate='one_to_one');extra=['held_unreal'] if target.startswith('hold') else [];base=old.PRICE+['pressure']+extra
        g['payoff']=g.position.map(net3) if target in old.RISK else g.y;ps=[]
        for fold,(lo,hi) in enumerate(old.FOLDS):
            train=g[(g.position<lo)&g.y.notna()&(g.known_date<g.date.iloc[lo])].copy();test=g[g.position.between(lo,hi-1)&g.y.notna()].copy()
            p=test[['date','position','y','payoff','r5','known_date']].copy();p['case']=key;p['fold']=fold
            for variant,cs in variants.items():
                cc=matrix_columns(train,test,cs,mode);fitcols=base+cc;pred=old.ridge(train,test,fitcols);p[variant]=pred
                threshold=float(np.median(old.ridge(train,train,fitcols))) if target in old.RISK else 0.
                p[f'keep/{variant}']=pred<=threshold if target in old.RISK else pred>=threshold
                meta.append({'case':key,'fold':fold,'variant':variant,'threshold':threshold,'train_n':len(train),'max_train_known_date':train.known_date.max(),'test_start':g.date.iloc[lo]})
                if variant=='full':coef.append({'case':key,'fold':fold,'standardized_coefficients':coefficients(train,fitcols)})
                if variant in ('baseline','full'):
                    before=prior[prior.target.eq(target)&prior.fold.eq(fold)].sort_values('position');ref='legacy' if variant=='baseline' else f'{mode}/{family}'
                    assert p.position.tolist()==before.position.tolist();np.testing.assert_allclose(pred,before[ref],rtol=1e-9,atol=1e-12)
            ps.append(p)
        p=pd.concat(ps,ignore_index=True);allpred.append(p);result={}
        for variant in variants:
            base_loss=(p.baseline-p.y)**2;loss=(p[variant]-p.y)**2
            z={'n':len(p),'mse_gain_vs_baseline':float(1-loss.mean()/base_loss.mean()),'utility':utility(p,variant,old),'folds':{},'states':{}}
            for fold,gg in p.groupby('fold'):z['folds'][str(fold)]={'mse_gain':float(1-((gg[variant]-gg.y)**2).mean()/((gg.baseline-gg.y)**2).mean()),'utility':utility(gg,variant,old)}
            for state,gg in p.groupby(p.r5.gt(0)):z['states']['r5_positive' if state else 'r5_nonpositive']=utility(gg,variant,old)
            z['omit_largest5_utility']=utility(p.drop(p.payoff.abs().nlargest(5).index),variant,old)
            gain=(p[f'keep/{variant}'].astype(int)-p['keep/baseline'].astype(int))*p.payoff
            v=pd.Series(gain.to_numpy(),index=p.position).reindex(range(434)).to_numpy();bs=[];rng=np.random.default_rng(13)
            for _ in range(499):
                ix=np.concatenate([np.arange(t,t+20) for t in rng.integers(0,415,size=22)])[:434];a=v[ix];a=a[np.isfinite(a)]
                if len(a):bs.append(float(a.mean()))
            z['retained_increment_vs_baseline']={'mean_per_event':float(gain.mean()),'ci95':np.quantile(bs,[.025,.975]).tolist()}
            if not target.startswith('hold'):z['frequency_upper_bound']=bound(p,variant,events,5 if target=='net5' else 3,x.date.tolist())
            result[variant]=z
        results[key]=result;print(key,'attribution complete',flush=True)
    pd.concat(allpred,ignore_index=True).to_csv(HERE/'others/predictions.csv',index=False);save(HERE/'others/thresholds.json',meta);save(HERE/'others/coefficients.json',coef);save(HERE/'others/results.json',results)
    save(HERE/'others/design_counts.json',{'cases':8,'variants_per_case':10,'added_single_or_omission_specs':64,'reproduced_family_specs':8,'reproduced_baselines':8,'total_fold_fits':320,'continuous_accounts':0,'threshold_search':0})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run']);{'prepare':prepare,'run':run}[p.parse_args().mode]()
