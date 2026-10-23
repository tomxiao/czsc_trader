"""Predeclared multi-role price components; no continuous strategy accounts."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import argparse,importlib.util,json
from hashlib import sha256
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent;EX=ExperimentRef('S015',HERE.name)
PRICE=['r1','r5','vol20','range20'];FOLDS=((100,184),(184,268),(268,352),(352,434))
TARGETS=['net1','net3','net5','entry','loss3','drawdown3','hold1','hold3','fill']
RISK={'loss3','drawdown3'}
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def module(p,name):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def context():return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
def material(p):return publish_evidence(context(),MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))
def prepare():
    assert not (HERE/'others/protocol_refs.json').exists()
    old=read(BASE/'EX035_20261023/others/published_refs.json');refs=old['materials']
    proto={'authorization':'用户批准按第一性原理框架返回阶段二自主执行，实验预算不限制；本轮为分职责组件验证，不构造完整策略。',
      'plan':refs['protocols/research_plan.md'],'dictionary':refs['protocols/signal_dictionary.json'],'features':refs['others/features.csv'],
      'targets':TARGETS,'folds':FOLDS,'baseline':PRICE,'legacy_baseline':PRICE+['pressure'],
      'models':'constant, price, legacy, six price+family models, price+all24; Ridge alpha10, standardized on training only, unpenalized intercept; fill projected [0,1]. Holding targets add known unrealized PnL to price and legacy/family bases, not constant.',
      'purge':'Training position<test start and label actual known_date strictly before first test date. Test outcomes never define features, scaling, bins, directions or selected participation count.',
      'targets_detail':'net1/3/5 original CLOSED event net/100000; entry original h1 marked entry_net/100000; loss3=max(-net3,0); drawdown3=max(0,-min(quantity*(Close[entry:exit)-buyprice)-buyfee)/100000), closes before actual exit only; hold1 at D compares net3-net1 for seed D-1; hold3 compares net5-net3 for seed D-3; both require bought by D, CLOSED both, same quantity, known=max exits; held_unreal uses D close. fill is buy_price nonmissing when next session exists.',
      'univariate':'24 signals x9 targets x4 folds, train-only tertiles. Report all three test-bin outcomes; training best/worst economic direction per signal also reported. Tied cutpoints are retained and support disclosed, not optimized.',
      'utilities':'For signed net/entry/holding targets predict<0 means exclude/exit; report caught loss/missed profit amounts and counts. Same-count diagnostic: top ceil(n/2) per test fold using model prediction (low for risk), tie earlier position; references price and legacy on same observations. Per-fold ranking is a retrospective allocation diagnostic requiring future prediction distribution, not an executable selection rule; fixed zero rule is causal. Risk reports mean/amount of selected risk, not profit. Fill reports Brier/no trading utility.',
      'bootstrap':'Paired MSE reduction vs price and legacy using 499 block20 draws across full434 time axis, seed13; signed-target zero-rule retained event amount difference vs price also bootstrapped. Equal-count diagnostic and risk/fill utility are point estimates only. All comparisons/folds/largest absolute5 omission; report-only no new gates.',
      'scope':'Original boundaries, costs, events and known historical-publication limitations. Fixed targets share overlapping future paths; all seen development data. No causal identification or new independent sample.',
      'next':'Use results to identify role-specific mechanisms and competing explanations. Stage2 followups may test predeclared nonlinear expression/ablation/conditional backgrounds; unlimited budget is not open-ended optimization or stage3 authority.'}
    save(HERE/'protocols/component_validation.json',proto)
    save(HERE/'others/protocol_refs.json',{p.name:material(p).to_dict() for p in (HERE/'protocols/component_validation.json',Path(__file__))});print('VALIDATION_PROTOCOL_FROZEN',flush=True)
def inputs():
    frozen=read(HERE/'others/protocol_refs.json')
    for name,sub in [('validate.py','src'),('component_validation.json','protocols')]:assert EvidenceRef.from_dict(frozen[name]).resolve(ROOT).read_bytes()==(HERE/sub/name).read_bytes()
    r=read(BASE/'EX035_20261023/others/published_refs.json')['materials'];refs={}
    for k in ('src/census.py','protocols/signal_dictionary.json','others/features.csv'):refs[k]=EvidenceRef.from_dict(r[k]);refs[k].resolve(ROOT)
    path=BASE/'EX035_20261023/src/census.py';assert path.read_bytes()==refs['src/census.py'].resolve(ROOT).read_bytes()
    loader=module(path,'authenticated_census');adj,raw,bars,ids=loader.data();x=pd.read_csv(refs['others/features.csv'].resolve(ROOT));families=read(refs['protocols/signal_dictionary.json'].resolve(ROOT))['families']
    er=EvidenceRef.from_dict(read(BASE/'EX026_20261023/others/delivery_validation.json')['materials']['events.csv']);e=pd.read_csv(er.resolve(ROOT));refs['event_labels']=er
    c=adj.Close.astype(float);daily=pd.DataFrame({'date':pd.to_datetime(adj.Date).dt.strftime('%Y-%m-%d'),'r1':c.pct_change(),'r5':c/c.shift(5)-1,'vol20':c.pct_change().rolling(20).std(ddof=1),'range20':((adj.High-adj.Low)/c).rolling(20).mean(),'pressure':raw.Close/(raw.Amount/raw.Volume)-1})
    x=x.merge(daily.iloc[75:],on='date',validate='one_to_one');assert len(x)==434 and np.isfinite(x[PRICE+['pressure']]).all().all()
    datasets={};dates=pd.to_datetime(adj.Date).dt.strftime('%Y-%m-%d').tolist();idx={d:i for i,d in enumerate(dates)}
    for target in TARGETS:
        g=x.copy();g['y']=np.nan;g['known_date']=None;g['held_unreal']=0.;g['cohort_signal_position']=np.nan
        if target.startswith('hold'):
            age=int(target[-1]);early=e[e.horizon.eq(age)].set_index('position');late=e[e.horizon.eq(age+2)].set_index('position')
            for pos in range(age,434):
                a,b=early.loc[pos-age],late.loc[pos-age];D=x.date.iloc[pos]
                if a.status!='CLOSED' or b.status!='CLOSED' or pd.isna(a.buy_price) or a.entry_date>D:continue
                assert a.quantity==b.quantity and abs(a.buy_price-b.buy_price)<1e-12
                g.loc[pos,['y','known_date','held_unreal','cohort_signal_position']]=[(b.net-a.net)/100000,max(a.actual_exit_date,b.actual_exit_date),(a.quantity*(float(adj.Close.iloc[pos+75])-a.buy_price)-a.buy_fee)/100000,pos-age]
        else:
            h=int(target[-1]) if target in ('net1','net3','net5') else 3 if target in ('loss3','drawdown3') else 1
            a=e[e.horizon.eq(h)].sort_values('position').reset_index(drop=True);assert a.position.tolist()==list(range(434))
            if target.startswith('net'):g['y']=a.net.where(a.status.eq('CLOSED'))/100000;g['known_date']=a.actual_exit_date
            elif target=='entry':g['y']=a.entry_net/100000;g['known_date']=a.entry_date
            elif target=='loss3':g['y']=(-a.net/100000).clip(lower=0).where(a.status.eq('CLOSED'));g['known_date']=a.actual_exit_date
            elif target=='fill':g['y']=a.buy_price.notna().astype(float).where(a.status.ne('NO_NEXT_SESSION'));g['known_date']=a.entry_date
            elif target=='drawdown3':
                for pos,row in a[a.status.eq('CLOSED')].iterrows():
                    close=adj.Close.iloc[idx[row.entry_date]:idx[row.actual_exit_date]].to_numpy(float);assert len(close)>0
                    g.loc[pos,'y']=max(0.,-float(np.min(row.quantity*(close-row.buy_price)-row.buy_fee)))/100000;g.loc[pos,'known_date']=row.actual_exit_date
        assert g.loc[g.y.notna(),'known_date'].notna().all()
        g['target']=target;datasets[target]=g
    save(HERE/'others/input_refs.json',{'evidence':{k:v.to_dict() for k,v in refs.items()},'data':ids})
    pd.concat([g[['date','position','target','y','known_date','held_unreal','cohort_signal_position']] for g in datasets.values()],ignore_index=True).to_csv(HERE/'others/labels.csv',index=False)
    x.to_csv(HERE/'others/model_features.csv',index=False)
    return datasets,families
def ridge(train,test,cols):
    if not cols:return np.full(len(test),float(train.y.mean()))
    a=train[cols].to_numpy(float);b=test[cols].to_numpy(float);m=a.mean(0);s=a.std(0);s[s==0]=1.
    a=np.column_stack([np.ones(len(a)),(a-m)/s]);b=np.column_stack([np.ones(len(b)),(b-m)/s]);reg=np.eye(a.shape[1])*10;reg[0,0]=0
    return b@np.linalg.solve(a.T@a+reg,a.T@train.y.to_numpy(float))
def amount(y):
    y=np.asarray(y,float);return {'n':len(y),'mean':float(y.mean()) if len(y) else None,'positive_n':int((y>0).sum()),'negative_n':int((y<0).sum()),'positive_sum':float(np.maximum(y,0).sum()),'negative_sum':float(-np.minimum(y,0).sum())}
def ratio(a,b):return float(a/b) if b else None
def utility(p,col,target):
    y=p.y.to_numpy(float);pred=p[col].to_numpy(float);out={}
    if target not in RISK and target!='fill':
        reject=pred<0;pos=np.maximum(y,0);neg=np.maximum(-y,0)
        out['zero_rule']={'reject_n':int(reject.sum()),'caught_loss_fraction':ratio(neg[reject].sum(),neg.sum()),'missed_profit_fraction':ratio(pos[reject].sum(),pos.sum()),'caught_loss_n':int(((y<0)&reject).sum()),'missed_profit_n':int(((y>0)&reject).sum()),'retained':amount(y[~reject]),'excluded':amount(y[reject])}
    if target!='fill':
        selected=[]
        for _,z in p.groupby('fold',sort=False):
            order=z.sort_values([col,'position'],ascending=[target in RISK,True]);selected.extend(order.index[:int(np.ceil(len(z)/2))].tolist())
        out['equal_count_diagnostic']=amount(p.loc[selected,'y'].to_numpy(float));out['selected_positions']=p.loc[selected,'position'].astype(int).tolist()
    return out
def metrics(p,col,target):
    y=p.y.to_numpy(float);loss=(p[col].to_numpy(float)-y)**2
    out={'n':len(p),'mse':float(loss.mean()),'utility':utility(p,col,target),'folds':{}}
    for baseline in ('constant','price','legacy'):
        bl=(p[baseline].to_numpy(float)-y)**2;out[f'mse_gain_vs_{baseline}']=1-float(loss.mean()/bl.mean()) if bl.mean()>0 else None
    for fold,z in p.groupby('fold',sort=False):
        l=(z[col]-z.y)**2;bl=(z.price-z.y)**2
        out['folds'][str(fold)]={'n':len(z),'mse_gain_vs_price':1-float(l.mean()/bl.mean()) if bl.mean()>0 else None,'utility':utility(z,col,target)}
    omit=p.drop(p.y.abs().nlargest(5).index);bl=(omit.price-omit.y)**2;l=(omit[col]-omit.y)**2
    out['omit_largest5_gain_vs_price']=1-float(l.mean()/bl.mean()) if bl.mean()>0 else None
    for baseline in ('price','legacy'):
        v=pd.Series((p[baseline].to_numpy()-y)**2-loss,index=p.position).reindex(range(434)).to_numpy();bs=[];rng=np.random.default_rng(13)
        for _ in range(499):
            ix=np.concatenate([np.arange(t,t+20) for t in rng.integers(0,415,size=22)])[:434];a=v[ix];a=a[np.isfinite(a)]
            if len(a):bs.append(float(a.mean()))
        out[f'paired_mse_reduction_ci_vs_{baseline}']=np.quantile(bs,[.025,.975]).tolist()
    if target not in RISK and target!='fill':
        gain=((p[col].to_numpy()>=0).astype(float)-(p.price.to_numpy()>=0).astype(float))*y
        v=pd.Series(gain,index=p.position).reindex(range(434)).to_numpy();bs=[];rng=np.random.default_rng(13)
        for _ in range(499):
            ix=np.concatenate([np.arange(t,t+20) for t in rng.integers(0,415,size=22)])[:434];a=v[ix];a=a[np.isfinite(a)]
            if len(a):bs.append(float(a.mean()))
        out['zero_rule_increment_vs_price']={'mean_event_amount_per100k':float(gain.mean()),'ci95':np.quantile(bs,[.025,.975]).tolist(),'not_an_account':True}
    return out
def run():
    assert not (HERE/'others/results.json').exists()
    datasets,families=inputs();result={};predictions=[];bins=[];fold_meta=[]
    allcols=[c for cols in families.values() for c in cols]
    for target,g in datasets.items():
        extra=['held_unreal'] if target.startswith('hold') else []
        models={'constant':[],'price':PRICE+extra,'legacy':PRICE+['pressure']+extra,**{fam:PRICE+extra+cols for fam,cols in families.items()},'all':PRICE+extra+allcols}
        ps=[]
        for fold,(lo,hi) in enumerate(FOLDS):
            train=g[(g.position<lo)&g.y.notna()&(g.known_date<g.date.iloc[lo])];test=g[g.position.between(lo,hi-1)&g.y.notna()]
            assert len(train)>70 and (train.known_date<test.date.min()).all()
            p=test[['date','position','y','known_date','held_unreal']].copy();p['fold']=fold;p['target']=target
            fold_meta.append({'target':target,'fold':fold,'train_n':len(train),'test_n':len(test),'max_train_known_date':train.known_date.max(),'test_start':g.date.iloc[lo]})
            for name,cols in models.items():
                pred=ridge(train,test,cols);p[name]=np.clip(pred,0,1) if target=='fill' else pred
            ps.append(p)
            for c in allcols:
                q=train[c].quantile([1/3,2/3]).to_numpy(float);tr=np.searchsorted(q,train[c].to_numpy(),side='right');te=np.searchsorted(q,test[c].to_numpy(),side='right')
                means={i:float(train.y.iloc[np.flatnonzero(tr==i)].mean()) for i in range(3) if (tr==i).any()}
                order=sorted(means,key=lambda i:((means[i] if target in RISK else -means[i]),i));best=order[0];worst=order[-1]
                for group in range(3):
                    yy=test.y.iloc[np.flatnonzero(te==group)].to_numpy(float)
                    bins.append({'target':target,'signal':c,'fold':fold,'group':group,'cut1':float(q[0]),'cut2':float(q[1]),'train_n':int((tr==group).sum()),'train_mean':means.get(group),'train_best':group==best,'train_worst':group==worst,**amount(yy)})
        p=pd.concat(ps,ignore_index=True);predictions.append(p)
        result[target]={'valid_all_n':int(g.y.notna().sum()),'y':amount(p.y),'models':{name:metrics(p,name,target) for name in models}}
        print(target,'completed',len(p),flush=True)
    pd.concat(predictions,ignore_index=True).to_csv(HERE/'others/predictions.csv',index=False);pd.DataFrame(bins).to_csv(HERE/'others/univariate_bins.csv',index=False)
    save(HERE/'others/folds.json',fold_meta);save(HERE/'others/results.json',result)
    save(HERE/'others/design_counts.json',{'families':6,'expressions':24,'targets':9,'model_specifications':90,'fold_fits':360,'family_or_all_vs_price_comparisons':63,'legacy_reference_comparisons':9,'univariate_target_pairs':216,'continuous_accounts':0,'parameter_searches':0})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run']);{'prepare':prepare,'run':run}[p.parse_args().mode]()
