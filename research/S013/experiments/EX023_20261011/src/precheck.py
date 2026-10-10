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

def expect_rejected(action, label):
    try:
        action()
    except ValueError:
        return
    raise AssertionError('Invalid input accepted: ' + label)


def synthetic(plan):
    new=module(SRC/'strategy_runtime','_ex023_mechanism','mechanism_range')
    original=module(SRC/'original/strategy_runtime','_ex023_original','reentry_confirmed_range')
    configs=plan['controls']+plan['configurations']
    assert len(configs)==4 and len(plan['configurations'])==2
    assert [c['payload']['parameters']['bull']['max_hold'] for c in configs]==[8,8,4,4]
    assert all(c['payload']['parameters']['bear']['max_hold']==4 for c in configs)
    assert all(c['payload']['parameters']['bear']['acf_min']==.1 for c in configs)
    rng=np.random.default_rng(13)
    dates=pd.bdate_range('2018-01-01',periods=480)
    close=6*np.exp(np.cumsum(rng.normal(.0004,.02,len(dates))))
    opens=close*np.exp(rng.normal(0.,.01,len(dates)))
    bars=pd.DataFrame({'Date':dates,'Open':opens,'High':np.maximum(close,opens)*1.01,
        'Low':np.minimum(close,opens)*.99,'Close':close,
        'Volume':np.exp(rng.normal(15,.2,len(dates))),'Amount':np.exp(rng.normal(18,.2,len(dates)))})
    sessions=dates[240:]
    def implement(parameters):
        return (new.MechanismRange if 'mechanism' in parameters else original.ReentryConfirmedRange)(ParameterSet(parameters))
    for cfg in configs:
        q=deepcopy(cfg['payload']['parameters'])
        impl=implement(q)
        full=impl.calculate_history({'daily':bars},sessions)
        cutoff=sessions[80]
        prefix=impl.calculate_history({'daily':bars[bars.Date<=cutoff]},sessions[:81])
        pd.testing.assert_frame_equal(full.loc[:cutoff],prefix,check_exact=True)
        changed=bars.copy()
        changed.loc[changed.Date>cutoff,['Open','High','Low','Close','Volume','Amount']]*=1.2
        pd.testing.assert_frame_equal(full.loc[:cutoff],impl.calculate_history({'daily':changed},sessions).loc[:cutoff],check_exact=True)
        if 'mechanism' in q:
            base={key:value for key,value in q.items() if key!='mechanism'}
            reference=implement(base).calculate_history({'daily':bars},sessions)
            for column in ('confirmation_score','regime','regime_momentum'):
                pd.testing.assert_series_equal(full[column],reference[column],check_exact=True)
            idx=bars.set_index('Date')
            momentum=idx.Close/idx.Close.shift(q['regime_window'])-1
            prev=np.where(momentum.shift(1).reindex(sessions)>=q['regime_threshold'],'bull','bear')
            assert np.array_equal(full.previous_regime,prev)
            applies=full.regime.eq('bull') & (prev=='bear')
            direction=idx.Close.reindex(sessions)>idx.Open.reindex(sessions)
            assert np.array_equal(full.entry_direction_gate_applies,applies)
            assert np.array_equal(full.entry_direction_up,direction)
            opportunity=full.confirmation_opportunity.astype(bool)
            assert np.array_equal(full.signal_reason.eq('entry'),opportunity & (~applies | direction) & full.confirmation_pass)
    old_helpers=[(owner,owner.components,owner.confirmation_features) for owner in (new,original)]
    counts=0
    try:
        for horizon in (1,4,8,60):
            short=dates[240:240+2*horizon+3]
            fixture=bars.copy()
            fixture['Close']=5.
            fixture['Open']=4.9
            def features(frame,window):
                index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
                return pd.DataFrame({'range_position':.5,'acf1':.2,'close':frame.Close.to_numpy(),'momentum20':0.},index=index)
            def confirmation(frame,acf,window):
                index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
                result=pd.DataFrame(0.,index=index,columns=['acf','turnover','volume'])
                return result,result
            for owner,_,_ in old_helpers:
                owner.components,owner.confirmation_features=features,confirmation
            for cfg in configs:
                q=deepcopy(cfg['payload']['parameters'])
                q['bull']['max_hold']=horizon
                history=implement(q).calculate_history({'daily':fixture},short)
                expected=['entry']+['hold']*(horizon-1)+['time']+['entry']+['hold']*(horizon-1)+['time']+['entry']
                assert history.signal_reason.tolist()==expected
                assert history.target_position.tolist()==[0. if reason=='time' else 1. for reason in expected]
                if 'mechanism' in q:
                    assert not history.entry_direction_gate_applies.any()
                    reference=implement({k:v for k,v in q.items() if k!='mechanism'}).calculate_history({'daily':fixture},short)
                    for column in reference:
                        pd.testing.assert_series_equal(history[column],reference[column],check_exact=True)
                counts+=1
            # Bear horizon remains four regardless of bull H, including H1/H60.
            fixture['Close']=4.9
            fixture.loc[fixture.Date<short[0],'Close']=5.
            for cfg in configs:
                q=deepcopy(cfg['payload']['parameters'])
                q['bull']['max_hold']=horizon
                history=implement(q).calculate_history({'daily':fixture},sessions[:6])
                assert history.regime.eq('bear').all()
                assert history.signal_reason.tolist()==['entry','hold','hold','hold','time','entry']
                counts+=1
    finally:
        for owner,features,confirmation in old_helpers:
            owner.components,owner.confirmation_features=features,confirmation
    for time_label,body_label in (('B0-TIME','B0-BODY'),('N0','N1')):
        t=next(c for c in configs if c['label']==time_label)['payload']['parameters']
        b=next(c for c in configs if c['label']==body_label)['payload']['parameters']
        assert t=={k:v for k,v in b.items() if k!='mechanism'}
    return {'status':'PASS','causal_histories':4,'controlled_histories':counts,
        'dose':'Only bull H8to4 changed, all other parameters matched; bear H4 remains.',
        'boundaries':'Bull H1/H4/H8/H60 exact TIME; stablebull TIME/BODY source columns equal; bear H4 unchanged.',
        'source':'Original TIME and EX020 BODY sources byte-identical to preserved controls.',
        'scope':'Pure synthetic, prefix/future mutation and dose checks; no real metrics.'}


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
