"""Independent standalone-model and four-state utility audit."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import importlib.util,json
from pathlib import Path
from hashlib import sha256
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[3];BASE=HERE.parent
def read(p):return json.loads(p.read_bytes())
def mod(p,n):
    s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def prior_module(ex,name):
    refs=read(BASE/ex/'others/published_refs.json')['materials'];p=BASE/ex/'src'/name
    assert EvidenceRef.from_dict(refs['src/'+name]).resolve(ROOT).read_bytes()==p.read_bytes()
    return mod(p,ex+'_'+name.replace('.','_'))
def interval(p,values):
    delta=np.full(434,np.nan);delta[p.position.to_numpy(int)]=np.asarray(values);rng=np.random.default_rng(13);boot=[]
    for _ in range(499):
        ix=(rng.integers(415,size=22)[:,None]+np.arange(20)).reshape(-1)[:434];boot.append(np.nanmean(delta[ix]))
    return np.quantile(boot,[.025,.975])
def main():
    a=prior_module('EX036_20261023','independent_audit.py');b=prior_module('EX037_20261023','independent_audit.py');u=prior_module('EX038_20261023','independent_audit.py');u.audit=a
    for refname,items in [('protocol_refs.json',[('standalone.py','src'),('standalone.json','protocols')]),('loader_correction_refs.json',[('run_verified.py','src'),('loader_correction.json','protocols')])]:
        refs=read(HERE/'others'/refname)
        for name,sub in items:assert EvidenceRef.from_dict(refs[name]).resolve(ROOT).read_bytes()==(HERE/sub/name).read_bytes()
    refs=read(HERE/'others/input_refs.json')
    def resolve(ex,p):return EvidenceRef.from_dict(refs[ex+'/'+p]).resolve(ROOT)
    for ex,name in [('EX036_20261023','validate.py'),('EX038_20261023','attribution.py')]:assert (BASE/ex/'src'/name).read_bytes()==resolve(ex,'src/'+name).read_bytes()
    x=pd.read_csv(resolve('EX036_20261023','others/model_features.csv'));labels=pd.read_csv(resolve('EX036_20261023','others/labels.csv'));prior=pd.read_csv(resolve('EX036_20261023','others/predictions.csv'));families=read(resolve('EX035_20261023','protocols/signal_dictionary.json'))['families']
    preds=pd.read_csv(HERE/'others/predictions.csv');results=read(HERE/'others/results.json');thresholds=read(HERE/'others/thresholds.json');lookup={(r['target'],r['fold'],r['model']):r for r in thresholds};assert len(lookup)==192
    net3=labels[labels.target=='net3'].set_index('position').y;fits=0
    for target,res in results.items():
        g=x.merge(labels[labels.target==target].drop(columns='date'),on='position',validate='one_to_one');g['payoff']=g.position.map(net3) if target in ('loss3','drawdown3') else g.y;p=preds[preds.target==target].reset_index(drop=True)
        extra=['held_unreal'] if target.startswith('hold') else [];price=['r1','r5','vol20','range20'];models={'constant':[],'price':price+extra,'legacy':price+['pressure']+extra,'path':families['temporal_order']+extra,'volatility':families['volatility_transition']+extra,'combined':families['temporal_order']+families['volatility_transition']+extra};assert set(models)==set(res)
        for fold,(lo,hi) in enumerate(((100,184),(184,268),(268,352),(352,434))):
            tr=g[(g.position<lo)&g.y.notna()&(g.known_date<g.date.iloc[lo])];te=g[(g.position>=lo)&(g.position<hi)&g.y.notna()];pp=p[p.fold==fold]
            a.eq(pp.position.tolist(),te.position.tolist());a.eq(pp.y,te.y);a.eq(pp.payoff,te.payoff);a.eq(pp.r1,te.r1);a.eq(pp.r5,te.r5);assert tr.known_date.max()<g.date.iloc[lo]
            for model,cols in models.items():
                pred=b.least_squares(tr,te,cols);trainpred=b.least_squares(tr,tr,cols);a.eq(pp[model],pred);fits+=1
                threshold=float(np.median(trainpred)) if target in ('loss3','drawdown3') else 0;row=lookup[target,fold,model];assert row['columns']==cols
                for k,v in [('threshold',threshold),('train_n',len(tr)),('test_n',len(te)),('max_train_known_date',tr.known_date.max()),('test_start',g.date.iloc[lo])]:a.eq(row[k],v)
                keep=pred<=threshold if target in ('loss3','drawdown3') else pred>=threshold;a.eq(pp['keep/'+model].to_numpy(bool),keep)
                if model in ('constant','price','legacy'):a.eq(pp[model].to_numpy(),prior[(prior.target==target)&(prior.fold==fold)][model].to_numpy())
        for model,out in res.items():
            loss=(p[model]-p.y)**2;a.eq(out['n'],len(p));a.eq(out['mse'],loss.mean());u.utility(out['utility'],p,model);a.check_amount(out['all_events'],p.payoff)
            for baseline in ('constant','legacy'):
                bl=(p[baseline]-p.y)**2;a.eq(out['mse_gain_vs_'+baseline],1-loss.mean()/bl.mean());a.eq(out['mse_delta_ci_vs_'+baseline],interval(p,bl-loss))
                change=np.where(p['keep/'+model],p.payoff,0)-np.where(p['keep/'+baseline],p.payoff,0);gain=out['retained_increment_vs_'+baseline];a.eq(gain['mean_per_event'],change.mean());a.eq(gain['ci95'],interval(p,change))
            for fold,z in p.groupby('fold'):
                f=out['folds'][str(fold)];u.utility(f['utility'],z,model);a.eq(f['mse_gain_vs_constant'],1-((z[model]-z.y)**2).mean()/((z.constant-z.y)**2).mean())
            for short in (False,True):
                for longer in (False,True):
                    z=p[((p.r1>0)==short)&((p.r5>0)==longer)];key=f'r1_{"positive" if short else "nonpositive"}/r5_{"positive" if longer else "nonpositive"}';s=out['states'][key];a.eq(s['n'],len(z));u.utility(s['utility'],z,model);a.check_amount(s['all_events'],z.payoff)
            u.utility(out['omit_largest5_utility'],p.drop(p.payoff.abs().nlargest(5).index),model)
    assert fits==192
    paths=[Path(__file__),*[HERE/'src'/f for f in ('standalone.py','run_verified.py')],*[HERE/'protocols'/f for f in ('standalone.json','loader_correction.json')],*[HERE/'others'/f for f in ('predictions.csv','thresholds.json','results.json')]]
    output={'status':'PASS','checks':a.CHECKS,'model_fits':fits,'new_model_fits':96,'baseline_refits':96,'thresholds':192,'targets':8,'models':6,'four_states_per_model':True,'sha256':{str(p.relative_to(HERE)).replace('\\','/'):sha256(p.read_bytes()).hexdigest() for p in paths},'method':'Independent augmented least squares from authenticated audited helpers, training-only thresholds, target/net3-payoff roles, baseline reproduction, every utility/fold/four-state/extreme-omission and MSE/payoff block interval. Loader supplement authenticates identical original source bytes and changes only import location.','limitations':['Adaptive selection after prior development results; not new independent validation.','Holding standalone models still condition on known held_unreal.','Overlapping event amounts are not portfolio returns; no continuous strategy qualification.']}
    (HERE/'others/independent_audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(output,ensure_ascii=False))
if __name__=='__main__':main()
