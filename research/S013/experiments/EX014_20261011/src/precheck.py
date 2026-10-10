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
    old=module(SRC/'original/strategy_runtime','_ex014_original','reentry_confirmed_range')
    new=module(SRC/'strategy_runtime','_ex014_price','price_confirmed_exit')
    rng=np.random.default_rng(13)
    dates=pd.bdate_range('2018-01-01',periods=450)
    close=6*np.exp(np.cumsum(rng.normal(.0004,.02,len(dates))))
    bars=pd.DataFrame({'Date':dates,'Open':close,'High':close*1.01,'Low':close*.99,'Close':close,
        'Volume':np.exp(rng.normal(15,.2,len(dates))),'Amount':np.exp(rng.normal(18,.2,len(dates)))})
    sessions=dates[230:]
    for config in plan['configurations']:
        cls=old.ReentryConfirmedRange if config['mechanism']=='TIME' else new.PriceConfirmedExitRange
        impl=cls(ParameterSet(config['payload']['parameters']))
        full=impl.calculate_history({'daily':bars},sessions)
        cutoff=sessions[80]
        prefix=impl.calculate_history({'daily':bars[bars.Date<=cutoff]},sessions[:81])
        pd.testing.assert_frame_equal(full.loc[:cutoff],prefix,check_exact=True)
        future=bars.copy()
        future.loc[future.Date>cutoff,['Close','Volume','Amount']]*=1.2
        changed=impl.calculate_history({'daily':future},sessions)
        pd.testing.assert_frame_equal(full.loc[:cutoff],changed.loc[:cutoff],check_exact=True)
        assert not full.signal_reason.eq('cooldown').any()
    p=deepcopy(plan['configurations'][0]['payload']['parameters'])
    p['bear']['max_hold']=4
    for invalid in (0,2,True,1.0):
        bad=deepcopy(p)
        bad['exit_confirmation']['direction']=invalid
        try:
            new.PriceConfirmedExitRange(ParameterSet(bad))
        except (ValueError,TypeError):
            pass
        else:
            raise AssertionError('invalid direction accepted')
    fixture=bars.copy()
    fixture.Close=6*np.exp(-.001*np.arange(len(fixture)))
    original_components,original_confirmation=new.components,new.confirmation_features
    def features(frame,window):
        index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
        return pd.DataFrame({'range_position':.5,'acf1':.2,'close':frame.Close.to_numpy(),'momentum20':-.02},index=index)
    def confirmation(frame,acf,window):
        index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
        result=pd.DataFrame(0.,index=index,columns=['acf','turnover','volume'])
        return result,result
    new.components,new.confirmation_features=features,confirmation
    try:
        down=deepcopy(p)
        down['exit_confirmation']['direction']=-1
        frame=new.PriceConfirmedExitRange(ParameterSet(down)).calculate_history({'daily':fixture},sessions)
        assert frame.signal_reason.iloc[4]=='time' and frame.signal_reason.iloc[1:4].eq('hold').all()
        up=deepcopy(p)
        up['exit_confirmation']['direction']=1
        frame=new.PriceConfirmedExitRange(ParameterSet(up)).calculate_history({'daily':fixture},sessions)
        assert frame.signal_reason.iloc[1:].eq('hold').all()
        equal=fixture.copy()
        equal.loc[equal.Date==sessions[4],'Close']=float(equal.loc[equal.Date==sessions[3],'Close'].iloc[0])
        for direction in (-1,1):
            params=deepcopy(p)
            params['exit_confirmation']['direction']=direction
            frame=new.PriceConfirmedExitRange(ParameterSet(params)).calculate_history({'daily':equal},sessions)
            assert frame.signal_reason.iloc[4]=='time'
        def range_exit(frame,window):
            result=features(frame,window)
            result.loc[sessions[6],'range_position']=1.
            return result
        new.components=range_exit
        frame=new.PriceConfirmedExitRange(ParameterSet(up)).calculate_history({'daily':fixture},sessions)
        assert frame.signal_reason.iloc[6]=='range'
        new.components=features
        switch=fixture.copy()
        switch.loc[switch.Date==sessions[2],'Close']*=1.2
        frame=new.PriceConfirmedExitRange(ParameterSet(up)).calculate_history({'daily':switch},sessions)
        assert frame.signal_reason.iloc[2]=='regime'
        # Bull route is unchanged even with a conflicting price direction.
        bull=fixture.copy()
        bull.Close=6*np.exp(.001*np.arange(len(bull)))
        frame=new.PriceConfirmedExitRange(ParameterSet(down)).calculate_history({'daily':bull},sessions)
        assert frame.signal_reason.iloc[8]=='time'
    finally:
        new.components,new.confirmation_features=original_components,original_confirmation
    return {'status':'PASS','causal_prefix_and_future_invariance':9,
        'branches':['bear timer cannot exit before age H','down/up direction differs','equality passes both',
            'range and regime exits preserved','bull timer unchanged','invalid direction rejected','zero cooldown'],
        'price_basis':'same HFQ daily close, previous actual trading session, no future close'}

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
