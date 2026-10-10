"""Independent native-data/state oracle and original four-economic-gate audit."""
import json
import numpy as np
import pandas as pd
from common import ROOT, PROTOCOLS, RUNS, CACHE, DEPENDENCIES, context, read, write, cache_read, file_hash
from run_parameters import resolve_center, authenticate_refresh_parent
from account_reference import verify_account
import ledger_reference as ledger
from analysis_reference import summarize, paired
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence


def audit_refresh(bound,frame,p):
    binding=next(iter(bound.input_bindings.values()))
    fetched=context(1).data.fetch(binding.plan.requests['daily'],prepared=binding.prepared)
    assert fetched.ready
    bars=fetched.dataframe.copy()
    bars.index=pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
    dates=pd.DatetimeIndex(pd.to_datetime(frame.signal_date)).normalize()
    close=bars.Close.astype(float)
    def acf(values):
        centered=values-values.mean()
        variance=np.mean(centered**2)
        return np.nan if np.isclose(variance,0) else float(np.dot(centered[1:],centered[:-1])/19/variance)
    full_acf=close.pct_change(fill_method=None).rolling(20).apply(acf,raw=True)
    values=full_acf.reindex(dates)
    np.testing.assert_array_equal(frame.acf1,values)
    positions={r:((close-bars.Low.rolling(p[r]['range_window']).min())/
        (bars.High.rolling(p[r]['range_window']).max()-bars.Low.rolling(p[r]['range_window']).min())).reindex(dates)
        for r in ('bull','bear')}
    for r in positions:
        np.testing.assert_array_equal(frame[r+'_range_position'],positions[r])
    raw_features={'acf':full_acf,
                  'turnover':bars.Amount.astype(float)/bars.Amount.astype(float).rolling(20).mean(),
                  'volume':np.log(bars.Volume.astype(float)).diff().rolling(20).mean()}
    def rank(items):
        current=items[-1]
        return float(((items<current).sum()+.5*(items==current).sum())/len(items)-.5)
    normalized={name:series.rolling(p['confirmation']['lookback'],min_periods=p['confirmation']['lookback']).apply(rank,raw=True).reindex(dates)
                for name,series in raw_features.items()}
    for name,series in normalized.items():
        np.testing.assert_array_equal(frame['confirmation_'+name],series)
    scores=.5*normalized['acf']+.25*normalized['turnover']+.25*normalized['volume']
    np.testing.assert_array_equal(frame.confirmation_score,scores)
    momentum=(close/close.shift(p['regime_window'])-1).reindex(dates)
    momentum20=(close/close.shift(20)-1).reindex(dates)
    holding=False
    route=None
    age=0
    pending=False
    last=None
    armed_count=release_count=blocked_count=0
    for i,row in enumerate(frame.itertuples()):
        current='bull' if momentum.iloc[i]>=p['regime_threshold'] else 'bear'
        assert row.regime==current and row.regime_momentum==momentum.iloc[i]
        previous_pending=pending
        released=False
        if not holding and pending and (current!='bear' or positions['bear'].iloc[i]>p['bear']['entry']
                or (p['bear']['acf_min'] is not None and values.iloc[i]<p['bear']['acf_min'])
                or (p['bear']['momentum_min'] is not None and momentum20.iloc[i]<p['bear']['momentum_min'])):
            pending=False
            released=True
        active=route if holding else current
        rp=p[active]
        position=positions[active].iloc[i]
        assert position==row.range_position
        eligible=(position<=rp['entry'] and (rp['acf_min'] is None or values.iloc[i]>=rp['acf_min'])
                  and (rp['momentum_min'] is None or momentum20.iloc[i]>=rp['momentum_min']))
        passed=scores.iloc[i]>=p['confirmation']['threshold']
        opportunity=bool(not holding and current=='bear' and eligible)
        blocked=bool(opportunity and pending)
        assert bool(row.confirmation_opportunity)==bool(not holding and eligible)
        assert bool(row.confirmation_pass)==bool(passed)
        assert row.confirmation_exit_context==(last or 'initial')
        armed=False
        reason='flat'
        if holding:
            age+=1
            assert rp['stop_loss'] is None and rp['trailing_stop'] is None
            reason=('range' if position>=rp['exit'] else 'time' if age>=rp['max_hold']
                    else 'regime' if current!=active else 'hold')
            if reason!='hold':
                armed=bool(active=='bear' and reason=='time' and current=='bear'
                           and positions['bear'].iloc[i]<=p['bear']['entry'])
                if armed:
                    pending=True
                holding=False
                route=None
                last=reason
        elif eligible:
            reason='entry_refresh_rejected' if blocked else 'entry' if passed else 'confirmation_rejected'
            if reason=='entry':
                holding=True
                route=current
                age=0
                last=None
        for name,expected in (('refresh_pending_before',previous_pending),('refresh_pending_after',pending),
                              ('refresh_opportunity',opportunity),('refresh_blocked',blocked),
                              ('refresh_released',released),('refresh_armed',armed)):
            assert bool(getattr(row,name))==expected
        assert row.holding_age==age and row.signal_reason==reason and row.target_position==float(holding)
        armed_count+=int(armed)
        release_count+=int(released)
        blocked_count+=int(blocked)
    return {'status':'PASS','armed_events':armed_count,'released_events':release_count,'blocked_bear_opportunities':blocked_count,
            'oracle':'Full native-bound HFQ OHLC independently reconstructs ACF20, both ranges, raw regime, momentum, volume/amount ranks and original score; all pending/age/entry/exit/reset state and priority checked.'}


