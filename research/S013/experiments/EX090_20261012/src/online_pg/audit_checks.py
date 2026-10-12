"""Synthetic stationarity and independent-statistics integration before EX090 inputs."""
from pathlib import Path
import importlib.util
import json
import numpy as np
import pandas as pd
import kernel
import audit
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


axis=pd.bdate_range('2020-11-02',periods=180).as_unit('ns')
rng=np.random.default_rng(902)
features=pd.DataFrame(rng.normal(0,1,(180,14)),index=axis,columns=kernel.FEATURES)
features.iloc[90,2]=np.nan
old=pd.DataFrame(rng.normal(.002,.001,(180,2)),index=axis,columns=kernel.INPUTS)
old.loc[axis.year<2021]=np.nan
old.iloc[112,0]=np.nan
y=np.where(np.arange(180)%2==0,.009,-.007)+rng.normal(0,.0003,180)
y[20]=0.
y[-5:]=np.nan
labels=pd.DataFrame({'return_4':y,'label_end_return_4':pd.Series(axis,index=axis).shift(-5)},index=axis)
prob=load('online_pg_check_probability',ROOT/'research/S013/experiments/EX084_20261012/src/kernel.py')
gain=load('online_pg_check_gain',ROOT/'research/S013/experiments/EX086_20261012/src/kernel.py')
clock=load('online_pg_check_clock',ROOT/'research/S013/experiments/EX083_20261012/src/kernel.py')
clock_audit=load('online_pg_check_clock_audit',ROOT/'research/S013/experiments/EX083_20261012/src/audit.py')
scores,result=kernel.analyze(features,labels,old,prob,gain,clock)
proof=audit.verify(features,labels,old,scores,result,clock_audit)
proof['real_inputs']=0
proof['experiment_allocation']=0
with Path(__file__).with_suffix('.json').open('x',encoding='utf-8') as stream:
    json.dump(proof,stream,ensure_ascii=False,indent=2,allow_nan=False)
    stream.write('\n')
print(proof)
