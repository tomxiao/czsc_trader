"""Independent scalar prior-four record, matched controls and all clocks."""
from math import fsum
import numpy as np
import pandas as pd
FAMILIES=('confirmation','original14')
MODELS=tuple(f'{family}_{kind}' for family in FAMILIES for kind in ('historical_control','matched_control','record4'))
SUFFIXES=('record_positive_mean','record_positive_minus_matched','record_greedy_mean',
          'record_greedy_minus_matched_greedy','record_greedy_minus_blocked')
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





def decisions(scores):
    axis=scores.index
    signals=pd.DataFrame(np.nan,index=axis,columns=MODELS)
    states=pd.DataFrame(index=axis)
    traces=[]
    for family_index,family in enumerate(FAMILIES):
        p=scores.iloc[:,family_index].to_numpy(float)
        maximum,available,qualify=[],[],[]
        matched,record=[],[]
        for i,value in enumerate(p):
            window=list(range(i-4,i)) if i>=4 else []
            good=bool(len(window)==4 and np.isfinite(value) and all(np.isfinite(p[j]) for j in window))
            level=max(p[j] for j in window) if good else np.nan
            yes=bool(good and value>0 and value>level)
            maximum.append(level)
            available.append(good)
            qualify.append(yes)
            matched.append(value if good else np.nan)
            record.append(value if yes else (0. if good else np.nan))
            traces.append({'family':family,'signal_date':axis[i].isoformat(),'available':good,'qualify':yes,
                           'past_positions':window if good else [],'model_year_crossing':bool(good and axis[i-4].year!=axis[i].year)})
        signals[family+'_historical_control']=p
        signals[family+'_matched_control']=matched
        signals[family+'_record4']=record
        states[family+'_issued_net_forecast']=p
        states[family+'_previous4_max']=maximum
        states[family+'_available']=available
        states[family+'_qualify']=qualify
    return states,signals,traces


def selector_masks(signals,clock):
    result={}
    for family in FAMILIES:
        before=signals[family+'_matched_control'].to_numpy()
        record=signals[family+'_record4'].to_numpy()
        selected=clock.selected(record,'greedy')
        prior=clock.selected(before,'greedy')
        result[family]=[[np.isfinite(record[i]) and record[i]>0,np.isfinite(before[i]) and before[i]>0,
                         i in selected,i in prior,np.isfinite(record[i]) and record[i]>0 and i not in selected] for i in range(len(signals))]
    return result


def quantities(y,masks,ids):
    result={}
    for family,mask in masks.items():
        averages=[]
        for column in range(5):
            ix=[int(i) for i in ids if np.isfinite(y[int(i)]) and mask[int(i)][column]]
            averages.append(mean(y[ix]) if len(ix)>=20 else None)
        difference=lambda a,b:averages[a]-averages[b] if averages[a] is not None and averages[b] is not None else None
        values=(averages[0],difference(0,1),averages[2],difference(2,3),difference(2,4))
        for suffix,value in zip(SUFFIXES,values):
            result[family+'_'+suffix]=value
    return result


def verify(scores,labels,reported_states,reported_signals,report,clock):
    states,signals,traces=decisions(scores)
    np.testing.assert_allclose(reported_states.to_numpy(float),states.to_numpy(float),atol=3e-12,rtol=2e-9,equal_nan=True)
    np.testing.assert_allclose(reported_signals,signals,atol=3e-12,rtol=2e-9,equal_nan=True)
    np.testing.assert_array_equal(reported_signals.to_numpy()>0,signals.to_numpy()>0)
    compare(report['state_traces'],traces,'all3270_causal_windows')
    for family_index,family in enumerate(FAMILIES):
        np.testing.assert_array_equal(signals[family+'_historical_control'],scores.iloc[:,family_index])
    axis,y=signals.index,labels.return_4.to_numpy(float)
    n=signals.to_numpy()
    groups={'all':list(range(len(y))),**{'year_'+str(t):[i for i,d in enumerate(axis) if d.year==t] for t in range(2020,2027)},
            **{'phase_'+str(k):[i for i in range(len(y)) if i%5==k] for k in range(5)}}
    compare(report['panels'],{key:{model:group(y,n[:,j],ids) for j,model in enumerate(MODELS)} for key,ids in groups.items()},'panels')
    masks=selector_masks(signals,clock)
    compare(report['selection_quality'],{key:quantities(y,masks,ids) for key,ids in groups.items()},'selection_quality')
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
    records=[quantities(y,masks,row) for row in ids]
    compare(report['bootstrap']['records'],records,'bootstrap_records')
    summary={}
    for key,value in quantities(y,masks,list(range(len(y)))).items():
        good=[r[key] for r in records if r[key] is not None]
        available=value is not None and len(good)>=400
        summary[key]={'value':value,'valid_replicates':len(good),'ci95':np.quantile(good,[.025,.975],method='linear').tolist() if available else None,
                      'status':'AVAILABLE' if available else 'INSUFFICIENT_DATA'}
    compare(report['bootstrap']['summary'],summary,'bootstrap_summary')
    return {'status':'PASS','new_annual_models':0,'new_accounts':0,'forecast_rows':len(y),'positive_flags':'EXACT',
            'historical_controls':'EXACT','causal_windows':2*len(y),'matched_controls':'VERIFIED','schedules':36,'bootstrap_checks':5000}
