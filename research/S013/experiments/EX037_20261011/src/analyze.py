"""Reconcile two short ACF accounts and two full reused controls."""
from statistics import mean
from hashlib import sha256
import json
import pandas as pd
import ledger_reference as ledger
from account_reference import verify_account
from analysis_reference import summarize,paired
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence,validate_evaluation_evidence
from common import ROOT,PROTOCOLS,RUNS,CACHE,read,write,cache_read,context
import numpy as np

def audit_acf(bound,history,p):
    binding=next(iter(bound.input_bindings.values()))
    fetched=context(1).data.fetch(binding.plan.requests['daily'],prepared=binding.prepared)
    assert fetched.ready
    bars=fetched.dataframe.copy()
    dates=pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
    returns=pd.Series(bars.Close.to_numpy(dtype=float),index=dates).pct_change(fill_method=None)
    def lag_covariance(values):
        centered=values-np.mean(values)
        variance=np.mean(centered**2)
        return np.nan if np.isclose(variance,0) else float(np.dot(centered[1:],centered[:-1])/19/variance)
    raw=returns.rolling(20).apply(lag_covariance,raw=True)
    rolling=raw.shift(1).rolling(p['confirmation']['lookback'],min_periods=p['confirmation']['lookback'])
    baseline=rolling.mean()
    filtered=raw-baseline
    selected=pd.DatetimeIndex(pd.to_datetime(history.signal_date)).normalize()
    np.testing.assert_allclose(history.bear_acf_raw,raw.reindex(selected),rtol=0,atol=0,equal_nan=True)
    np.testing.assert_allclose(history.bear_acf_centered,filtered.reindex(selected),rtol=0,atol=0,equal_nan=True)
    np.testing.assert_allclose(history.bear_acf_baseline,baseline.reindex(selected),rtol=0,atol=0,equal_nan=True)
    # Threshold comparison uses >=, finite estimates required; routing/score/ledger audited separately.
    expected=np.isfinite(filtered.reindex(selected)) & filtered.reindex(selected).ge(p['bear']['acf_min'])
    crossings=int(np.count_nonzero(np.asarray(expected)!=np.asarray(raw.reindex(selected).ge(p['bear']['acf_min']))))
    bars.index=dates
    close=bars.Close.astype(float)
    regime=(close/close.shift(p['regime_window'])-1).reindex(selected)
    range_positions={r:((close-bars.Low.rolling(p[r]['range_window']).min())/
        (bars.High.rolling(p[r]['range_window']).max()-bars.Low.rolling(p[r]['range_window']).min())).reindex(selected)
        for r in ('bull','bear')}
    momentum=(close/close.shift(20)-1).reindex(selected)
    previous_regime=np.where((close/close.shift(p['regime_window'])-1).shift(1).reindex(selected)>=p['regime_threshold'],'bull','bear')
    previous_close=close.shift(1).reindex(selected)
    np.testing.assert_array_equal(history.previous_regime,previous_regime)
    np.testing.assert_array_equal(history.entry_signal_close,close.reindex(selected))
    np.testing.assert_array_equal(history.entry_signal_open,bars.Open.reindex(selected))
    np.testing.assert_array_equal(history.previous_signal_close,previous_close)
    raw_features={'acf':raw,'turnover':bars.Amount.astype(float)/bars.Amount.astype(float).rolling(20).mean(),
        'volume':np.log(bars.Volume.astype(float)).diff().rolling(20).mean()}
    def rank(v):
        return float(((v<v[-1]).sum()+.5*(v==v[-1]).sum())/len(v)-.5)
    normalized={name:series.rolling(p['confirmation']['lookback']).apply(rank,raw=True).reindex(selected) for name,series in raw_features.items()}
    for name,series in normalized.items():
        np.testing.assert_array_equal(history['confirmation_'+name],series)
    np.testing.assert_array_equal(history.confirmation_score,.5*normalized['acf']+.25*normalized['turnover']+.25*normalized['volume'])
    previous=close.shift(1)
    tr=pd.concat([bars.High-bars.Low,(bars.High-previous).abs(),(bars.Low-previous).abs()],axis=1).max(axis=1)
    unit=tr.shift(1).rolling(20).mean().reindex(selected)
    np.testing.assert_array_equal(history.risk_true_range_hfq,tr.reindex(selected))
    np.testing.assert_array_equal(history.risk_reference_mean20_hfq,unit)
    assert np.isfinite(unit.to_numpy()).all() and (unit>0).all()
    risk_hits=0
    holding=False
    active=None
    age=0
    anchor=peak=0.
    last=None
    for i,row in enumerate(history.itertuples()):
        current='bull' if regime.iloc[i]>=p['regime_threshold'] else 'bear'
        assert row.regime==current
        route=active if holding else current
        rp=p[route]
        position=range_positions[route].iloc[i]
        acf=filtered.reindex(selected).iloc[i] if route=='bear' else raw.reindex(selected).iloc[i]
        passed_acf=rp['acf_min'] is None or acf>=rp['acf_min']
        assert row.entry_acf_value==acf and bool(row.entry_acf_pass)==bool(passed_acf)
        assert row.range_position==position
        eligible=(position<=rp['entry'] and passed_acf and
            (rp['momentum_min'] is None or momentum.iloc[i]>=rp['momentum_min']))
        c=p['confirmation']
        applies=c['scope'] in ('both',current) and (p['context']['entry_gate']=='all' or last=='regime')
        passed=not applies or row.confirmation_score>=c['threshold']
        direction_up=(row.close>previous_close.iloc[i] if p['mechanism']=='MEAN_ACF_NEW_BULL_CLOSE' else row.close>bars.Open.reindex(selected).iloc[i])
        gate_applies=p['mechanism']=='BEAR_MEAN_ACF_BODY_ADVERSE_TR' and current=='bull' and previous_regime[i]=='bear'
        state_pass=not gate_applies or direction_up
        assert bool(row.entry_direction_up)==bool(direction_up) and bool(row.entry_direction_gate_applies)==bool(gate_applies)
        assert bool(row.confirmation_opportunity)==bool(not holding and eligible)
        assert bool(row.confirmation_pass)==bool(passed)
        assert row.confirmation_exit_context==(last or 'initial')
        reason='flat'
        adverse=max(anchor-row.close,0.) if holding and active=='bear' else 0.
        hit=bool(holding and active=='bear' and adverse>=unit.iloc[i])
        assert row.bear_adverse_displacement_hfq==adverse and bool(row.bear_risk_hit)==hit
        if holding:
            age+=1
            peak=max(peak,row.close)
            loss=rp['stop_loss'] is not None and row.close/anchor-1<=-rp['stop_loss']
            trail=rp['trailing_stop'] is not None and row.close/peak-1<=-rp['trailing_stop']
            reason=('loss' if loss else 'trailing' if trail else 'bear_risk' if hit else 'range' if position>=rp['exit']
                else 'time' if age>=rp['max_hold'] else 'regime' if p['exit_on_regime_change'] and current!=active else 'hold')
            if reason!='hold':
                holding=False
                active=None
                last=reason
        elif eligible:
            reason='entry_direction_rejected' if not state_pass else 'entry' if passed else 'confirmation_rejected'
            if passed and state_pass:
                holding=True
                active=current
                age=0
                anchor=peak=row.close
                last=None
        assert bool(row.bear_risk_trigger)==(reason=='bear_risk')
        assert row.holding_age==age and row.entry_anchor_signal_close==anchor
        risk_hits+=int(reason=='bear_risk')
        assert row.signal_reason==reason and row.target_position==float(holding)
    return {'status':'PASS','threshold_gate_changed_days':crossings,'bear_risk_exits':risk_hits,'oracle':'Independent full bound Close returns, ACF20 covariance, strictlylagged L baseline centering, ranges, raw regime and full holding/entry/exit state machine; exact daily values, opportunities and reasons.'}


