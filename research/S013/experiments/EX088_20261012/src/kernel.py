"""EX088 causal forecast record over prior h4 conflict span; no fit or future ranks."""
import numpy as np
import pandas as pd

INPUTS=('confirmation_110','original14_110')
FAMILIES=('confirmation','original14')
KINDS=('historical_control','matched_control','record4')
MODELS=tuple(f'{family}_{kind}' for family in FAMILIES for kind in KINDS)
SUFFIXES=('record_positive_mean','record_positive_minus_matched','record_greedy_mean',
          'record_greedy_minus_matched_greedy','record_greedy_minus_blocked')
QUANTITIES=tuple(f'{family}_{suffix}' for family in FAMILIES for suffix in SUFFIXES)


def decisions(scores):
    axis=scores.index
    if not isinstance(axis,pd.DatetimeIndex) or axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()):
        raise ValueError('Unique ordered naive midnight signal dates')
    if tuple(scores.columns)!=INPUTS or len(axis)<40 or np.isinf(scores.to_numpy()).any() or scores.loc[axis.year==2020].notna().any().any():
        raise ValueError('Exact two frozen inputs, at least40, no infinite/2020 forecast')
    signals=pd.DataFrame(np.nan,index=axis,columns=MODELS)
    states=pd.DataFrame(index=axis)
    traces=[]
    for family,name in zip(FAMILIES,INPUTS):
        p=scores[name].to_numpy(float)
        past=pd.concat([scores[name].shift(k) for k in range(1,5)],axis=1)
        available=np.isfinite(p)&past.notna().all(axis=1).to_numpy()
        prior_max=past.max(axis=1).to_numpy(copy=True)
        prior_max[~available]=np.nan
        qualify=available&(p>0)&(p>prior_max)
        signals[family+'_historical_control']=p
        signals[family+'_matched_control']=np.where(available,p,np.nan)
        signals[family+'_record4']=np.where(available,np.where(qualify,p,0.),np.nan)
        states[family+'_issued_net_forecast']=p
        states[family+'_previous4_max']=prior_max
        states[family+'_available']=available
        states[family+'_qualify']=qualify
        for i in range(len(axis)):
            traces.append({'family':family,'signal_date':axis[i].isoformat(),'available':bool(available[i]),
                'qualify':bool(qualify[i]),'past_positions':list(range(i-4,i)) if available[i] else [],
                'model_year_crossing':bool(available[i] and axis[i-4].year!=axis[i].year)})
    return states,signals,traces


def validate_labels(signals,labels):
    if not signals.index.equals(labels.index):
        raise ValueError('Shared axis')
    y=labels.return_4.to_numpy(float)
    ends=pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    finite=np.isfinite(y)
    if np.isinf(y).any() or not np.array_equal(finite,ends.notna()) or (y[finite]<=-1).any() or (ends[finite].to_numpy()<=signals.index[finite].to_numpy()).any():
        raise ValueError('Valid future paired net price label/maturity')
    return y


def selected(y,p,mask):
    eligible=mask&np.isfinite(p)
    positive=eligible&(p>0)
    mature=positive&np.isfinite(y)
    n=int(mature.sum())
    return {'forecasts':int(eligible.sum()),'positive_forecasts':int(positive.sum()),'mature_positive':n,
            'missing_positive_truth':int((positive&~np.isfinite(y)).sum()),'positive_mean':float(y[mature].mean()) if n>=20 else None,
            'hit_rate':float((y[mature]>0).mean()) if n>=20 else None,'false_positive_rate':float((y[mature]<=0).mean()) if n>=20 else None,
            'status':'AVAILABLE' if n>=20 else 'INSUFFICIENT_DATA'}


def selector_masks(signals,clock):
    p=signals.to_numpy()
    result={}
    for family_index,family in enumerate(FAMILIES):
        before,record=p[:,3*family_index+1],p[:,3*family_index+2]
        result[family]=np.column_stack((record>0,before>0,clock.entries(record,'greedy'),clock.entries(before,'greedy'),
                                        (record>0)&~clock.entries(record,'greedy')))
    return result


def quantities(y,masks,ids):
    out={}
    for family,mask in masks.items():
        yy,mm=y[ids],mask[ids]
        finite=np.isfinite(yy)
        means=[float(yy[finite&mm[:,j]].mean()) if (finite&mm[:,j]).sum()>=20 else None for j in range(5)]
        diff=lambda a,b:means[a]-means[b] if means[a] is not None and means[b] is not None else None
        values=(means[0],diff(0,1),means[2],diff(2,3),diff(2,4))
        out.update({family+'_'+key:value for key,value in zip(SUFFIXES,values)})
    return out


def bootstrap(y,masks):
    n,rng=len(y),np.random.default_rng(13)
    starts=rng.integers(0,n-39,(500,(n+39)//40))
    ids=(starts[:,:,None]+np.arange(40)).reshape(500,-1)[:,:n]
    original=quantities(y,masks,np.arange(n))
    records=[quantities(y,masks,row) for row in ids]
    summary={}
    for key,value in original.items():
        good=[r[key] for r in records if r[key] is not None]
        available=value is not None and len(good)>=400
        summary[key]={'value':value,'valid_replicates':len(good),'ci95':np.quantile(good,[.025,.975],method='linear').tolist() if available else None,
                      'status':'AVAILABLE' if available else 'INSUFFICIENT_DATA'}
    return {'summary':summary,'records':records,'blocks':40,'repetitions':500,'seed':13,'refitted_models':0,
            'clock_resimulation_within_replicates':False}


def analyze(scores,labels,clock):
    states,signals,traces=decisions(scores)
    axis=signals.index
    y=validate_labels(signals,labels)
    groups={'all':np.ones(len(y),bool),**{'year_'+str(year):axis.year==year for year in range(2020,2027)},
            **{'phase_'+str(k):np.arange(len(y))%5==k for k in range(5)}}
    panels={key:{name:selected(y,signals[name].to_numpy(),mask) for name in MODELS} for key,mask in groups.items()}
    schedules={name:{c:clock.schedule(axis,signals[name].to_numpy(),y,c) for c in clock.CLOCKS} for name in MODELS}
    masks=selector_masks(signals,clock)
    quality={key:quantities(y,masks,np.flatnonzero(mask)) for key,mask in groups.items()}
    return states,signals,{'signals':len(y),'panels':panels,'schedules':schedules,'state_traces':traces,
        'selection_quality':quality,'bootstrap':bootstrap(y,masks),'new_annual_models':0,'new_accounts':0,'provider_calls':0,
        'raw_forecasts_unchanged':True,'decision_scores_are_not_new_return_forecasts':True,'objective_achieved':False}
