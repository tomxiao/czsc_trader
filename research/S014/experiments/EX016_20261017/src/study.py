"""Fixed causal state calibration, economic contrast and opportunity capacity."""
import importlib.util
import json
from pathlib import Path
from hashlib import sha256
import numpy as np
import pandas as pd
from component import causal_gap_environment
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1];RUN=ROOT/'research/S014/assets/runs'/EX.name
OLD=ROOT/'research/S014/experiments/EX013_20261017'

def inputs():
    spec=importlib.util.spec_from_file_location('prior_inputs',OLD/'src/inputs.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m.load()

def strict(g):
    keep=[];end=-1
    for i,row in g.sort_values('signal').iterrows():
        if row.entry>end:keep.append(i);end=int(row.maturity)
    return g.loc[keep]

def clusters(g,column):
    c=-1;end=-1;ids=[]
    for row in g.itertuples():
        if row.entry>end:c+=1
        ids.append(c);end=max(end,row.maturity)
    g=g.copy();g['cluster']=ids;v=g.groupby('cluster')[column].mean();leave=[float(v.drop(i).mean()) for i in v.index] if len(v)>1 else []
    return {'n':len(g),'clusters':len(v),'cluster_equal':float(v.mean()),'leave_min':min(leave) if leave else None,'leave_max':max(leave) if leave else None},g

def main():
    if (EX/'others/computation.json').exists():raise RuntimeError('Preserve result')
    refs=json.loads((EX/'protocols/published_design.json').read_text(encoding='utf-8'))
    for key,rel in [('design','protocols/design.json'),('study','src/study.py'),('component','src/component.py')]:assert sha256((EX/rel).read_bytes()).hexdigest()==refs[key]['sha256']
    data,dates,labels,*rest=inputs();stock=data['stock.ohlcv'];ret=np.log(stock.Close/stock.Close.shift());vol=ret.rolling(20).std();ret20=np.log(stock.Close/stock.Close.shift(20))
    h1=labels.loc[labels.horizon.eq(1)&labels.maturity.ge(0)].set_index('signal');h3=labels.loc[labels.horizon.eq(3)&labels.maturity.ge(0)].set_index('signal')
    session=json.loads((OLD/'others/session_result.json').read_text(encoding='utf-8'));oldcuts={v['year']:v['threshold'] for v in session['splits'] if v['horizon']==3 and v['variant']=='primary20'}
    records=[];observations=[];coverage=[];matching=[];capacity=[];summaries=[];primary=None;readyinfo=[]
    for window in (252,126,504):
        f=causal_gap_environment(stock,window);f['vol20']=vol;f['ret20']=ret20
        for name,key in [('market','market'),('sector','sector')]:f[name+'_ret5']=np.log(data[key].Close/data[key].Close.shift(5))
        ready=f.loc[f.ready];readyinfo.append({'window':window,'first_ready_signal':int(ready.index.min()),'first_ready_date':str(dates[ready.index.min()].date()),'ready_n':len(ready)})
        ids=sorted(set(h1.index)&set(h3.index)&set(f.index[f.ready&f.parent]));g=h3.loc[ids].copy();g['signal']=g.index;g['signal_date']=dates[ids].astype(str);g['year']=dates[ids].year;g['window']=window
        for col in ('high','gap','intraday','vol20','ret20','market_ret5','sector_ret5','correlation','threshold'):g[col]=f.loc[ids,col].to_numpy()
        g['high']=g.high.astype(bool);g['extension']=g.net_return-h1.loc[ids,'net_return'];g['old_high']=[bool(f.loc[i,'correlation']>=oldcuts[y]) if y in oldcuts else None for i,y in zip(ids,g.year)]
        g=g.reset_index(drop=True);observations.append(g)
        for scope,part in [('ALL',g),('WITHOUT2026',g.loc[g.year.ne(2026)]),('OVERLAP2023',g.loc[g.year.ge(2023)]),*[(str(y),v) for y,v in g.groupby('year')]]:
            a=part.loc[part.high];b=part.loc[~part.high];no=strict(part);na=no.loc[no.high];nb=no.loc[~no.high]
            records.append({'window':window,'scope':scope,'high_n':len(a),'low_n':len(b),'high_net':float(a.net_return.mean()),'low_net':float(b.net_return.mean()),'difference':float(a.net_return.mean()-b.net_return.mean()),
                'high_extension':float(a.extension.mean()),'low_extension':float(b.extension.mean()),'nonoverlap_n':len(no),'nonoverlap_diff':float(na.net_return.mean()-nb.net_return.mean()) if len(na) and len(nb) else None,
                'nonoverlap_low_extension':float(nb.extension.mean()) if len(nb) else None})
        for year in sorted(set(dates.year)):
            mask=dates.year==year;parent=f.ready&f.parent&mask;valid=g.loc[g.year.eq(year)]
            coverage.append({'window':window,'year':int(year),'calendar':int(mask.sum()),'ready':int((f.ready&mask).sum()),'parent_signals':int(parent.sum()),'high_signals':int((parent&f.high.fillna(False)).sum()),
                'closed_attempts':len(valid),'filled':int(valid.entry_filled.sum()),'unfilled':int((~valid.entry_filled).sum()),'censored_or_missing':int(parent.sum()-len(valid))})
        if window!=252:continue
        primary=g.copy();cols=['gap','intraday','ret20','vol20','market_ret5','sector_ret5']
        for year,part in g.groupby('year'):
            before=int(np.flatnonzero(dates.year==year)[0]) if year>2020 else int(ready.index.min())
            train=f.iloc[:before][cols].dropna();center=train.mean();scale=train.std(ddof=0).replace(0,1.);z=(part.set_index('signal')[cols]-center)/scale;lookup=part.set_index('signal');available=list(part.loc[~part.high,'signal'].astype(int))
            for signal in part.loc[part.high,'signal'].astype(int):
                if not available:break
                distances=np.sqrt(((z.loc[available].to_numpy()-z.loc[signal].to_numpy())**2).mean(1));j=int(np.argmin(distances))
                if distances[j]>1:continue
                control=available.pop(j);a=lookup.loc[signal];b=lookup.loc[control]
                matching.append({'year':int(year),'a':signal,'b':control,'distance':float(distances[j]),'a_return':float(a.net_return),'b_return':float(b.net_return),'difference':float(a.net_return-b.net_return),
                    'a_extension':float(a.extension),'b_extension':float(b.extension),'a_entry':int(a.entry),'b_entry':int(b.entry),'a_end':int(a.maturity),'b_end':int(b.maturity)})
        for group,part in [('high',g.loc[g.high]),('low',g.loc[~g.high])]:
            for value in ('net_return','extension'):
                row,_=clusters(part,value);summaries.append({'group':group,'value':value,**row})
        for name,frame in [('parent_H1',h1.loc[ids]),('parent_H3',h3.loc[ids]),('high_H3',h3.loc[g.loc[g.high,'signal']])]:
            frame=frame.loc[frame.entry_filled].copy();frame['signal']=frame.index;frame=frame.reset_index(drop=True);end=-1;chosen=[]
            for row in frame.sort_values(['maturity','signal']).itertuples():
                if row.signal>=end:chosen.append(int(row.signal));end=int(row.maturity)
            capacity.append({'kind':name,'filled_attempts':len(frame),'schedulable_count':len(chosen),'per60_calendar':len(chosen)*60/len(dates),'signals':chosen})
    g=primary;idx=g.signal.to_numpy(int);countA=np.zeros(len(dates));countB=countA.copy();sumA=countA.copy();sumB=countA.copy();ext=countA.copy()
    countA[idx]=g.high;countB[idx]=~g.high;sumA[idx]=g.net_return*g.high;sumB[idx]=g.net_return*~g.high;ext[idx]=g.extension*~g.high
    chunks=[np.flatnonzero((dates.year==y)&(np.arange(len(dates))>=idx.min())&(np.arange(len(dates))<=idx.max())) for y in sorted(set(g.year))]
    rng=np.random.default_rng(16017);draw=[]
    for _ in range(2000):
        ix=np.concatenate([a[((rng.integers(0,len(a),size=(len(a)+19)//20)[:,None]+np.arange(20))%len(a)).ravel()[:len(a)]] for a in chunks if len(a)])
        if countA[ix].sum() and countB[ix].sum():draw.append([sumA[ix].sum()/countA[ix].sum()-sumB[ix].sum()/countB[ix].sum(),ext[ix].sum()/countB[ix].sum()])
    draws=np.asarray(draw);point=np.array([g.loc[g.high,'net_return'].mean()-g.loc[~g.high,'net_return'].mean(),g.loc[~g.high,'extension'].mean()]);sd=draws.std(0);crit=np.quantile(np.max(abs(draws-point)/np.where(sd>0,sd,1.),axis=1),.95)
    ci=[{'metric':name,'point':float(point[j]),'low':float(np.quantile(draws[:,j],.025)),'high':float(np.quantile(draws[:,j],.975)),'sim_low':float(point[j]-crit*sd[j]),'sim_high':float(point[j]+crit*sd[j])} for j,name in enumerate(['H3_high_low','low_H1_H3'])]
    overlap=g.loc[g.year.ge(2023)]
    RUN.mkdir(parents=True,exist_ok=True);pd.concat(observations,ignore_index=True).to_csv(RUN/'observations.csv',index=False,lineterminator='\n')
    for name,values in [('annual',records),('coverage',coverage),('matches',matching),('clusters',summaries)]:pd.DataFrame(values).to_csv(EX/'others'/f'{name}.csv',index=False,lineterminator='\n')
    result={'ready':readyinfo,'intervals':ci,'capacity':capacity,'old_agreement_n':int(overlap.high.eq(overlap.old_high).sum()),'old_comparable_n':len(overlap),'source_calls':0,'account_runs':0,'remaining_rounds':8}
    (EX/'others/computation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'ready':readyinfo,'intervals':ci,'capacity':[{k:v for k,v in x.items() if k!='signals'} for x in capacity]}))
if __name__=='__main__':main()
