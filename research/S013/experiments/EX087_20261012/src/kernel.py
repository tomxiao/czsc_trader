"""EX087 frozen P/G/L factorial attribution; no fitting and no clock selection."""
from itertools import product
import numpy as np
import pandas as pd

FAMILIES=('confirmation','original14')
BITS=tuple(''.join(map(str,row)) for row in product((0,1),repeat=3))
MODELS=tuple(f'{family}_{bits}' for family in FAMILIES for bits in BITS)
PROBABILITIES=('training_probability','confirmation_logit','original14_logit')
MAGNITUDES=('confirmation_gain','confirmation_loss','original14_gain','original14_loss')
PRIOR=('training_mean','confirmation_only','original14_joint','confirmation_probability_payoff',
       'original14_probability_payoff','confirmation_conditional_payoff','original14_conditional_payoff')
SUFFIXES=('gain_only_mse_vs_constant','gain_given_probability_mse','probability_given_gain_mse',
          'gain_only_positive_mean','probability_gain_positive_mean','gain_given_probability_mean_difference',
          'loss_given_probability_gain_mean_difference')
QUANTITIES=tuple(f'{family}_{suffix}' for family in FAMILIES for suffix in SUFFIXES)


def combine(probabilities,magnitudes,constants,prior):
    axis=probabilities.index
    if not isinstance(axis,pd.DatetimeIndex) or axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()):
        raise ValueError('Unique ordered naive midnight signal dates')
    if tuple(probabilities.columns)!=PROBABILITIES or tuple(magnitudes.columns)!=MAGNITUDES or tuple(constants.columns)!=('gain','loss') or tuple(prior.columns)!=PRIOR or not all(f.index.equals(axis) for f in (magnitudes,constants,prior)):
        raise ValueError('Exact frozen columns and shared axis')
    values=[f.to_numpy(float) for f in (probabilities,magnitudes,constants,prior)]
    if any(np.isinf(v).any() for v in values):
        raise ValueError('Finite or missing frozen inputs')
    masks=[np.isfinite(v) for v in values]
    support=masks[0][:,0]
    if any(not (mask==support[:,None]).all() for mask in masks) or support[axis.year==2020].any():
        raise ValueError('Identical forecast support and unavailable2020')
    if ((values[0][support]<=0)|(values[0][support]>=1)).any() or any((v[support]<=0).any() for v in values[1:3]):
        raise ValueError('Strict probabilities and positive magnitude means; no clipping')
    nets=pd.DataFrame(np.nan,index=axis,columns=MODELS)
    for family_index,family in enumerate(FAMILIES):
        for bits in BITS:
            p=values[0][:,family_index+1] if bits[0]=='1' else values[0][:,0]
            gain=values[1][:,2*family_index] if bits[1]=='1' else values[2][:,0]
            loss=values[1][:,2*family_index+1] if bits[2]=='1' else values[2][:,1]
            nets[f'{family}_{bits}']=p*gain-(1-p)*loss
        for bits,column in (('000',0),('100',3+family_index),('111',5+family_index)):
            np.testing.assert_allclose(nets[f'{family}_{bits}'],prior.iloc[:,column],atol=3e-13,rtol=2e-11,equal_nan=True)
            nets[f'{family}_{bits}']=prior.iloc[:,column]
    return nets


def validate_labels(nets,labels):
    axis=nets.index
    if not labels.index.equals(axis) or len(axis)<40:
        raise ValueError('Shared axis at least40 positions')
    y=labels.return_4.to_numpy(float)
    ends=pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    finite=np.isfinite(y)
    if np.isinf(y).any() or not np.array_equal(finite,ends.notna()) or (y[finite]<=-1).any() or (ends[finite].to_numpy()<=axis[finite].to_numpy()).any():
        raise ValueError('Valid future paired net label/maturity')
    return y


def selected(y,prediction,mask):
    eligible=mask&np.isfinite(prediction)
    positive=eligible&(prediction>0)
    mature=positive&np.isfinite(y)
    n=int(mature.sum())
    return {'forecasts':int(eligible.sum()),'positive_forecasts':int(positive.sum()),'mature_positive':n,
            'missing_positive_truth':int((positive&~np.isfinite(y)).sum()),
            'positive_mean':float(y[mature].mean()) if n>=20 else None,
            'hit_rate':float((y[mature]>0).mean()) if n>=20 else None,
            'false_positive_rate':float((y[mature]<=0).mean()) if n>=20 else None,
            'status':'AVAILABLE' if n>=20 else 'INSUFFICIENT_DATA'}


