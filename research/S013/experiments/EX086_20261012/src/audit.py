"""Independent scalar conditional-mean Newton, maturity and economics."""
from math import fsum, exp, log
from bisect import bisect_left, bisect_right
import numpy as np
import pandas as pd
MODELS = ('training_mean','confirmation_only','original14_joint','confirmation_probability_payoff',
          'original14_probability_payoff','confirmation_conditional_payoff','original14_conditional_payoff')
MAGNITUDES = ('confirmation_gain','confirmation_loss','original14_gain','original14_loss')
QUANTITIES = tuple(f'{prefix}_{suffix}' for prefix in ('confirmation','original14') for suffix in
                  ('gain_mse_improvement','loss_mse_improvement','net_mse_improvement_vs_fixed','conditional_positive_mean','mean_difference_vs_fixed'))
def mean(values):
    return fsum(float(v) for v in values) / len(values)


def cdf(train, values):
    ordered = sorted(float(v) for v in train)
    return [(bisect_left(ordered, float(v)) + bisect_right(ordered, float(v))) / (2 * len(ordered)) - .5 for v in values]


def solve(matrix, right):
    n = len(right)
    a = [[float(v) for v in row] + [float(right[i])] for i, row in enumerate(matrix)]
    for i in range(n):
        best = max(range(i, n), key=lambda j: abs(a[j][i]))
        a[i], a[best] = a[best], a[i]
        if abs(a[i][i]) < 1e-14:
            raise ValueError('Independent Newton system singular')
        pivot = a[i][i]
        a[i] = [v / pivot for v in a[i]]
        for j in range(n):
            if j != i:
                factor = a[j][i]
                a[j] = [u - factor * v for u, v in zip(a[j], a[i])]
    return [a[i][-1] for i in range(n)]


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



def fit(train,target,test):
    x=[[1.,*map(float,r)] for r in train]
    n,d=len(x),len(x[0])
    if any(v<0 or not np.isfinite(v) for v in target) or mean(target)<=0:
        raise ValueError('Nonnegative magnitudes and positive training mean required')
    beta=[log(mean(target)),*([0.]*(d-1))]
    penalty=[0.,*([10.]*(d-1))]
    def objective(b):
        z=[fsum(a*v for a,v in zip(r,b)) for r in x]
        return fsum(v+float(t)*exp(-v) for v,t in zip(z,target))+.5*fsum(k*v*v for k,v in zip(penalty,b))
    for iteration in range(100):
        ratio=[float(t)*exp(-fsum(a*b for a,b in zip(r,beta))) for r,t in zip(x,target)]
        gradient=[fsum(x[i][j]*(1-ratio[i]) for i in range(n))+penalty[j]*beta[j] for j in range(d)]
        norm=max(abs(v) for v in gradient)
        if norm<=1e-10:
            prediction=[exp(fsum(a*b for a,b in zip([1.,*r],beta))) for r in test]
            return prediction,{'coefficients':beta,'iterations':iteration,'max_abs_gradient':norm,'objective':objective(beta)}
        h=[[fsum(x[i][a]*x[i][b]*ratio[i] for i in range(n))+(penalty[a] if a==b else 0.) for b in range(d)] for a in range(d)]
        step=solve(h,gradient)
        old,rate=objective(beta),1.
        for _ in range(40):
            candidate=[v-rate*s for v,s in zip(beta,step)]
            if objective(candidate)<=old-1e-4*rate*fsum(a*b for a,b in zip(gradient,step))+1e-12:
                beta=candidate
                break
            rate*=.5
        else:
            raise ValueError('Independent conditional mean line search failed')
    raise ValueError('Independent conditional mean convergence failed')


def forecasts(features,labels,probabilities,prior,prior_statistics):
    axis,y=features.index,labels.return_4.to_numpy(float)
    ends=pd.to_datetime(labels.label_end_return_4)
    x=features.to_numpy(float)
    complete=[all(np.isfinite(v) for v in row) for row in x]
    mag=pd.DataFrame(np.nan,index=axis,columns=MAGNITUDES)
    constants=pd.DataFrame(np.nan,index=axis,columns=('gain','loss'))
    nets=prior.reindex(columns=MODELS).copy()
    years={}
    for year in sorted(set(t.year for t in axis if t.year>=2021)):
        first=next(t for t in axis if t.year==year)
        tr=[i for i,t in enumerate(axis) if complete[i] and np.isfinite(y[i]) and 2020<=t.year<year and ends.iloc[i]<first]
        te=[i for i,t in enumerate(axis) if complete[i] and t.year==year]
        wins=[i for i in tr if y[i]>0]
        losses=[i for i in tr if y[i]<=0]
        available=len(tr)>=40 and len(wins)>=20 and len(losses)>=20
        dates=[axis[i].isoformat() for i in tr]
        assert prior_statistics['fit_years'][str(year)]['train_dates']==dates
        row={'first_signal':first.isoformat(),'train_n':len(tr),'win_n':len(wins),'nonpositive_n':len(losses),
             'zero_net_n':sum(y[i]==0 for i in tr),'train_dates':dates,'max_maturity':max(ends.iloc[i] for i in tr).isoformat() if tr else None,
             'feature_test_n':len(te),'available':available,'future_test_count_gate':False,'models':{},'payoffs':None}
        if available:
            gain,loss=mean(y[wins]),mean(-y[losses])
            row['payoffs']={'gain':gain,'loss':loss}
            constants.iloc[te]=[gain,loss]
            rt=[cdf(x[tr,j],x[tr,j]) for j in range(14)]
            rv=[cdf(x[tr,j],x[te,j]) for j in range(14)]
            for family,columns in ((0,[8]),(1,list(range(14)))):
                p=probabilities.iloc[te,family+1].to_numpy()
                np.testing.assert_allclose(prior.iloc[te,3+family],[v*gain-(1-v)*loss for v in p],atol=3e-13,rtol=2e-11)
                predictions=[]
                for offset,ids in ((0,wins),(1,losses)):
                    positions=[tr.index(i) for i in ids]
                    tx=[[rt[j][i] for j in columns] for i in positions]
                    vx=[[rv[j][i] for j in columns] for i in range(len(te))]
                    target=[abs(y[i]) for i in ids]
                    prediction,proof=fit(tx,target,vx)
                    name=MAGNITUDES[2*family+offset]
                    mag.loc[axis[te],name]=prediction
                    row['models'][name]=proof
                    predictions.append(prediction)
                nets.iloc[te,5+family]=[pp*g-(1-pp)*loss_value for pp,g,loss_value in zip(p,*predictions)]
        years[str(year)]=row
    return mag,constants,nets,years


