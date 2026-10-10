"""Synthetic branch proof and one public serial/spawn account equivalence."""
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

def module(folder, name):
    package=types.ModuleType(name)
    package.__path__=[str(folder/'strategies')]
    sys.modules[name]=package
    spec=importlib.util.spec_from_file_location(name+'.reentry_confirmed_range',folder/'strategies/reentry_confirmed_range.py')
    loaded=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=loaded
    spec.loader.exec_module(loaded)
    return loaded

def synthetic(plan):
    old=module(SRC/'original/strategy_runtime','_s013_ex013_original')
    new=module(SRC/'strategy_runtime','_s013_ex013_nullable')
    rng=np.random.default_rng(13)
    dates=pd.bdate_range('2018-01-01',periods=450)
    close=6*np.exp(np.cumsum(rng.normal(.0004,.02,len(dates))))
    bars=pd.DataFrame({'Date':dates,'Open':close,'High':close*1.01,'Low':close*.99,
        'Close':close,'Volume':np.exp(rng.normal(15,.2,len(dates))),
        'Amount':np.exp(rng.normal(18,.2,len(dates)))})
    sessions=dates[230:]
    for config in plan['controls']:
        params=ParameterSet(config['payload']['parameters'])
        original=old.ReentryConfirmedRange(params).calculate_history({'daily':bars},sessions)
        modified=new.ReentryConfirmedRange(params).calculate_history({'daily':bars},sessions)
        pd.testing.assert_frame_equal(original,modified,check_exact=True)
    for config in plan['configurations']:
        loaded=old if config['source_directory'].startswith('original') else new
        impl=loaded.ReentryConfirmedRange(ParameterSet(config['payload']['parameters']))
        full=impl.calculate_history({'daily':bars},sessions)
        cutoff=sessions[80]
        prefix=impl.calculate_history({'daily':bars[bars.Date<=cutoff]},sessions[:81])
        pd.testing.assert_frame_equal(full.loc[:cutoff],prefix,check_exact=True)
        future=bars.copy()
        future.loc[future.Date>cutoff,['Close','Volume','Amount']]*=1.2
        altered=impl.calculate_history({'daily':future},sessions)
        pd.testing.assert_frame_equal(full.loc[:cutoff],altered.loc[:cutoff],check_exact=True)
        assert not full.signal_reason.eq('cooldown').any()
    p=deepcopy(plan['controls'][0]['payload']['parameters'])
    p['bear']['max_hold']=None
    for invalid in (True,0,-1,61,3.0,'off'):
        bad=deepcopy(p)
        bad['bear']['max_hold']=invalid
        try:
            new.ReentryConfirmedRange(ParameterSet(bad))
        except (ValueError,TypeError):
            pass
        else:
            raise AssertionError('invalid nullable timer accepted')
    bad=deepcopy(p)
    bad['bull']['max_hold']=None
    try:
        new.ReentryConfirmedRange(ParameterSet(bad))
    except ValueError:
        pass
    else:
        raise AssertionError('bull timer unexpectedly nullable')
    # A known down-state path, fixed eligible range and passing confirmation.
    # The feature patch only tests branch semantics; it is never used in accounts.
    original_component,original_confirmation=new.components,new.confirmation_features
    fixture=bars.copy()
    fixture.Close=6*np.exp(-.001*np.arange(len(fixture)))
    def features(frame, window):
        index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
        return pd.DataFrame({'range_position':.5,'acf1':.2,'close':frame.Close.to_numpy(),
            'momentum20':-.02},index=index)
    def confirmation(frame, acf, window):
        index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
        values=pd.DataFrame(0.,index=index,columns=['acf','turnover','volume'])
        return values,values
    new.components,new.confirmation_features=features,confirmation
    try:
        frame=new.ReentryConfirmedRange(ParameterSet(p)).calculate_history({'daily':fixture},sessions)
        assert frame.signal_reason.iloc[0]=='entry'
        assert frame.signal_reason.iloc[1:].eq('hold').all()
        timed=deepcopy(p)
        timed['bear']['max_hold']=4
        bounded=new.ReentryConfirmedRange(ParameterSet(timed)).calculate_history({'daily':fixture},sessions)
        assert bounded.signal_reason.iloc[4]=='time'
        def range_exit(frame, window):
            result=features(frame,window)
            result.loc[sessions[6],'range_position']=1.
            return result
        new.components=range_exit
        ranged=new.ReentryConfirmedRange(ParameterSet(p)).calculate_history({'daily':fixture},sessions)
        assert ranged.signal_reason.iloc[6]=='range'
        new.components=features
        switch=fixture.copy()
        switch.loc[switch.Date==sessions[8],'Close']*=1.2
        switched=new.ReentryConfirmedRange(ParameterSet(p)).calculate_history({'daily':switch},sessions)
        assert switched.signal_reason.iloc[8]=='regime'
    finally:
        new.components,new.confirmation_features=original_component,original_confirmation
    return {'status':'PASS','original_integer_timer_exact_equivalence':3,
        'new_causal_prefix_and_future_invariance':5,
        'branches':['nullable bear timer holds beyond 60 sessions without time exit',
            'integer 4 timer exits at age 4','range exit still works','regime exit still works',
            'invalid timer values rejected','bull null rejected','no fixed cooldown']}

def main():
    assert not (RUNS/'precheck.json').exists()
    plan=read(PROTOCOLS/'plan.json')
    for name,digest in plan['source_files'].items():
        assert file_hash(SRC/name)==digest
    proof=synthetic(plan)
    write(RUNS/'synthetic_check.json',proof)
    config=next(c for c in plan['configurations'] if c['label']=='N1')
    ctx=context(1)
    bound=ctx.evaluation.prepare(request(config))
    print({'public_prepare':'PASS','configuration':'N1'},flush=True)
    serial=ctx.evaluation.evaluate(bound)
    cache_write(CACHE/'preflight-serial.pkl.gz',(bound,serial))
    print({'serial_account':'SUCCEEDED'},flush=True)
    outcome=context(2).evaluation.evaluate_many((bound,))[0]
    assert outcome.status.value=='SUCCEEDED',outcome.error
    parallel=outcome.result
    cache_write(CACHE/'preflight-spawn.pkl.gz',(bound,parallel))
    left,right=serial.runs[0],parallel.runs[0]
    pd.testing.assert_frame_equal(left.signals.decisions,right.signals.decisions,check_exact=True)
    for kind in ('execution','buyhold'):
        a,b=getattr(left,kind),getattr(right,kind)
        if kind=='buyhold':
            a,b=a.execution,b.execution
        for field in ('decisions','orders','fills','account_daily','trades'):
            pd.testing.assert_frame_equal(getattr(a,field),getattr(b,field),check_exact=True)
    assert serial.result_hash==parallel.result_hash
    assert not SOURCE_CALLS
    cache_write(CACHE/'N1.pkl.gz',(bound,serial))
    write(RUNS/'precheck.json',{'status':'PASS','synthetic':proof,
        'serial_spawn_equivalence':'EXACT_EQUAL signals and five strategy and benchmark ledgers',
        'configuration':'N1','account_evaluations':2,'provider_calls':SOURCE_CALLS,
        'result_hash':serial.result_hash})
    print({'precheck':'PASS','serial_spawn':'EXACT_EQUAL'},flush=True)

if __name__=='__main__':
    main()
