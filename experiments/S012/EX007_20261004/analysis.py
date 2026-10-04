"""Selected opportunity attribution and execution attainability diagnostics."""
import numpy as np
import pandas as pd
from .base import features,signals,labels,summarize,diagnostics,dedup,net

NAMES=('fx_q75_dip_q25','fx_positive_dip_negative','fx_positive_dip_q25','fx_q75_dip_negative',
       'fx_positive_day_dip','fx_q75_day_dip','fx_session_dip_q25','fx_q75_no_dip',
       'fx_low_dip_q25','dip_q25_all','fx_q75_all','dip_turn','sge_cheap','fx_or_dipturn')
HORIZONS=(1,3,5,10)
FOCUS=('fx_q75_dip_q25','fx_positive_dip_negative','fx_session_dip_q25','dip_turn','sge_cheap','fx_or_dipturn')

def masks(raw,inherited):
    f=features(raw,inherited); f['fx_session5']=f.fx_level.pct_change(5,fill_method=None)
    old,cells,_=signals(f)
    out=pd.DataFrame(np.nan,index=f.index,columns=NAMES)
    for year in sorted(set(f.index.year)):
        train=f.loc[f.index.year<year]
        if len(train)<252:continue
        x=f.loc[f.index.year==year]; high=x.fx_change_5>=train.fx_change_5.quantile(.75)
        dip=x.r3<=train.r3.quantile(.25); positive=x.fx_change_5>0
        conditions=(high&dip,positive&(x.r3<0),positive&dip,high&(x.r3<0),positive&(x.r1<0),high&(x.r1<0),
            (x.fx_session5>=train.fx_session5.quantile(.75))&dip,high&~dip,~high&dip,dip,high,
            old.loc[x.index,'dip_turn']==1,old.loc[x.index,'sge_cheap']==1,(high&dip)|(old.loc[x.index,'dip_turn']==1))
        valid=x[['r1','r3','fx_change_5','fx_session5']].notna().all(axis=1)
        for name,cond in zip(NAMES,conditions):
            good=valid & (old.loc[x.index,'sge_cheap'].notna() if name=='sge_cheap' else True)
            out.loc[x.index[good],name]=cond.loc[good].astype(float)
    return out,cells,f

def attribution(frame):
    """Within-dip high-FX contrast; four-cell interaction is descriptive, not causal proof."""
    rows=[]
    for year in [0,*sorted(set(frame.index.year))]:
        g=frame if year==0 else frame.loc[frame.index.year==year]
        cells={}
        for high in (0,1):
            for dip in (0,1):
                a=g.loc[(g.high==high)&(g.dip==dip),'gross']
                cells[f'{high}{dip}']={'n':len(a),'gross':float(a.mean()) if len(a) else None}
        means=[cells[k]['gross'] for k in ('11','01','10','00')]
        did=means[0]-means[1]-means[2]+means[3] if all(v is not None for v in means) else None
        rows.append({'year':int(year),'cells':cells,'interaction':did})
    return rows

def limit_events(raw,signal,h,offset):
    """Independent next-session limit orders; no portfolio/account simulation."""
    p=raw.assign(Date=pd.to_datetime(raw.Date)).set_index('Date').sort_index()
    limit=np.floor((p.Close*(1-offset)+1e-10)/.001)*.001
    opening=p.Open.shift(-1); low=p.Low.shift(-1); exit_=p.Open.shift(-h-1)
    fill=opening.where(opening<=limit,limit.where(low<=limit))
    valid=signal.notna()&exit_.notna()&opening.notna()&low.notna()
    selected=valid&(signal==1)
    positions=np.arange(len(p)); ordered=dedup(positions[selected],h)
    independent=net(exit_/fill-1).where(selected)
    chosen=independent.iloc[ordered].dropna()
    gross=exit_/fill-1
    span=int(positions[valid][-1]-positions[valid][0]+1)
    return {'orders':int(selected.sum()),'filled':int(independent.notna().sum()),
        'fill_rate':float(independent.notna().sum()/max(selected.sum(),1)),
        'net20':float(independent.dropna().mean()) if independent.notna().any() else None,
        'net40':float(net(gross,.002).where(selected).dropna().mean()) if independent.notna().any() else None,
        'dedup_orders':len(ordered),'dedup_filled':len(chosen),'dedup_net20':float(chosen.mean()) if len(chosen) else None,
        'fullspan_sessions':span,'dedup_fills_per60':float(len(chosen)*60/span),
        'missed_open_net20':float(net(exit_/opening-1).where(selected&fill.isna()).dropna().mean()) if (selected&fill.isna()).any() else None}

def analyze(raw,inherited):
    m,cells,f=masks(raw,inherited); pos=pd.Series(np.arange(len(m)),index=m.index)
    records=[]; annual=[]; sensitivity=[]; execution=[]; attribution_rows=[]
    for name in NAMES:
        for h in HORIZONS:
            for lag in (0,1,2):
                frame=pd.concat([labels(raw,h),m[name].shift(lag).rename('signal'),cells.rename('cell')],axis=1).dropna()
                info={'mechanism':name,'horizon':h,'lag':lag}; r=summarize(frame,h,pos)
                r.update(info)
                r['fullspan_sessions']=int(pos.loc[frame.index[-1]]-pos.loc[frame.index[0]]+1)
                r['fullspan_events_per60']=r['nonoverlap_n']*60/r['fullspan_sessions']
                if lag==0:r.update(diagnostics(frame,12007+h))
                records.append(r)
                for year in sorted(set(frame.index.year)):
                    item=summarize(frame.loc[frame.index.year==year],h,pos);item.update(info,year=int(year));annual.append(item)
                if name in FOCUS and lag==0 and h in (3,5,10):
                    variants={'trim_absolute_top1pct':frame.loc[frame.gross.abs()<=frame.gross.abs().quantile(.99)]}
                    best=frame.loc[frame.signal==1].gross.nlargest(5).index
                    variants['remove_best5_events']=frame.drop(index=best)
                    for year in sorted(set(frame.index.year)):variants[f'omit_{year}']=frame.loc[frame.index.year!=year]
                    for phase in range(h+1):variants[f'calendar_phase_{phase}']=frame.loc[pos.loc[frame.index]%(h+1)==phase]
                    for key,v in variants.items():
                        item=summarize(v,h,pos);item.update(info,variant=key);sensitivity.append(item)
                    for offset in (0.,.001):
                        result=limit_events(raw,m[name],h,offset);result.update(info,limit_discount=offset);execution.append(result)
    primary=[r for r in records if 'shift_p' in r];order=np.argsort([r['shift_p'] for r in primary]);last=1.
    for rank in range(len(order)-1,-1,-1):
        r=primary[order[rank]];last=min(last,r['shift_p']*len(order)/(rank+1));r['shift_q']=last
    for h in HORIZONS:
        g=pd.concat([labels(raw,h),m.fx_q75_all.rename('high'),m.dip_q25_all.rename('dip')],axis=1).dropna()
        for r in attribution(g):r['horizon']=h;attribution_rows.append(r)
    return {'opportunities.json':records,'annual.json':annual,'sensitivity.json':sensitivity,
            'limit_events.json':execution,'attribution.json':attribution_rows},pd.concat([m,cells.rename('cell')],axis=1)