def main():
    assert read(RUNS/'matrix.json')['status']=='COMPLETE'
    assert all(r['status']=='SUCCEEDED' for r in read(RUNS/'matrix.json')['rows'])
    plan=read(PROTOCOLS/'plan.json')
    prior_refs={e:read(ROOT/f'research/S013/assets/runs/{e}/account_references.json') for e in ('EX015_20261011','EX028_20261011','EX029_20261011')}
    ledger.verify_account=verify_account
    rows={}
    reuse={}
    bound_results={}
    for config in plan['controls']+plan['configurations']:
        label=config['label']
        if config['reused']:
            old_label=config['reuse_label']
            old_exp=config['reuse_from']
            ref=EvidenceRef.from_dict(prior_refs[old_exp][old_label])
            cache_path=ROOT/'.tmp'/('s013-mechanism-'+old_exp[:5])/(old_label+'.pkl.gz')
            while not cache_path.exists():
                old_plan=read(ROOT/f'research/S013/experiments/{old_exp}/protocols/plan.json')
                original=next(c for c in old_plan['controls'] if c['label']==old_label)
                old_exp,old_label=original['reuse_from'],original['reuse_label']
                cache_path=ROOT/'.tmp'/('s013-mechanism-'+old_exp[:5])/(old_label+'.pkl.gz')
            bound,result=cache_read(cache_path)
            raw=(ROOT/ref.repository_path).read_bytes()
            assert sha256(raw).hexdigest()==ref.sha256
            formal=read(ROOT/ref.repository_path)
            validate_evaluation_evidence(formal)
            reconstructed=serialize_evaluation_evidence(bound,result)
            assert reconstructed==formal, 'Cached control differs from immutable full account'
            reuse[label]={'reference':ref.to_dict(),'comparison':'EXACT_EQUAL entire serialized account',
                'request_hash':result.request_hash,'result_hash':result.result_hash}
        else:
            bound,result=cache_read(CACHE/(label+'.pkl.gz'))
        assert result.runs[0].identity.content_sha256==config['content_sha256']
        assert json.loads(json.dumps(dict(bound.strategy.payload),default=dict))==config['payload']
        row,history=summarize(bound,result,config,ledger)
        if not config['reused']:
            row['acf_audit']=audit_acf(bound,history,config['payload']['parameters'])
        row.update(label=label,mechanism=config['mechanism'],reused=config['reused'],key=config.get('key'))
        assert row['account_audit']['known_low_error_potential_orders']==0
        closed=[c for c in row['paths']['cycles'] if c['status']=='CLOSED']
        row['holding_diagnostic']={'mean_closed_sessions':mean(c['holding_sessions'] for c in closed),
            'max_closed_sessions':max(c['holding_sessions'] for c in closed),
            'bear_closed_cycles':len([c for c in closed if c['entry_route']=='bear']),
            'bear_time_exits':sum(c['entry_route']=='bear' and c['exit_reason']=='time' for c in closed),
            'open_tail_cycles':[c for c in row['paths']['cycles'] if c['status']!='CLOSED']}
        if config['payload']['parameters']['bear']['max_hold'] is None:
            assert row['holding_diagnostic']['bear_time_exits']==0
        rows[label]=row
        bound_results[label]=(bound,result)
    benchmark=bound_results['B0-TIME'][1].runs[0].buyhold.execution
    for label,(bound,result) in bound_results.items():
        own=result.runs[0].buyhold.execution
        for field in ('decisions','orders','fills','account_daily','trades'):
            pd.testing.assert_frame_equal(getattr(benchmark,field),getattr(own,field),check_exact=True)
    cells=[{**cell,'net_cagr':rows[cell['label']]['net_cagr'],
        'drawdown':rows[cell['label']]['drawdown'],'closed_trades':rows[cell['label']]['closed_trades'],
        'qualified':rows[cell['label']]['qualified'],'gates':rows[cell['label']]['gates']} for cell in plan['cells']]
    comparisons=[paired(rows['B0-MEAN'],rows['N0'],'Bear risk exit on meanACF'),paired(rows['B0-BODY'],rows['N1'],'Bear risk exit on meanACF BODY'),paired(rows['N0'],rows['N1'],'BODY context with same risk exit')]
    write(RUNS/'analysis.json' ,ledger.plain({'status':'PASS','rows':rows,'cells':cells,
        'paired_comparisons':comparisons,'control_reuse':reuse,'benchmark_ledgers':'EXACT_EQUAL all 5 accounts',
        'new_business_configurations':2,'new_account_evaluations':3,'historical_controls_reused':3,
        'data_scope':'existing S013 only, already seen development pool; no independent validation',
        'qualification_policy':'four original economic gates only; deleted-coordinate equality is not a robustness result',
        'provider_calls':read(RUNS/'matrix.json')['provider_calls']}))
    print({'analysis':'PASS','summary':[{k:r[k] for k in ('label','net_cagr','drawdown','closed_trades','qualified','gates')} for r in rows.values()]},flush=True)

if __name__=='__main__':
    main()
