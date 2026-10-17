"""Targeted falsification, fixed neighbors and paired duration uncertainty."""
import json
import numpy as np
import pandas as pd
from study import ROOT,EX,RUN,OLD,source,nonoverlap

def pair_summary(m,metric):
    m=m.sort_values('a').copy();c=-1;end=-1;clusters=[]
    for row in m.itertuples():
        if row.a_entry>end:c+=1
        clusters.append(c);end=max(end,row.a_end)
    m['cluster']=clusters
    vals=m.groupby('cluster')[metric].mean();minus=[float(vals.drop(i).mean()) for i in vals.index] if len(vals)>1 else []
    # Keep pairs with no overlap within either leg. Cross-leg dependence still disclosed.
    keep=[];intervals=[]
    for i,row in m.iterrows():
        intervals_new=[(int(row.a_entry),int(row.a_end)),(int(row.b_entry),int(row.b_end))]
        overlap=lambda x,y:max(x[0],y[0])<=min(x[1],y[1])
        if overlap(*intervals_new) or any(overlap(x,y) for x in intervals_new for y in intervals):continue
        keep.append(i);intervals.extend(intervals_new)
    return {'n':len(m),'mean':float(m[metric].mean()),'clusters':len(vals),'cluster_equal':float(vals.mean()),
        'leave_one_min':min(minus) if minus else None,'leave_one_max':max(minus) if minus else None,
        'both_leg_n':len(keep),'both_leg_mean':float(m.loc[keep,metric].mean()) if keep else None},m

