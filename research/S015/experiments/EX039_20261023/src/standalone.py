"""Separate standalone price-path information from incremental legacy-model repair."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import argparse,importlib.util,json
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent;EX=ExperimentRef('S015',HERE.name)
TARGETS=['net1','net3','net5','entry','loss3','drawdown3','hold1','hold3']
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def module(p,name):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def context():return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
def material(p):return publish_evidence(context(),MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))
def prepare():
    assert not (HERE/'others/protocol_refs.json').exists()
    proto={'authorization':'用户不限轮次阶段二；EX036-38结果已见，路径与波动家族据此选择，不能称独立验证。',
      'targets':TARGETS,'models':'path=temporal_order4; volatility=volatility_transition4; combined=8. Fixed linear Ridge10, same four purged expanding folds. No old r1/r5/pressure controls in new models. Holding roles additionally include known held_unreal; constant remains train target mean. Reproduce price and legacy only as comparisons.',
      'policies':'Signed targets prediction>=0. Risk prediction<=same-model training-fitted median, fixed per fold, evaluate net3 payoff. Not an out-of-sample training calibration. Also compare all-observed-event payoff; overlapping independent events, not account.',
      'diagnostics':'All 8 targets x3 new models; no fill model because only7 unfilled. All four known r1 positive/nonpositive x r5 positive/nonpositive states, no outcome-driven state selection. All folds, omit top5 abs payoffs, 499 block20 seed13 intervals for MSE and retained payoff differences vs constant and legacy. No new hard gates or threshold search.',
      'source':read(BASE/'EX038_20261023/others/published_refs.json'),
      'stop':'Assess independent information, auxiliary use and missing roles, then integrate stage2. No full accounts or stage3.'}
    save(HERE/'protocols/standalone.json',proto);save(HERE/'others/protocol_refs.json',{p.name:material(p).to_dict() for p in (HERE/'protocols/standalone.json',Path(__file__))});print('EX039_FROZEN',flush=True)
def inputs():
    fr=read(HERE/'others/protocol_refs.json')
    for name,sub in [('standalone.py','src'),('standalone.json','protocols')]:assert EvidenceRef.from_dict(fr[name]).resolve(ROOT).read_bytes()==(HERE/sub/name).read_bytes()
    refs={};paths={}
    for ex,k in [('EX036_20261023','src/validate.py'),('EX036_20261023','others/model_features.csv'),('EX036_20261023','others/labels.csv'),('EX036_20261023','others/predictions.csv'),('EX035_20261023','protocols/signal_dictionary.json'),('EX038_20261023','src/attribution.py')]:
        ref=EvidenceRef.from_dict(read(BASE/ex/'others/published_refs.json')['materials'][k]);refs[ex+'/'+k]=ref.to_dict();paths[k]=ref.resolve(ROOT)
    save(HERE/'others/input_refs.json',refs)
    return module(paths['src/validate.py'],'old39'),module(paths['src/attribution.py'],'attr39'),pd.read_csv(paths['others/model_features.csv']),pd.read_csv(paths['others/labels.csv']),pd.read_csv(paths['others/predictions.csv']),read(paths['protocols/signal_dictionary.json'])['families']
def interval(p,v):
    a=pd.Series(np.asarray(v),index=p.position).reindex(range(434)).to_numpy();rng=np.random.default_rng(13);out=[]
    for _ in range(499):
        ix=np.concatenate([np.arange(t,t+20) for t in rng.integers(0,415,size=22)])[:434];z=a[ix];z=z[np.isfinite(z)]
        if len(z):out.append(float(z.mean()))
    return np.quantile(out,[.025,.975]).tolist()
def run():
    assert not (HERE/'others/results.json').exists()
    old,attr,x,labels,prior,fam=inputs();results={};preds=[];meta=[];net3=labels[labels.target.eq('net3')].set_index('position').y
    for target in TARGETS:
        extra=['held_unreal'] if target.startswith('hold') else []
        models={'constant':[],'price':old.PRICE+extra,'legacy':old.PRICE+['pressure']+extra,'path':fam['temporal_order']+extra,'volatility':fam['volatility_transition']+extra,'combined':fam['temporal_order']+fam['volatility_transition']+extra}
        g=x.merge(labels[labels.target.eq(target)].drop(columns=['date']),on='position',validate='one_to_one');g['payoff']=g.position.map(net3) if target in old.RISK else g.y;pp=[]
        for fold,(lo,hi) in enumerate(old.FOLDS):
            train=g[(g.position<lo)&g.y.notna()&(g.known_date<g.date.iloc[lo])].copy();test=g[g.position.between(lo,hi-1)&g.y.notna()].copy()
            p=test[['date','position','known_date','r1','r5','y','payoff']].copy();p['target']=target;p['fold']=fold
            before=prior[prior.target.eq(target)&prior.fold.eq(fold)].sort_values('position');assert p.position.tolist()==before.position.tolist()
            for name,cols in models.items():
                p[name]=old.ridge(train,test,cols);threshold=float(np.median(old.ridge(train,train,cols))) if target in old.RISK else 0.
                p['keep/'+name]=p[name]<=threshold if target in old.RISK else p[name]>=threshold
                if name in ('constant','price','legacy'):np.testing.assert_allclose(p[name],before[name],rtol=1e-9,atol=1e-12)
                meta.append({'target':target,'fold':fold,'model':name,'columns':cols,'threshold':threshold,'train_n':len(train),'test_n':len(test),'max_train_known_date':train.known_date.max(),'test_start':g.date.iloc[lo]})
            pp.append(p)
        p=pd.concat(pp,ignore_index=True);preds.append(p);rr={}
        for name in models:
            loss=(p[name]-p.y)**2;z={'n':len(p),'mse':float(loss.mean()),'utility':attr.utility(p,name,old),'folds':{},'states':{},'all_events':old.amount(p.payoff)}
            for baseline in ('constant','legacy'):
                bl=(p[baseline]-p.y)**2;gain=(p['keep/'+name].astype(int)-p['keep/'+baseline].astype(int))*p.payoff
                z['mse_gain_vs_'+baseline]=float(1-loss.mean()/bl.mean());z['mse_delta_ci_vs_'+baseline]=interval(p,bl-loss)
                z['retained_increment_vs_'+baseline]={'mean_per_event':float(gain.mean()),'ci95':interval(p,gain)}
            for fold,gg in p.groupby('fold'):
                z['folds'][str(fold)]={'utility':attr.utility(gg,name,old),'mse_gain_vs_constant':float(1-((gg[name]-gg.y)**2).mean()/((gg.constant-gg.y)**2).mean())}
            for a in (False,True):
                for b in (False,True):
                    gg=p[p.r1.gt(0).eq(a)&p.r5.gt(0).eq(b)];z['states'][f'r1_{"positive" if a else "nonpositive"}/r5_{"positive" if b else "nonpositive"}']={'n':len(gg),'utility':attr.utility(gg,name,old),'all_events':old.amount(gg.payoff)}
            z['omit_largest5_utility']=attr.utility(p.drop(p.payoff.abs().nlargest(5).index),name,old);rr[name]=z
        results[target]=rr;print(target,'standalone complete',flush=True)
    pd.concat(preds,ignore_index=True).to_csv(HERE/'others/predictions.csv',index=False);save(HERE/'others/thresholds.json',meta);save(HERE/'others/results.json',results)
    save(HERE/'others/design_counts.json',{'new_model_specs':24,'reproduced_baseline_specs':24,'new_fold_fits':96,'reproduced_fold_fits':96,'continuous_accounts':0,'parameter_search':0})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run']);{'prepare':prepare,'run':run}[p.parse_args().mode]()
