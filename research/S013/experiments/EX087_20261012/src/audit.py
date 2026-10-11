"""Independent scalar P/G/L combination and all factorial economics."""
from math import fsum
from itertools import product
import numpy as np
import pandas as pd
FAMILIES=('confirmation','original14')
BITS=tuple(''.join(map(str,row)) for row in product((0,1),repeat=3))
MODELS=tuple(f'{family}_{bits}' for family in FAMILIES for bits in BITS)
SUFFIXES=('gain_only_mse_vs_constant','gain_given_probability_mse','probability_given_gain_mse',
          'gain_only_positive_mean','probability_gain_positive_mean','gain_given_probability_mean_difference',
          'loss_given_probability_gain_mean_difference')
QUANTITIES=tuple(f'{family}_{suffix}' for family in FAMILIES for suffix in SUFFIXES)
def mean(values):
    return fsum(float(v) for v in values) / len(values)


def compare(a, b, where='root'):
    if isinstance(b, dict):
        assert set(a) == set(b), where
        for key in b:
            compare(a[key], b[key], where + '/' + key)
    elif isinstance(b, list):
        assert len(a) == len(b), where
        for i, (aa, bb) in enumerate(zip(a, b)):
            compare(aa, bb, where + '/' + str(i))
    elif isinstance(b, float):
        assert np.isclose(a, b, atol=3e-12, rtol=2e-9), (where, a, b)
    else:
        assert a == b, (where, a, b)


