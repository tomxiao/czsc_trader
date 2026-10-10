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
    new=module(SRC/'strategy_runtime','_ex020_mechanism','mechanism_range')
    original=module(SRC/'strategy_runtime','_ex020_original','reentry_confirmed_range')
    rng=np.random.default_rng(13)
    dates=pd.bdate_range('2018-01-01',periods=480)
    close=6*np.exp(np.cumsum(rng.normal(.0004,.02,len(dates))))
    opens=close*np.exp(rng.normal(0.,.01,len(dates)))
    bars=pd.DataFrame({'Date':dates,'Open':opens,'High':np.maximum(close,opens)*1.01,
        'Low':np.minimum(close,opens)*.99,'Close':close,
        'Volume':np.exp(rng.normal(15,.2,len(dates))),'Amount':np.exp(rng.normal(18,.2,len(dates)))})
    sessions=dates[240:]
    assert len(plan['configurations'])==4
    assert {cfg['payload']['parameters']['mechanism'] for cfg in plan['configurations']}=={
        'NEW_BULL_CLOSE_UP','NEW_BULL_BODY_UP'}
    for cfg in plan['configurations']:
        p=deepcopy(cfg['payload']['parameters'])
        impl=new.MechanismRange(ParameterSet(p))
        full=impl.calculate_history({'daily':bars},sessions)
        cutoff=sessions[80]
        prefix=impl.calculate_history({'daily':bars[bars.Date<=cutoff]},sessions[:81])
        pd.testing.assert_frame_equal(full.loc[:cutoff],prefix,check_exact=True)
        changed=bars.copy()
        changed.loc[changed.Date>cutoff,['Open','High','Low','Close','Volume','Amount']]*=1.2
        actual=impl.calculate_history({'daily':changed},sessions)
        pd.testing.assert_frame_equal(full.loc[:cutoff],actual.loc[:cutoff],check_exact=True)
        indexed=bars.set_index('Date')
        expected_previous=indexed.Close.shift(1).reindex(sessions)
        assert np.array_equal(full.previous_signal_close.to_numpy(),expected_previous.to_numpy())
        assert np.array_equal(full.entry_signal_close.to_numpy(),indexed.Close.reindex(sessions).to_numpy())
        assert np.array_equal(full.entry_signal_open.to_numpy(),indexed.Open.reindex(sessions).to_numpy())
        direction=(indexed.Close.reindex(sessions)>expected_previous if p['mechanism']=='NEW_BULL_CLOSE_UP'
                   else indexed.Close.reindex(sessions)>indexed.Open.reindex(sessions))
        assert np.array_equal(full.entry_direction_up.to_numpy(),direction.to_numpy())
        raw_momentum=indexed.Close/indexed.Close.shift(p['regime_window'])-1
        previous_momentum=raw_momentum.shift(1).reindex(sessions)
        previous_regime=np.where(previous_momentum.to_numpy()>=p['regime_threshold'],'bull','bear')
        assert np.array_equal(full.previous_regime.to_numpy(),previous_regime)
        assert np.array_equal(full.previous_regime_momentum.to_numpy(),previous_momentum.to_numpy())
        applies=full.regime.eq('bull') & full.previous_regime.eq('bear')
        assert np.array_equal(full.entry_direction_gate_applies.to_numpy(),applies.to_numpy())
        gate=~applies | direction
        opportunity=full.confirmation_opportunity.astype(bool)
        score_pass=full.confirmation_pass.astype(bool)
        assert np.array_equal(opportunity & ~gate,full.signal_reason.eq('entry_direction_rejected'))
        assert np.array_equal(opportunity & gate & ~score_pass,full.signal_reason.eq('confirmation_rejected'))
        assert np.array_equal(opportunity & gate & score_pass,full.signal_reason.eq('entry'))
        assert np.isin(full.target_position.to_numpy(),(0.,1.)).all()
        base={key:value for key,value in p.items() if key!='mechanism'}
        reference=original.ReentryConfirmedRange(ParameterSet(base)).calculate_history({'daily':bars},sessions)
        pd.testing.assert_series_equal(full.confirmation_score,reference.confirmation_score,check_exact=True)
        pd.testing.assert_series_equal(full.regime,reference.regime,check_exact=True)
    base=deepcopy(plan['configurations'][0]['payload']['parameters'])
    old_helpers=[(owner,owner.components,owner.confirmation_features) for owner in (new,original)]
    case_count=0

    def controlled(parameters,closes,opens,positions=None,scores=None,previous_reference=7.):
        fixture=bars.copy()
        fixture['Close']=5.
        fixture['Open']=5.
        fixture.loc[fixture.Date==dates[239],'Close']=6.
        fixture.loc[fixture.Date==dates[239-parameters['regime_window']],'Close']=previous_reference
        short=sessions[:len(closes)]
        fixture.loc[fixture.Date.isin(short),'Close']=closes
        fixture.loc[fixture.Date.isin(short),'Open']=opens
        fixture['High']=np.maximum(fixture.Close,fixture.Open)*1.01
        fixture['Low']=np.minimum(fixture.Close,fixture.Open)*.99
        positions=[.5]*len(short) if positions is None else positions
        scores=[0.]*len(short) if scores is None else scores

        def features(frame,window):
            index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
            result=pd.DataFrame({'range_position':.5,'acf1':.2,
                'close':frame.Close.to_numpy(),'momentum20':0.},index=index)
            result.loc[short,'range_position']=positions
            return result

        def confirmation(frame,acf,window):
            index=pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
            result=pd.DataFrame(0.,index=index,columns=['acf','turnover','volume'])
            result.loc[short,:]=np.asarray(scores)[:,None]
            return result,result

        for owner,_,_ in old_helpers:
            owner.components,owner.confirmation_features=features,confirmation
        changed=new.MechanismRange(ParameterSet(parameters)).calculate_history({'daily':fixture},short)
        stripped={key:value for key,value in parameters.items() if key!='mechanism'}
        control=original.ReentryConfirmedRange(ParameterSet(stripped)).calculate_history({'daily':fixture},short)
        return changed,control,fixture,short

    try:
        for mode in ('NEW_BULL_CLOSE_UP','NEW_BULL_BODY_UP'):
            p=deepcopy(base)
            p['mechanism']=mode
            # Both examples remain bull relative to the genuine twenty-session history (5.0).
            result,_,_,_=controlled(p,[6.01],[6.02])
            assert result.regime.iloc[0]=='bull'
            assert result.signal_reason.iloc[0]==('entry' if mode=='NEW_BULL_CLOSE_UP' else 'entry_direction_rejected')
            result,_,_,_=controlled(p,[5.99],[5.98])
            assert result.regime.iloc[0]=='bull'
            assert result.signal_reason.iloc[0]==('entry' if mode=='NEW_BULL_BODY_UP' else 'entry_direction_rejected')
            result,_,_,_=controlled(p,[6.],[6.])
            assert result.signal_reason.iloc[0]=='entry_direction_rejected'
            result,_,_,_=controlled(p,[6.01],[6.01])
            assert result.signal_reason.iloc[0]==('entry' if mode=='NEW_BULL_CLOSE_UP' else 'entry_direction_rejected')
            result,_,_,_=controlled(p,[6.],[5.99])
            assert result.signal_reason.iloc[0]==('entry' if mode=='NEW_BULL_BODY_UP' else 'entry_direction_rejected')
            result,_,fixture,short=controlled(p,[6.01],[6.])
            assert result.signal_reason.iloc[0]=='entry'
            assert result.previous_signal_close.iloc[0]==6.
            assert result.entry_signal_close.iloc[0]==6.01 and result.entry_signal_open.iloc[0]==6.
            pd.testing.assert_frame_equal(new.MechanismRange(ParameterSet(p)).calculate_history(
                {'daily':fixture[fixture.Date<=short[0]]},short),result,check_exact=True)
            result,_,_,_=controlled(p,[6.01],[6.],scores=[-.4])
            assert result.signal_reason.iloc[0]=='confirmation_rejected'
            result,_,_,_=controlled(p,[5.99],[6.02],scores=[-.4])
            assert result.signal_reason.iloc[0]=='entry_direction_rejected' and not result.confirmation_pass.iloc[0]
            case_count+=8
            # New-bull transition can come solely from changing the old denominator 7 -> 5.
            result,_,_,_=controlled(p,[5.99],[5.98])
            assert result.previous_regime.iloc[0]=='bear' and result.regime.iloc[0]=='bull'
            assert result.entry_direction_gate_applies.iloc[0]
            assert not (result.entry_signal_close.iloc[0]>result.previous_signal_close.iloc[0])
            assert result.signal_reason.iloc[0]==('entry' if mode=='NEW_BULL_BODY_UP' else 'entry_direction_rejected')
            result,_,_,_=controlled(p,[5.99,5.98],[6.02,6.01])
            assert result.signal_reason.tolist()==['entry_direction_rejected','entry']
            assert result.entry_direction_gate_applies.tolist()==[True,False]
            assert not result.entry_direction_up.any()
            # Stable bull and an exactly-zero previous raw return are original entry opportunities.
            for previous_reference in (5.,6.):
                result,control,_,_=controlled(p,[5.99],[6.02],previous_reference=previous_reference)
                assert result.previous_regime.iloc[0]=='bull' and not result.entry_direction_gate_applies.iloc[0]
                assert not result.entry_direction_up.iloc[0] and result.signal_reason.iloc[0]=='entry'
                pd.testing.assert_frame_equal(result.loc[:,control.columns],control,check_exact=True)
            result,_,_,_=controlled(p,[5.],[4.9])
            assert result.regime_momentum.iloc[0]==0. and result.regime.iloc[0]=='bull'
            assert result.entry_direction_gate_applies.iloc[0]
            assert result.signal_reason.iloc[0]==('entry' if mode=='NEW_BULL_BODY_UP' else 'entry_direction_rejected')
            result,control,_,_=controlled(p,[4.99,6.01,6.],[5.01,6.02,6.1])
            assert result.signal_reason.tolist()==['entry','regime','entry']
            assert result.entry_direction_gate_applies.tolist()==[False,True,False]
            assert not result.entry_direction_up.iloc[-1]
            pd.testing.assert_frame_equal(result.loc[:,control.columns],control,check_exact=True)
            q=deepcopy(p)
            q['regime_window']=60
            q['bull']['range_window']=q['bear']['range_window']=21
            q['confirmation']['lookback']=40
            implementation=new.MechanismRange(ParameterSet(q))
            requirement=next(item for item in implementation.definition.inputs.requirements if item.name=='daily')
            assert implementation._warmup==requirement.lookback_sessions==62
            result,_,fixture,short=controlled(q,[6.01],[6.])
            exact=fixture.loc[fixture.Date.isin(dates[179:241])]
            pd.testing.assert_frame_equal(implementation.calculate_history({'daily':exact},short),result,check_exact=True)
            insufficient=fixture.loc[fixture.Date.isin(dates[180:241])]
            expect_rejected(lambda: implementation.calculate_history({'daily':insufficient},short),
                            'current W60 valid but previous W60 missing')
            case_count+=7
            # Bear entry and both bear holding/time/state exits must ignore bullish direction refusal.
            result,control,_,_=controlled(p,[4.99,4.98],[5.01,5.01])
            assert not result.entry_direction_up.iloc[0] and result.regime.iloc[0]=='bear'
            assert result.signal_reason.tolist()==['entry','hold']
            pd.testing.assert_frame_equal(result.loc[:,control.columns],control,check_exact=True)
            q=deepcopy(p)
            q['bear']['max_hold']=1
            result,control,_,_=controlled(q,[4.99,4.98],[5.01,5.01])
            assert result.signal_reason.tolist()==['entry','time']
            pd.testing.assert_frame_equal(result.loc[:,control.columns],control,check_exact=True)
            result,control,_,_=controlled(p,[4.99,6.01],[5.01,6.02])
            assert result.signal_reason.tolist()==['entry','regime']
            pd.testing.assert_frame_equal(result.loc[:,control.columns],control,check_exact=True)
            # Holding must not receive an extra price exit; compare every original TIME output column.
            result,control,_,_=controlled(p,[6.01,6.],[6.,6.1])
            assert not result.entry_direction_up.iloc[1] and result.signal_reason.tolist()==['entry','hold']
            pd.testing.assert_frame_equal(result.loc[:,control.columns],control,check_exact=True)
            exits=[]
            q=deepcopy(p)
            q['bull']['max_hold']=1
            exits.append(('time',q,[6.01,6.],[6.,6.1],[.5,.5]))
            exits.append(('range',p,[6.01,6.],[6.,6.1],[.5,.99]))
            exits.append(('regime',p,[6.01,4.9],[6.,6.1],[.5,.5]))
            q=deepcopy(p)
            q['bull']['stop_loss']=.05
            exits.append(('loss',q,[6.01,5.5],[6.,6.1],[.5,.5]))
            q=deepcopy(p)
            q['bull']['trailing_stop']=.03
            exits.append(('trailing',q,[6.01,6.4,6.1],[6.,6.3,6.2],[.5,.5,.5]))
            # Force overlapping exit conditions to preserve loss > trailing > range > time > regime.
            for label,loss,trail,position in (
                ('loss',.05,.03,.99),('trailing',.05,.03,.99),
                ('range',None,None,.99),('time',None,None,.5)):
                q=deepcopy(p)
                q['regime_threshold']=.19
                q['bull'].update(max_hold=1,stop_loss=loss,trailing_stop=trail)
                last=4.9 if label=='loss' else 5.8
                exits.append((label,q,[6.01,last],[6.,6.1],[.5,position]))
            for label,q,closes,opens,positions in exits:
                result,control,_,_=controlled(q,closes,opens,positions=positions)
                assert result.signal_reason.iloc[0]=='entry' and result.signal_reason.iloc[-1]==label
                assert not result.entry_direction_up.iloc[-1]
                pd.testing.assert_frame_equal(result.loc[:,control.columns],control,check_exact=True)
            case_count+=4+len(exits)
            # Explicit invalid-price rejection, including the pre-window previous close.
            result,_,fixture,short=controlled(p,[6.01],[6.])
            for column,value in (('Open',float('nan')),('Close',float('inf')),('Open',-1.),('Close',0.)):
                invalid=fixture.copy()
                invalid.loc[invalid.Date==short[0],column]=value
                expect_rejected(lambda invalid=invalid: new.MechanismRange(ParameterSet(p)).calculate_history(
                    {'daily':invalid},short),column+' nonfinite/nonpositive')
            expect_rejected(lambda: new.MechanismRange(ParameterSet(p)).calculate_history(
                {'daily':fixture.drop(columns='Open')},short),'missing Open')
            invalid=fixture.copy()
            invalid.loc[invalid.Date==dates[239],'Close']=float('nan')
            expect_rejected(lambda: new.MechanismRange(ParameterSet(p)).calculate_history(
                {'daily':invalid},short),'nonfinite previous Close')
            # Reject absent pre-window price before looking up stubbed features/momentum.
            expect_rejected(lambda: new.MechanismRange(ParameterSet(p)).calculate_history(
                {'daily':fixture[fixture.Date>=short[0]]},short),'missing previous price')
    finally:
        for owner,features,confirmation in old_helpers:
            owner.components,owner.confirmation_features=features,confirmation
    invalid=deepcopy(base)
    invalid['mechanism']='INVALID'
    expect_rejected(lambda: new.MechanismRange(ParameterSet(invalid)),'invalid mechanism')
    invalid=deepcopy(base)
    invalid['confirmation']['enabled']=False
    expect_rejected(lambda: new.MechanismRange(ParameterSet(invalid)),'disabled original score gate')
    return {'status':'PASS','causal_configurations':4,'controlled_cases':case_count,
        'direction_oracle':'EXACT_EQUAL bound signal Close versus prior actual row or same-row Open',
        'refusal_priority':'raw new-bull only direction before original score; distinct refusal reasons',
        'previous_raw_regime':'EXACT_EQUAL full causal momentum shift before session reindex',
        'warmup_W60':'62 rows accepted; 61 with missing previous regime rejected',
        'preserved_time_columns':'EXACT_EQUAL all original columns on controlled bear/holding/all-exit cases',
        'branches':['close up/body down','close down/body up','equality refused','first session real warmup close',
            'original score refusal','direction refusal before score refusal','bear gate bypass',
            'bear holding/time/regime preserved','bull hold/loss/trailing/range/time/regime preserved',
            'original overlapping exit priorities preserved','old reference rolls high-to-low without price rise',
            'rejected transition then stable-bull falling-price entry','stable bull and previous equality unchanged',
            'current equality is new bull','bear holding exits then stable-bull entry'],
        'price_rejections_per_mode':7,'invalid_mechanism_and_disabled_confirmation_rejected':True,
        'scope':'Synthetic signal-only checks; no account evaluation or publication.'}


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
