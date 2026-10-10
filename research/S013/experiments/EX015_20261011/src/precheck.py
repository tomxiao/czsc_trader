"""Causal price-trigger checks and exact public serial/spawn account preflight."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[variable]='1'
from copy import deepcopy
import importlib.util
import sys
import types
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from common import SRC,PROTOCOLS,RUNS,CACHE,SOURCE_CALLS,read,write,request,context,cache_write,file_hash

def module(folder,name,filename):
    package=types.ModuleType(name)
    package.__path__=[str(folder/'strategies')]
    sys.modules[name]=package
    spec=importlib.util.spec_from_file_location(name+'.'+filename,folder/'strategies'/(filename+'.py'))
    loaded=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=loaded
    spec.loader.exec_module(loaded)
    return loaded

def synthetic(plan):
    new=module(SRC/'strategy_runtime','_ex015_mechanism','mechanism_range')
    rng=np.random.default_rng(13)
    dates=pd.bdate_range('2018-01-01',periods=480)
    close=6*np.exp(np.cumsum(rng.normal(.0004,.02,len(dates))))
    bars=pd.DataFrame({'Date':dates,'Open':close,'High':close*1.01,'Low':close*.99,'Close':close,
        'Volume':np.exp(rng.normal(15,.2,len(dates))),'Amount':np.exp(rng.normal(18,.2,len(dates)))})
    sessions=dates[240:]
    for cfg in plan['configurations']:
        impl=new.MechanismRange(ParameterSet(cfg['payload']['parameters']))
        full=impl.calculate_history({'daily':bars},sessions)
        cutoff=sessions[80]
        prefix=impl.calculate_history({'daily':bars[bars.Date<=cutoff]},sessions[:81])
        pd.testing.assert_frame_equal(full.loc[:cutoff],prefix,check_exact=True)
        changed=bars.copy()
        changed.loc[changed.Date>cutoff,['Close','Volume','Amount']]*=1.2
        actual=impl.calculate_history({'daily':changed},sessions)
        pd.testing.assert_frame_equal(full.loc[:cutoff],actual.loc[:cutoff],check_exact=True)
    p=deepcopy(plan['configurations'][0]['payload']['parameters'])
    fixture=bars.copy()
    fixture.Close=6*np.exp(-.001*np.arange(len(fixture)))
    old_components,old_confirmation=new.components,new.confirmation_features
    def features(frame,window):
        index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
        return pd.DataFrame({'range_position':.5,'acf1':.2,'close':frame.Close.to_numpy(),'momentum20':-.02},index=index)
    def confirmation(frame,acf,window):
        index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
        result=pd.DataFrame(0.,index=index,columns=['acf','turnover','volume'])
        result.loc[sessions[5]:,:]=-.4
        return result,result
    new.components,new.confirmation_features=features,confirmation
    try:
        for mode in ('LOW_SCORE','HIGH_SCORE','SMOOTH'):
            q=deepcopy(p)
            q['mechanism']=mode
            history=new.MechanismRange(ParameterSet(q)).calculate_history({'daily':fixture},sessions)
            expected=5 if mode=='LOW_SCORE' else 4
            assert history.signal_reason.iloc[expected]=='time'
            assert history.signal_reason.iloc[1:expected].eq('hold').all()
        raw=old_components(bars,120)
        smooth=raw.acf1.rolling(20).mean()
        new.components,new.confirmation_features=old_components,old_confirmation
        h=new.MechanismRange(ParameterSet(p)).calculate_history({'daily':bars},sessions)
        expected=(h.bear_range_position<=p['bear']['entry']) & (smooth.reindex(sessions)>=p['bear']['acf_min'])
        actual=h.loc[h.regime.eq('bear') & h.signal_reason.isin(['entry','confirmation_rejected']),'confirmation_opportunity']
        assert actual.all()
        assert expected.loc[actual.index].all()
        q=deepcopy(p)
        q['mechanism']='INVALID'
        try:
            new.MechanismRange(ParameterSet(q))
        except ValueError:
            pass
        else:
            raise AssertionError('invalid mechanism accepted')
    finally:
        new.components,new.confirmation_features=old_components,old_confirmation
    return {'status':'PASS','causal_configurations':12,'branches':['LOW requires age then weak score','HIGH opposite direction','SMOOTH exact 20-session ACF mean','invalid mode rejected'],
        'preserved':'bull route, range/regime exits and original score computation unchanged in reviewed source'}


def main():
    assert not (RUNS/'precheck.json').exists()
    plan=read(PROTOCOLS/'plan.json')
    for path,digest in plan['source_files'].items():
        assert file_hash(SRC/path)==digest
    write(RUNS/'synthetic_check.json',synthetic(plan))
    config=plan['configurations'][0]
    bound=context(1).evaluation.prepare(request(config))
    print({'prepared':config['label']},flush=True)
    serial=context(1).evaluation.evaluate(bound)
    cache_write(CACHE/'preflight-serial.pkl.gz',(bound,serial))
    print({'serial':'SUCCEEDED'},flush=True)
    outcome=context(2).evaluation.evaluate_many((bound,))[0]
    assert outcome.status.value=='SUCCEEDED',outcome.error
    parallel=outcome.result
    cache_write(CACHE/'preflight-spawn.pkl.gz',(bound,parallel))
    a,b=serial.runs[0],parallel.runs[0]
    pd.testing.assert_frame_equal(a.signals.decisions,b.signals.decisions,check_exact=True)
    for kind in ('execution','buyhold'):
        left,right=getattr(a,kind),getattr(b,kind)
        if kind=='buyhold':
            left,right=left.execution,right.execution
        for field in ('decisions','orders','fills','account_daily','trades'):
            pd.testing.assert_frame_equal(getattr(left,field),getattr(right,field),check_exact=True)
    assert serial.result_hash==parallel.result_hash and not SOURCE_CALLS
    cache_write(CACHE/'N0.pkl.gz',(bound,serial))
    write(RUNS/'precheck.json',{'status':'PASS','serial_spawn':'EXACT_EQUAL signals and 5 ledgers on both accounts',
        'result_hash':serial.result_hash,'configuration':'N0','account_evaluations':2,'provider_calls':SOURCE_CALLS})
    print({'precheck':'PASS'},flush=True)

if __name__=='__main__':
    main()
