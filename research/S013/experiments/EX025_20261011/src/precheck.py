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
    new=module(SRC/'strategy_runtime','_ex025_mechanism','mechanism_range')
    original=module(SRC/'strategy_runtime','_ex025_original','reentry_confirmed_range')
    configs=plan['configurations']
    modes=('BULL_ANCHOR_LOSS','NEW_BULL_BODY_ANCHOR_LOSS')
    assert len(configs)==2 and {cfg['payload']['parameters']['mechanism'] for cfg in configs}==set(modes)
    rng=np.random.default_rng(13)
    dates=pd.bdate_range('2018-01-01',periods=480)
    close=6*np.exp(np.cumsum(rng.normal(.0004,.02,len(dates))))
    opens=close*np.exp(rng.normal(0.,.01,len(dates)))
    bars=pd.DataFrame({'Date':dates,'Open':opens,'High':np.maximum(close,opens)*1.01,
        'Low':np.minimum(close,opens)*.99,'Close':close,
        'Volume':np.exp(rng.normal(15,.2,len(dates))),'Amount':np.exp(rng.normal(18,.2,len(dates)))})
    sessions=dates[240:]
    counts={'causal_configurations':2,'controlled_history_calls':0,'strict_anchor_cases':0,
            'exit_priority_cases':0,'horizon_cases':0,'body_scope_cases':0,'price_rejections':0}

    def audit(p,history):
        holding=False
        active_route=None
        age=0
        anchor=peak=0.
        for row in history.itertuples():
            if holding:
                age+=1
                peak=max(peak,row.entry_signal_close)
                rp=p[active_route]
                loss=rp['stop_loss'] is not None and row.entry_signal_close/anchor-1<=-rp['stop_loss']
                trail=rp['trailing_stop'] is not None and row.entry_signal_close/peak-1<=-rp['trailing_stop']
                condition=active_route=='bull' and age>=1 and row.entry_signal_close<anchor
                assert row.bull_anchor_loss_condition==condition
                assert row.bull_anchor_loss_trigger==(condition and not loss and not trail)
                assert row.entry_anchor_signal_close==anchor
                if row.target_position==0.:
                    holding=False
                    active_route=None
                else:
                    assert age<rp['max_hold']
            else:
                assert not row.bull_anchor_loss_condition and not row.bull_anchor_loss_trigger
                if row.signal_reason=='entry':
                    holding=True
                    active_route=row.regime
                    age=0
                    anchor=peak=row.entry_signal_close
                assert row.entry_anchor_signal_close==anchor
            assert row.bull_anchor_loss_trigger==(row.signal_reason=='bull_anchor_loss')
            assert row.target_position in (0.,1.)

    for cfg in configs:
        p=deepcopy(cfg['payload']['parameters'])
        impl=new.MechanismRange(ParameterSet(p))
        full=impl.calculate_history({'daily':bars},sessions)
        audit(p,full)
        cutoff=sessions[80]
        prefix=impl.calculate_history({'daily':bars[bars.Date<=cutoff]},sessions[:81])
        pd.testing.assert_frame_equal(full.loc[:cutoff],prefix,check_exact=True)
        changed=bars.copy()
        changed.loc[changed.Date>cutoff,['Open','High','Low','Close','Volume','Amount']]*=1.2
        actual=impl.calculate_history({'daily':changed},sessions)
        pd.testing.assert_frame_equal(full.loc[:cutoff],actual.loc[:cutoff],check_exact=True)
        indexed=bars.set_index('Date')
        raw=indexed.Close/indexed.Close.shift(p['regime_window'])-1
        previous=raw.shift(1).reindex(sessions)
        assert np.array_equal(full.previous_regime,np.where(previous>=p['regime_threshold'],'bull','bear'))
        assert np.array_equal(full.previous_regime_momentum,previous)
        assert np.array_equal(full.previous_signal_close,indexed.Close.shift(1).reindex(sessions))
        assert np.array_equal(full.entry_signal_close,indexed.Close.reindex(sessions))
        assert np.array_equal(full.entry_signal_open,indexed.Open.reindex(sessions))
        assert np.array_equal(full.entry_direction_up,full.entry_signal_close>full.entry_signal_open)
        applies=(full.regime.eq('bull') & full.previous_regime.eq('bear')
                 if p['mechanism']==modes[1] else np.zeros(len(full),dtype=bool))
        assert np.array_equal(full.entry_direction_gate_applies,applies)
        reference=original.ReentryConfirmedRange(ParameterSet({key:value for key,value in p.items()
                                                              if key!='mechanism'})).calculate_history({'daily':bars},sessions)
        for column in ('confirmation_score','confirmation_acf','confirmation_turnover','confirmation_volume',
                       'regime','regime_momentum','bull_range_position','bear_range_position'):
            pd.testing.assert_series_equal(full[column],reference[column],check_exact=True)
    base=deepcopy(configs[0]['payload']['parameters'])
    old_helpers=[(owner,owner.components,owner.confirmation_features) for owner in (new,original)]

    def controlled(p,closes,opens=None,positions=None,scores=None,previous_reference=7.,references=None):
        counts['controlled_history_calls']+=1
        fixture=bars.copy()
        fixture['Close']=5.
        fixture['Open']=5.
        fixture.loc[fixture.Date==dates[239],'Close']=6.
        fixture.loc[fixture.Date==dates[239-p['regime_window']],'Close']=previous_reference
        short=sessions[:len(closes)]
        fixture.loc[fixture.Date.isin(short),'Close']=closes
        fixture.loc[fixture.Date.isin(short),'Open']=np.asarray(closes)-.01 if opens is None else opens
        if references is not None:
            assert len(references)==len(short)
            fixture.loc[fixture.Date.isin(dates[240-p['regime_window']:240-p['regime_window']+len(short)]),'Close']=references
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
        audit(p,history)
        return history,control,fixture,short

    try:
        for mode in modes:
            p=deepcopy(base)
            p['mechanism']=mode
            body=mode==modes[1]
            for price,label in ((5.99,'bull_anchor_loss'),(6.,'hold'),(6.01,'hold')):
                history,control,_,_=controlled(p,[6.,price])
                assert history.signal_reason.tolist()==['entry',label]
                assert history.bull_anchor_loss_condition.tolist()==[False,price<6.]
                assert history.entry_anchor_signal_close.tolist()==[6.,6.]
                if price>=6.:
                    pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
                counts['strict_anchor_cases']+=1
            # Rejection before first entry keeps zero; exit/flat keep the last actual signal-model anchor.
            history,_,_,_=controlled(p,[6.,6.,5.99,5.98,4.9],scores=[-.4,0.,0.,-.4,0.])
            assert history.signal_reason.tolist()==['confirmation_rejected','entry','bull_anchor_loss','confirmation_rejected','entry']
            assert history.entry_anchor_signal_close.tolist()==[0.,6.,6.,6.,4.9]
            # Bear holdings ignore the protection even when below their own entry signal price.
            history,control,_,_=controlled(p,[4.99,4.8],[5.01,5.01])
            assert history.signal_reason.tolist()==['entry','hold']
            assert not history.bull_anchor_loss_condition.any() and not history.bull_anchor_loss_trigger.any()
            pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
            history,control,_,_=controlled(p,[4.99,6.01],[5.01,6.02])
            assert history.signal_reason.tolist()==['entry','regime']
            assert not history.bull_anchor_loss_condition.any()
            pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
            history,_,_,_=controlled(p,[6.01,4.99])
            assert history.signal_reason.tolist()==['entry','bull_anchor_loss']
            assert history.regime.tolist()==['bull','bear']
            # Full original horizons apply when protection does not fire, including H1.
            for route,price in (('bull',6.),('bear',4.)):
                for horizon in (1,4,8,60):
                    q=deepcopy(p)
                    q['regime_threshold']=.2 if route=='bear' else 0.
                    q[route]['max_hold']=horizon
                    history,control,_,_=controlled(q,[price]*(horizon+2))
                    assert history.signal_reason.tolist()==['entry']+['hold']*(horizon-1)+['time','entry']
                    assert not history.bull_anchor_loss_condition.any()
                    pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
                    counts['horizon_cases']+=1
            # Strict anchor protection wins over simultaneous range/time/raw-regime exits.
            for label,loss,trail,last,position in (
                ('loss',.05,.03,5.5,.99),('trailing',.05,.03,5.8,.99),
                ('bull_anchor_loss',None,None,5.8,.99),
                ('range',None,None,6.,.99),('time',None,None,6.,.5)):
                q=deepcopy(p)
                q['regime_threshold']=.19
                q['bull'].update(max_hold=1,stop_loss=loss,trailing_stop=trail)
                history,_,_,_=controlled(q,[6.,last],positions=[.5,position])
                assert history.signal_reason.tolist()==['entry',label]
                assert history.bull_anchor_loss_condition.iloc[-1]==(last<6.)
                assert history.bull_anchor_loss_trigger.iloc[-1]==(label=='bull_anchor_loss')
                counts['exit_priority_cases']+=1
            history,control,_,_=controlled(p,[6.,6.],references=[5.,7.])
            assert history.signal_reason.tolist()==['entry','regime']
            assert not history.bull_anchor_loss_condition.any()
            pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
            counts['exit_priority_cases']+=1
            # Plain protection has no entry gate; BODY retains exactly the EX020 boundary scope.
            history,_,_,_=controlled(p,[5.99,5.98],[6.02,6.01])
            assert history.entry_direction_gate_applies.tolist()==([True,False] if body else [False,False])
            assert history.signal_reason.tolist()==(['entry_direction_rejected','entry'] if body else ['entry','bull_anchor_loss'])
            for previous_reference in (5.,6.):
                history,control,_,_=controlled(p,[5.99],[6.02],previous_reference=previous_reference)
                assert history.previous_regime.iloc[0]=='bull' and not history.entry_direction_gate_applies.iloc[0]
                assert history.signal_reason.iloc[0]=='entry'
                pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
            history,_,_,_=controlled(p,[6.],[6.])
            assert history.signal_reason.iloc[0]==('entry_direction_rejected' if body else 'entry')
            history,_,_,_=controlled(p,[6.01],[6.],scores=[-.4])
            assert history.signal_reason.iloc[0]=='confirmation_rejected'
            history,_,_,_=controlled(p,[5.99],[6.02],scores=[-.4])
            assert history.signal_reason.iloc[0]==('entry_direction_rejected' if body else 'confirmation_rejected')
            history,control,_,_=controlled(p,[4.99],[5.01],scores=[-.4])
            assert history.signal_reason.iloc[0]=='confirmation_rejected' and not history.entry_direction_gate_applies.iloc[0]
            pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
            counts['body_scope_cases']+=7
            q=deepcopy(p)
            q['regime_window']=60
            q['bull']['range_window']=q['bear']['range_window']=21
            q['confirmation']['lookback']=40
            impl=new.MechanismRange(ParameterSet(q))
            requirement=next(item for item in impl.definition.inputs.requirements if item.name=='daily')
            assert impl._warmup==requirement.lookback_sessions==62
            history,_,fixture,short=controlled(q,[6.01],[6.])
            exact=fixture.loc[fixture.Date.isin(dates[179:241])]
            pd.testing.assert_frame_equal(impl.calculate_history({'daily':exact},short),history,check_exact=True)
            expect_rejected(lambda:impl.calculate_history({'daily':fixture.loc[fixture.Date.isin(dates[180:241])]},short),
                            'missing previous W60 regime')
            for column,value in (('Open',float('nan')),('Close',float('inf')),('Open',-1.),('Close',0.)):
                invalid=fixture.copy()
                invalid.loc[invalid.Date==short[0],column]=value
                expect_rejected(lambda invalid=invalid:new.MechanismRange(ParameterSet(q)).calculate_history(
                    {'daily':invalid},short),'nonfinite/nonpositive signal price')
                counts['price_rejections']+=1
            expect_rejected(lambda:new.MechanismRange(ParameterSet(q)).calculate_history(
                {'daily':fixture.drop(columns='Open')},short),'missing Open')
            counts['price_rejections']+=1
            invalid=fixture.copy()
            invalid.loc[invalid.Date==dates[239],'Close']=float('nan')
            expect_rejected(lambda:new.MechanismRange(ParameterSet(q)).calculate_history({'daily':invalid},short),'invalid prior Close')
            counts['price_rejections']+=1
    finally:
        for owner,features,confirmation in old_helpers:
            owner.components,owner.confirmation_features=features,confirmation
    for mutation in ({'mechanism':'INVALID'},{'confirmation':{**base['confirmation'],'enabled':False}}):
        bad=deepcopy(base)
        bad.update(mutation)
        expect_rejected(lambda bad=bad:new.MechanismRange(ParameterSet(bad)),'invalid mechanism/disabled confirmation')
    return {'status':'PASS',**counts,'anchor':'Initial zero, recent signal entry Close retained while flat; no actual-fill reset',
        'protection':'Held bull only, age>=1, strict current signal Close<anchor; equality does not trigger',
        'priority':'loss > trailing > bull_anchor_loss > range > time > raw regime',
        'body':'EX020 raw-boundary only; stablebull/bear unchanged, direction refusal before original score',
        'original_features':'Exact raw regime, range/confirmation features and original score on synthetic histories',
        'warmup_W60':'62 accepted, 61 missing previous raw regime rejected',
        'scope':'Pure synthetic signals only, no real market results or prepare/eval/publish.'}


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
