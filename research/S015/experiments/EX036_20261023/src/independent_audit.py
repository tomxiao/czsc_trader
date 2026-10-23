"""Independent stage-two audit: labels, augmented least squares, folds and utilities."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

HERE=Path(__file__).resolve().parents[1]
ROOT=HERE.parents[3]
BASE=HERE.parent
CHECKS=0
def read(p):return json.loads(p.read_bytes())
def eq(a,b):
    global CHECKS
    if a is None or b is None:assert a is None and b is None,(a,b)
    elif isinstance(a,(str,bool)):assert a==b,(a,b)
    else:np.testing.assert_allclose(a,b,rtol=2e-8,atol=2e-11,equal_nan=True)
    CHECKS+=1
def ratio(a,b):return float(a/b) if b else None
def amount(y):
    y=np.asarray(y,float)
    return dict(n=len(y),mean=float(y.mean()) if len(y) else None,positive_n=int(sum(y>0)),negative_n=int(sum(y<0)),positive_sum=float(sum(y[y>0])),negative_sum=float(-sum(y[y<0])))
def check_amount(actual,y):
    for k,v in amount(y).items():
        a=actual[k]
        if v is None and a is not None and pd.isna(a):a=None
        eq(a,v)
def utility(actual,p,col,target):
    y=p.y.to_numpy();v=p[col].to_numpy();risk=target in ('loss3','drawdown3')
    if target not in ('loss3','drawdown3','fill'):
        a=actual['zero_rule'];reject=v<0
        eq(a['reject_n'],sum(reject));eq(a['caught_loss_n'],sum(reject&(y<0)));eq(a['missed_profit_n'],sum(reject&(y>0)))
        eq(a['caught_loss_fraction'],ratio(-sum(y[reject&(y<0)]),-sum(y[y<0])))
        eq(a['missed_profit_fraction'],ratio(sum(y[reject&(y>0)]),sum(y[y>0])))
        check_amount(a['retained'],y[~reject]);check_amount(a['excluded'],y[reject])
    if target!='fill':
        chosen=[]
        for fold in sorted(p.fold.unique()):
            z=p[p.fold==fold]
            ix=sorted(z.index,key=lambda j:((z.loc[j,col] if risk else -z.loc[j,col]),z.loc[j,'position']))
            chosen+=ix[:(len(ix)+1)//2]
        eq(actual['selected_positions'],p.loc[chosen,'position'].tolist())
        check_amount(actual['equal_count_diagnostic'],p.loc[chosen,'y'])

def main():
    refs=read(HERE/'others/protocol_refs.json')
    for name,sub in [('validate.py','src'),('component_validation.json','protocols')]:
        assert EvidenceRef.from_dict(refs[name]).resolve(ROOT).read_bytes()==(HERE/sub/name).read_bytes()
    old=read(BASE/'EX035_20261023/others/published_refs.json')['materials']
    path=EvidenceRef.from_dict(old['src/census.py']).resolve(ROOT)
    # Load the workspace copy only after authenticating its bytes; its relative imports use its real location.
    actual=BASE/'EX035_20261023/src/census.py';assert actual.read_bytes()==path.read_bytes()
    spec=importlib.util.spec_from_file_location('audit_census',actual);loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)
    adj,raw,bars,ids=loader.data()
    e=pd.read_csv(EvidenceRef.from_dict(read(BASE/'EX026_20261023/others/delivery_validation.json')['materials']['events.csv']).resolve(ROOT))
    dic=read(EvidenceRef.from_dict(old['protocols/signal_dictionary.json']).resolve(ROOT));families=dic['families']
    x=pd.read_csv(HERE/'others/model_features.csv');labels=pd.read_csv(HERE/'others/labels.csv');pall=pd.read_csv(HERE/'others/predictions.csv');results=read(HERE/'others/results.json')
    census=pd.read_csv(EvidenceRef.from_dict(old['others/features.csv']).resolve(ROOT))
    assert x.date.tolist()==census.date.tolist()
    for col in [c for cols in families.values() for c in cols]:eq(x[col],census[col])
    c=adj.Close.to_numpy(float);returns=np.r_[np.nan,c[1:]/c[:-1]-1]
    eq(x.r1,returns[75:]);eq(x.r5,c[75:]/c[70:-5]-1)
    eq(x.vol20,[np.std(returns[j-19:j+1],ddof=1) for j in range(75,509)])
    amp=(adj.High.to_numpy()-adj.Low.to_numpy())/c
    eq(x.range20,[np.mean(amp[j-19:j+1]) for j in range(75,509)])
    eq(x.pressure,(raw.Close/(raw.Amount/raw.Volume)-1).iloc[75:])
    dates=pd.to_datetime(adj.Date).dt.strftime('%Y-%m-%d').tolist();index={d:i for i,d in enumerate(dates)}
    events={(int(r.position),int(r.horizon)):r for r in e.itertuples()}
    expected=[]
    for r in labels.itertuples():
        pos=int(r.position);t=r.target;y=np.nan;known=None;unreal=0.;cohort=np.nan
        if t in ('hold1','hold3'):
            age=int(t[-1])
            if pos>=age:
                a=events[pos-age,age];b=events[pos-age,age+2]
                if a.status=='CLOSED' and b.status=='CLOSED' and pd.notna(a.buy_price) and a.entry_date<=r.date:
                    eq(a.quantity,b.quantity);eq(a.buy_price,b.buy_price)
                    # Direct sell proceeds difference independently eliminates the common entry cashflow.
                    y=(b.quantity*b.sell_price-b.sell_fee-a.quantity*a.sell_price+a.sell_fee)/100000
                    known=max(a.actual_exit_date,b.actual_exit_date);unreal=(a.quantity*(c[index[r.date]]-a.buy_price)-a.buy_fee)/100000;cohort=pos-age
        else:
            h=int(t[-1]) if t in ('net1','net3','net5') else 3 if t in ('loss3','drawdown3') else 1
            a=events[pos,h]
            if t=='fill' and a.status!='NO_NEXT_SESSION':y=float(pd.notna(a.buy_price));known=a.entry_date
            elif t=='entry' and pd.notna(a.buy_price):y=(a.quantity*(c[index[a.entry_date]]-a.buy_price)-a.buy_fee)/100000;known=a.entry_date
            elif a.status=='CLOSED':
                net=(a.quantity*(a.sell_price-a.buy_price)-a.buy_fee-a.sell_fee)/100000
                if t.startswith('net'):y=net
                elif t=='loss3':y=max(-net,0)
                elif t=='drawdown3':y=max([0.]+[(a.quantity*(a.buy_price-c[j])+a.buy_fee)/100000 for j in range(index[a.entry_date],index[a.actual_exit_date])])
                known=a.actual_exit_date
        eq(r.y,y);eq(r.held_unreal,unreal);eq(r.cohort_signal_position,cohort)
        if np.isfinite(y):eq(r.known_date,known)
        expected.append(y)
    foldrecords=read(HERE/'others/folds.json');bins=pd.read_csv(HERE/'others/univariate_bins.csv')
    for target,result in results.items():
        lab=labels[labels.target==target].reset_index(drop=True);g=x.merge(lab[['position','y','known_date','held_unreal']],on='position',validate='one_to_one');p=pall[pall.target==target].reset_index(drop=True)
        eq(result['valid_all_n'],g.y.notna().sum());check_amount(result['y'],p.y)
        extra=['held_unreal'] if target.startswith('hold') else []
        price=['r1','r5','vol20','range20']
        models={'constant':[],'price':price+extra,'legacy':price+['pressure']+extra,**{k:price+extra+v for k,v in families.items()},'all':price+extra+sum(families.values(),[])}
        for fold,(lo,hi) in enumerate(((100,184),(184,268),(268,352),(352,434))):
            cutoff=g.date.iloc[lo];tr=g[(g.position<lo)&g.y.notna()&(g.known_date<cutoff)];te=g[(g.position>=lo)&(g.position<hi)&g.y.notna()];pred=p[p.fold==fold]
            eq(pred.position.tolist(),te.position.tolist());eq(pred.y,te.y)
            fm=next(r for r in foldrecords if r['target']==target and r['fold']==fold)
            for k,v in [('train_n',len(tr)),('test_n',len(te)),('max_train_known_date',tr.known_date.max()),('test_start',cutoff)]:eq(fm[k],v)
            for name,cols in models.items():
                if not cols:val=np.repeat(tr.y.mean(),len(te))
                else:
                    a=tr[cols].to_numpy();b=te[cols].to_numpy();mu=np.mean(a,axis=0);sd=np.std(a,axis=0);sd[sd==0]=1
                    a=np.c_[np.ones(len(a)),(a-mu)/sd];b=np.c_[np.ones(len(b)),(b-mu)/sd]
                    penalty=np.diag([0.]+[np.sqrt(10)]*len(cols));aug=np.vstack([a,penalty]);response=np.r_[tr.y.to_numpy(),np.zeros(len(cols)+1)]
                    val=b@np.linalg.lstsq(aug,response,rcond=None)[0]
                if target=='fill':val=np.minimum(1,np.maximum(0,val))
                eq(pred[name],val)
            for signal in sum(families.values(),[]):
                cut=np.quantile(tr[signal],[1/3,2/3]);tri=np.sum(tr[signal].to_numpy()[:,None]>=cut,axis=1);tei=np.sum(te[signal].to_numpy()[:,None]>=cut,axis=1)
                means={k:tr.y.to_numpy()[tri==k].mean() for k in range(3) if sum(tri==k)}
                order=sorted(means,key=lambda k:((means[k] if target in ('loss3','drawdown3') else -means[k]),k))
                rows=bins[(bins.target==target)&(bins.fold==fold)&(bins.signal==signal)]
                for row in rows.itertuples():
                    k=row.group;eq(row.cut1,cut[0]);eq(row.cut2,cut[1]);eq(row.train_n,sum(tri==k));eq(row.train_mean,means.get(k,np.nan));eq(row.train_best,k==order[0]);eq(row.train_worst,k==order[-1]);check_amount(row._asdict(),te.y.to_numpy()[tei==k])
        for name,out in result['models'].items():
            loss=(p[name]-p.y)**2;eq(out['n'],len(p));eq(out['mse'],loss.mean());utility(out['utility'],p,name,target)
            for ref in ('constant','price','legacy'):
                denominator=((p[ref]-p.y)**2).mean();eq(out['mse_gain_vs_'+ref],1-loss.mean()/denominator if denominator>0 else None)
            for fold,z in p.groupby('fold'):
                f=out['folds'][str(fold)];eq(f['n'],len(z));eq(f['mse_gain_vs_price'],1-((z[name]-z.y)**2).mean()/((z.price-z.y)**2).mean());utility(f['utility'],z,name,target)
            omit=p.drop(p.y.abs().nlargest(5).index);eq(out['omit_largest5_gain_vs_price'],1-((omit[name]-omit.y)**2).mean()/((omit.price-omit.y)**2).mean())
            for ref in ('price','legacy'):
                delta=np.full(434,np.nan);delta[p.position.to_numpy(int)]=((p[ref]-p.y)**2-loss).to_numpy();rng=np.random.default_rng(13);boot=[]
                for _ in range(499):
                    starts=rng.integers(415,size=22);indices=(starts[:,None]+np.arange(20)[None,:]).reshape(-1)[:434];boot.append(float(np.nanmean(delta[indices])))
                eq(out['paired_mse_reduction_ci_vs_'+ref],np.quantile(boot,[.025,.975]))
            if target not in ('loss3','drawdown3','fill'):
                change=np.where(p[name]>=0,p.y,0)-np.where(p.price>=0,p.y,0)
                u=out['zero_rule_increment_vs_price'];eq(u['mean_event_amount_per100k'],change.mean());eq(u['not_an_account'],True)
                delta=np.full(434,np.nan);delta[p.position.to_numpy(int)]=change;rng=np.random.default_rng(13);boot=[]
                for _ in range(499):
                    starts=rng.integers(415,size=22);indices=(starts[:,None]+np.arange(20)[None,:]).reshape(-1)[:434];boot.append(float(np.nanmean(delta[indices])))
                eq(u['ci95'],np.quantile(boot,[.025,.975]))
    artifacts=[Path(__file__),HERE/'src/validate.py',HERE/'protocols/component_validation.json',*[HERE/'others'/name for name in ('labels.csv','model_features.csv','predictions.csv','univariate_bins.csv','folds.json','results.json')]]
    hashes={str(path.relative_to(HERE)).replace('\\','/'):sha256(path.read_bytes()).hexdigest() for path in artifacts}
    out={'status':'PASS','scalar_or_array_checks':CHECKS,'targets':9,'model_specifications':90,'fold_fits':360,'univariate_bins':len(bins),'prediction_rows':len(pall),'label_rows':len(labels),'sha256':hashes,'method':'Independent label cashflows and close-risk reconstruction; augmented least-squares Ridge; all folds, predictions, utility denominators, rankings, bins and paired MSE bootstrap intervals. Authenticated inputs; no strategy accounts.','limitations':['Conditional on executed and complete events for monetary labels.','Equal-count per-fold selection is retrospective and not executable.','MSE block intervals are exploratory and unadjusted for multiple comparisons; all development observations have been seen.']}
    (HERE/'others/independent_audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__':main()
