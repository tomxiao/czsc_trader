"""Fixed H3 environment: downside decomposition and paired duration, no new execution."""
from hashlib import sha256
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]
OLD=ROOT/'research/S014/experiments/EX013_20261017'
RUN=ROOT/'research/S014/assets/runs'/EX.name
NAMES=['downside_share','incomplete_repair','down_volume_share','joint_market_weakness']
MATCH=['vol20','abs_gap','intraday','ret20']

def source(key,csv=True):
    r=json.loads((OLD/'others/result.json').read_text(encoding='utf-8'))
    ref=EvidenceRef.from_dict(r['evidence'][key]);raw=ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest()==ref.sha256
    return (pd.read_csv(BytesIO(raw)) if csv else json.loads(raw)),ref.to_dict()

def features(bars,f):
    ret=np.log(bars.Close/bars.Close.shift());v=bars.Volume
    x=f.copy();x['abs_gap']=abs(x.gap)
    x['downside_share']=(ret.clip(upper=0).pow(2).rolling(20).sum()/ret.pow(2).rolling(20).sum()).reindex(x.index)
    x['down_volume_share']=(v.where(ret.lt(0),0).rolling(20).sum()/v.rolling(20).sum()).reindex(x.index)
    x['incomplete_repair']=x.ret1.lt(0).astype(int)
    x['joint_market_weakness']=(x.market_ret5.lt(0)&x.sector_ret5.lt(0)).astype(int)
    return x

def stats(y):
    y=np.asarray(y,float);n=len(y)
    return {'n':n,'mean':float(y.mean()),'positive':float(np.maximum(y,0).mean()),'downside':float(np.minimum(y,0).mean()),
        'loss_rate':float((y<0).mean()),'loss3_rate':float((y<=-.03).mean()),'worst10_mean':float(np.sort(y)[:max(1,int(np.ceil(n*.1)))].mean())} if n else {'n':0}

def nonoverlap(g,end='maturity'):
    keep=[];last=-1
    for i,row in g.sort_values('signal').iterrows():
        if row.entry>last:keep.append(i);last=int(row[end])
    return g.loc[keep]

