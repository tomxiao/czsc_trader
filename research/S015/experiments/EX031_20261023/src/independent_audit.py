"""Independent fixed funding audit; reads local S015 artifacts, no data calls."""
import os
for _key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[_key] = '1'
import json
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / 'research/S015/experiments'
H = BASE / 'EX027_20261023/others'
DEST = BASE / 'EX031_20261023/others/independent_audit.json'
F = ['f1','f5','f20','persist5']
C = ['r1','r5','vol20','pressure','range20']
SEG = [(100,184),(184,268),(268,352),(352,434)]
counts = {}
maxdiff = {}

def read(p):
    return json.loads(p.read_bytes())

def check(a,b,category,tol=1e-10):
    if a is None or b is None:
        assert a is None and b is None, (category,a,b)
    else:
        delta = abs(float(a)-float(b))
        assert delta <= tol * max(1.,abs(float(a)),abs(float(b))), (category,a,b,delta)
        maxdiff[category] = max(maxdiff.get(category,0),delta)
    counts[category] = counts.get(category,0)+1

def metrics(frame):
    y = frame.y.to_numpy()
    bm = np.average(np.square(frame.base.to_numpy()-y))
    fm = np.average(np.square(frame.fund.to_numpy()-y))
    out = {'n':len(frame),'base_mse':bm,'fund_mse':fm,'relative_mse_gain':1-fm/bm,'filters':{}}
    positives = sum(float(v) for v in y if v>0)
    negatives = sum(-float(v) for v in y if v<0)
    for name in ('base','fund'):
        rejected = [(float(v),float(p)) for v,p in zip(y,frame[name]) if p<0]
        pos = sum(v for v,_ in rejected if v>0)
        neg = sum(-v for v,_ in rejected if v<0)
        out['filters'][name] = dict(reject_n=len(rejected),rejected_negative_n=sum(v<0 for v,_ in rejected),rejected_positive_n=sum(v>0 for v,_ in rejected),caught_negative_yuan=neg*100000,missed_positive_yuan=pos*100000,caught_negative_fraction=neg/negatives if negatives else None,missed_positive_fraction=pos/positives if positives else None)
    return out

def compare_metrics(a,b):
    for key,val in a.items():
        if key=='filters':
            for model,values in val.items():
                for field,value in values.items(): check(value,b[key][model][field],'filter_'+field)
        else: check(val,b[key],'metric_'+key)

def predict(train,test,cols,target):
    # Augmented least-squares system, independent of production normal equations.
    xa = np.asarray(train[cols],float)
    xb = np.asarray(test[cols],float)
    mu = np.average(xa,axis=0)
    scale = np.sqrt(np.average((xa-mu)**2,axis=0))
    scale = np.where(scale==0,1,scale)
    xa = np.c_[np.ones(len(xa)),(xa-mu)/scale]
    xb = np.c_[np.ones(len(xb)),(xb-mu)/scale]
    penalty = np.diag([0]+[np.sqrt(10)]*len(cols))
    coef = np.linalg.lstsq(np.r_[xa,penalty],np.r_[np.asarray(train[target])/100000,np.zeros(len(cols)+1)],rcond=None)[0]
    return xb@coef

