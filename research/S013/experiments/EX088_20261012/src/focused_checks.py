"""Synthetic record strength, prefix, tie and missingness checks; no real inputs."""
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


clock=load('strength_synthetic_clock',ROOT/'research/S013/experiments/EX083_20261012/src/kernel.py')
clock_audit=load('strength_synthetic_clock_audit',ROOT/'research/S013/experiments/EX083_20261012/src/audit.py')
axis=pd.bdate_range('2020-09-01',periods=400).as_unit('ns')
rng=np.random.default_rng(73)
scores=pd.DataFrame(rng.normal(.001,.004,(400,2)),index=axis,columns=kernel.INPUTS)
scores.loc[axis.year==2020]=np.nan
scores.iloc[106:111,0]=.004
scores.iloc[115,1]=np.nan
y=rng.normal(0,.02,400)
y[-5:]=np.nan
labels=pd.DataFrame({'return_4':y,'label_end_return_4':pd.Series(axis,index=axis).shift(-5)},index=axis)
states,signals,result=kernel.analyze(scores,labels,clock)
proof=audit.verify(scores,labels,states,signals,result,clock_audit)
assert proof['status']=='PASS'
assert not states.iloc[110]['confirmation_qualify']
assert states.loc[axis[115:120],'original14_available'].eq(False).all()
first=np.flatnonzero(scores.notna().all(axis=1))[0]
assert not states.iloc[first:first+4].confirmation_available.any()
cut=axis[axis.year==2022][0]
keep=axis<=cut
ss,dd,_=kernel.decisions(scores.loc[keep])
pd.testing.assert_frame_equal(ss,states.loc[keep],check_exact=True)
np.testing.assert_array_equal(dd,signals.loc[keep])
changed=scores.copy()
changed.loc[axis>cut]*=-5
ss,dd,_=kernel.decisions(changed)
pd.testing.assert_frame_equal(ss.loc[keep],states.loc[keep],check_exact=True)
np.testing.assert_array_equal(dd.loc[keep],signals.loc[keep])
changed_labels=labels.copy()
changed_labels.loc[labels.return_4.notna(),'return_4']+=.4
ss,dd,_=kernel.analyze(scores,changed_labels,clock)
pd.testing.assert_frame_equal(ss,states,check_exact=True)
np.testing.assert_array_equal(dd,signals)
assert states.loc[axis.year==2020,'confirmation_qualify'].eq(False).all()
assert signals.iloc[-5:].notna().all().all()
refused=0
for kind in ('infinite','2020_forecast','order','columns'):
    bad=scores.copy()
    if kind=='infinite':
        bad.iloc[101,0]=np.inf
    elif kind=='2020_forecast':
        bad.iloc[0,0]=0.
    elif kind=='order':
        bad=bad.iloc[::-1]
    else:
        bad=bad.iloc[:,::-1]
    try:
        kernel.decisions(bad)
    except ValueError:
        refused+=1
    else:
        raise AssertionError('Invalid causal forecast input accepted')
output={'status':'PASS','checks':['Scalar all record windows and matched controls independent','Strict ties do not qualify',
          'Full four issued predictions required; missingness no fallback','Historical controls exact','Prefix and future scores leave past unchanged',
          'Future labels never alter states or decisions','2020 unavailable and feature-only tail retained','All36 clocks and5000 bootstrap quantities'],
          'refusals':refused,'artificial_signals':400,'real_inputs':0,'real_statistics':0,'new_annual_models':0,'new_accounts':0,
          'experiment_allocation':0,'independent':proof,
          'files':{name:sha256((WORK/name).read_bytes()).hexdigest() for name in ('kernel.py','audit.py','focused_checks.py')}}
with (WORK/'focused_checks.json').open('x',encoding='utf-8') as stream:
    json.dump(output,stream,ensure_ascii=False,indent=2,allow_nan=False)
print({'status':'PASS','checks':len(output['checks']),'refusals':refused,'real_inputs':0})
