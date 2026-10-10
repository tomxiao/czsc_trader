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
    from itertools import product
    new=module(SRC/'strategy_runtime','_ex024_majority','regime_majority_range')
    original=module(SRC/'strategy_runtime','_ex024_original','reentry_confirmed_range')
    configs=plan['configurations']
    assert len(configs)==2 and all(cfg['payload']['parameters']['mechanism']=='REGIME_MAJORITY3' for cfg in configs)
    assert sorted(cfg['payload']['parameters']['bear']['max_hold'] for cfg in configs)==[3,4]
    rng=np.random.default_rng(13)
    dates=pd.bdate_range('2018-01-01',periods=640)
    close=6*np.exp(np.cumsum(rng.normal(.0004,.02,len(dates))))
    bars=pd.DataFrame({'Date':dates,'Open':close,'High':close*1.01,'Low':close*.99,'Close':close,
        'Volume':np.exp(rng.normal(15,.2,len(dates))),'Amount':np.exp(rng.normal(18,.2,len(dates)))})
    sessions=dates[400:]
    counts={'causal_configurations':2,'vote_sequences':0,'controlled_history_calls':0,
            'domain_endpoints':0,'exit_cases':0,'horizon_cases':0,'input_rejections':0}

    def oracle(p,history,frame,selected):
        indexed=frame.set_index('Date')
        raw=indexed.Close/indexed.Close.shift(p['regime_window'])-1
        triples=np.column_stack([raw.shift(lag).reindex(selected).to_numpy() for lag in (2,1,0)])
        assert np.isfinite(triples).all()
        votes=(triples>=p['regime_threshold']).sum(axis=1)
        assert np.array_equal(history.regime_bull_votes,votes)
        assert np.array_equal(history.regime,np.where(votes>=2,'bull','bear'))
        expected_raw=raw.reindex(selected)
        assert np.array_equal(history.raw_momentum,expected_raw)
        assert np.array_equal(history.regime_momentum,expected_raw)
        assert np.array_equal(history.raw_regime,np.where(expected_raw>=p['regime_threshold'],'bull','bear'))
        assert np.isin(history.target_position,(0.,1.)).all()

    for cfg in configs:
        p=deepcopy(cfg['payload']['parameters'])
        impl=new.RegimeMajorityRange(ParameterSet(p))
        full=impl.calculate_history({'daily':bars},sessions)
        oracle(p,full,bars,sessions)
        cutoff=sessions[80]
        prefix=impl.calculate_history({'daily':bars[bars.Date<=cutoff]},sessions[:81])
        pd.testing.assert_frame_equal(full.loc[:cutoff],prefix,check_exact=True)
        changed=bars.copy()
        changed.loc[changed.Date>cutoff,['Open','High','Low','Close','Volume','Amount']]*=1.2
        actual=impl.calculate_history({'daily':changed},sessions)
        pd.testing.assert_frame_equal(full.loc[:cutoff],actual.loc[:cutoff],check_exact=True)
        base={key:value for key,value in p.items() if key!='mechanism'}
        reference=original.ReentryConfirmedRange(ParameterSet(base)).calculate_history({'daily':bars},sessions)
        for column in ('confirmation_score','confirmation_acf','confirmation_turnover','confirmation_volume',
                       'bull_range_position','bear_range_position','regime_momentum'):
            pd.testing.assert_series_equal(full[column],reference[column],check_exact=True)
    base=deepcopy(configs[0]['payload']['parameters'])
    coordinates=(('bull.range_window',21,360),('bull.entry',0.,1.),('bull.exit',0.,1.),('bull.max_hold',1,60),
        ('bear.range_window',21,360),('bear.entry',0.,1.),('bear.exit',0.,1.),('bear.max_hold',1,60),
        ('bear.acf_min',-.6,.5),('regime_window',5,60),('regime_threshold',-.2,.2),
        ('confirmation.lookback',40,120),('confirmation.threshold',-.5,.5))
    for name,lower,upper in coordinates:
        for value in (lower,upper):
            p=deepcopy(base)
            for route in ('bull','bear'):
                p[route]['entry']=0.
                p[route]['exit']=1.
            destination=p
            parts=name.split('.')
            for part in parts[:-1]:
                destination=destination[part]
            destination[parts[-1]]=value
            if (name.endswith('.entry') and value==1.) or (name.endswith('.exit') and value==0.):
                expect_rejected(lambda p=p:new.RegimeMajorityRange(ParameterSet(p)),'entry must be below exit')
            else:
                impl=new.RegimeMajorityRange(ParameterSet(p))
                assert impl._parameters.values==ParameterSet(p).values
                assert impl._warmup>=max(p['regime_window']+3,p['bull']['range_window'],
                                        p['bear']['range_window'],p['confirmation']['lookback']+20)
            counts['domain_endpoints']+=1
    old_helpers=[(owner,owner.components,owner.confirmation_features) for owner in (new,original)]

    def controlled(p,closes,pre=(5.,5.),positions=None,scores=None):
        counts['controlled_history_calls']+=1
        fixture=bars.copy()
        fixture['Close']=5.
        fixture['Open']=5.
        fixture.loc[fixture.Date.isin(dates[398:400]),'Close']=pre
        short=sessions[:len(closes)]
        fixture.loc[fixture.Date.isin(short),'Close']=closes
        fixture['High']=np.maximum(fixture.Close,fixture.Open)*1.01
        fixture['Low']=np.minimum(fixture.Close,fixture.Open)*.99
        positions=[.5]*len(short) if positions is None else positions
        scores=[0.]*len(short) if scores is None else scores
        def features(frame,window):
            index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
            result=pd.DataFrame({'range_position':.5,'acf1':.2,'close':frame.Close.to_numpy(),'momentum20':0.},index=index)
            present=short.intersection(index)
            result.loc[present,'range_position']=pd.Series(positions,index=short).reindex(present)
            return result
        def confirmation(frame,acf,window):
            index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
            result=pd.DataFrame(0.,index=index,columns=['acf','turnover','volume'])
            present=short.intersection(index)
            result.loc[present,:]=pd.Series(scores,index=short).reindex(present).to_numpy()[:,None]
            return result,result
        for owner,_,_ in old_helpers:
            owner.components,owner.confirmation_features=features,confirmation
        history=new.RegimeMajorityRange(ParameterSet(p)).calculate_history({'daily':fixture},short)
        control=original.ReentryConfirmedRange(ParameterSet({key:value for key,value in p.items()
                                                             if key!='mechanism'})).calculate_history({'daily':fixture},short)
        oracle(p,history,fixture,short)
        return history,control,fixture,short

    def assert_original(history,control):
        pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)

    try:
        for bits in product((False,True),repeat=3):
            prices=[5. if bit else 4. for bit in bits]
            history,_,_,_=controlled(base,[prices[-1]],pre=tuple(prices[:2]))
            assert history.regime_bull_votes.iloc[0]==sum(bits)
            assert history.regime.iloc[0]==('bull' if sum(bits)>=2 else 'bear')
            assert history.raw_regime.iloc[0]==('bull' if bits[-1] else 'bear')
            counts['vote_sequences']+=1
        # Two prior bullish states permit effective-bull entry on a raw bearish day.
        history,control,_,_=controlled(base,[4.],pre=(5.,5.))
        assert history.regime.iloc[0]=='bull' and control.regime.iloc[0]=='bear'
        assert history.signal_reason.iloc[0]=='entry'
        # The effective route also governs the original confirmation scope.
        q=deepcopy(base)
        q['confirmation']['scope']='bull'
        history,control,_,_=controlled(q,[4.],pre=(5.,5.),scores=[-.4])
        assert history.signal_reason.iloc[0]=='confirmation_rejected' and control.signal_reason.iloc[0]=='entry'
        history,_,_,_=controlled(q,[6.],pre=(4.,4.),scores=[-.4])
        assert history.regime.iloc[0]=='bear' and history.raw_regime.iloc[0]=='bull'
        assert history.signal_reason.iloc[0]=='entry'
        # A single excursion is ignored; two opposing states switch the effective route.
        history,_,_,_=controlled(base,[6.,4.,4.],pre=(6.,6.))
        assert history.raw_regime.tolist()==['bull','bear','bear']
        assert history.regime.tolist()==['bull','bull','bear']
        assert history.signal_reason.tolist()==['entry','hold','regime']
        history,_,_,_=controlled(base,[4.,6.,6.],pre=(4.,4.))
        assert history.regime.tolist()==['bear','bear','bull']
        assert history.signal_reason.tolist()==['entry','hold','regime']
        # Finite memory rather than a sticky state or arbitrary confirmation reset.
        history,_,_,_=controlled(base,[6.,4.,6.,4.,6.],pre=(6.,6.))
        assert history.regime_bull_votes.tolist()==[3.,2.,2.,1.,2.]
        assert history.regime.tolist()==['bull','bull','bull','bear','bull']
        history,_,_,_=controlled(base,[5.,5.,5.],pre=(5.,5.))
        assert history.raw_momentum.eq(0.).all() and history.regime.eq('bull').all()
        assert history.regime_bull_votes.eq(3.).all()
        q=deepcopy(base)
        q['regime_threshold']=6./5.-1
        history,_,_,_=controlled(q,[6.],pre=(6.,6.))
        assert history.raw_momentum.iloc[0]==q['regime_threshold']
        assert history.regime_bull_votes.iloc[0]==3. and history.regime.iloc[0]=='bull'
        # Full pre-session history is essential even if current raw momentum alone is available.
        warmups=[]
        for window in (5,60):
            q=deepcopy(base)
            q['regime_window']=window
            q['bull']['range_window']=q['bear']['range_window']=21
            q['confirmation']['lookback']=40
            impl=new.RegimeMajorityRange(ParameterSet(q))
            original_impl=original.ReentryConfirmedRange(ParameterSet({key:value for key,value in q.items() if key!='mechanism'}))
            expected=max(original_impl._warmup,window+3)
            requirement=next(item for item in impl.definition.inputs.requirements if item.name=='daily')
            assert impl._warmup==requirement.lookback_sessions==expected
            history,_,fixture,short=controlled(q,[6.],pre=(6.,6.))
            rows=window+3
            complete=fixture.loc[fixture.Date.isin(dates[401-rows:401])]
            pd.testing.assert_frame_equal(impl.calculate_history({'daily':complete},short),history,check_exact=True)
            incomplete=fixture.loc[fixture.Date.isin(dates[402-rows:401])]
            expect_rejected(lambda:impl.calculate_history({'daily':incomplete},short),'missing first raw state')
            warmups.append({'W':window,'declared_warmup':expected,'minimum_vote_rows':rows})
        # W affects the state votes; it remains an active numeric coordinate.
        windows=[]
        for window in (5,60):
            q=deepcopy(base)
            q['regime_window']=window
            history=new.RegimeMajorityRange(ParameterSet(q)).calculate_history({'daily':bars},sessions)
            oracle(q,history,bars,sessions)
            windows.append(history)
        assert not np.array_equal(windows[0].raw_momentum,windows[1].raw_momentum)
        assert not np.array_equal(windows[0].regime,windows[1].regime)
        # Persistent effective/raw routes preserve every original TIME output column.
        for route,price in (('bull',5.),('bear',4.)):
            for horizon in (1,3,4,60):
                q=deepcopy(base)
                q['regime_window']=60
                q['exit_on_regime_change']=False
                q['regime_threshold']=.2 if route=='bear' else 0.
                q[route]['max_hold']=horizon
                history,control,_,_=controlled(q,[price]*(horizon+2),pre=(price,price))
                expected=['entry']+['hold']*(horizon-1)+['time','entry']
                assert history.signal_reason.tolist()==expected
                assert_original(history,control)
                counts['horizon_cases']+=1
            q=deepcopy(base)
            history,control,_,_=controlled(q,[price],pre=(price,price),scores=[-.4])
            assert history.signal_reason.iloc[0]=='confirmation_rejected'
            assert_original(history,control)
        # Higher-priority exits remain immediate despite the three-state regime memory.
        for route,pre,first,last in (('bull',(6.,6.),6.,4.),('bear',(4.,4.),4.,3.8)):
            for label,loss,trail,position in (
                ('loss',.01,.005,.99),('trailing',None,.005,.99),
                ('range',None,None,.99),('time',None,None,.5)):
                q=deepcopy(base)
                q[route].update(max_hold=1,stop_loss=loss,trailing_stop=trail)
                history,control,_,_=controlled(q,[first,last],pre=pre,positions=[.5,position])
                assert history.signal_reason.tolist()==['entry',label]
                pd.testing.assert_frame_equal(history.loc[:,control.columns].drop(columns='regime'),
                    control.drop(columns='regime'),check_exact=True)
                counts['exit_cases']+=1
        # Force all priorities concurrent with an effective regime change on the second day.
        for label,loss,trail,position in (
            ('loss',.05,.03,.99),('trailing',None,.03,.99),
            ('range',None,None,.99),('time',None,None,.5),('regime',None,None,.5)):
            q=deepcopy(base)
            q['bull'].update(max_hold=8 if label=='regime' else 1,stop_loss=loss,trailing_stop=trail)
            history,_,_,_=controlled(q,[4.9,4.],pre=(6.,6.),positions=[.5,position])
            assert history.regime.tolist()==['bull','bear']
            assert history.signal_reason.tolist()==['entry',label]
            counts['exit_cases']+=1
        # Invalid raw prices never turn into bearish votes or substituted history.
        _,_,fixture,short=controlled(base,[6.],pre=(6.,6.))
        for column,value,date in (('Close',float('nan'),short[0]),('Close',float('inf'),dates[398]),
                                   ('Close',0.,dates[399]),('Close',-1.,dates[400-base['regime_window']])):
            invalid=fixture.copy()
            invalid.loc[invalid.Date==date,column]=value
            expect_rejected(lambda invalid=invalid:new.RegimeMajorityRange(ParameterSet(base)).calculate_history(
                {'daily':invalid},short),'invalid raw reference or current close')
            counts['input_rejections']+=1
        for invalid_inputs in ({},{'daily':fixture.drop(columns='Close')},
                               {'daily':fixture[fixture.Date!=short[0]]}):
            expect_rejected(lambda invalid_inputs=invalid_inputs:new.RegimeMajorityRange(ParameterSet(base)).calculate_history(
                invalid_inputs,short),'missing daily/Close/requested session')
            counts['input_rejections']+=1
    finally:
        for owner,features,confirmation in old_helpers:
            owner.components,owner.confirmation_features=features,confirmation
    for mutation in ({'mechanism':'REGIME_MAJORITY5'},{'confirmation':{**base['confirmation'],'enabled':False}}):
        bad=deepcopy(base)
        bad.update(mutation)
        expect_rejected(lambda bad=bad:new.RegimeMajorityRange(ParameterSet(bad)),'invalid category/disabled original confirmation')
    return {'status':'PASS',**counts,'warmups':warmups,
        'oracle':'Independent current and two shifted raw-momentum arrays, finite all three; votes >=2 only',
        'missing_raw':'NaN remains invalid, never a bear vote; W60 needs 63 rows, 62 rejected',
        'original_features':'Exact route ranges/confirmation feature and score histories; TIME columns exact on common-route paths',
        'priority':'loss > trailing > range > time > effective-regime; both original horizons retained',
        'scope':'Pure synthetic signals only, no observed market results or prepare/eval/publish.'}


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