def bootstrap(g,contrasts,dates,reps=2000):
    # Sample full trading calendars, including non-event sessions, preserving cross-contrast dependence.
    rng=np.random.default_rng(14017); idx=g.signal.to_numpy(int)
    years=[np.flatnonzero((dates.year==y)&(np.arange(len(dates))>=min(idx))&(np.arange(len(dates))<=max(idx))) for y in (2023,2024,2025,2026)]
    specs=[]
    for name,a,b,values in contrasts:
        av=np.zeros(len(dates));bv=av.copy();ac=av.copy();bc=av.copy()
        av[idx]=np.asarray(values)*a;bv[idx]=np.asarray(values)*b;ac[idx]=a;bc[idx]=b
        specs.append((name,av,bv,ac,bc))
    points=np.array([av.sum()/ac.sum()-bv.sum()/bc.sum() for _,av,bv,ac,bc in specs]);draws=[]
    for _ in range(reps):
        ix=np.concatenate([v[((rng.integers(0,len(v),size=(len(v)+19)//20)[:,None]+np.arange(20))%len(v)).ravel()[:len(v)]] for v in years if len(v)])
        row=[av[ix].sum()/ac[ix].sum()-bv[ix].sum()/bc[ix].sum() if ac[ix].sum() and bc[ix].sum() else np.nan for _,av,bv,ac,bc in specs]
        draws.append(row)
    arr=np.array(draws);valid=np.isfinite(arr).all(axis=1);arr=arr[valid];sd=arr.std(axis=0,ddof=1);safe=np.where(sd>0,sd,1)
    critical=np.quantile(np.max(abs(arr-points)/safe,axis=1),.95)
    return [{'name':name,'difference':float(points[j]),'low':float(np.quantile(arr[:,j],.025)),'high':float(np.quantile(arr[:,j],.975)),
        'sim_low':float(points[j]-critical*sd[j]),'sim_high':float(points[j]+critical*sd[j]),'valid_draws':len(arr)} for j,(name,*_) in enumerate(specs)]

def main():
    if (EX/'others/computation.json').exists():raise RuntimeError('Preserve result')
    published=json.loads((EX/'protocols/published_design.json').read_text(encoding='utf-8'))
    for key,rel in [('study-py','src/study.py'),('design-json','protocols/design.json')]:assert sha256((EX/rel).read_bytes()).hexdigest()==published[key]['sha256']
    f,fr=source('ex013-corrected-features-csv');f=f.set_index('signal')
    labels,lr=source('ex013-corrected-labels-csv');session,sr=source('ex013-others-session_result-json',False)
    spec=importlib.util.spec_from_file_location('prior_inputs',OLD/'src/inputs.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    data,dates,original,*rest=module.load();bars=data['stock.ohlcv'];f=features(bars,f)
    cuts={v['year']:v['threshold'] for v in session['splits'] if v['horizon']==3 and v['variant']=='primary20'}
    h3=labels.loc[labels.horizon.eq(3)&labels.year.ge(2023)].sort_values('signal').copy()
    h3['parent']=f.loc[h3.signal,'gap_down_repair'].eq(1).to_numpy()
    h3['high']=f.loc[h3.signal,'gap_autocorr'].to_numpy()>=h3.year.map(cuts).to_numpy()
    h3['parent_high']=h3.parent&h3.high
    for col in [*MATCH,*NAMES]:h3[col]=f.loc[h3.signal,col].to_numpy()
    calibration=[]
    for year,g in h3.groupby('year'):
        train=labels.loc[labels.horizon.eq(3)&labels.maturity.lt(int(g.signal.min()))]
        tx=f.loc[train.signal];train=train.loc[(tx.gap_down_repair.eq(1)&tx.gap_autocorr.ge(cuts[year])).to_numpy()]
        for name in NAMES:
            threshold=float(f.loc[train.signal,name].median()) if name in ('downside_share','down_volume_share') else .5
            h3.loc[g.index,'risk_'+name]=g[name].gt(threshold)
            calibration.append({'year':int(year),'name':name,'threshold':threshold,'train_n':len(train),'max_maturity':int(train.maturity.max()),'first_test':int(g.signal.min())})
    groups=[('ALL',h3),('WITHOUT2026',h3.loc[h3.year.ne(2026)]),*[(str(y),g) for y,g in h3.groupby('year')]]
    decomp=[];risk=[];pairs=[]
    for year,g in groups:
        for state in (False,True):decomp.append({'year':year,'high':state,**stats(g.loc[g.parent&g.high.eq(state),'net_return'])})
        for name in NAMES:
            for state in (False,True):risk.append({'year':year,'name':name,'risk':state,**stats(g.loc[g.parent_high&g['risk_'+name].eq(state),'net_return'])})
    for year,g in h3.groupby('year'):
        train=labels.loc[labels.horizon.eq(3)&labels.maturity.lt(int(g.signal.min()))]
        center=f.loc[train.signal,MATCH].mean();scale=f.loc[train.signal,MATCH].std(ddof=0).replace(0,1.)
        z=(f.loc[g.signal,MATCH]-center)/scale;lookup=g.set_index('signal')
        for name in NAMES:
            available=list(g.loc[g.parent_high&~g['risk_'+name].astype(bool),'signal'].astype(int))
            for signal in g.loc[g.parent_high&g['risk_'+name].astype(bool),'signal'].astype(int):
                if not available:break
                d=np.sqrt(((z.loc[available].to_numpy()-z.loc[signal].to_numpy())**2).mean(axis=1));j=int(np.argmin(d))
                if d[j]>1:continue
                b=available.pop(j);a=lookup.loc[signal];c=lookup.loc[b]
                pairs.append({'name':name,'year':int(year),'a':signal,'b':b,'distance':float(d[j]),'a_return':float(a.net_return),'b_return':float(c.net_return),
                    'a_entry':int(a.entry),'b_entry':int(c.entry),'a_end':int(a.maturity),'b_end':int(c.maturity)})
    contrasts=[]
    for name in NAMES:
        a=(h3.parent_high&h3['risk_'+name].astype(bool)).to_numpy();b=(h3.parent_high&~h3['risk_'+name].astype(bool)).to_numpy()
        for mode in ('downside','return'):
            y=h3.net_return.to_numpy();contrasts.append((name+'_'+mode,a,b,np.minimum(y,0) if mode=='downside' else y))
    intervals=bootstrap(h3,contrasts,dates)
    # Freeze H3 parent and thresholds for all durations, restrict to common observed labels.
    parent=h3.loc[h3.parent].copy();horizons=[1,3,5,10,20];common=set(parent.signal)
    for h in horizons:common &= set(labels.loc[labels.horizon.eq(h),'signal'])
    cohort=parent.loc[parent.signal.isin(common)].copy()
    for h in horizons:
        q=labels.loc[labels.horizon.eq(h)].set_index('signal').loc[cohort.signal]
        for col in ('entry','quantity','entry_filled','entry_price'):assert np.allclose(q[col],cohort[col],equal_nan=True),col
        cohort['y'+str(h)]=q.net_return.to_numpy();cohort['end'+str(h)]=q.maturity.to_numpy()
        cohort['delay'+str(h)]=(q.maturity-q.planned_exit).to_numpy()
    duration=[];durcontr=[];increments=[]
    for label,g in [('ALL',cohort),('WITHOUT2026',cohort.loc[cohort.year.ne(2026)]),*[(str(y),g) for y,g in cohort.groupby('year')],('NONOVERLAP',nonoverlap(cohort,'end20'))]:
        for state in (False,True):
            part=g.loc[g.high.eq(state)]
            for h in horizons:duration.append({'scope':label,'high':state,'horizon':h,**stats(part['y'+str(h)])})
            for left,right in zip(horizons[:-1],horizons[1:]):
                increments.append({'scope':label,'high':state,'from':left,'to':right,**stats(part['y'+str(right)]-part['y'+str(left)]),'same_exit':int(part['end'+str(left)].eq(part['end'+str(right)]).sum())})
    for h in horizons:durcontr.append(('high_minus_low_H'+str(h),cohort.high.to_numpy(),~cohort.high.to_numpy(),cohort['y'+str(h)].to_numpy()))
    # Paired increments represented as difference of two group means with identical memberships.
    durinterval=bootstrap(cohort,durcontr,dates)
    RUN.mkdir(parents=True,exist_ok=True)
    h3.to_csv(RUN/'observations.csv',index=False,lineterminator='\n');cohort.to_csv(RUN/'duration.csv',index=False,lineterminator='\n')
    f.to_csv(RUN/'features.csv',lineterminator='\n')
    for name,values in [('decomposition',decomp),('risk',risk),('matches',pairs),('duration',duration),('increments',increments)]:pd.DataFrame(values).to_csv(EX/'others'/f'{name}.csv',index=False,lineterminator='\n')
    result={'source_refs':[fr,lr,sr],'calibration':calibration,'risk_intervals':intervals,'duration_intervals':durinterval,
        'parent_n':len(parent),'high_n':int(parent.high.sum()),'common_n':len(cohort),'excluded_signals':sorted(set(parent.signal)-common),
        'source_calls':0,'strategy_accounts':0,'dates':{'count':len(dates),'start':str(dates[0]),'end':str(dates[-1])}}
    (EX/'others/computation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'risk':intervals,'duration':durinterval,'common_n':len(cohort)}))
if __name__=='__main__':main()
