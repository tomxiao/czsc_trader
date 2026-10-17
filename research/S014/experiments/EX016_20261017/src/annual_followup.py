"""Preserve annual calibration identity; disclose adaptive startup extension."""
import json
from hashlib import sha256
import numpy as np
import pandas as pd
from study import EX,ROOT,RUN,OLD,inputs,strict,clusters

COLS=['gap','intraday','ret1','ret5','ret20','range','volume_ratio','vol20','market_ret5','sector_ret5']

def calibrate(f,labels,dates):
    valid=np.isfinite(f.to_numpy(float)).all(axis=1)
    q=labels.loc[labels.horizon.eq(3)&labels.maturity.ge(0)&labels.signal.isin(f.index[valid])]
    threshold=pd.Series(np.nan,index=f.index);splits=[];previous=None;cut=None
    for i,year in enumerate(dates.year):
        if cut is None or year!=previous:
            train=q.loc[q.maturity.lt(i)]
            if len(train)>=60:
                cut=float(f.loc[train.signal,'gap_autocorr'].median())
                splits.append({'year':int(year),'signal':i,'date':str(dates[i].date()),'threshold':cut,'train_n':len(train),'last_maturity':int(train.maturity.max())})
        if cut is not None:threshold.loc[i]=cut
        previous=year
    return threshold,splits

