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
    new=module(SRC/'strategy_runtime','_ex021_mechanism','mechanism_range')
    original=module(SRC/'strategy_runtime','_ex021_original','reentry_confirmed_range')
    configs=plan['configurations']
    assert {c['payload']['parameters']['mechanism'] for c in configs}=={'LAG3_MEAN','LAG5_MEAN'}
    rng=np.random.default_rng(13)
    dates=pd.bdate_range('2018-01-01',periods=480)
    close=6*np.exp(np.cumsum(rng.normal(.0004,.02,len(dates))))
    bars=pd.DataFrame({'Date':dates,'Open':close,'High':close*1.01,'Low':close*.99,'Close':close,
        'Volume':np.exp(rng.normal(15,.2,len(dates))),'Amount':np.exp(rng.normal(18,.2,len(dates)))})
    sessions=dates[240:]
    counts={'causal_configurations':len(configs),'active_window_cases':0,'controlled_history_calls':0,
            'boundary_cases':0,'spike_cases':0,'exit_cases':0,'price_rejections':0}

    def oracle(p,history,frame,selected):
        index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
        prices=pd.Series(frame.Close.to_numpy(),index=index)
        k=1 if p['mechanism']=='LAG3_MEAN' else 2
        refs=np.column_stack([prices.shift(lag).reindex(selected).to_numpy()
                              for lag in range(p['regime_window']-k,p['regime_window']+k+1)])
        expected=refs.mean(axis=1)
        np.testing.assert_allclose(history.regime_reference_mean.to_numpy(),expected,rtol=1e-14,atol=1e-12)
        np.testing.assert_allclose(history.regime_momentum.to_numpy(),prices.reindex(selected)/expected-1,
                                   rtol=1e-14,atol=1e-12)
        assert history.regime_reference_count.eq(2*k+1).all() and history.regime_kernel_halfwidth.eq(k).all()
        assert p['regime_window']-k>=3
        assert np.isin(history.target_position.to_numpy(),(0.,1.)).all()
        assert np.array_equal(history.regime.to_numpy(),
            np.where(history.regime_momentum.to_numpy()>=p['regime_threshold'],'bull','bear'))

    for cfg in configs:
        p=deepcopy(cfg['payload']['parameters'])
        impl=new.MechanismRange(ParameterSet(p))
        full=impl.calculate_history({'daily':bars},sessions)
        oracle(p,full,bars,sessions)
        cutoff=sessions[80]
        prefix=impl.calculate_history({'daily':bars[bars.Date<=cutoff]},sessions[:81])
        pd.testing.assert_frame_equal(full.loc[:cutoff],prefix,check_exact=True)
        changed=bars.copy()
        changed.loc[changed.Date>cutoff,['Open','High','Low','Close','Volume','Amount']]*=1.2
        actual=impl.calculate_history({'daily':changed},sessions)
        pd.testing.assert_frame_equal(full.loc[:cutoff],actual.loc[:cutoff],check_exact=True)
        stripped={key:value for key,value in p.items() if key!='mechanism'}
        raw=original.ReentryConfirmedRange(ParameterSet(stripped)).calculate_history({'daily':bars},sessions)
        for column in ('confirmation_score','confirmation_acf','confirmation_turnover','confirmation_volume',
                       'bull_range_position','bear_range_position'):
            pd.testing.assert_series_equal(full[column],raw[column],check_exact=True)
    base=deepcopy(configs[0]['payload']['parameters'])
    for mode in ('LAG3_MEAN','LAG5_MEAN'):
        outputs=[]
        for window in (5,60):
            p=deepcopy(base)
            p.update(mechanism=mode,regime_window=window)
            history=new.MechanismRange(ParameterSet(p)).calculate_history({'daily':bars},sessions)
            oracle(p,history,bars,sessions)
            outputs.append(history)
            counts['active_window_cases']+=1
        assert not np.array_equal(outputs[0].regime_reference_mean,outputs[1].regime_reference_mean)
        assert not np.array_equal(outputs[0].regime_momentum,outputs[1].regime_momentum)
    old_helpers=[(owner,owner.components,owner.confirmation_features) for owner in (new,original)]

    def controlled(p,closes,positions=None,scores=None):
        counts['controlled_history_calls']+=1
        fixture=bars.copy()
        fixture['Close']=5.
        fixture['Open']=5.
        fixture.loc[fixture.Date==dates[239],'Close']=6.
        short=sessions[:len(closes)]
        fixture.loc[fixture.Date.isin(short),'Close']=closes
        fixture['High']=np.maximum(fixture.Close,fixture.Open)*1.01
        fixture['Low']=np.minimum(fixture.Close,fixture.Open)*.99
        positions=[.5]*len(short) if positions is None else positions
        scores=[0.]*len(short) if scores is None else scores
        def features(frame,window):
            index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
            result=pd.DataFrame({'range_position':.5,'acf1':.2,'close':frame.Close.to_numpy(),'momentum20':0.},index=index)
            result.loc[short,'range_position']=positions
            return result
        def confirmation(frame,acf,window):
            index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
            result=pd.DataFrame(0.,index=index,columns=['acf','turnover','volume'])
            result.loc[short,:]=np.asarray(scores)[:,None]
            return result,result
        for owner,_,_ in old_helpers:
            owner.components,owner.confirmation_features=features,confirmation
        history=new.MechanismRange(ParameterSet(p)).calculate_history({'daily':fixture},short)
        control=original.ReentryConfirmedRange(ParameterSet({key:value for key,value in p.items()
                                                             if key!='mechanism'})).calculate_history({'daily':fixture},short)
        return history,control,fixture,short

    warmups=[]
    try:
        for mode in ('LAG3_MEAN','LAG5_MEAN'):
            p=deepcopy(base)
            p['mechanism']=mode
            k=1 if mode=='LAG3_MEAN' else 2
            count=2*k+1
            for window in (5,60):
                q=deepcopy(p)
                q['regime_window']=window
                q['bull']['range_window']=q['bear']['range_window']=21
                q['confirmation']['lookback']=40
                impl=new.MechanismRange(ParameterSet(q))
                parent=original.ReentryConfirmedRange(ParameterSet({key:value for key,value in q.items() if key!='mechanism'}))
                expected=max(parent._warmup,window+k+1)
                requirement=next(item for item in impl.definition.inputs.requirements if item.name=='daily')
                assert impl._warmup==requirement.lookback_sessions==expected
                history,_,fixture,short=controlled(q,[6.01])
                rows=window+k+1
                complete=fixture.loc[fixture.Date.isin(dates[240-rows+1:241])]
                pd.testing.assert_frame_equal(impl.calculate_history({'daily':complete},short),history,check_exact=True)
                partial=fixture.loc[fixture.Date.isin(dates[240-rows+2:241])]
                expect_rejected(lambda partial=partial:impl.calculate_history({'daily':partial},short),'incomplete kernel')
                warmups.append({'mechanism':mode,'W':window,'declared_warmup':expected,'minimum_reference_rows':rows})
                counts['boundary_cases']+=1
            history,control,fixture,short=controlled(p,[6.01])
            assert history.regime_reference_mean.iloc[0]==5.
            pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
            for lag in range(p['regime_window']-k,p['regime_window']+k+1):
                spike=fixture.copy()
                date=dates[240-lag]
                spike.loc[spike.Date==date,'Close']=8.
                spike.loc[spike.Date==date,'High']=8.08
                actual=new.MechanismRange(ParameterSet(p)).calculate_history({'daily':spike},short)
                np.testing.assert_allclose(actual.regime_reference_mean.iloc[0],5.+3./count,rtol=0,atol=1e-12)
                oracle(p,actual,spike,short)
                counts['spike_cases']+=1
            current=fixture.copy()
            current.loc[current.Date==short[0],'Close']=6.41
            current.loc[current.Date==short[0],'High']=6.48
            actual=new.MechanismRange(ParameterSet(p)).calculate_history({'daily':current},short)
            assert actual.regime_reference_mean.iloc[0]==history.regime_reference_mean.iloc[0]
            np.testing.assert_allclose(actual.regime_momentum.iloc[0],6.41/5.-1,rtol=0,atol=1e-12)
            for price,threshold in ((5.,0.),(6.,6./5.-1)):
                q=deepcopy(p)
                q['regime_threshold']=threshold
                history,control,_,_=controlled(q,[price])
                assert history.regime_momentum.iloc[0]==threshold and history.regime.iloc[0]=='bull'
                assert history.signal_reason.iloc[0]=='entry'
                pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
            history,control,_,_=controlled(p,[6.01],scores=[-.4])
            assert history.signal_reason.iloc[0]=='confirmation_rejected'
            pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
            for closes,expected in (([4.99,4.98],['entry','hold']),([4.99,6.01],['entry','regime']),
                                    ([6.01,6.],['entry','hold'])):
                history,control,_,_=controlled(p,closes)
                assert history.signal_reason.tolist()==expected
                pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
            q=deepcopy(p)
            q['bear']['max_hold']=1
            history,control,_,_=controlled(q,[4.99,4.98])
            assert history.signal_reason.tolist()==['entry','time']
            pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
            q=deepcopy(p)
            q['bull']['max_hold']=1
            exits=[('time',q,[6.01,6.],[.5,.5]),('range',p,[6.01,6.],[.5,.99]),('regime',p,[6.01,4.9],[.5,.5])]
            q=deepcopy(p)
            q['bull']['stop_loss']=.05
            exits.append(('loss',q,[6.01,5.5],[.5,.5]))
            q=deepcopy(p)
            q['bull']['trailing_stop']=.03
            exits.append(('trailing',q,[6.01,6.4,6.1],[.5,.5,.5]))
            for label,loss,trail,position in (('loss',.05,.03,.99),('trailing',.05,.03,.99),
                                            ('range',None,None,.99),('time',None,None,.5)):
                q=deepcopy(p)
                q['regime_threshold']=.19
                q['bull'].update(max_hold=1,stop_loss=loss,trailing_stop=trail)
                exits.append((label,q,[6.01,4.9 if label=='loss' else 5.8],[.5,position]))
            for label,q,closes,positions in exits:
                history,control,_,_=controlled(q,closes,positions=positions)
                assert history.signal_reason.iloc[0]=='entry' and history.signal_reason.iloc[-1]==label
                pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
                counts['exit_cases']+=1
            _,_,fixture,short=controlled(p,[6.01])
            for value in (float('nan'),float('inf'),0.,-1.):
                bad=fixture.copy()
                bad.loc[bad.Date==short[0],'Close']=value
                expect_rejected(lambda bad=bad:new.MechanismRange(ParameterSet(p)).calculate_history({'daily':bad},short),'current price')
                counts['price_rejections']+=1
            expect_rejected(lambda:new.MechanismRange(ParameterSet(p)).calculate_history(
                {'daily':fixture.drop(columns='Close')},short),'missing Close')
            counts['price_rejections']+=1
            bad=fixture.copy()
            bad.loc[bad.Date==dates[240-p['regime_window']],'Close']=-1.
            expect_rejected(lambda:new.MechanismRange(ParameterSet(p)).calculate_history({'daily':bad},short),'negative lagged price')
            counts['price_rejections']+=1
    finally:
        for owner,features,confirmation in old_helpers:
            owner.components,owner.confirmation_features=features,confirmation
    for mode in ('INVALID','LAG4_MEAN'):
        bad=deepcopy(base)
        bad['mechanism']=mode
        expect_rejected(lambda bad=bad:new.MechanismRange(ParameterSet(bad)),'invalid fixed category')
    bad=deepcopy(base)
    bad['confirmation']['enabled']=False
    expect_rejected(lambda:new.MechanismRange(ParameterSet(bad)),'disabled original confirmation')
    bad=deepcopy(base)
    bad['regime_window']=4
    expect_rejected(lambda:new.MechanismRange(ParameterSet(bad)),'illegal W')
    return {'status':'PASS',**counts,'boundary_warmups':warmups,
        'reference_oracle':'Independent individual shifted Close arithmetic mean; no current/future reference',
        'spike_weight':'1/3 or 1/5 within 1e-12 arithmetic tolerance',
        'current_close':'Unsmoothed numerator; unchanged reference after current Close mutation',
        'confirmation_features':'EXACT_EQUAL random original histories',
        'controlled_original_columns':'EXACT_EQUAL TIME columns when reference prices agree',
        'exit_priority':'loss > trailing > range > time > regime; bear and bull paths',
        'invalid_fixed_categories_and_window_rejected':True,
        'scope':'Synthetic signals only; no account evaluation/publication or observed market outcomes.'}


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