def mean_ci(g,columns,dates,block=60):
    rng=np.random.default_rng(14018);idx=g.signal.to_numpy(int);calendar=np.arange(len(dates))
    ranges=[np.flatnonzero((dates.year==y)&(calendar>=idx.min())&(calendar<=idx.max())) for y in (2023,2024,2025,2026)]
    sums=np.zeros((len(dates),len(columns)));count=np.zeros(len(dates));sums[idx]=g[columns];count[idx]=1;draw=[]
    for _ in range(2000):
        ix=np.concatenate([a[((rng.integers(0,len(a),size=(len(a)+block-1)//block)[:,None]+np.arange(block))%len(a)).ravel()[:len(a)]] for a in ranges if len(a)])
        if count[ix].sum():draw.append(sums[ix].sum(axis=0)/count[ix].sum())
    draw=np.asarray(draw)
    return [{'metric':col,'mean':float(g[col].mean()),'low':float(np.quantile(draw[:,j],.025)),'high':float(np.quantile(draw[:,j],.975)),
        'trim_best3':float(g[col].sort_values().iloc[:-3].mean()) if len(g)>3 else None} for j,col in enumerate(columns)]

def main():
    target=EX/'others/followup.json'
    if target.exists():raise RuntimeError('Preserve followup')
    g=pd.read_csv(RUN/'observations.csv');d=pd.read_csv(RUN/'duration.csv');f=pd.read_csv(RUN/'features.csv',index_col='signal')
    labels,_=source('ex013-corrected-labels-csv');pred,_=source('ex013-corrected-predictions-csv')
    dates=pd.DatetimeIndex(pd.to_datetime(labels.drop_duplicates('signal').sort_values('signal').signal_date))
    # Recover the full calendar solely from already bound input; not compacted event time.
    import importlib.util
    spec=importlib.util.spec_from_file_location('prior_inputs',OLD/'src/inputs.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    data,dates,*_=mod.load()
    ret_market=np.log(data['market'].Close);ret_sector=np.log(data['sector'].Close)
    rows=[];matched=[];volrows=[];cells=[]
    risk=g.loc[g.parent_high].copy()
    for window in (3,5,10):
        mw=(ret_market-ret_market.shift(window)).lt(0);sw=(ret_sector-ret_sector.shift(window)).lt(0)
        for h in (1,3,5):
            if window!=5 and h!=3:continue
            q=labels.loc[labels.horizon.eq(h)].set_index('signal');s=risk.loc[risk.signal.isin(q.index)].copy();s['y']=q.loc[s.signal,'net_return'].to_numpy()
            s['market_down']=mw.loc[s.signal].to_numpy();s['sector_down']=sw.loc[s.signal].to_numpy();s['both']=s.market_down&s.sector_down
            for scope,part in [('ALL',s),('WITHOUT2026',s.loc[s.year.ne(2026)]),*[(str(y),v) for y,v in s.groupby('year')]]:
                for kind,mask in [('both',part.both),('market',part.market_down),('sector',part.sector_down)]:
                    a=part.loc[mask,'y'];b=part.loc[~mask,'y']
                    rows.append({'window':window,'horizon':h,'scope':scope,'kind':kind,'a':len(a),'b':len(b),'return_diff':float(a.mean()-b.mean()),'down_diff':float(a.clip(upper=0).mean()-b.clip(upper=0).mean())})
                if window==5 and h==3:
                    for m in (False,True):
                        for sec in (False,True):
                            yy=part.loc[part.market_down.eq(m)&part.sector_down.eq(sec),'y']
                            cells.append({'scope':scope,'market_down':m,'sector_down':sec,'n':len(yy),'mean':float(yy.mean()) if len(yy) else None,'downside':float(yy.clip(upper=0).mean()) if len(yy) else None})
    for year,part in risk.groupby('year'):
        first=int(g.loc[g.year.eq(year),'signal'].min());train=labels.loc[labels.horizon.eq(3)&labels.maturity.lt(first)]
        cuts=f.loc[train.signal,'vol20'].quantile([.25,.5,.75]).to_numpy();buckets=np.searchsorted(cuts,part.vol20)
        for bucket in range(4):
            v=part.loc[buckets==bucket];a=v.loc[v.risk_joint_market_weakness,'net_return'];b=v.loc[~v.risk_joint_market_weakness,'net_return']
            volrows.append({'year':int(year),'bucket':bucket,'a':len(a),'b':len(b),'weight':min(len(a),len(b)),
                'down_diff':float(a.clip(upper=0).mean()-b.clip(upper=0).mean()) if len(a) and len(b) else None,'return_diff':float(a.mean()-b.mean()) if len(a) and len(b) else None})
    allpairs=pd.read_csv(EX/'others/matches.csv');p=allpairs.loc[allpairs.name.eq('joint_market_weakness')].copy()
    p['down_diff']=p.a_return.clip(upper=0)-p.b_return.clip(upper=0);p['return_diff']=p.a_return-p.b_return
    for scope,part in [('ALL',p),('WITHOUT2026',p.loc[p.year.ne(2026)]),*[(str(y),v) for y,v in p.groupby('year')]]:
        for metric in ('down_diff','return_diff'):
            summary,clusters=pair_summary(part,metric);summary.update(scope=scope,metric=metric,
                drop_most_negative3=float(part[metric].sort_values().iloc[3:].mean()))
            matched.append(summary)
    _,clusterpairs=pair_summary(p,'down_diff');clusterpairs.to_csv(EX/'others/risk_pair_clusters.csv',index=False,lineterminator='\n')
    riskres=[]
    controls=['vol20','abs_gap','intraday','ret20','market_ret5','sector_ret5']
    for year,part in g.groupby('year'):
        train=labels.loc[labels.horizon.eq(3)&labels.maturity.lt(int(part.signal.min()))]
        tx=f.loc[train.signal,controls].to_numpy();test=f.loc[part.signal,controls].to_numpy()
        center=tx.mean(axis=0);scale=tx.std(axis=0);scale[scale<1e-12]=1
        tx=(tx-center)/scale;test=(test-center)/scale;y=train.net_return.clip(upper=0).to_numpy()
        beta=np.linalg.solve(tx.T@tx+10*np.eye(len(controls)),tx.T@(y-y.mean()))
        predicted=test@beta+y.mean();actual=part.net_return.clip(upper=0).to_numpy()
        for pos,(_,row) in enumerate(part.iterrows()):
            riskres.append({'signal':int(row.signal),'year':int(year),'parent_high':bool(row.parent_high),'risk':bool(row.risk_joint_market_weakness),
                'prediction':float(predicted[pos]),'residual':float(actual[pos]-predicted[pos])})
    pd.DataFrame(riskres).to_csv(EX/'others/risk_residual_observations.csv',index=False,lineterminator='\n')
    dur=[];increments=[];residual=[]
    horizons=[1,3,5,10,20]
    for left,right in zip(horizons[:-1],horizons[1:]):d[f'inc_{left}_{right}']=d['y'+str(right)]-d['y'+str(left)]
    d['inc_3_20']=d.y20-d.y3
    cols=[c for c in d if c.startswith('inc_')]
    for scope,part in [('ALL',d),('WITHOUT2026',d.loc[d.year.ne(2026)]),*[(str(y),v) for y,v in d.groupby('year')],('NONOVERLAP',nonoverlap(d,'end20'))]:
        for state in (False,True):
            sub=part.loc[part.high.eq(state)]
            for value in mean_ci(sub,cols,dates):increments.append({'scope':scope,'high':state,'n':len(sub),**value})
    oldpairs=pd.read_csv(OLD/'others/session_matches.csv');oldpairs=oldpairs.loc[oldpairs.a.isin(d.signal)&oldpairs.b.isin(d.signal)].copy();lookup=d.set_index('signal')
    for h in horizons:
        p=oldpairs.copy();p['a_entry']=lookup.loc[p.a,'entry'].to_numpy();p['b_entry']=lookup.loc[p.b,'entry'].to_numpy()
        p['a_end']=lookup.loc[p.a,'end20'].to_numpy();p['b_end']=lookup.loc[p.b,'end20'].to_numpy()
        p['effect']=lookup.loc[p.a,'y'+str(h)].to_numpy()-lookup.loc[p.b,'y'+str(h)].to_numpy()
        for scope,part in [('ALL',p),('WITHOUT2026',p.loc[p.year.ne(2026)]),*[(str(y),v) for y,v in p.groupby('year')]]:
            summary,_=pair_summary(part,'effect');dur.append({'horizon':h,'scope':scope,**summary})
        q=pred.loc[pred.horizon.eq(h)].set_index('signal');y=d['y'+str(h)].to_numpy()-q.loc[d.signal,'prediction_ridge_base'].to_numpy()
        for scope,mask in [('ALL',np.ones(len(d),bool)),('WITHOUT2026',d.year.ne(2026).to_numpy())]:
            residual.append({'horizon':h,'scope':scope,'difference':float(y[mask&d.high.to_numpy()].mean()-y[mask&~d.high.to_numpy()].mean())})
    for name,values in [('risk_neighbors',rows),('risk_cells',cells),('risk_volatility',volrows),('risk_matching',matched),('duration_matching',dur),('duration_increment_ci',increments),('duration_residual',residual)]:pd.DataFrame(values).to_csv(EX/'others'/f'{name}.csv',index=False,lineterminator='\n')
    target.write_text(json.dumps({'risk_pairs':len(clusterpairs),'duration_pairs':len(oldpairs),'source_calls':0,'account_runs':0,'block_length':60,'bootstrap_reps':2000},indent=2)+'\n',encoding='utf-8',newline='\n')
    print('FOLLOWUP_COMPLETE')
if __name__=='__main__':main()
