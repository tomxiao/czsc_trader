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
    new=module(SRC/'strategy_runtime','_ex022_mechanism','mechanism_range')
    original=module(SRC/'strategy_runtime','_ex022_original','reentry_confirmed_range')
    modes=('EARLY_POSITIVE','EARLY_NONPOSITIVE','NEW_BULL_BODY_EARLY_POSITIVE','NEW_BULL_BODY_EARLY_NONPOSITIVE')
    configs=plan['configurations']
    assert len(configs)==4 and {cfg['payload']['parameters']['mechanism'] for cfg in configs}==set(modes)
    rng=np.random.default_rng(13)
    dates=pd.bdate_range('2018-01-01',periods=480)
    close=6*np.exp(np.cumsum(rng.normal(.0004,.02,len(dates))))
    opens=close*np.exp(rng.normal(0.,.01,len(dates)))
    bars=pd.DataFrame({'Date':dates,'Open':opens,'High':np.maximum(close,opens)*1.01,
        'Low':np.minimum(close,opens)*.99,'Close':close,
        'Volume':np.exp(rng.normal(15,.2,len(dates))),'Amount':np.exp(rng.normal(18,.2,len(dates)))})
    sessions=dates[240:]
    counts={'causal_configurations':4,'controlled_cases':0,'cap_boundary_cases':0,
            'exit_priority_cases':0,'body_scope_cases':0,'price_rejections':0}

    def audit(p,history):
        holding=False
        active_route=None
        age=0
        anchor=0.
        for row in history.itertuples():
            condition=eligible=False
            if holding:
                age+=1
                if active_route=='bear':
                    condition=(row.entry_signal_close>anchor if p['mechanism'].endswith('_POSITIVE')
                               else row.entry_signal_close<=anchor)
                    eligible=max(1,p['bear']['max_hold']-1)<=age<p['bear']['max_hold']
                assert row.early_timer_condition==condition
                assert row.early_timer_eligible==eligible
                assert row.entry_anchor_signal_close==anchor
                assert row.early_timer_trigger==(eligible and condition and row.signal_reason not in ('loss','trailing','range'))
                if row.target_position==0.:
                    holding=False
                    active_route=None
                else:
                    assert age<p[active_route]['max_hold']
            else:
                assert not row.early_timer_condition and not row.early_timer_eligible and not row.early_timer_trigger
                if row.signal_reason=='entry':
                    holding=True
                    active_route=row.regime
                    age=0
                    anchor=row.entry_signal_close
                assert row.entry_anchor_signal_close==anchor
            assert row.early_timer_trigger==(row.signal_reason in ('time_early_positive','time_early_nonpositive'))
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
        raw_momentum=indexed.Close/indexed.Close.shift(p['regime_window'])-1
        previous=raw_momentum.shift(1).reindex(sessions)
        assert np.array_equal(full.previous_regime,np.where(previous>=p['regime_threshold'],'bull','bear'))
        assert np.array_equal(full.previous_regime_momentum,previous)
        assert np.array_equal(full.previous_signal_close,indexed.Close.shift(1).reindex(sessions))
        assert np.array_equal(full.entry_signal_close,indexed.Close.reindex(sessions))
        assert np.array_equal(full.entry_signal_open,indexed.Open.reindex(sessions))
        assert np.array_equal(full.entry_direction_up,full.entry_signal_close>full.entry_signal_open)
        applies=(full.regime.eq('bull') & full.previous_regime.eq('bear')
                 if p['mechanism'].startswith('NEW_BULL_BODY_') else np.zeros(len(full),dtype=bool))
        assert np.array_equal(full.entry_direction_gate_applies,applies)
        raw=original.ReentryConfirmedRange(ParameterSet({key:value for key,value in p.items()
                                                        if key!='mechanism'})).calculate_history({'daily':bars},sessions)
        for column in ('confirmation_score','confirmation_acf','confirmation_turnover','confirmation_volume',
                       'regime','regime_momentum','bull_range_position','bear_range_position'):
            pd.testing.assert_series_equal(full[column],raw[column],check_exact=True)
    base=deepcopy(configs[0]['payload']['parameters'])
    old_helpers=[(owner,owner.components,owner.confirmation_features) for owner in (new,original)]

    def controlled(p,closes,opens=None,positions=None,scores=None,previous_reference=7.):
        counts['controlled_cases']+=1
        fixture=bars.copy()
        fixture['Close']=5.
        fixture['Open']=5.
        fixture.loc[fixture.Date==dates[239],'Close']=6.
        fixture.loc[fixture.Date==dates[239-p['regime_window']],'Close']=previous_reference
        short=sessions[:len(closes)]
        fixture.loc[fixture.Date.isin(short),'Close']=closes
        fixture.loc[fixture.Date.isin(short),'Open']=closes if opens is None else opens
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
            positive=mode.endswith('_POSITIVE')
            early_label='time_early_positive' if positive else 'time_early_nonpositive'
            # H1 cannot be early; all longer horizons have only one eligible age.
            for horizon in (1,2,4,60):
                q=deepcopy(p)
                q['bear']['max_hold']=horizon
                q['regime_window']=60
                for sign,last in (('positive',4.01),('zero',4.),('negative',3.99)):
                    prior=4. if positive else 4.01
                    closes=[4.]+[prior]*max(0,horizon-2)+[last]
                    history,_,_,_=controlled(q,closes)
                    meets=(last>4. if positive else last<=4.)
                    expected=early_label if horizon>1 and meets else ('time' if horizon==1 else 'hold')
                    assert history.signal_reason.iloc[-1]==expected,(mode,horizon,sign)
                    assert not history.early_timer_eligible.iloc[0]
                    if horizon>1:
                        assert not history.early_timer_eligible.iloc[:horizon-1].any()
                        assert history.early_timer_eligible.iloc[-1]
                    counts['cap_boundary_cases']+=1
                # Refuse the early condition at H-1, then make it true at H: still default time.
                off=3.99 if positive else 4.01
                on=4.01 if positive else 3.99
                closes=[4.]+[off]*(horizon-1)+[on,off]
                opens=closes.copy()
                opens[-1]=off-.01
                history,_,_,_=controlled(q,closes,opens)
                assert history.signal_reason.iloc[horizon]=='time'
                assert history.early_timer_condition.iloc[horizon]
                assert not history.early_timer_eligible.iloc[horizon] and not history.early_timer_trigger.iloc[horizon]
                assert history.target_position.iloc[horizon]==0.
                assert history.signal_reason.iloc[horizon+1]=='entry',(mode,horizon)
                counts['cap_boundary_cases']+=1
            # Bear scope alone: early wins over changed regime, while earlier original exits remain.
            for label,loss,trail,position,last in (
                ('loss',.01,.005,.99,3.8),('trailing',None,.005,.99,3.8),
                ('range',None,None,.99,4.01 if positive else 3.99),
                (early_label,None,None,.5,4.01 if positive else 3.99)):
                q=deepcopy(p)
                q['bear'].update(max_hold=2,stop_loss=loss,trailing_stop=trail)
                history,_,_,_=controlled(q,[4.,last],positions=[.5,position])
                assert history.signal_reason.iloc[-1]==label
                assert history.early_timer_trigger.iloc[-1]==(label==early_label)
                counts['exit_priority_cases']+=1
            q=deepcopy(p)
            q['bear'].update(max_hold=3,trailing_stop=.005)
            history,_,_,_=controlled(q,[4.,4.5,4.01 if positive else 3.99])
            assert history.signal_reason.tolist()==['entry','hold','trailing']
            assert history.early_timer_eligible.iloc[-1] and history.early_timer_condition.iloc[-1]
            assert not history.early_timer_trigger.iloc[-1]
            counts['exit_priority_cases']+=1
            q=deepcopy(p)
            q['bear']['max_hold']=2
            # Positive condition plus regime switch, or nonpositive condition with lowered threshold.
            q['regime_threshold']=0. if positive else -.21
            if not positive:
                # Keep within the legal threshold bound and choose an anchor at 4.5.
                q['regime_threshold']=-.1
            pair=[4.,6.01] if positive else [4.5,4.5]
            if not positive:
                # Prior denominator for entry differs from next-day denominator by one reference row.
                history,_,fixture,short=controlled(q,pair)
                fixture.loc[fixture.Date==dates[240-q['regime_window']],'Close']=6.
                fixture.loc[fixture.Date==dates[241-q['regime_window']],'Close']=4.
                history=new.MechanismRange(ParameterSet(q)).calculate_history({'daily':fixture},short)
                audit(q,history)
            else:
                history,_,_,_=controlled(q,pair)
            assert history.regime.tolist()==['bear','bull']
            assert history.signal_reason.tolist()==['entry',early_label]
            assert history.early_timer_trigger.iloc[-1]
            counts['exit_priority_cases']+=1
            # Bull holdings and all original bull exits ignore the new bear timer.
            history,control,_,_=controlled(p,[6.01,6.],[6.,6.1])
            assert history.signal_reason.tolist()==['entry','hold']
            pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
            exits=[]
            for label,loss,trail,position,last in (
                ('loss',.05,.03,.99,4.9),('trailing',.05,.03,.99,5.8),
                ('range',None,None,.99,5.8),('time',None,None,.5,5.8),
                ('regime',None,None,.5,4.9)):
                q=deepcopy(p)
                q['regime_threshold']=.19
                q['bull'].update(max_hold=8 if label=='regime' else 1,stop_loss=loss,trailing_stop=trail)
                exits.append((label,q,last,position))
            for label,q,last,position in exits:
                history,control,_,_=controlled(q,[6.01,last],[6.,6.1],positions=[.5,position])
                assert history.signal_reason.tolist()==['entry',label]
                pd.testing.assert_frame_equal(history.loc[:,control.columns],control,check_exact=True)
                counts['exit_priority_cases']+=1
            # Body group alone refuses first raw bull. A following stable bull is unfiltered.
            body=mode.startswith('NEW_BULL_BODY_')
            history,_,_,_=controlled(p,[5.99,5.98],[6.02,6.01])
            assert history.entry_direction_gate_applies.tolist()==([True,False] if body else [False,False])
            assert history.signal_reason.iloc[0]==('entry_direction_rejected' if body else 'entry')
            assert history.signal_reason.iloc[1]==('entry' if body else 'hold')
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
            history,_,_,_=controlled(p,[4.99],[5.01],scores=[-.4])
            assert history.signal_reason.iloc[0]=='confirmation_rejected' and not history.entry_direction_gate_applies.iloc[0]
            history,_,_,_=controlled(p,[4.99,6.01,6.],[5.01,6.02,6.1])
            assert history.signal_reason.tolist()==['entry','regime','entry']
            counts['body_scope_cases']+=8
            # W60 must retain previous raw regime before reindex; use the first real warmup price.
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
                    {'daily':invalid},short),'nonfinite/nonpositive price')
                counts['price_rejections']+=1
            expect_rejected(lambda:new.MechanismRange(ParameterSet(q)).calculate_history(
                {'daily':fixture.drop(columns='Open')},short),'missing Open')
            counts['price_rejections']+=1
            invalid=fixture.copy()
            invalid.loc[invalid.Date==dates[239],'Close']=float('nan')
            expect_rejected(lambda:new.MechanismRange(ParameterSet(q)).calculate_history(
                {'daily':invalid},short),'invalid previous Close')
            counts['price_rejections']+=1
    finally:
        for owner,features,confirmation in old_helpers:
            owner.components,owner.confirmation_features=features,confirmation
    for mutation in ({'mechanism':'INVALID'},{'confirmation':{**base['confirmation'],'enabled':False}}):
        bad=deepcopy(base)
        bad.update(mutation)
        expect_rejected(lambda bad=bad:new.MechanismRange(ParameterSet(bad)),'invalid mechanism/disabled confirmation')
    return {'status':'PASS',**counts,
        'cap':'H1 never early; H2/H4/H60 only H-1; at H default time, H+1 flat state can reenter',
        'anchor':'Finite most recent entry signal Close, initially zero; not execution profit',
        'early_flags':'Independent holding-bear state/age/price audit, higher-priority exits suppress trigger only',
        'priority':'loss > trailing > range > time (early/default) > regime; bull TIME unchanged',
        'body_gate':'Only raw bear-to-bull entry, direction before score; stable bull and bear unchanged',
        'original_features':'Exact original route/regime/score features on synthetic histories',
        'warmup_W60':'62 accepted; 61 missing previous regime rejected',
        'scope':'Pure synthetic signals; no real market outcomes, prepare, evaluation, declaration, or publication.'}


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