def group(y, prediction, ids):
    eligible = [i for i in ids if np.isfinite(prediction[i])]
    positive = [i for i in eligible if prediction[i] > 0]
    mature = [i for i in positive if np.isfinite(y[i])]
    n = len(mature)
    return {'forecasts': len(eligible), 'positive_forecasts': len(positive), 'mature_positive': n,
            'missing_positive_truth': len(positive) - n, 'positive_mean': mean(y[mature]) if n >= 20 else None,
            'hit_rate': sum(y[i] > 0 for i in mature) / n if n >= 20 else None,
            'false_positive_rate': sum(y[i] <= 0 for i in mature) / n if n >= 20 else None,
            'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}




def combine(probabilities,magnitudes,constants,prior):
    rows=[]
    for i in range(len(probabilities)):
        row=[]
        for family in range(2):
            for bits in BITS:
                if not np.isfinite(probabilities.iloc[i,0]):
                    row.append(np.nan)
                    continue
                p=float(probabilities.iloc[i,family+1 if bits[0]=='1' else 0])
                gain=float(magnitudes.iloc[i,2*family]) if bits[1]=='1' else float(constants.iloc[i,0])
                loss=float(magnitudes.iloc[i,2*family+1]) if bits[2]=='1' else float(constants.iloc[i,1])
                calculated=p*gain-(1-p)*loss
                if bits in ('000','100','111'):
                    col=0 if bits=='000' else (3+family if bits=='100' else 5+family)
                    exact=float(prior.iloc[i,col])
                    assert np.isclose(calculated,exact,atol=3e-13,rtol=2e-11)
                    row.append(exact)
                else:
                    row.append(calculated)
        rows.append(row)
    return pd.DataFrame(rows,index=probabilities.index,columns=MODELS)


def utility(y,nets,ids):
    ix=[int(i) for i in ids if np.isfinite(y[int(i)]) and all(np.isfinite(v) for v in nets[int(i)])]
    if len(ix)<20:
        return None,None
    mse=[mean([(nets[i,j]-y[i])**2 for i in ix]) for j in range(16)]
    averages=[]
    for j in range(16):
        selected=[i for i in ix if nets[i,j]>0]
        averages.append(mean(y[selected]) if len(selected)>=20 else None)
    return mse,averages


def quantities(y,nets,ids):
    mse,avg=utility(y,nets,ids)
    if mse is None:
        return dict.fromkeys(QUANTITIES)
    result={}
    for family_index,family in enumerate(FAMILIES):
        base=family_index*8
        improve=lambda after,before:float(1-mse[base+after]/mse[base+before]) if mse[base+before]>0 else None
        difference=lambda after,before:avg[base+after]-avg[base+before] if avg[base+after] is not None and avg[base+before] is not None else None
        values=(improve(2,0),improve(6,4),improve(6,2),avg[base+2],avg[base+6],difference(6,4),difference(7,6))
        for suffix,value in zip(SUFFIXES,values):
            result[family+'_'+suffix]=value
    return result


def edges(y,nets,ids):
    mse,avg=utility(y,nets,ids)
    result={}
    for family_index,family in enumerate(FAMILIES):
        for leg,weight in (('P',4),('G',2),('L',1)):
            for before in range(8):
                if before&weight:
                    continue
                after=before+weight
                a,b=8*family_index+after,8*family_index+before
                old,new=f'{before:03b}',f'{after:03b}'
                result[f'{family}_{leg}_{old}_to_{new}']={'before':family+'_'+old,'after':family+'_'+new,
                    'mse_improvement':float(1-mse[a]/mse[b]) if mse is not None and mse[b]>0 else None,
                    'selected_mean_difference':avg[a]-avg[b] if avg is not None and avg[a] is not None and avg[b] is not None else None}
    return result


def verify(probabilities,magnitudes,constants,prior,labels,reported_nets,report,clock):
    nets=combine(probabilities,magnitudes,constants,prior)
    np.testing.assert_allclose(reported_nets,nets,atol=3e-12,rtol=2e-9,equal_nan=True)
    np.testing.assert_array_equal(reported_nets.to_numpy()>0,nets.to_numpy()>0)
    np.testing.assert_array_equal(nets.iloc[:,0],nets.iloc[:,8])
    for family in range(2):
        for offset,column in ((0,0),(4,3+family),(7,5+family)):
            np.testing.assert_array_equal(nets.iloc[:,8*family+offset],prior.iloc[:,column])
    axis,y=nets.index,labels.return_4.to_numpy(float)
    n=nets.to_numpy()
    common=[i for i in range(len(y)) if np.isfinite(y[i]) and all(np.isfinite(v) for v in n[i])]
    assert report['mature_common']==len(common)
    masks={'all':list(range(len(y))),**{'year_'+str(t):[i for i,d in enumerate(axis) if d.year==t] for t in range(2020,2027)},
           **{'phase_'+str(k):[i for i in range(len(y)) if i%5==k] for k in range(5)}}
    compare(report['panels'],{key:{model:group(y,n[:,j],ids) for j,model in enumerate(MODELS)} for key,ids in masks.items()},'panels')
    compare(report['factorial_edges'],{key:edges(y,n,ids) for key,ids in masks.items()},'all_factorial_edges')
    schedules={}
    for j, model in enumerate(MODELS):
        prediction = n[:, j]
        positive = [i for i, v in enumerate(prediction) if np.isfinite(v) and v > 0]
        schedules[model] = {}
        for name in clock.CLOCKS:
            ix = clock.selected(prediction, name)
            mature = [i for i in ix if np.isfinite(y[i])]
            accepted = set(ix)
            blocked = [i for i in positive if i not in accepted]
            mb = [i for i in blocked if np.isfinite(y[i])]
            panel = {'all': clock.attribution(y, ix), **{'year_' + str(t): clock.attribution(y, [i for i in ix if axis[i].year == t]) for t in range(2020, 2027)}}
            schedules[model][name] = {'accepted': len(ix), 'missing_truth_accepted': len(ix) - len(mature),
                'positive_forecasts': len(positive), 'blocked_positive_forecasts': len(blocked),
                'accepted_mean': mean(y[mature]) if len(mature) >= 20 else None,
                'blocked_positive_mean': mean(y[mb]) if len(mb) >= 20 else None, 'mature_blocked_positive': len(mb), 'panels': panel,
                'records': [{'signal_date': axis[i].isoformat(), 'position': i, 'prediction': float(prediction[i]),
                             'proxy_return': float(y[i]) if np.isfinite(y[i]) else None} for i in ix]}
    compare(report['schedules'],schedules,'schedules')
    rng=np.random.default_rng(13)
    starts=rng.integers(0,len(y)-39,(500,(len(y)+39)//40))
    ids=np.concatenate([starts[:,j:j+1]+np.arange(40) for j in range(starts.shape[1])],axis=1)[:,:len(y)]
    records=[quantities(y,n,row) for row in ids]
    compare(report['bootstrap']['records'],records,'bootstrap_records')
    summary={}
    for key,value in quantities(y,n,list(range(len(y)))).items():
        good=[r[key] for r in records if r[key] is not None]
        ok=value is not None and len(good)>=400
        summary[key]={'value':value,'valid_replicates':len(good),'ci95':np.quantile(good,[.025,.975],method='linear').tolist() if ok else None,
                      'status':'AVAILABLE' if ok else 'INSUFFICIENT_DATA'}
    compare(report['bootstrap']['summary'],summary,'bootstrap_summary')
    return {'status':'PASS','new_annual_models':0,'new_accounts':0,'forecast_rows':len(y),'mature_common':len(common),
            'positive_flags':'EXACT','EX084_EX086_controls':'EXACT','factorial_coordinates':16,'distinct_predictions':15,
            'schedules':96,'factorial_edges':24,'bootstrap_checks':7000}
