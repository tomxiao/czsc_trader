"""Synthetic attribution/prefix/strict-zero controls; no fit or real data."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
import kernel
import audit

WORK=Path(__file__).resolve().parent
ROOT=WORK.parents[1]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


clock=load('legs_synthetic_clock',ROOT/'research/S013/experiments/EX083_20261012/src/kernel.py')
clock_audit=load('legs_synthetic_clock_audit',ROOT/'research/S013/experiments/EX083_20261012/src/audit.py')
axis=pd.bdate_range('2020-09-01',periods=400).as_unit('ns')
rng=np.random.default_rng(61)
probs=pd.DataFrame(np.column_stack((np.full(400,.5),rng.uniform(.2,.8,400),rng.uniform(.2,.8,400))),index=axis,columns=kernel.PROBABILITIES)
mag=pd.DataFrame(rng.uniform(.005,.045,(400,4)),index=axis,columns=kernel.MAGNITUDES)
constants=pd.DataFrame(np.full((400,2),.02),index=axis,columns=('gain','loss'))
prior=pd.DataFrame(np.nan,index=axis,columns=kernel.PRIOR)
prior.iloc[:,0]=0.
prior.iloc[:,1:3]=rng.uniform(-.01,.01,(400,2))
for family in range(2):
    p=probs.iloc[:,family+1]
    prior.iloc[:,family+3]=p*.02-(1-p)*.02
    prior.iloc[:,family+5]=p*mag.iloc[:,2*family]-(1-p)*mag.iloc[:,2*family+1]
for frame in (probs,mag,constants,prior):
    frame.loc[axis.year==2020]=np.nan
y=rng.normal(0,.02,400)
y[-5:]=np.nan
labels=pd.DataFrame({'return_4':y,'label_end_return_4':pd.Series(axis,index=axis).shift(-5)},index=axis)
nets,result=kernel.analyze(probs,mag,constants,prior,labels,clock)
proof=audit.verify(probs,mag,constants,prior,labels,nets,result,clock_audit)
assert proof['status']=='PASS'
assert not (nets.confirmation_000>0).any() and not (nets.original14_000>0).any()
cut=axis[axis.year==2022][0]
keep=axis<=cut
prefix=kernel.combine(*(f.loc[keep] for f in (probs,mag,constants,prior)))
np.testing.assert_array_equal(prefix,nets.loc[keep])
changed_labels=labels.copy()
changed_labels.loc[labels.return_4.notna(),'return_4']+=.3
changed,_=kernel.analyze(probs,mag,constants,prior,changed_labels,clock)
np.testing.assert_array_equal(changed,nets)
for family in kernel.FAMILIES:
    e=result['factorial_edges']['all']
    a=e[family+'_G_100_to_110']['selected_mean_difference']
    b=e[family+'_L_110_to_111']['selected_mean_difference']
    c=e[family+'_L_100_to_101']['selected_mean_difference']
    other=e[family+'_G_101_to_111']['selected_mean_difference']
    np.testing.assert_allclose(a+b,c+other,atol=1e-14)
refused=0
for frame_index in range(4):
    frames=[f.copy() for f in (probs,mag,constants,prior)]
    frames[frame_index].iloc[110,0]=np.inf
    try:
        kernel.combine(*frames)
    except ValueError:
        refused+=1
    else:
        raise AssertionError('Nonfinite frozen field accepted')
for frame_index,value in ((0,1.),(1,0.),(2,-.1)):
    frames=[f.copy() for f in (probs,mag,constants,prior)]
    frames[frame_index].iloc[110,0]=value
    try:
        kernel.combine(*frames)
    except ValueError:
        refused+=1
    else:
        raise AssertionError('Invalid probability/magnitude admitted')
bad=prior.copy()
bad.iloc[110,0]+=.03
try:
    kernel.combine(probs,mag,constants,bad)
except AssertionError:
    refused+=1
else:
    raise AssertionError('Inconsistent old control accepted')
assert nets.loc[axis.year==2020].isna().all().all() and nets.iloc[-5:].notna().all().all()
output={'status':'PASS','checks':['Scalar all16 combinations and all24 edges independent','Six old controls exact with shared000 counted once',
          'Strict positive decision excludes zero expectation','Factorial path selected mean differences telescope',
          'Prefix and future labels do not alter frozen predictions','2020 unavailable and feature-only tail retained',
          'All96 clocks and7000 bootstrap quantities'],'refusals':refused,'artificial_signals':400,
          'real_inputs':0,'real_statistics':0,'new_annual_models':0,'new_accounts':0,'experiment_allocation':0,'independent':proof,
          'files':{name:sha256((WORK/name).read_bytes()).hexdigest() for name in ('kernel.py','audit.py','focused_checks.py')}}
with (WORK/'focused_checks.json').open('x',encoding='utf-8') as stream:
    json.dump(output,stream,ensure_ascii=False,indent=2,allow_nan=False)
print({'status':'PASS','checks':len(output['checks']),'refusals':refused,'real_inputs':0})