def interval(g,dates,block):
    n=len(dates);a=np.zeros(n);b=a.copy();sa=a.copy();sb=a.copy();ext=a.copy();idx=g.signal.to_numpy(int)
    a[idx]=g.high;b[idx]=~g.high;sa[idx]=g.net_return*g.high;sb[idx]=g.net_return*~g.high;ext[idx]=g.extension*~g.high
    chunks=[np.flatnonzero((dates.year==y)&(np.arange(n)>=idx.min())&(np.arange(n)<=idx.max())) for y in sorted(set(g.year))]
    rng=np.random.default_rng(16017);draw=[]
    for _ in range(2000):
        ix=np.concatenate([x[((rng.integers(0,len(x),size=(len(x)+block-1)//block)[:,None]+np.arange(block))%len(x)).ravel()[:len(x)]] for x in chunks])
        if a[ix].sum() and b[ix].sum():draw.append([sa[ix].sum()/a[ix].sum()-sb[ix].sum()/b[ix].sum(),ext[ix].sum()/b[ix].sum()])
    draws=np.array(draw);point=np.array([g.loc[g.high,'net_return'].mean()-g.loc[~g.high,'net_return'].mean(),g.loc[~g.high,'extension'].mean()]);sd=draws.std(0);crit=np.quantile(np.max(abs(draws-point)/np.where(sd>0,sd,1.),axis=1),.95)
    return [{'block':block,'metric':name,'point':float(point[j]),'low':float(np.quantile(draws[:,j],.025)),'high':float(np.quantile(draws[:,j],.975)),'sim_low':float(point[j]-crit*sd[j]),'sim_high':float(point[j]+crit*sd[j])} for j,name in enumerate(['H3_high_low','low_extension'])]

def main():
    target=EX/'others/annual_followup.json'
    if target.exists():raise RuntimeError('Preserve followup')
    refs=json.loads((EX/'protocols/published_annual.json').read_text(encoding='utf-8'))
    for rel,ref in refs.items():assert sha256((EX/rel).read_bytes()).hexdigest()==ref['sha256']
    data,dates,labels,*_=inputs();f=pd.read_csv(ROOT/'research/S014/assets/runs/EX013_20261017/corrected/features.csv',index_col='signal')
    threshold,splits=calibrate(f,labels,dates);h1=labels.loc[labels.horizon.eq(1)&labels.maturity.ge(0)].set_index('signal');h3=labels.loc[labels.horizon.eq(3)&labels.maturity.ge(0)].set_index('signal')
    parent=f.gap_down_repair.eq(1);ready=threshold.notna();ids=sorted(set(f.index[parent&ready])&set(h1.index)&set(h3.index))
    g=h3.loc[ids].copy();g['signal']=g.index;g['year']=dates[ids].year;g['threshold']=threshold.loc[ids];g['high']=f.loc[ids,'gap_autocorr']>=threshold.loc[ids];g['extension']=g.net_return-h1.loc[ids,'net_return'];g=g.reset_index(drop=True)
    annual=[];cluster_rows=[]
    for scope,part in [('ALL',g),('EARLY2020_2022',g.loc[g.year.le(2022)]),('OLD2023_2026',g.loc[g.year.ge(2023)]),('WITHOUT2026',g.loc[g.year.ne(2026)]),*[(str(y),x) for y,x in g.groupby('year')]]:
        a=part.loc[part.high];b=part.loc[~part.high];no=strict(part);lo=no.loc[~no.high];hi=no.loc[no.high]
        annual.append({'scope':scope,'n':len(part),'high_n':len(a),'low_n':len(b),'high_net':a.net_return.mean(),'low_net':b.net_return.mean(),'difference':a.net_return.mean()-b.net_return.mean(),'high_extension':a.extension.mean(),'low_extension':b.extension.mean(),'nonoverlap_n':len(no),'nonoverlap_diff':hi.net_return.mean()-lo.net_return.mean(),'nonoverlap_low_extension':lo.extension.mean(),'low_drop_worst3':b.extension.sort_values().iloc[3:].mean(),'high_drop_best3':a.net_return.sort_values().iloc[:-3].mean()})
        for name,p in [('high',a),('low',b)]:
            for column in ('net_return','extension'):
                row,_=clusters(p,column);cluster_rows.append({'scope':scope,'group':name,'value':column,**row})
    matches=[]
    for year,part in g.groupby('year'):
        split=next(x for x in splits if x['year']==year);train=labels.loc[labels.horizon.eq(3)&labels.maturity.ge(0)&labels.maturity.lt(split['signal'])&labels.signal.isin(f.index[np.isfinite(f.to_numpy(float)).all(1)])]
        center=f.loc[train.signal,COLS].mean();scale=f.loc[train.signal,COLS].std(ddof=0).replace(0,1);z=(f.loc[part.signal,COLS]-center)/scale;available=list(part.loc[~part.high,'signal'].astype(int));lookup=part.set_index('signal')
        for signal in part.loc[part.high,'signal'].astype(int):
            if not available:break
            distances=np.sqrt(((z.loc[available].to_numpy()-z.loc[signal].to_numpy())**2).mean(1));j=int(np.argmin(distances))
            if distances[j]>1:continue
            control=available.pop(j);a=lookup.loc[signal];b=lookup.loc[control]
            matches.append({'year':int(year),'a':signal,'b':control,'distance':float(distances[j]),'difference':float(a.net_return-b.net_return),'a_extension':float(a.extension),'b_extension':float(b.extension)})
    capacity=[]
    for name,frame in [('parent_H1',h1.loc[ids]),('parent_H3',h3.loc[ids]),('high_H3',h3.loc[g.loc[g.high,'signal']])]:
        frame=frame.loc[frame.entry_filled].copy();frame['signal']=frame.index;frame=frame.reset_index(drop=True);end=-1;chosen=[]
        for row in frame.sort_values(['maturity','signal']).itertuples():
            if row.signal>=end:chosen.append(int(row.signal));end=int(row.maturity)
        capacity.append({'kind':name,'filled_attempts':len(frame),'schedulable_count':len(chosen),'per60_calendar':len(chosen)*60/len(dates),'signals':chosen})
    coverage=[]
    for year in sorted(set(dates.year)):
        mask=dates.year==year;p=parent&ready&mask;v=g.loc[g.year.eq(year)]
        coverage.append({'year':int(year),'calendar':int(mask.sum()),'ready':int((ready&mask).sum()),'parent_signals':int(p.sum()),'high_signals':int((p&f.gap_autocorr.ge(threshold)).sum()),'closed_attempts':len(v),'filled':int(v.entry_filled.sum()),'unfilled':int((~v.entry_filled).sum()),'censored_or_missing':int(p.sum()-len(v))})
    for name,rows in [('annual_extension',annual),('annual_clusters',cluster_rows),('annual_matches',matches),('annual_coverage',coverage)]:pd.DataFrame(rows).to_csv(EX/'others'/f'{name}.csv',index=False,lineterminator='\n')
    g.to_csv(RUN/'annual_observations.csv',index=False,lineterminator='\n')
    result={'splits':splits,'capacity':capacity,'intervals':interval(g,dates,20)+interval(g,dates,60),'source_calls':0,'account_runs':0,'adaptive_followup':True}
    target.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(pd.DataFrame(annual).to_string(index=False));print(json.dumps({'splits':splits,'intervals':result['intervals'],'capacity':[{k:v for k,v in x.items() if k!='signals'} for x in capacity]}))

if __name__=='__main__':main()
