"""Prospective synthetic causal model checks, zero real data."""
from pathlib import Path
from hashlib import sha256
import importlib.util
import json
import sys
import numpy as np
import pandas as pd

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


def main():
    k=load('co_down_synthetic_kernel',WORK/'kernel.py')
    num=load('co_down_synthetic_numerical',ROOT/'research/S013/experiments/EX075_20261011/src/statistics_draft_v2.py')
    clock=load('co_down_synthetic_clock',ROOT/'research/S013/experiments/EX083_20261012/src/kernel.py')
    rng=np.random.default_rng(48)
    axis=pd.bdate_range('2020-01-02',periods=600).as_unit('ns')
    features=pd.DataFrame(rng.normal(size=(600,28)),index=axis,columns=[*k.CONTROLS,'X'])
    labels=pd.DataFrame({'return_4':-.01*features.X+.02*rng.normal(size=600),
        'label_end_return_4':pd.Series(axis,index=axis).shift(-5)},index=axis)
    labels.iloc[-5:,0]=np.nan
    scores,traces=k.forecasts(features,labels,num)
    assert scores.loc[axis.year==2020].isna().all().all()
    assert len(traces)==6 and sum(row['reason'] is None for row in traces)==2
    assert scores.iloc[-5:].notna().all().all()
    for row in traces:
        if row['reason'] is None:
            first=pd.Timestamp(row['first_test'])
            assert all(labels.label_end_return_4.iloc[i]<first for i in row['train_positions'])
    altered=labels.copy()
    altered.loc[(axis.year==2022)&labels.return_4.notna(),'return_4']=100
    changed,_=k.forecasts(features,altered,num)
    pd.testing.assert_frame_equal(scores,changed,check_exact=True)
    augmented=features.copy()
    augmented.loc[axis.year==2022,'X']*=100
    _,newtrace=k.forecasts(augmented,labels,num)
    assert [row['models'] for row in newtrace]==[row['models'] for row in traces]
    out=k.analyze(features,labels,scores,traces,num,clock)
    assert out['new_models']==4 and len(out['schedules'])==3
    assert out['fixed_hypothesis']=='negative' and len(k.CONTROLS)==27
    assert all(len(clocks)==6 for clocks in out['schedules'].values())
    assert len(out['bootstrap']['records'])==500
    assert all(row['valid_replicates']==500 for row in out['bootstrap']['summary'].values())
    assert k.quantities(np.array([0.]),np.array([[0.,0.,0.]]),np.array([0]))['augmented_positive_mean'] is None
    refusals=0
    for bad in (features.iloc[::-1],features.drop(columns=['X']),features.rename(columns={'X':'return_4'})):
        try:
            k.forecasts(bad,labels,num)
        except ValueError:
            refusals+=1
        else:
            raise AssertionError('Invalid frame accepted')
    output={'status':'PASS','real_inputs':0,'checks':8,'refusals':refusals,'new_accounts':0,
        'source_sha256':sha256((WORK/'kernel.py').read_bytes()).hexdigest(),
        'fixed_hypothesis':'negative','checks_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest()}
    with (WORK/'kernel_checks.json').open('x',encoding='utf-8') as stream:
        json.dump(output,stream,ensure_ascii=False,indent=2)
    print(output,flush=True)


if __name__=='__main__':
    main()
