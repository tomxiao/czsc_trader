"""Falsify the promising conditional gap-sequence mechanism."""
import json
import numpy as np
import pandas as pd
from inputs import ROOT,EX

RUN=ROOT/'research/S014/assets/runs'/EX.name/'corrected'
COLS=['gap','intraday','ret1','ret5','ret20','range','volume_ratio','vol20','market_ret5','sector_ret5']


def main():
    target=EX/'others/session_result.json'
    if target.exists():raise RuntimeError('Preserve session evidence')
    f=pd.read_csv(RUN/'features.csv',index_col='signal');labels=pd.read_csv(RUN/'labels.csv');p=pd.read_csv(RUN/'predictions.csv')
    variants={'primary20':f.gap_autocorr,'prior20':f.gap_autocorr.shift(),'window10':f.gap.rolling(10).corr(f.gap.shift()),'window40':f.gap.rolling(40).corr(f.gap.shift())}
    records=[];members=[];pairs=[];bins=[];splits=[]
    for h in (1,3,5):
        for variant,series in variants.items():
            if h!=3 and variant!='primary20':continue
            q=p.loc[p.horizon.eq(h)].sort_values('signal').copy();frames=[]
            for year,g in q.groupby('year'):
                train=labels.loc[labels.horizon.eq(h)&labels.maturity.lt(int(g.signal.min()))]
                threshold=float(series.loc[train.signal].median());low,high=series.loc[train.signal].quantile([1/3,2/3])
                x=f.loc[g.signal];g=g.copy();g['state']=series.loc[g.signal].to_numpy();g['threshold']=threshold
                g['a']=(x.gap_down_repair.eq(1)&series.loc[g.signal].ge(threshold)).to_numpy()
                g['b']=(x.gap_down_repair.eq(1)&series.loc[g.signal].lt(threshold)).to_numpy()
                g['parent']=x.gap_down_repair.eq(1).to_numpy();g['high_state']=series.loc[g.signal].ge(threshold).to_numpy()
                g['bin']=np.where(g.state<=low,0,np.where(g.state<=high,1,2));g['variant']=variant;frames.append(g)
                splits.append({'horizon':h,'variant':variant,'year':int(year),'threshold':threshold,'q33':float(low),'q67':float(high),'train_n':len(train),'latest_maturity':int(train.maturity.max())})
                if h==3 and variant=='primary20':
                    center=f.loc[train.signal,COLS].mean();scale=f.loc[train.signal,COLS].std(ddof=0).replace(0,1.)
                    z=(f.loc[g.signal,COLS]-center)/scale
                    available=list(g.loc[g.b,'signal'].astype(int));lookup=g.set_index('signal')
                    for signal in g.loc[g.a,'signal'].astype(int):
                        if not available:break
                        distances=np.sqrt(((z.loc[available].to_numpy()-z.loc[signal].to_numpy())**2).mean(axis=1));j=int(np.argmin(distances))
                        if distances[j]>1:continue
                        control=available.pop(j)
                        pairs.append({'year':int(year),'a':signal,'b':control,'distance':float(distances[j]),'a_return':float(lookup.loc[signal,'net_return']),
                            'b_return':float(lookup.loc[control,'net_return']),'difference':float(lookup.loc[signal,'net_return']-lookup.loc[control,'net_return']),
                            'residual_difference':float((lookup.loc[signal,'net_return']-lookup.loc[signal,'prediction_ridge_base'])-(lookup.loc[control,'net_return']-lookup.loc[control,'prediction_ridge_base']))})
            g=pd.concat(frames,ignore_index=True).sort_values('signal').reset_index(drop=True);members.append(g[['signal','signal_date','year','horizon','variant','net_return','a','b','parent','state','threshold','bin']])
            greedy=np.zeros(len(g),dtype=bool);last=-1
            for i,row in g.iterrows():
                if row.entry>last:greedy[i]=True;last=int(row.maturity)
            for year,part in [('ALL',g),('WITHOUT2026',g.loc[g.year.ne(2026)]),*list(g.groupby('year'))]:
                a=part.a.to_numpy();b=part.b.to_numpy();y=part.net_return.to_numpy();trim=a.copy();positive=np.flatnonzero(a&(y>0));trim[positive[np.argsort(y[positive])[-3:]]]=False
                ix=part.index.to_numpy();na=a&greedy[ix];nb=b&greedy[ix]
                mean=lambda mask:float(y[mask].mean()) if mask.any() else None
                records.append({'horizon':h,'variant':variant,'year':str(year),'selected':int(a.sum()),'control':int(b.sum()),'filled':int(part.loc[a,'entry_filled'].sum()),
                    'selected_mean':mean(a),'control_mean':mean(b),'difference':mean(a)-mean(b) if a.any() and b.any() else None,
                    'trimmed_difference':mean(trim)-mean(b) if trim.any() and b.any() else None,
                    'nonoverlap_selected':int(na.sum()),'nonoverlap_control':int(nb.sum()),'nonoverlap_difference':mean(na)-mean(nb) if na.any() and nb.any() else None})
                if h==3 and variant=='primary20':
                    for bucket in range(3):
                        selected=(part.bin.eq(bucket)&part.parent).to_numpy()
                        bins.append({'kind':'tercile','year':str(year),'bin':bucket,'n':int(selected.sum()),'mean':mean(selected)})
                    for parent in (False,True):
                        for state in (False,True):
                            selected=(part.parent.eq(parent)&part.high_state.eq(state)).to_numpy()
                            bins.append({'kind':'interaction','year':str(year),'parent':parent,'high':state,'n':int(selected.sum()),'mean':mean(selected)})
    pd.concat(members,ignore_index=True).to_csv(RUN.parent/'session_members.csv',index=False,lineterminator='\n')
    pd.DataFrame(records).to_csv(EX/'others/session_annual.csv',index=False,lineterminator='\n')
    pd.DataFrame(pairs).to_csv(EX/'others/session_matches.csv',index=False,lineterminator='\n')
    # Correct the known annual-mean export defect without replacing its original artifact.
    obs=pd.read_csv(RUN.parent/'direct_observations.csv');corrected=[]
    for (family,h),g in obs.groupby(['family','horizon']):
        original=p.loc[p.horizon.eq(h)].set_index('signal')
        for year,part in [('ALL',g),*list(g.groupby('year'))]:
            a=part.a.to_numpy();b=part.b.to_numpy()
            for mode in ('raw','residual'):
                y=part.net_return.to_numpy()-(original.loc[part.signal,'prediction_ridge_base'].to_numpy() if mode=='residual' else 0)
                corrected.append({'family':family,'horizon':int(h),'year':str(year),'mode':mode,'selected':int(a.sum()),'control':int(b.sum()),
                    'selected_mean':float(y[a].mean()) if a.any() else None,'control_mean':float(y[b].mean()) if b.any() else None,
                    'difference':float(y[a].mean()-y[b].mean()) if a.any() and b.any() else None})
    pd.DataFrame(corrected).to_csv(EX/'others/direct_annual_corrected.csv',index=False,lineterminator='\n')
    target.write_text(json.dumps({'splits':splits,'bins_and_interaction':bins,'matched_pairs':len(pairs),'source_calls':0,'strategy_accounts':0},indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('SESSION_COMPLETE',len(pairs))


if __name__=='__main__':main()
