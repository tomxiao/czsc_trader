"""Direct mechanism contrasts plus numerical-estimator placebo diagnostics."""
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from inputs import ROOT,EX
from study import predict
from features import GROUPS

RUN=ROOT/'research/S014/assets/runs'/EX.name/'corrected'


def main():
    target=EX/'others/direct_result.json'
    if target.exists():raise RuntimeError('Preserve direct result')
    f=pd.read_csv(RUN/'features.csv',index_col='signal');p=pd.read_csv(RUN/'predictions.csv');labels=pd.read_csv(RUN/'labels.csv')
    main_result=json.loads((EX/'others/computation_result_v2.json').read_text(encoding='utf-8'))
    comparisons=[];annual=[];observations=[]
    dates=pd.to_datetime(p.drop_duplicates('signal').set_index('signal').signal_date)
    masks={}
    for h,g in p.groupby('horizon'):
        g=g.sort_values('signal').reset_index(drop=True);x=f.loc[g.signal].reset_index(drop=True)
        thresholds={}
        for year,part in g.groupby('year'):
            train=labels.loc[labels.horizon.eq(h)&labels.maturity.lt(int(part.signal.min()))]
            thresholds[int(year)]={c:float(f.loc[train.signal,c].median()) for c in ('positive_concentration','corr_sector','gap_autocorr')}
        med=lambda c:np.array([thresholds[int(y)][c] for y in g.year])
        conditions={
          'breakout_path':(x.retest_hold.eq(1),x.first_retest.eq(1)),
          'concentration':(x.ret20.gt(0)&x.ret1.gt(0),x.positive_concentration.le(med('positive_concentration'))),
          'participation':(x.ret5.lt(0)&x.ret1.gt(0),x.impact_change.lt(0)),
          'coupling':((x.twofactor_gap+x.twofactor_intraday).gt(0),x.corr_sector.ge(med('corr_sector'))),
          'session_memory':(x.gap_down_repair.eq(1),x.gap_autocorr.ge(med('gap_autocorr')))}
        greedy=np.zeros(len(g),dtype=bool);last=-1
        for i,r in g.iterrows():
            if r.entry>last:greedy[i]=True;last=int(r.maturity)
        for name,(parent,state) in conditions.items():
            a=(parent&state).to_numpy();b=(parent&~state).to_numpy();signal=g.signal.to_numpy(dtype=int)
            for mode in ('raw','residual'):
                y=g.net_return.to_numpy()-(g.prediction_ridge_base.to_numpy() if mode=='residual' else 0)
                row={'family':name,'horizon':int(h),'mode':mode,'selected':int(a.sum()),'control':int(b.sum())}
                row['difference']=float(y[a].mean()-y[b].mean()) if a.any() and b.any() else None
                row['selected_mean']=float(y[a].mean()) if a.any() else None
                row['control_mean']=float(y[b].mean()) if b.any() else None
                comparisons.append(row);masks[(name,int(h),mode)]=(g,signal,y,a,b)
                for year,part in [('ALL',g),*list(g.groupby('year'))]:
                    ix=part.index.to_numpy();aa=a[ix];bb=b[ix];yy=y[ix]
                    trim=np.ones(len(ix),dtype=bool);candidates=np.flatnonzero(aa&(yy>0));trim[candidates[np.argsort(yy[candidates])[-3:]]]=False
                    def diff(left,right):return float(yy[left].mean()-yy[right].mean()) if left.any() and right.any() else None
                    annual.append({**row,'year':str(year),'selected':int(aa.sum()),'control':int(bb.sum()),'difference':diff(aa,bb),
                        'trimmed_difference':diff(aa&trim,bb),'nonoverlap_difference':diff(aa&greedy[ix],bb&greedy[ix])})
            obs=g[['signal','signal_date','year','horizon','net_return']].copy();obs['family']=name;obs['a']=a;obs['b']=b;observations.append(obs)
    # Common complete trading-session grid; differing maturity tails remain missing.
    grid=np.arange(int(p.signal.min()),int(p.signal.max())+1);years=pd.Series(index=grid,dtype=float)
    for s,y in p[['signal','year']].drop_duplicates().itertuples(index=False,name=None):years.loc[s]=y
    assert years.notna().all()
    rng=np.random.default_rng(1317);draws=[]
    for _ in range(2000):
        draws.append(np.concatenate([v[((rng.integers(0,len(v),size=(len(v)+19)//20)[:,None]+np.arange(20))%len(v)).ravel()[:len(v)]] for y in (2023,2024,2025,2026) for v in [grid[years.to_numpy()==y]]]))
    draws=np.asarray(draws);boot=[]
    for row in comparisons:
        g,signal,y,a,b=masks[(row['family'],row['horizon'],row['mode'])]
        aa=np.zeros(grid[-1]+1);bb=aa.copy();ya=aa.copy();yb=aa.copy()
        aa[signal]=a;bb[signal]=b;ya[signal]=y*a;yb[signal]=y*b
        na=aa[draws].sum(axis=1);nb=bb[draws].sum(axis=1)
        values=np.divide(ya[draws].sum(axis=1),na,out=np.full(2000,np.nan),where=na>0)-np.divide(yb[draws].sum(axis=1),nb,out=np.full(2000,np.nan),where=nb>0)
        boot.append(values);row['bootstrap_missing']=int(np.isnan(values).sum())
    boot=np.column_stack(boot);points=np.array([r['difference'] if r['difference'] is not None else np.nan for r in comparisons]);sd=np.nanstd(boot,axis=0,ddof=1)
    critical=float(np.nanquantile(np.nanmax(abs(boot-points)/np.where(sd>0,sd,1),axis=1),.95))
    for i,row in enumerate(comparisons):
        if row['difference'] is not None:
            row.update(ci_low=float(np.nanquantile(boot[:,i],.025)),ci_high=float(np.nanquantile(boot[:,i],.975)),
                simultaneous_low=float(points[i]-critical*sd[i]),simultaneous_high=float(points[i]+critical*sd[i]))
    placebo=[];tie=[];fits=0
    q=labels.loc[labels.horizon.eq(5)];base=main_result['baseline_columns']
    for year in (2023,2024,2025,2026):
        test=q.loc[q.year.eq(year)].sort_values('signal');first=int(test.signal.min());train=q.loc[q.maturity.lt(first)]
        history=f.loc[np.isfinite(f).all(axis=1)&(f.index<=int(test.signal.max()))]
        old=p.loc[p.horizon.eq(5)&p.year.eq(year)].sort_values('signal')
        for name,cs in [('base',base),('added',base+GROUPS['drawdown_age']),('constant5',base)]:
            x=f.loc[train.signal,cs].to_numpy();z=history[cs].to_numpy()
            if name=='constant5':x=np.column_stack([x,np.zeros((len(x),5))]);z=np.column_stack([z,np.zeros((len(z),5))])
            scores=pd.Series(predict(('tree',x,z,train.net_return.to_numpy())),index=history.index);fits+=1
            threshold=scores.shift().rolling(126).quantile(.75);original=scores>=threshold;pure=original.copy()
            ties=np.array([int(sha256(f'S014-{i}-13017'.encode()).hexdigest()[:12],16)/16**12 for i in scores.index])
            values=scores.to_numpy()
            for i in range(126,len(scores)):
                if values[i]==threshold.iloc[i]:
                    before=values[i-126:i];pure.iloc[i]=np.mean((before<values[i])|((before==values[i])&(ties[i-126:i]<ties[i])))>=.75
            assert original[scores.ne(threshold)].equals(pure[scores.ne(threshold)])
            for mode,selection in [('original',original),('pure_tie',pure)]:
                mask=selection.loc[test.signal].to_numpy();base_old=old.select_tree_base.to_numpy()
                tie.append({'year':year,'model':name,'mode':mode,'selected':int(mask.sum()),'base_selected':int(base_old.sum()),
                    'per_origin':float((test.net_return.to_numpy()*mask).mean()),'delta_vs_original_base':float((test.net_return.to_numpy()*(mask.astype(float)-base_old.astype(float))).mean()),
                    'changed':int((mask!=original.loc[test.signal].to_numpy()).sum()),'n':len(test)})
            placebo.append({'year':year,'model':name,'predictions_differ_from_base':int((abs(scores.loc[test.signal].to_numpy()-old.prediction_tree_base.to_numpy())>1e-10).sum())})
    pd.concat(observations,ignore_index=True).to_csv(RUN.parent/'direct_observations.csv',index=False,lineterminator='\n')
    pd.DataFrame(annual).to_csv(EX/'others/direct_annual.csv',index=False,lineterminator='\n')
    target.write_text(json.dumps({'comparisons':comparisons,'placebo':placebo,'tie':tie,'fits':fits,'source_calls':0},ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('DIRECT_COMPLETE',len(comparisons),fits)


if __name__=='__main__':main()
