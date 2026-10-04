"""Pre-open cross-market information, with completed GMT source days only."""
import numpy as np
import pandas as pd
from .base import summarize,diagnostics,dedup,net

NAMES=('gold_positive_dip','gold_strong_dip','overnight_gold_etfweak','relative_cheap',
       'relative_cheap_gold_positive','gold_strong_no_dip','gold_down_dip','fx_strong_dip')

def source_align(source,index):
    x=source.copy().sort_index()
    if 'AvailableDate' not in x: raise ValueError('Explicit availability is required')
    decision=pd.DatetimeIndex(index)+pd.Timedelta(hours=8,minutes=45)
    result=pd.merge_asof(pd.DataFrame({'entry_date':index,'decision_time':decision}),
        x.reset_index(names='source_date').sort_values('AvailableDate'),
        left_on='decision_time',right_on='AvailableDate',allow_exact_matches=True,direction='backward',
        tolerance=pd.Timedelta(days=7)).set_index('entry_date')
    matched=result.AvailableDate.notna()
    assert (result.loc[matched,'AvailableDate']<=result.loc[matched,'decision_time']).all()
    return result

def build(raw,inherited,xau,fx):
    p=raw.assign(Date=pd.to_datetime(raw.Date)).set_index('Date').sort_index()
    gold=xau.assign(Date=pd.to_datetime(xau.Date)).set_index('Date').BidClose
    cnh=fx.assign(Date=pd.to_datetime(fx.Date)).set_index('Date').BidClose
    native=pd.concat([gold.rename('gold'),cnh.rename('fx')],axis=1).dropna()
    available=pd.concat([xau.assign(Date=pd.to_datetime(xau.Date)).set_index('Date').AvailableDate,
                         fx.assign(Date=pd.to_datetime(fx.Date)).set_index('Date').AvailableDate],axis=1)
    native['AvailableDate']=available.max(axis=1).reindex(native.index)
    native['rmbgold']=native.gold*native.fx
    native['gold1']=native.rmbgold.pct_change(fill_method=None)
    native['gold5']=native.rmbgold.pct_change(5,fill_method=None)
    native['fx5']=native.fx.pct_change(5,fill_method=None)
    f=source_align(native,p.index)
    good=f.source_date.notna();assert (f.loc[good,'source_date']<f.index[good]).all()
    f['r1']=p.Close.pct_change(fill_method=None).shift(1)
    f['r3']=p.Close.pct_change(3,fill_method=None).shift(1)
    f['momentum_20']=inherited.momentum_20.shift(1)
    f['volatility_20']=inherited.volatility_20.shift(1)
    ratio=p.Close.shift(1)/f.rmbgold
    f['relative']=ratio/ratio.rolling(20).mean()-1
    out=pd.DataFrame(np.nan,index=f.index,columns=NAMES);cells=pd.Series(np.nan,index=f.index);cuts=[]
    for year in sorted(set(f.index.year)):
        train=f.loc[f.index.year<year]
        if len(train)<252:continue
        x=f.loc[f.index.year==year]
        q={k:float(train[k].quantile(v)) for k,v in [('gold1',.75),('gold5',.75),('fx5',.75),('r3',.25),('relative',.25)]}
        cuts.append({'year':int(year),'thresholds':q})
        dip=x.r3<=q['r3'];strong=x.gold5>=q['gold5'];cheap=x.relative<=q['relative']
        conditions=((x.gold5>0)&dip,strong&dip,(x.gold1>=q['gold1'])&(x.r1<0),cheap,
                    cheap&(x.gold5>0),strong&~dip,(x.gold5<0)&dip,(x.fx5>=q['fx5'])&dip)
        valid=x[['gold1','gold5','fx5','r1','r3','relative','momentum_20','volatility_20']].notna().all(axis=1)
        for name,cond in zip(NAMES,conditions):out.loc[x.index[valid],name]=cond.loc[valid].astype(float)
        bins=[float(train.volatility_20.quantile(v)) for v in (1/3,2/3)]
        cell=(year-2020)*6+(x.momentum_20>0).astype(int)*3+np.digitize(x.volatility_20,bins)
        cells.loc[x.index[valid]]=cell.loc[valid]
    return out,cells,f,cuts

def labels(raw,h):
    p=raw.assign(Date=pd.to_datetime(raw.Date)).set_index('Date').sort_index()
    return pd.DataFrame({'gross':p.Open.shift(-h)/p.Open-1,
       'mae':1-pd.concat([p.Low.shift(-j) for j in range(h)],axis=1).min(axis=1,skipna=False)/p.Open,
       'mfe':pd.concat([p.High.shift(-j) for j in range(h)],axis=1).max(axis=1,skipna=False)/p.Open-1})

def analyze(raw,inherited,xau,fx):
    m,cells,f,cuts=build(raw,inherited,xau,fx);pos=pd.Series(np.arange(len(m)),index=m.index)
    records=[];annual=[]
    for name in NAMES:
        for h in (1,3,5,10):
            for lag in (0,1,2):
                frame=pd.concat([labels(raw,h),m[name].shift(lag).rename('signal'),cells.rename('cell')],axis=1).dropna()
                item=summarize(frame,h,pos);item.update(mechanism=name,horizon=h,lag=lag)
                if item['n'] and lag==0:item.update(diagnostics(frame,12008+h))
                records.append(item)
                for year in sorted(set(frame.index.year)):
                    r=summarize(frame.loc[frame.index.year==year],h,pos);r.update(mechanism=name,horizon=h,lag=lag,year=int(year));annual.append(r)
    primary=[r for r in records if 'shift_p' in r];order=np.argsort([r['shift_p'] for r in primary]);last=1.
    for rank in range(len(order)-1,-1,-1):
        r=primary[order[rank]];last=min(last,r['shift_p']*len(order)/(rank+1));r['shift_q']=last
    return {'opportunities.json':records,'annual.json':annual,'thresholds.json':cuts},f,m
