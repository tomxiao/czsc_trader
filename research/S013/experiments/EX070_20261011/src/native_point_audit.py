"""Independent full daily features, OR state and cash/economics verification."""
from dataclasses import replace
import json
import math
import numpy as np
import pandas as pd
from dataflows import canonical_frame_sha256
from strategy_runtime import canonical_sha256
from czsc_trader.research_tools import build_assessment_evidence
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
import feature_certificate as helper
import oracle
import economics_reference
import account_reference

ORIGINAL='RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY'

def identity(value):
    return {n:getattr(value,n) for n in ('dataset','source','symbol','data_start','data_cutoff','content_sha256')}|{'metadata':dict(value.metadata)}

def dates(values):
    idx=pd.DatetimeIndex(pd.to_datetime(values)).normalize().as_unit('ns')
    assert idx.tz is None and not idx.hasnans and idx.is_unique and idx.is_monotonic_increasing
    return idx

def audit(ctx,bound,result,formal,*,new,expected_cost=.001):
    validate_evaluation_evidence(formal)
    assert serialize_evaluation_evidence(bound,result)==formal
    rid=ctx.runtime.identify(bound.strategy,dependencies=bound.dependencies)
    assert rid.content_sha256==result.runs[0].identity.content_sha256
    assert result.data_identity==bound.execution_data.fingerprint
    assert result.runtime_binding_hash==canonical_sha256(bound.runtime_binding)
    assert bound.execution_mode=='FULL' and bound.workers==1 and len(result.runs)==1
    assert bound.initial_cash==1_000_000 and bound.price_basis.value=='HFQ_RESEARCH'
    assert bound.benchmark.execution.premium==.01
    assert len(bound.costs)==1 and bound.costs[0].one_way_cost==expected_cost
    binding=bound.input_bindings['full']
    p=json.loads(json.dumps(dict(bound.strategy.payload['parameters']),default=dict))
    oldp={k:v for k,v in p.items() if k!='short_confirmation_lookback4'}|{'mechanism':ORIGINAL}
    assert oldp['confirmation']['scope']=='both' and oldp['context']['entry_gate']=='all'
    inputs={}; identities={}
    for name in ('daily',binding.plan.calendar_name):
        request=binding.plan.requests[name]
        fetched=ctx.data.fetch(request,prepared=binding.prepared)
        assert fetched.ready and canonical_frame_sha256(fetched.dataframe)==fetched.identity.content_sha256
        assert fetched.identity.dataset==str(request.dataset) and fetched.identity.symbol==request.symbol
        identities[name]=identity(fetched.identity)
        inputs[name]=fetched.dataframe
    daily=inputs['daily']; calendar=inputs[binding.plan.calendar_name]
    assert identities['daily']['metadata'].get('adjustment')=='hfq'
    assert identities[binding.plan.calendar_name]['content_sha256']==binding.plan.calendar_sha256
    caldays=dates(calendar.Date)
    creq=binding.plan.requests[binding.plan.calendar_name]
    pd.testing.assert_index_equal(caldays,pd.date_range(creq.start,creq.end).as_unit('ns'),check_names=False)
    assert calendar.IsOpen.isin((0,1)).all()
    opened=caldays[calendar.IsOpen.to_numpy()==1]
    pd.testing.assert_index_equal(opened,dates(binding.plan.calendar_dates),check_names=False)
    previous=dates(calendar.loc[calendar.IsOpen.eq(1),'PreviousTradingDate'])
    pd.testing.assert_index_equal(previous[1:],opened[:-1],check_names=False)
    frame=result.runs[0].execution.decisions.copy()
    signal=dates(frame.signal_date); execution=dates(frame.valid_session)
    window=binding.plan.tradable_window
    valid=opened[(opened>=pd.Timestamp(window.start))&(opened<=pd.Timestamp(window.end))]
    loc=opened.get_indexer(valid); assert (loc>0).all()
    pd.testing.assert_index_equal(execution,valid,check_names=False)
    pd.testing.assert_index_equal(signal,opened[loc-1],check_names=False)
    dreq=binding.plan.requests['daily']; didx=dates(daily.Date)
    expected=opened[(opened>=pd.Timestamp(dreq.start))&(opened<=pd.Timestamp(dreq.end))]
    pd.testing.assert_index_equal(didx,expected,check_names=False)
    pd.testing.assert_index_equal(dates(bound.execution_data.evaluation_sessions),execution,check_names=False)
    certified=helper.certify_features(helper.FeatureCertificateRequest(daily,tuple(signal),helper.C8880Parameters.from_parameters(oldp)))
    ind=certified.features
    native=frame.set_index(signal)
    pairs={'close':'Close','acf1':'acf20','bear_acf_raw':'acf20','momentum20':'momentum20',
        'bull_range_position':'bull_range_position','bear_range_position':'bear_range_position',
        'regime_momentum':'regime_momentum','previous_regime_momentum':'previous_regime_momentum',
        'entry_signal_close':'Close','entry_signal_open':'Open','previous_signal_close':'previous_close',
        'confirmation_score':'confirmation_score','confirmation_acf':'confirmation_acf',
        'confirmation_turnover':'confirmation_turnover','confirmation_volume':'confirmation_volume'}
    for n,q in pairs.items():
        assert np.allclose(native[n].to_numpy(float),ind[q].to_numpy(float),rtol=helper.NUMERIC_RTOL,atol=helper.NUMERIC_ATOL),n
    for n in ('regime','previous_regime'):
        assert np.array_equal(native[n],ind[n]),n
    for n,expect in (('entry_direction_up',ind.body_up),('entry_direction_gate_applies',ind.regime.eq('bull')&ind.previous_regime.eq('bear'))):
        assert np.array_equal(native[n],expect),n
    # New observation calculated by independent scalar loops over full warmup.
    close=daily.Close.to_numpy(float); count=p.get('short_confirmation_lookback4',4)
    short=np.full(len(close),np.nan); alt=np.zeros(len(close),dtype=bool); reasons=np.full(len(close),'INCOMPLETE_HISTORY',dtype=object)
    for i in range(max(20,count),len(close)):
        returns=close[i-19:i+1]/close[i-20:i]-1
        vol=float(np.std(returns,ddof=1))
        if vol==0:
            reasons[i]='ZERO_VOLATILITY'; continue
        short[i]=(math.log(float(close[i]))-math.log(float(close[i-count])))/(vol*math.sqrt(count))
        alt[i]=short[i]<=0; reasons[i]='COMPLETE'
    locations=didx.get_indexer(signal)
    short,alt,reasons=short[locations],alt[locations],reasons[locations]
    if new:
        assert np.allclose(native.short_stretch4.to_numpy(float),short,rtol=1e-11,atol=1e-12,equal_nan=True)
        assert np.array_equal(native.short_alt_pass,alt)
        assert np.array_equal(native.short_stretch_reason,reasons)
    def rule(q):
        return oracle.Rule(q['entry'],q['exit'],q['max_hold'],q['acf_min'],q['momentum_min'],q['stop_loss'],q['trailing_stop'])
    bull,bear=rule(p['bull']),rule(p['bear']); threshold=p['confirmation']['threshold']; state=oracle.State()
    alternate_entries=[]
    for i,(day,row) in enumerate(native.iterrows()):
        fr=ind.iloc[i]
        feature=oracle.Feature(str(fr.regime),str(fr.previous_regime),float(fr.Close),float(fr.Open),
            float(fr.bull_range_position),float(fr.bear_range_position),float(fr.acf20),float(fr.momentum20),float(fr.confirmation_score))
        original_pass=feature.score>=threshold
        final_pass=original_pass or (new and bool(alt[i]))
        effective=replace(feature,score=threshold if final_pass else threshold-1.)
        outcome=oracle.step(oracle.Policy.ORIGINAL,state,effective,bull,bear,threshold)
        chosen=bull if outcome.management_route=='bull' else bear
        position=feature.bull_position if outcome.management_route=='bull' else feature.bear_position
        acfpass=chosen.acf_min is None or feature.acf>=chosen.acf_min
        eligible=position<=chosen.entry and (chosen.momentum_min is None or feature.momentum>=chosen.momentum_min) and (acfpass or outcome.recovered)
        altopp=outcome.opportunity and not original_pass and bool(alt[i])
        altentry=new and outcome.reason=='entry' and not original_pass
        expect={'target_position':float(outcome.target),'signal_reason':outcome.reason,
            'confirmation_opportunity':outcome.opportunity,'confirmation_pass':original_pass,
            'entry_acf_recovery_applies':outcome.recovered,'entry_eligible':eligible,
            'entry_acf_pass':acfpass,'confirmation_exit_context':state.last_reason or 'initial'}
        if new:
            expect|={'original_pass':original_pass,'alt_only_opportunity':altopp,'alt_only_entry':altentry,
                'entry_confirmation_origin':('SHORT_ALTERNATIVE' if altentry else 'ORIGINAL_CONFIRMATION') if outcome.reason=='entry' else 'NONE'}
        for n,v in expect.items(): assert row[n]==v,(day,n,row[n],v)
        for n,v in (('last_exit_reason',state.last_reason),('last_exit_route',state.last_route),('last_exit_category',state.category)):
            actual=None if row[n] is None or pd.isna(row[n]) else row[n]
            assert actual==v,(day,n,actual,v)
        if altentry:alternate_entries.append({'signal_date':str(day.date()),'valid_session':str(pd.Timestamp(row.valid_session).date()),'decision_id':row.decision_id})
        state=outcome.next_state
    facts=build_assessment_evidence(bound,result)
    assert len(facts)==1
    econ=economics_reference.economics(facts[0])
    account=account_reference.verify_account(bound,result)
    for year,row in account['annual'].items():
        assert abs(row['net_return']-econ['annual'][year]['return'])<1e-12
        assert abs(row['drawdown_magnitude']-econ['annual'][year]['drawdown'])<1e-12
    return {'status':'PASS','whole_formal_native_exact':True,'content_sha256':rid.content_sha256,
        'prepared_inputs':identities,'original_feature_certificate':dict(certified.provenance),
        'signal_days':len(native),'independent_or_state_exact':True,'new_parameter_count':14 if new else 13,
        'cash_account':account,'economics':econ,'alternate_signal_entries':alternate_entries,
        'pricing':{'basis':bound.price_basis.value,'anchor_date':str(bound.execution_data.pricing.anchor_date),
            'anchor_factor':bound.execution_data.pricing.anchor_factor,'fingerprint':bound.execution_data.pricing.fingerprint},
        'hypothesis_status':'NOT_JUDGED','parameter_diagnostic_status':'NOT_RUN_CENTER_ONLY'}
