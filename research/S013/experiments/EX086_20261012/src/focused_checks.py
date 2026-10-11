"""Synthetic causal conditional-mean, exact control and independent audit checks."""
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


original=load('synthetic_probability',ROOT/'research/S013/experiments/EX084_20261012/src/kernel.py')
clock=load('synthetic_clock',ROOT/'research/S013/experiments/EX083_20261012/src/kernel.py')
clock_audit=load('synthetic_clock_audit',ROOT/'research/S013/experiments/EX083_20261012/src/audit.py')
axis=pd.bdate_range('2020-09-01',periods=400).as_unit('ns')
rng=np.random.default_rng(63)
features=pd.DataFrame(rng.normal(size=(400,14)),index=axis,columns=kernel.FEATURES)
features.iloc[:19,6]=np.nan
y=.012*features.momentum20.to_numpy()+rng.normal(0,.02,400)
y[-5:]=np.nan
ends=pd.Series(axis,index=axis).shift(-5)
labels=pd.DataFrame({'return_4':y,'label_end_return_4':ends},index=axis)
raw=pd.DataFrame(np.nan,index=axis,columns=kernel.MODELS[:3])
complete=np.isfinite(features.to_numpy()).all(axis=1)
for year in (2021,2022):
    first=axis[axis.year==year][0]
    tr=complete&np.isfinite(y)&(axis.year<year)&(ends<first).to_numpy()
    te=complete&(axis.year==year)
    raw.loc[te,'training_mean']=np.mean(y[tr])
    raw.loc[te,'confirmation_only']=.001*features.confirmation_score[te]
    raw.loc[te,'original14_joint']=.001*features.momentum20[te]
probs,prior,fit_years=original.forecasts(features,labels,raw)
stats={'fit_years':fit_years}
mag,constants,nets,result=kernel.analyze(features,labels,probs,prior,stats,clock)
proof=audit.verify(features,labels,probs,prior,stats,mag,constants,nets,result,clock_audit)
assert proof['status']=='PASS'
np.testing.assert_array_equal(nets.iloc[:,:5],prior)
constant,_=kernel.fit(np.zeros((60,1)),np.r_[np.zeros(20),np.full(40,.03)],np.zeros((5,1)))
np.testing.assert_allclose(constant,.02,atol=1e-14)
tx=rng.uniform(-.5,.5,(70,2))
target=np.exp(-4+tx[:,0])
pred,proof1=kernel.fit(tx,target,tx[:3])
scaled,proof2=kernel.fit(tx,target*10,tx[:3])
np.testing.assert_allclose(scaled,pred*10,atol=3e-12)
np.testing.assert_allclose(proof1['coefficients'][1:],proof2['coefficients'][1:],atol=3e-12)
np.testing.assert_allclose(kernel.rank(np.array([0.,0.,2.,4.]),np.array([-1.,0.,4.,9.])),[-.5,-.25,.375,.5])
cut=axis[axis.year==2022][0]
keep=axis<=cut
short=labels.loc[keep].copy()
late=short.label_end_return_4>cut
short.loc[late,'return_4']=np.nan
short.loc[late,'label_end_return_4']=pd.NaT
mm,cc,nn,_=kernel.forecasts(features.loc[keep],short,probs.loc[keep],prior.loc[keep],stats)
np.testing.assert_allclose(mm,mag.loc[keep],atol=3e-12,equal_nan=True)
np.testing.assert_allclose(nn,nets.loc[keep],atol=3e-12,equal_nan=True)
changed=features.copy()
changed.loc[axis>cut]*=-3
mm,_,nn,_=kernel.forecasts(changed,labels,probs,prior,stats)
np.testing.assert_allclose(mm.loc[keep],mag.loc[keep],atol=3e-12,equal_nan=True)
np.testing.assert_allclose(nn.loc[keep],nets.loc[keep],atol=3e-12,equal_nan=True)
changed_labels=labels.copy()
changed_labels.loc[(axis.year==2022)&np.isfinite(y),'return_4']+=.4
mm,_,nn,_=kernel.forecasts(features,changed_labels,probs,prior,stats)
np.testing.assert_allclose(mm,mag,atol=3e-12,equal_nan=True)
np.testing.assert_allclose(nn,nets,atol=3e-12,equal_nan=True)
assert nets.loc[axis.year==2020].isna().all().all()
assert mag.iloc[-5:].notna().all().all() and nets.iloc[-5:,5:].notna().all().all()
refused=0
for target in (np.full(40,-.1),np.zeros(40),np.full(40,np.nan)):
    try:
        kernel.fit(np.zeros((40,1)),target,np.zeros((1,1)))
    except ValueError:
        refused+=1
    else:
        raise AssertionError('Invalid mean target accepted')
bad=probs.copy()
bad.iloc[110,1]=1.
try:
    kernel.forecasts(features,labels,bad,prior,stats)
except ValueError:
    refused+=1
else:
    raise AssertionError('Boundary probability silently clipped')
output={'status':'PASS','checks':['Scalar Newton positive means and coefficients independent','EX084 controls bit exact',
        'Constant feature equals arithmetic mean including zero magnitudes','Currency scaling changes intercept only',
        'CDF midpoint ties and extremes','Annual strict maturity prefix with one current T',
        'Future features and labels do not alter past predictions','2020 unavailable and feature-only tail retained',
        'All42clocks and5000 bootstrap quantities'],'refusals':refused,'artificial_signals':400,'real_inputs':0,
        'real_statistics':0,'new_accounts':0,'experiment_allocation':0,'independent':proof,
        'files':{name:sha256((WORK/name).read_bytes()).hexdigest() for name in ('kernel.py','audit.py','focused_checks.py')}}
with (WORK/'focused_checks.json').open('x',encoding='utf-8') as stream:
    json.dump(output,stream,ensure_ascii=False,indent=2,allow_nan=False)
print({'status':'PASS','checks':len(output['checks']),'refusals':refused,'real_inputs':0})