def quantities(y,mag,constants,nets,ids):
    ix=[int(i) for i in ids if np.isfinite(y[int(i)]) and np.isfinite(mag[int(i)]).all() and np.isfinite(constants[int(i)]).all() and np.isfinite(nets[int(i)]).all()]
    if len(ix)<20:
        return dict.fromkeys(QUANTITIES)
    out={}
    for family in range(2):
        keys=QUANTITIES[5*family:5*family+5]
        for offset in range(2):
            subset=[i for i in ix if (y[i]>0 if offset==0 else y[i]<=0)]
            baseline=mean([(constants[i,offset]-abs(y[i]))**2 for i in subset]) if len(subset)>=20 else None
            out[keys[offset]]=float(1-mean([(mag[i,2*family+offset]-abs(y[i]))**2 for i in subset])/baseline) if baseline is not None and baseline>0 else None
        old,new=3+family,5+family
        baseline=mean([(nets[i,old]-y[i])**2 for i in ix])
        out[keys[2]]=float(1-mean([(nets[i,new]-y[i])**2 for i in ix])/baseline) if baseline>0 else None
        newids=[i for i in ix if nets[i,new]>0]
        oldids=[i for i in ix if nets[i,old]>0]
        newmean=mean(y[newids]) if len(newids)>=20 else None
        oldmean=mean(y[oldids]) if len(oldids)>=20 else None
        out[keys[3]]=newmean
        out[keys[4]]=newmean-oldmean if newmean is not None and oldmean is not None else None
    return out


def verify(features,labels,probabilities,prior,prior_statistics,reported_mag,reported_constants,reported_nets,report,clock):
    mag,constants,nets,years=forecasts(features,labels,probabilities,prior,prior_statistics)
    np.testing.assert_allclose(reported_mag,mag,atol=3e-12,rtol=2e-9,equal_nan=True)
    np.testing.assert_allclose(reported_constants,constants,atol=3e-12,rtol=2e-9,equal_nan=True)
    np.testing.assert_allclose(reported_nets,nets,atol=3e-12,rtol=2e-9,equal_nan=True)
    np.testing.assert_array_equal(reported_nets.to_numpy()>0,nets.to_numpy()>0)
    np.testing.assert_array_equal(reported_nets.iloc[:,:5],prior)
    compare(report['fit_years'],years,'matched_fits')
    axis,y=features.index,labels.return_4.to_numpy(float)
    m,c,n=mag.to_numpy(),constants.to_numpy(),nets.to_numpy()
    common=[i for i in range(len(y)) if np.isfinite(y[i]) and np.isfinite(n[i]).all()]
    assert report['mature_common']==len(common)
    masks={'all':list(range(len(y))),**{'year_'+str(t):[i for i,d in enumerate(axis) if d.year==t] for t in range(2020,2027)},
           **{'phase_'+str(k):[i for i in range(len(y)) if i%5==k] for k in range(5)}}
    panels={key:{model:group(y,n[:,j],ids) for j,model in enumerate(MODELS)} for key,ids in masks.items()}
    compare(report['panels'],panels,'panels')
    compare(report['conditional_quality'],{key:quantities(y,m,c,n,ids) for key,ids in masks.items()},'conditional_quality')
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
    records=[quantities(y,m,c,n,row) for row in ids]
    compare(report['bootstrap']['records'],records,'bootstrap_records')
    summary={}
    for key,value in quantities(y,m,c,n,list(range(len(y)))).items():
        good=[r[key] for r in records if r[key] is not None]
        ok=value is not None and len(good)>=400
        summary[key]={'value':value,'valid_replicates':len(good),'ci95':np.quantile(good,[.025,.975],method='linear').tolist() if ok else None,
                      'status':'AVAILABLE' if ok else 'INSUFFICIENT_DATA'}
    compare(report['bootstrap']['summary'],summary,'bootstrap_summary')
    return {'status':'PASS','new_annual_models':4*sum(r['available'] for r in years.values()),'reused_probability_models':12,
            'new_accounts':0,'forecast_rows':len(y),'mature_common':len(common),'positive_flags':'EXACT',
            'scalar_conditional_mean_normal_equations':True,'EX084_controls':'EXACT','matched_training':True,'schedules':42,'bootstrap_checks':5000}