def main():
    shares = pd.read_csv(H/'own_shares.csv')
    assert len(shares)==508 and len(set(shares.Date))==508
    assert shares.Date.iloc[0]=='2024-09-10' and shares.Date.iloc[-1]=='2026-10-21'
    assert all(shares.TotalShare>0)
    inputs = read(H/'input_refs.json')
    event_ref = EvidenceRef.from_dict(inputs['events'])
    events = pd.read_csv(event_ref.resolve(ROOT))
    assert len(events)==1302
    closed = events[events.status=='CLOSED']
    assert len(closed)==1269
    for r in closed.itertuples():
        check(r.net,r.quantity*(r.sell_price-r.buy_price)-r.quantity*(r.sell_price+r.buy_price)*.001,'closed_fee_formula',1e-9)
        check(r.entry_net,r.entry_gross-r.buy_fee,'entry_fee_formula',1e-9)
        check(r.gross,r.entry_gross+r.subsequent_gross,'gross_attribution',1e-9)
    frames = {}
    earliest = 999
    for lag in (1,2,3):
        x = pd.read_csv(H/f'features_lag{lag}.csv'); frames[lag]=x
        assert len(x)==434 and set(x.date)==set(events.date)
        for r in x.itertuples():
            # In 508-row share vector, development starts at 74, not raw-price 75.
            j = 74+int(r.position)-lag
            assert shares.Date.iloc[74+int(r.position)]==r.date
            assert shares.Date.iloc[j]<r.date
            for k in (1,5,20):
                earliest=min(earliest,j-k)
                check(getattr(r,f'f{k}'),shares.TotalShare.iloc[j]/shares.TotalShare.iloc[j-k]-1,'scalar_share_feature')
            p = sum(shares.TotalShare.iloc[q]>shares.TotalShare.iloc[q-1] for q in range(j-4,j+1))/5-.5
            check(r.persist5,p,'scalar_persistence')
    assert earliest==51 # raw price index52; missing index0 cannot be used.
    quadrants = read(BASE/'EX029_20261023/others/results.json')
    for horizon in (1,3,5):
        g = closed[closed.horizon==horizon].merge(frames[1],on=['date','position'],suffixes=('','_feature'),validate='one_to_one')
        total=0
        for fs in ('positive','negative','zero'):
            for ps in ('up','down','flat'):
                rows=[r for r in g.itertuples() if ('positive' if r.f5>0 else 'negative' if r.f5<0 else 'zero')==fs and ('up' if r.r5>0 else 'down' if r.r5<0 else 'flat')==ps]
                reported=quadrants[str(horizon)]['cells'][f'{fs}_{ps}']
                check(len(rows),reported['n'],'quadrant_n');total+=len(rows)
                check(sum(r.net for r in rows),reported['net_yuan'],'quadrant_net',1e-9)
                check(sum(r.net for r in rows if r.net>0),reported['positive_yuan'],'quadrant_positive',1e-9)
                check(-sum(r.net for r in rows if r.net<0),reported['negative_yuan'],'quadrant_negative',1e-9)
        check(total,len(g),'quadrant_denominator')
    train_audit=[]
    extrapolation=[]
    for lag in (1,2,3):
        x=frames[lag]
        if lag==1:
            summaries=read(BASE/'EX030_20261023/others/results.json')
            pred=pd.read_csv(BASE/'EX030_20261023/others/predictions.csv')
        else:
            summaries=read(BASE/'EX031_20261023/others/results.json')[str(lag)]['models']
            pred=pd.read_csv(BASE/f'EX031_20261023/others/predictions_lag{lag}.csv')
        for target,horizon in [('net',1),('net',3),('net',5),('entry_net',1)]:
            key=f'{target}_h{horizon}'
            g=events[events.horizon==horizon].merge(x[['date',*F,*C]],on='date',validate='one_to_one',suffixes=('_event',''))
            if target=='net':g=g[g.status=='CLOSED'].copy();known='actual_exit_date'
            else:g=g[g.entry_net.notna()].copy();known='entry_date'
            for lo,hi in SEG:
                cutoff=x.date.iloc[lo]
                train=g[(g.position<lo)&(g[known]<cutoff)]
                test=g[(g.position>=lo)&(g.position<hi)]
                actual=pred[(pred.target==key)&(pred.fold==f'{lo}:{hi}')].sort_values('position')
                assert list(actual.position)==list(test.position)
                assert all(train[known]<cutoff)
                assert set(train.position).isdisjoint(test.position)
                check(len(train),summaries[key]['folds'][f'{lo}:{hi}']['train_n'],'purged_train_n')
                for model,cols in [('base',C),('fund',C+F)]:
                    independently=predict(train,test,cols,target)
                    for a,b in zip(independently,actual[model]):check(a,b,'ridge_prediction',1e-11)
                for a,b in zip(test[target]/100000,actual.y):check(a,b,'prediction_target')
                compare_metrics(metrics(actual),summaries[key]['folds'][f'{lo}:{hi}'])
                train_audit.append(dict(lag=lag,target=key,fold=f'{lo}:{hi}',train_n=len(train),test_n=len(test),max_train_known_date=train[known].max(),cutoff=cutoff))
                if target=='net' and horizon==1:
                    for f in F:
                        low=float(train[f].min());high=float(train[f].max())
                        extrapolation.append(dict(lag=lag,fold=f'{lo}:{hi}',feature=f,train_min=low,train_max=high,test_min=float(test[f].min()),test_max=float(test[f].max()),test_below_train=int((test[f]<low).sum()),test_above_train=int((test[f]>high).sum()),test_n=len(test)))
            allpred=pred[pred.target==key]
            compare_metrics(metrics(allpred),summaries[key])
            reduced=allpred.drop(allpred.y.abs().nlargest(5).index)
            compare_metrics(metrics(reduced),summaries[key]['omit_largest5_absolute_label'])
    distribution={}
    x=frames[1]
    for lo,hi in [(0,100),*SEG]:
        group=x.iloc[lo:hi]
        distribution[f'{lo}:{hi}']={f:dict(positive_n=int((group[f]>0).sum()),negative_n=int((group[f]<0).sum()),zero_n=int((group[f]==0).sum()),minimum=float(group[f].min()),maximum=float(group[f].max())) for f in F}
    for r in events[events.horizon==1].merge(x[['date','pressure']],on='date',suffixes=('_old','_new')).itertuples():
        check(r.pressure_old,r.pressure_new,'historical_pressure_identity')
    result=dict(status='PASS',method='Independent scalar share formulas, fee identities, 9-cell partition, augmented least-squares ridge, independent metric summations. No main-study imports or external calls.',checks=counts,max_absolute_difference=maxdiff,share_missing_day=dict(missing='2024-09-09',earliest_required_share_vector_index=earliest,earliest_required_raw_price_index=earliest+1,earliest_required_date=shares.Date.iloc[earliest],development_rows=434,all_features_finite=all(np.isfinite(x[F+C]).all().all() for x in frames.values())),folds=train_audit,fixed_period_feature_distribution=distribution,range_extrapolation_diagnostic=extrapolation,interpretation=['All 12 aggregate funding-augmented models (3 lags x 4 labels) have worse MSE than fixed price/volume controls. This rejects useful predictive increment for this model specification, not all potential funding mechanisms.','The f20 positive-vs-negative unconditional spread is confounded with time regimes: all 84 decisions in fixed period 184:268 are positive and share growth exceeds prior training ranges. Block bootstrap does not by itself resolve this regime confounding.','Entry-day funding filter catches 40.576% negative amount and misses 21.902% positive amount at lag1, versus baseline 47.979% and 32.624%. This is a tradeoff with fewer rejected events, not a simultaneous improvement in both rates.','persist5 equals positive-day count divided by 5 minus 0.5: exact zero group is mathematically impossible, not a data gap.'],limitations=['Fund publication and revision PIT not authenticated; next-session availability is a stated assumption.','MSE and loss-filter results are event-level diagnostics on seen development data, not account qualification.','Four primary price/share quadrants plus zero/flat partitions are descriptive and cannot establish causality or eliminate arbitrage/product-substitution alternatives.','Does not rerun exchange execution simulation or verify provider historical revisions.'])
    DEST.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    print(json.dumps({'status':result['status'],'checks':sum(counts.values()),'folds':len(train_audit),'earliest_required_date':shares.Date.iloc[earliest]}))

if __name__=='__main__':main()
