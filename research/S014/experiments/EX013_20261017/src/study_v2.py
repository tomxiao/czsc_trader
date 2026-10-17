"""Corrected fixed annual out-of-training census and common multiple-comparison diagnostics."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from hashlib import sha256
import json
import time
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeRegressor
from czsc_trader.research_tools import EvidenceRef
from inputs import ROOT,EX,RUN,load
from features_v2 import GROUPS,compute
RUN=ROOT/'research/S014/assets/runs'/EX.name/'corrected'


def predict(task):
    algo,x,z,y=task
    assert np.isfinite(x).all() and np.isfinite(z).all() and np.isfinite(y).all()
    if algo=='tree':
        model=DecisionTreeRegressor(max_depth=3,min_samples_leaf=40,random_state=13).fit(x,y)
        return model.predict(z)
    center=x.mean(axis=0);scale=x.std(axis=0);scale[scale<1e-12]=1.
    x=(x-center)/scale;z=(z-center)/scale
    beta=np.linalg.solve(x.T@x+10*np.eye(x.shape[1]),x.T@(y-y.mean()))
    return z@beta+y.mean()


def diagnostics(predictions,dates,bootstrap=True):
    results=[];annual=[];deltas=[]
    for h,p in predictions.groupby('horizon'):
        p=p.sort_values('signal').reset_index(drop=True);signals=p.signal.to_numpy(dtype=int);y=p.net_return.to_numpy()
        for algo in ('ridge','tree'):
            base=p[f'select_{algo}_base'].to_numpy(dtype=bool)
            for name in [*GROUPS,'joint']:
                selected=p[f'select_{algo}_{name}'].to_numpy(dtype=bool);delta=y*(selected.astype(float)-base.astype(float))
                identity={'horizon':int(h),'algorithm':algo,'family':name}
                record={**identity,'n':len(p),'selected':int(selected.sum()),'base_selected':int(base.sum()),
                    'filled_selected':int(p.loc[selected,'entry_filled'].sum()),'selected_mean':float(y[selected].mean()) if selected.any() else None,
                    'base_mean':float(y[base].mean()) if base.any() else None,'allocation_delta':float(delta.mean()),
                    'mae_delta':float((abs(p[f'prediction_{algo}_{name}']-y)-abs(p[f'prediction_{algo}_base']-y)).mean()),
                    'without_2026':float(delta[p.year.ne(2026)].mean())}
                years=[];trim=[]
                for year,g in p.groupby('year'):
                    idx=g.index.to_numpy();d=delta[idx];keep=np.ones(len(d),dtype=bool)
                    positive=np.flatnonzero(d>0);drop=positive[np.argsort(d[positive])[-3:]];keep[drop]=False
                    # Maintain original denominator and set omitted positive contributions to zero.
                    trimmed=float(d[keep].sum()/len(d));trim.append(trimmed)
                    sparse=(g.signal.to_numpy()-int(g.signal.min()))%(int(h)+1)==0
                    value={**identity,'year':int(year),'n':len(g),'selected':int(selected[idx].sum()),'base_selected':int(base[idx].sum()),
                        'allocation_delta':float(d.mean()),'drop_best3_delta':trimmed,'sparse_n':int(sparse.sum()),
                        'sparse_delta':float(d[sparse].mean()) if sparse.any() else None,
                        'selected_mean':float(y[idx][selected[idx]].mean()) if selected[idx].any() else None}
                    annual.append(value);years.append(value['allocation_delta'])
                record['positive_years']=sum(x>0 for x in years);record['mean_annual_trimmed']=float(np.mean(trim))
                results.append(record)
                vector=np.full(len(dates),np.nan);vector[signals]=delta;deltas.append(vector)
    matrix=np.column_stack(deltas);point=np.nanmean(matrix,axis=0)
    if bootstrap:
        rng=np.random.default_rng(13017);sample=[]
        blocks=[np.flatnonzero((dates.year==year)&np.any(np.isfinite(matrix),axis=1)) for year in (2023,2024,2025,2026)]
        for _ in range(2000):
            ix=np.concatenate([block[((rng.integers(0,len(block),size=(len(block)+19)//20)[:,None]+np.arange(20))%len(block)).ravel()[:len(block)]] for block in blocks])
            sample.append(np.nanmean(matrix[ix],axis=0))
        values=np.asarray(sample);sd=values.std(axis=0,ddof=1);safe=sd.copy();safe[safe==0]=1.
        maximum=np.max(abs(values-point)/safe,axis=1);critical=float(np.quantile(maximum,.95))
        for j,r in enumerate(results):
            r.update(ci_low=float(np.quantile(values[:,j],.025)),ci_high=float(np.quantile(values[:,j],.975)),
                simultaneous_low=float(point[j]-critical*sd[j]),simultaneous_high=float(point[j]+critical*sd[j]))
    return results,annual,matrix


def main():
    if RUN.exists():raise RuntimeError('Preserve original run')
    start=time.monotonic()
    for receipt in ('published_design','published_implementation_v2'):
        for v in json.loads((EX/f'protocols/{receipt}.json').read_text(encoding='utf-8')).values():
            r=EvidenceRef.from_dict(v);assert sha256(r.resolve(ROOT).read_bytes()).hexdigest()==r.sha256
    data,dates,labels,legacy,previous,sources=load()
    feature,base=compute(data,legacy,previous)
    for n in (400,801,1200):
        prefix,_=compute({k:v.iloc[:n].copy() for k,v in data.items()},legacy.iloc[:n],previous.iloc[:n])
        pd.testing.assert_frame_equal(feature.iloc[:n],prefix,check_exact=False,rtol=0,atol=1e-12)
    altered={k:v.copy() for k,v in data.items()}
    altered['stock.ohlcv'].loc[801:,['Open','High','Low','Close']]*=1.37
    future,_=compute(altered,legacy,previous)
    pd.testing.assert_frame_equal(feature.iloc[:801],future.iloc[:801],check_exact=False,rtol=0,atol=1e-12)
    models={'base':base,**{k:base+v for k,v in GROUPS.items()},'joint':base+sum(GROUPS.values(),[])}
    valid=np.isfinite(feature.to_numpy(dtype=float)).all(axis=1)
    valid_ids=np.flatnonzero(valid);assert len(valid_ids)>1200
    labels=labels.loc[labels.maturity.ge(0)&labels.signal.isin(valid_ids)].copy()
    labels['year']=[dates[int(s)].year for s in labels.signal]
    frames=[];splits=[];fits=0
    with ProcessPoolExecutor(max_workers=2,mp_context=get_context('spawn')) as pool:
        synthetic=('ridge',np.arange(80).reshape(20,4).astype(float),np.ones((3,4)),np.arange(20).astype(float))
        np.testing.assert_array_equal(predict(synthetic),pool.submit(predict,synthetic).result())
        for h in (1,3,5,10,20):
            q=labels.loc[labels.horizon.eq(h)].sort_values('signal')
            for year in (2023,2024,2025,2026):
                test=q.loc[q.year.eq(year)].copy();first=int(test.signal.min());last=int(test.signal.max())
                train=q.loc[q.maturity.lt(first)];assert train.maturity.max()<first
                history=feature.loc[valid & (feature.index<=last)]
                tasks={(algo,name):pool.submit(predict,(algo,feature.loc[train.signal,cols].to_numpy(),history[cols].to_numpy(),train.net_return.to_numpy())) for algo in ('ridge','tree') for name,cols in models.items()}
                for (algo,name),job in tasks.items():
                    scores=pd.Series(job.result(),index=history.index);fits+=1
                    threshold=scores.shift().rolling(126,min_periods=126).quantile(.75)
                    assert threshold.loc[test.signal].notna().all()
                    test[f'prediction_{algo}_{name}']=scores.loc[test.signal].to_numpy()
                    test[f'threshold_{algo}_{name}']=threshold.loc[test.signal].to_numpy()
                    test[f'select_{algo}_{name}']=test[f'prediction_{algo}_{name}']>=test[f'threshold_{algo}_{name}']
                frames.append(test);splits.append({'horizon':h,'year':year,'train_n':len(train),'test_n':len(test),'first_signal':first,'latest_train_maturity':int(train.maturity.max())})
            print('HORIZON_COMPLETE',h,flush=True)
    p=pd.concat(frames,ignore_index=True)
    comparisons,annual,matrix=diagnostics(p,dates)
    RUN.mkdir(parents=True)
    feature.to_csv(RUN/'features.csv',index_label='signal',lineterminator='\n')
    labels.to_csv(RUN/'labels.csv',index=False,lineterminator='\n')
    p.to_csv(RUN/'predictions.csv',index=False,lineterminator='\n')
    pd.DataFrame(annual).to_csv(EX/'others/annual_v2.csv',index=False,lineterminator='\n')
    result={'sources':sources,'fits':fits,'primary_comparisons':len(comparisons),'baseline_columns':base,'groups':GROUPS,
        'feature_columns':len(feature.columns),'first_valid_signal':int(valid_ids.min()),'valid_sessions':len(valid_ids),
        'splits':splits,'comparisons':comparisons,'prechecks':['3prefixes','future_perturbation','spawn_equal','cross_label_horizons_equal'],
        'new_source_calls':0,'strategy_accounts':0,'seconds':time.monotonic()-start,'phase_two_complete':False}
    assert fits==360 and len(comparisons)==80
    (EX/'others/computation_result_v2.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:result[k] for k in ('fits','primary_comparisons','feature_columns','first_valid_signal','seconds')}),flush=True)


if __name__=='__main__':main()
