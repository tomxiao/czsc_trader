"""Synthetic matched-state/window causal checks before EX085 allocation."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
import kernel
import audit

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


logit=load('synthetic_fixed_logit',ROOT/'research/S013/experiments/EX084_20261012/src/kernel.py')
clock=load('synthetic_fixed_clock',ROOT/'research/S013/experiments/EX083_20261012/src/kernel.py')
clock_audit=load('synthetic_independent_clock',ROOT/'research/S013/experiments/EX083_20261012/src/audit.py')
axis=pd.bdate_range('2020-09-01',periods=400).as_unit('ns')
rng=np.random.default_rng(93)
features=pd.DataFrame(rng.normal(size=(400,14)),index=axis,columns=kernel.FEATURES)
features.iloc[:19,6]=np.nan
y=.020*features.momentum20.to_numpy()+.007*features.confirmation_score.to_numpy()+rng.normal(0,.01,400)
y[-5:]=np.nan
ends=pd.Series(axis,index=axis).shift(-5)
labels=pd.DataFrame({'return_4':y,'label_end_return_4':ends},index=axis)
state,probs,nets,result=kernel.analyze(features,labels,logit,clock)
proof=audit.verify(features,labels,state,probs,nets,result,clock_audit)
assert proof['status']=='PASS'
assert state.iloc[:24].isna().all().all() and state.iloc[24].notna().all()
assert result['state_traces'][24]['positions']==list(range(20))
for date,row in zip(axis,result['state_traces']):
    assert row['max_maturity'] is None or pd.Timestamp(row['max_maturity'])<=date
cut=axis[axis.year==2022][0]
keep=axis<=cut
prefix_labels=labels.loc[keep].copy()
late=prefix_labels.label_end_return_4>cut
prefix_labels.loc[late,'return_4']=np.nan
prefix_labels.loc[late,'label_end_return_4']=pd.NaT
ss,_,pp,nn,_=kernel.forecasts(features.loc[keep],prefix_labels,logit)
for actual,expected in ((ss,state.loc[keep]),(pp,probs.loc[keep]),(nn,nets.loc[keep])):
    np.testing.assert_allclose(actual,expected,atol=3e-12,equal_nan=True)
changed=features.copy()
changed.loc[axis>cut]*=-3
ss,_,pp,nn,_=kernel.forecasts(changed,labels,logit)
for actual,expected in ((ss.loc[keep],state.loc[keep]),(pp.loc[keep],probs.loc[keep]),(nn.loc[keep],nets.loc[keep])):
    np.testing.assert_allclose(actual,expected,atol=3e-12,equal_nan=True)
changed_labels=labels.copy()
changed_labels.loc[(ends>cut)&np.isfinite(y),'return_4']+=.4
ss,_,pp,nn,_=kernel.forecasts(features,changed_labels,logit)
for actual,expected in ((ss.loc[keep],state.loc[keep]),(pp.loc[keep],probs.loc[keep]),(nn.loc[keep],nets.loc[keep])):
    np.testing.assert_allclose(actual,expected,atol=3e-12,equal_nan=True)
assert not np.allclose(ss.loc[axis>cut].to_numpy(),state.loc[axis>cut].to_numpy(),equal_nan=True)
assert probs.loc[axis.year==2020].isna().all().all() and nets.loc[axis.year==2020].isna().all().all()
assert probs.iloc[-5:].notna().all().all() and nets.iloc[-5:].notna().all().all()
zero=labels.copy()
zero.loc[np.isfinite(y),'return_4']=0.
_,_,pp,nn,fit=kernel.forecasts(features,zero,logit)
assert pp.isna().all().all() and nn.isna().all().all() and not any(r['available'] for r in fit.values())
refused=0
cases=[]
bad=features.copy()
bad.iloc[31,0]=np.inf
cases.append((bad,labels))
bad=labels.copy()
bad.iloc[31,1]=axis[31]
cases.append((features,bad))
cases.append((features.drop(columns=['acf1']),labels))
for args in cases:
    try:
        kernel.forecasts(*args,logit)
    except ValueError:
        refused+=1
    else:
        raise AssertionError('Invalid input admitted')
output={'status':'PASS','checks':['Independent allstate cells and20matured positions',
        'Label mature atT allowed, own future target never used', 'Minimum20matured full window, no shorter fallback',
        'Matched annual ridge/logistic datasets and independent models', 'Prefix with only1current-year testT',
        'Future features and unelapsed labels cannot alter past', 'Past effects change only after information matures',
        '2020unavailable and feature-only forecast tail retained', 'Oneclass training remains unavailable without fallback',
        'All30clocks and5000conditional bootstrap quantities'],
        'refusals':refused,'artificial_signals':400,'real_inputs':0,'real_statistics':0,'new_accounts':0,'experiment_allocation':0,
        'independent':proof,'files':{name:sha256((WORK/name).read_bytes()).hexdigest() for name in ('kernel.py','audit.py','focused_checks.py')}}
with (WORK/'focused_checks.json').open('x',encoding='utf-8') as stream:
    json.dump(output,stream,ensure_ascii=False,indent=2,allow_nan=False)
print({'status':'PASS','checks':len(output['checks']),'refusals':refused,'real_inputs':0})