def main():
    assert read(RUNS/'matrix.json')['status']=='COMPLETE'
    plan=read(PROTOCOLS/'plan.json')
    cfg=plan['configurations'][0]
    ledger.verify_account=verify_account
    rows={}
    reuse={}
    prior_refs=read(ROOT/'research/S013/assets/runs/EX034_20261011/account_references.json')
    native_accounts=[]
    for control in plan['controls']:
        label=control['label']
        origin='B0-TIME' if label=='B0-TIME' else 'N0'
        native_ref=EvidenceRef.from_dict(prior_refs[origin])
        assert file_hash(native_ref.resolve(ROOT))==native_ref.sha256
        old_bound,old_result=resolve_center(control)
        formal=read(native_ref.resolve(ROOT))
        validate_evaluation_evidence(formal)
        assert formal==serialize_evaluation_evidence(old_bound,old_result)
        actual=context(1).runtime.identify(old_bound.strategy,dependencies=old_bound.dependencies)
        assert actual.content_sha256==control['content_sha256']
        reuse[label]={'reference':native_ref.to_dict(),'identity_account':'EXACT_REUSE'}
        native_accounts.append((control,old_bound,old_result))
    authenticate_refresh_parent(context(1),cfg,plan,{label:value['reference'] for label,value in reuse.items()})
    for config,bound,result in (*native_accounts,(cfg,*cache_read(CACHE/'N0.pkl.gz'))):
        assert result.runs[0].identity.content_sha256==config['content_sha256']
        assert json.loads(json.dumps(dict(bound.strategy.payload),default=dict))==config['payload']
        row,frame=summarize(bound,result,config,ledger)
        row.update(label=config['label'],mechanism=config['mechanism'],reused=config['reused'])
        if not config['reused']:
            row['refresh_audit']=audit_refresh(bound,frame,config['payload']['parameters'])
        assert row['account_audit']['known_low_error_potential_orders']==0
        rows[config['label']]=row
    new_bound,new_result=cache_read(CACHE/'N0.pkl.gz')
    assert context(1).runtime.identify(new_bound.strategy,dependencies=DEPENDENCIES).content_sha256==cfg['content_sha256']
    for _,_,old_result in native_accounts:
        for field in ('decisions','orders','fills','account_daily','trades'):
            pd.testing.assert_frame_equal(getattr(old_result.runs[0].buyhold.execution,field),getattr(new_result.runs[0].buyhold.execution,field),check_exact=True)
    write(RUNS/'analysis.json',ledger.plain({'status':'PASS','rows':rows,'cells':plan['cells'],
        'control_reuse':reuse,
        'paired_comparisons':[paired(rows[label],rows['N0'],'Eligibility refresh versus '+label) for label in ('B0-TIME','C0-RANGE_REFRESH')],
        'benchmark_ledgers':'EXACT_EQUAL all 5 ledgers','new_business_configurations':1,'new_account_evaluations':2,
        'qualification_policy':'four unchanged original economic gates; all diagnostics report only'}))
    print({'analysis':'PASS','summary':[{k:r[k] for k in ('label','net_cagr','drawdown','closed_trades','gates','qualified')} for r in rows.values()]},flush=True)


if __name__=='__main__':
    main()
