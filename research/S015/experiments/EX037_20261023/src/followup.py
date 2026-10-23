"""Counterchecks of functional form and incremental value over legacy inputs."""
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
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def module(p,name):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def context():return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
def material(p):return publish_evidence(context(),MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))
def prepare():
    assert not (HERE/'others/protocol_refs.json').exists()
    old=read(BASE/'EX036_20261023/others/published_refs.json')
    proto={'authorization':'用户授权阶段二自主执行，预算不限；EX036有限线索和全特征劣化触发表达/冗余反证，未进入阶段三。',
      'selection_history':'已观察EX036全部九目标：时间/波动小幅改善，全24列全目标劣化；本次对全部六家族和all对称处理，不只试优胜家族。',
      'sources':old,'hypotheses':['Pure-price gains may only duplicate legacy pressure information.','Linear effects may miss nonmonotonic price-state information.','More features may worsen estimation without adding signal.'],
      'linear':'Legacy five controls (+held_unreal on held roles) plus one family/all, same Ridge10 as EX036. Compare true nested increment, not separate rival models.',
      'nonlinear':'Same legacy baseline plus train-only tertile indicators group1/group2 for each signal (group0 reference). Freeze cutpoints for test fold; ties retained, empty/constant dummy allowed standardized convention. Fixed Ridge10; no model-depth, cutoff or parameter search.',
      'coverage':'Nine same roles, four identical purged forward folds, six families plusall, two expressions=126 added specifications/504 fits. All known-date boundaries and event identities inherited. Existing constant/price/legacy predictions reproduced exactly.',
      'reporting':'All overall andfold MSE, legacy incremental errors, same causal zero rules and retrospective equal-count diagnostics, legacy/price block20 MSE intervals, single-feature univariate history not reselected. Nonlinear failure does not exhaust all expressions.',
      'stop':'Assess whether useful roles survive stronger base and alternate expression. Necessary ablation or risk-profit opportunity tradeoffs may follow if they can change decision; no unlimited tuning to produce positive evidence. All original targets unchanged.'}
    save(HERE/'protocols/expression_checks.json',proto);save(HERE/'others/protocol_refs.json',{p.name:material(p).to_dict() for p in (HERE/'protocols/expression_checks.json',Path(__file__))});print('FOLLOWUP_FROZEN',flush=True)
def inputs():
    fr=read(HERE/'others/protocol_refs.json')
    for name,sub in [('followup.py','src'),('expression_checks.json','protocols')]:assert EvidenceRef.from_dict(fr[name]).resolve(ROOT).read_bytes()==(HERE/sub/name).read_bytes()
    refs=read(HERE/'protocols/expression_checks.json')['sources']['materials'];out={}
    for k in ('src/validate.py','others/model_features.csv','others/labels.csv','others/predictions.csv'):
        out[k]=EvidenceRef.from_dict(refs[k]);out[k].resolve(ROOT)
    p=BASE/'EX036_20261023/src/validate.py';assert out['src/validate.py'].resolve(ROOT).read_bytes()==p.read_bytes();old=module(p,'verified_role_methods')
    dr=EvidenceRef.from_dict(read(BASE/'EX035_20261023/others/published_refs.json')['materials']['protocols/signal_dictionary.json']);families=read(dr.resolve(ROOT))['families']
    features=pd.read_csv(out['others/model_features.csv'].resolve(ROOT));labels=pd.read_csv(out['others/labels.csv'].resolve(ROOT));pred=pd.read_csv(out['others/predictions.csv'].resolve(ROOT))
    save(HERE/'others/input_refs.json',{'evidence':{k:v.to_dict() for k,v in out.items()},'dictionary':dr.to_dict()})
    return old,features,labels,pred,families
def run():
    assert not (HERE/'others/results.json').exists()
    old,x,labels,prior,families=inputs();families={**families,'all':[c for v in families.values() for c in v]};result={};preds=[];cuts=[]
    for target in old.TARGETS:
        g=x.merge(labels[labels.target.eq(target)].drop(columns=['date']),on='position',validate='one_to_one')
        extra=['held_unreal'] if target.startswith('hold') else [];base=old.PRICE+['pressure']+extra;ps=[]
        for fold,(lo,hi) in enumerate(old.FOLDS):
            train=g[(g.position<lo)&g.y.notna()&(g.known_date<g.date.iloc[lo])].copy();test=g[g.position.between(lo,hi-1)&g.y.notna()].copy()
            p=test[['date','position','y','known_date','held_unreal']].copy();p['target']=target;p['fold']=fold
            for name,cols in [('constant',[]),('price',old.PRICE+extra),('legacy',base)]:
                pred=old.ridge(train,test,cols);p[name]=np.clip(pred,0,1) if target=='fill' else pred
                before=prior[prior.target.eq(target)&prior.fold.eq(fold)].sort_values('position');assert before.position.tolist()==p.position.tolist();np.testing.assert_allclose(p[name],before[name],rtol=1e-10,atol=1e-12)
            for c in families['all']:
                q=train[c].quantile([1/3,2/3]).to_numpy();a=np.searchsorted(q,train[c].to_numpy(),side='right');b=np.searchsorted(q,test[c].to_numpy(),side='right')
                for i in (1,2):train[f'{c}_bin{i}']=(a==i).astype(float);test[f'{c}_bin{i}']=(b==i).astype(float)
                cuts.append({'target':target,'fold':fold,'signal':c,'cut1':float(q[0]),'cut2':float(q[1]),'train_counts':[int((a==i).sum()) for i in range(3)]})
            for family,cols in families.items():
                for mode in ('linear','binned'):
                    columns=cols if mode=='linear' else [f'{c}_bin{i}' for c in cols for i in (1,2)]
                    pred=old.ridge(train,test,base+columns);p[f'{mode}/{family}']=np.clip(pred,0,1) if target=='fill' else pred
            ps.append(p)
        p=pd.concat(ps,ignore_index=True);preds.append(p);result[target]={}
        for name in ['constant','price','legacy',*[f'{m}/{f}' for m in ('linear','binned') for f in families]]:
            out=old.metrics(p,name,target)
            for fold,z in p.groupby('fold'):
                den=((z.legacy-z.y)**2).mean();out['folds'][str(fold)]['mse_gain_vs_legacy']=float(1-((z[name]-z.y)**2).mean()/den) if den>0 else None
            result[target][name]=out
        print(target,'counterchecks complete',flush=True)
    pd.concat(preds,ignore_index=True).to_csv(HERE/'others/predictions.csv',index=False);save(HERE/'others/cutpoints.json',cuts);save(HERE/'others/results.json',result)
    save(HERE/'others/design_counts.json',{'added_model_specifications':126,'added_fold_fits':504,'reproduced_baseline_specifications':27,'targets':9,'families_and_all':7,'expressions':['linear','binned'],'continuous_accounts':0,'parameter_searches':0})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run']);{'prepare':prepare,'run':run}[p.parse_args().mode]()