def utility(y,nets,ids):
    yy,nn=y[ids],nets[ids]
    good=np.isfinite(yy)&np.isfinite(nn).all(axis=1)
    yy,nn=yy[good],nn[good]
    if len(yy)<20:
        return None,None
    mse=np.mean((nn-yy[:,None])**2,axis=0)
    means=[float(yy[nn[:,j]>0].mean()) if (nn[:,j]>0).sum()>=20 else None for j in range(16)]
    return mse,means


def quantities(y,nets,ids):
    mse,means=utility(y,nets,ids)
    if mse is None:
        return dict.fromkeys(QUANTITIES)
    out={}
    for family_index,family in enumerate(FAMILIES):
        positions={bits:8*family_index+i for i,bits in enumerate(BITS)}
        improvement=lambda after,before:float(1-mse[positions[after]]/mse[positions[before]]) if mse[positions[before]]>0 else None
        difference=lambda after,before:means[positions[after]]-means[positions[before]] if means[positions[after]] is not None and means[positions[before]] is not None else None
        values=(improvement('010','000'),improvement('110','100'),improvement('110','010'),means[positions['010']],
                means[positions['110']],difference('110','100'),difference('111','110'))
        out.update({f'{family}_{key}':value for key,value in zip(SUFFIXES,values)})
    return out


def edges(y,nets,ids):
    mse,means=utility(y,nets,ids)
    result={}
    for family_index,family in enumerate(FAMILIES):
        positions={bits:8*family_index+i for i,bits in enumerate(BITS)}
        for leg_index,leg in enumerate(('P','G','L')):
            for before in BITS:
                if before[leg_index]!='0':
                    continue
                after=before[:leg_index]+'1'+before[leg_index+1:]
                old,new=positions[before],positions[after]
                result[f'{family}_{leg}_{before}_to_{after}']={'before':f'{family}_{before}','after':f'{family}_{after}',
                    'mse_improvement':float(1-mse[new]/mse[old]) if mse is not None and mse[old]>0 else None,
                    'selected_mean_difference':means[new]-means[old] if means is not None and means[new] is not None and means[old] is not None else None}
    return result


def bootstrap(y,nets):
    n,rng=len(y),np.random.default_rng(13)
    starts=rng.integers(0,n-39,(500,(n+39)//40))
    ids=(starts[:,:,None]+np.arange(40)).reshape(500,-1)[:,:n]
    original=quantities(y,nets,np.arange(n))
    records=[quantities(y,nets,row) for row in ids]
    summary={}
    for name,value in original.items():
        good=[r[name] for r in records if r[name] is not None]
        ok=value is not None and len(good)>=400
        summary[name]={'value':value,'valid_replicates':len(good),'ci95':np.quantile(good,[.025,.975],method='linear').tolist() if ok else None,
                       'status':'AVAILABLE' if ok else 'INSUFFICIENT_DATA'}
    return {'summary':summary,'records':records,'blocks':40,'repetitions':500,'seed':13,'refitted_models':0}


def analyze(probabilities,magnitudes,constants,prior,labels,clock):
    nets=combine(probabilities,magnitudes,constants,prior)
    axis=nets.index
    y=validate_labels(nets,labels)
    common=np.isfinite(y)&np.isfinite(nets.to_numpy()).all(axis=1)
    masks={'all':np.ones(len(y),bool),**{'year_'+str(t):axis.year==t for t in range(2020,2027)},
           **{'phase_'+str(k):np.arange(len(y))%5==k for k in range(5)}}
    panels={key:{m:selected(y,nets[m].to_numpy(),mask) for m in MODELS} for key,mask in masks.items()}
    schedules={m:{c:clock.schedule(axis,nets[m].to_numpy(),y,c) for c in clock.CLOCKS} for m in MODELS}
    result={'signals':len(y),'mature_common':int(common.sum()),'panels':panels,'schedules':schedules,
            'factorial_edges':{key:edges(y,nets.to_numpy(),np.flatnonzero(mask)) for key,mask in masks.items()},
            'bootstrap':bootstrap(y,nets.to_numpy()),'new_annual_models':0,'new_accounts':0,'provider_calls':0,
            'factorial_coordinates':16,'distinct_prediction_columns':15,'new_prediction_columns':10,
            'duplicate':'confirmation_000 equals original14_000, retained as shared control, not independent trials',
            'objective_achieved':False}
    return nets,result
