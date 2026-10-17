"""Separate environment discrimination from stronger model-selection utility."""
import json
import numpy as np
import pandas as pd
from inputs import ROOT,EX
from study import predict


def main():
    target=EX/'others/operational_result.json'
    if target.exists():raise RuntimeError('Preserve operational test')
    run=ROOT/'research/S014/assets/runs'/EX.name/'corrected'
    f=pd.read_csv(run/'features.csv',index_col='signal');labels=pd.read_csv(run/'labels.csv');old=pd.read_csv(run/'predictions.csv')
    q=labels.loc[labels.horizon.eq(3)];base=json.loads((EX/'others/computation_result_v2.json').read_text(encoding='utf-8'))['baseline_columns']
    frames=[];fits=0;splits=[]
    for year in (2023,2024,2025,2026):
        test=q.loc[q.year.eq(year)].copy();first=int(test.signal.min());train=q.loc[q.maturity.lt(first)]
        threshold=float(f.loc[train.signal,'gap_autocorr'].median());x=f.copy()
        x['high_state']=x.gap_autocorr.ge(threshold).astype(float)
        x['state_interaction']=x.high_state*x.gap_down_repair
        x['continuous_interaction']=x.gap_autocorr*x.gap_down_repair
        history=x.loc[np.isfinite(x).all(axis=1)&(x.index<=int(test.signal.max()))]
        for algo in ('ridge','tree'):
            for name,cols in {'base':base,'continuous':base+['gap_autocorr','continuous_interaction'],'binary':base+['high_state','state_interaction']}.items():
                scores=pd.Series(predict((algo,x.loc[train.signal,cols].to_numpy(),history[cols].to_numpy(),train.net_return.to_numpy())),index=history.index);fits+=1
                cut=scores.shift().rolling(126).quantile(.75)
                test[f'prediction_{algo}_{name}']=scores.loc[test.signal].to_numpy()
                test[f'selected_{algo}_{name}']=(scores.loc[test.signal]>=cut.loc[test.signal]).to_numpy()
                if name=='base':np.testing.assert_allclose(test[f'prediction_{algo}_{name}'],old.loc[old.horizon.eq(3)&old.year.eq(year),f'prediction_{algo}_base'],rtol=0,atol=1e-10)
        test['parent']=x.loc[test.signal,'gap_down_repair'].eq(1).to_numpy();test['state_high']=x.loc[test.signal,'high_state'].eq(1).to_numpy();frames.append(test)
        splits.append({'year':year,'threshold':threshold,'first_signal':first,'latest_train_maturity':int(train.maturity.max())})
    p=pd.concat(frames,ignore_index=True).sort_values('signal').reset_index(drop=True);annual=[];comps=[];columns=[];denominators=[]
    for algo in ('ridge','tree'):
        for name in ('continuous','binary'):
            a=p[f'selected_{algo}_{name}'].to_numpy();b=p[f'selected_{algo}_base'].to_numpy()
            for scope in ('all','parent'):
                mask=np.ones(len(p),dtype=bool) if scope=='all' else p.parent.to_numpy()
                delta=p.net_return.to_numpy()*(a.astype(float)-b.astype(float))*mask;columns.append(delta);denominators.append(mask)
                identity={'algorithm':algo,'model':name,'scope':scope}
                comps.append({**identity,'delta':float(delta.sum()/mask.sum())})
                for year,g in [('ALL',p),('WITHOUT2026',p.loc[p.year.ne(2026)]),*list(p.groupby('year'))]:
                    ix=g.index.to_numpy();d=delta[ix];m=mask[ix];positive=np.flatnonzero(d>0);trim=d.copy();trim[positive[np.argsort(d[positive])[-3:]]]=0
                    annual.append({**identity,'year':str(year),'n':int(m.sum()),'selected':int((a[ix]&m).sum()),'base_selected':int((b[ix]&m).sum()),
                        'delta':float(d.sum()/m.sum()),'drop_best3':float(trim.sum()/m.sum())})
    values=np.column_stack(columns);den=np.column_stack(denominators);rng=np.random.default_rng(13417);boot=[]
    for _ in range(2000):
        ix=np.concatenate([v[((rng.integers(0,len(v),size=(len(v)+19)//20)[:,None]+np.arange(20))%len(v)).ravel()[:len(v)]] for year in (2023,2024,2025,2026) for v in [np.flatnonzero(p.year.eq(year))]])
        boot.append(values[ix].sum(axis=0)/den[ix].sum(axis=0))
    boot=np.asarray(boot);point=values.sum(axis=0)/den.sum(axis=0);sd=boot.std(axis=0,ddof=1);safe=np.where(sd>0,sd,1.)
    critical=float(np.quantile(np.max(abs(boot-point)/safe,axis=1),.95))
    for i,r in enumerate(comps):r.update(ci_low=float(np.quantile(boot[:,i],.025)),ci_high=float(np.quantile(boot[:,i],.975)),simultaneous_low=float(point[i]-critical*sd[i]),simultaneous_high=float(point[i]+critical*sd[i]))
    direct=[]
    for year,g in [('ALL',p),('WITHOUT2026',p.loc[p.year.ne(2026)]),*list(p.groupby('year'))]:
        parent=g.loc[g.parent];weak=~parent.state_high
        direct.append({'year':str(year),'parent_n':len(parent),'weak_n':int(weak.sum()),'delta_per_parent':float(-(parent.net_return*weak).mean())})
    p.to_csv(run.parent/'operational_predictions.csv',index=False,lineterminator='\n')
    pd.DataFrame(annual).to_csv(EX/'others/operational_annual.csv',index=False,lineterminator='\n')
    target.write_text(json.dumps({'fits':fits,'splits':splits,'comparisons':comps,'direct_filter':direct,'source_calls':0,'strategy_accounts':0},indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'comparisons':comps,'direct_filter':direct},ensure_ascii=False))


if __name__=='__main__':main()
