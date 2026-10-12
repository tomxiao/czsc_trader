"""Before-data synthetic integration of independent EX089 audit."""
from pathlib import Path
import importlib.util
import json
import numpy as np
import pandas as pd
import kernel
import audit

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


axis=pd.bdate_range('2020-09-01',periods=400).as_unit('ns')
rng=np.random.default_rng(79)
scores=pd.DataFrame(rng.normal(.004,.002,(400,2)),index=axis,columns=kernel.INPUTS)
scores.loc[axis.year==2020]=np.nan
scores.iloc[115,1]=np.nan
y=rng.normal(.002,.015,400)
y[-5:]=np.nan
labels=pd.DataFrame({'return_4':y,'label_end_return_4':pd.Series(axis,index=axis).shift(-5)},index=axis)
primary_clock=module('calibration_synth_primary_clock',ROOT/'research/S013/experiments/EX083_20261012/src/kernel.py')
independent_clock=module('calibration_synth_independent_clock',ROOT/'research/S013/experiments/EX083_20261012/src/audit.py')
states,signals,report=kernel.analyze(scores,labels,primary_clock)
proof=audit.verify(scores,labels,states,signals,report,independent_clock)
proof['real_inputs']=0
proof['experiment_allocation']=0
with Path(__file__).with_suffix('.json').open('x',encoding='utf-8') as stream:
    json.dump(proof,stream,ensure_ascii=False,indent=2,allow_nan=False)
    stream.write('\n')
print(proof)
