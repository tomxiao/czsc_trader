"""Reconcile two persistent bull-protection accounts and four reused controls."""
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

def audit_protection(bound,history,p):
    binding=next(iter(bound.input_bindings.values()))
    fetched=context(1).data.fetch(binding.plan.requests['daily'],prepared=binding.prepared)
    assert fetched.ready
    bars=fetched.dataframe.copy()
    bars.index=pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
    selected=pd.DatetimeIndex(pd.to_datetime(history.signal_date)).normalize()
    close=bars.Close.astype(float)
    returns=close.pct_change(fill_method=None)
    def covariance(values):
        centered=values-np.mean(values)
        variance=np.mean(centered**2)
        return np.nan if np.isclose(variance,0) else float(np.dot(centered[1:],centered[:-1])/19/variance)
    acf=returns.rolling(20).apply(covariance,raw=True).reindex(selected)
    raw=close/close.shift(p['regime_window'])-1
    bears=raw.lt(p['regime_threshold']).astype(float).where(np.isfinite(raw))
    counts=bears.rolling(3,min_periods=3).sum().reindex(selected)
    np.testing.assert_array_equal(history.raw_bear_count3,counts)
    momentum=raw.reindex(selected)
    positions={r:((close-bars.Low.rolling(p[r]['range_window']).min())/
        (bars.High.rolling(p[r]['range_window']).max()-bars.Low.rolling(p[r]['range_window']).min())).reindex(selected)
        for r in ('bull','bear')}
    np.testing.assert_array_equal(history.bull_range_position,positions['bull'])
    np.testing.assert_array_equal(history.bear_range_position,positions['bear'])
    momentum20=(close/close.shift(20)-1).reindex(selected)
    prices=close.reindex(selected)
    holding=False
    route=None
    age=0
    anchor=peak=0.
    last=None
    changed_days=regime_exits=currentbull_exits=0
    for i,row in enumerate(history.itertuples()):
        current='bull' if momentum.iloc[i]>=p['regime_threshold'] else 'bear'
        assert row.regime==current and row.regime_momentum==momentum.iloc[i]
        active=route if holding else current
        rp=p[active]
        position=positions[active].iloc[i]
        assert row.range_position==position
        eligible=(position<=rp['entry'] and (rp['acf_min'] is None or acf.iloc[i]>=rp['acf_min'])
            and (rp['momentum_min'] is None or momentum20.iloc[i]>=rp['momentum_min']))
        c=p['confirmation']
        applies=c['scope'] in ('both',current) and (p['context']['entry_gate']=='all' or last=='regime')
        passed=not applies or row.confirmation_score>=c['threshold']
        assert bool(row.confirmation_opportunity)==bool(not holding and eligible)
        assert bool(row.confirmation_pass)==bool(passed)
        assert row.confirmation_exit_context==(last or 'initial')
        condition=trigger=False
        reason='flat'
        if holding:
            age+=1
            peak=max(peak,prices.iloc[i])
            loss=rp['stop_loss'] is not None and prices.iloc[i]/anchor-1<=-rp['stop_loss']
            trail=rp['trailing_stop'] is not None and prices.iloc[i]/peak-1<=-rp['trailing_stop']
            condition=bool(p['exit_on_regime_change'] and
                ((counts.iloc[i]==3 if p['mechanism']=='BULL_EXIT_BEAR3' else counts.iloc[i]>=2)
                 if active=='bull' else current=='bull'))
            ranged=position>=rp['exit']
            timed=age>=rp['max_hold']
            trigger=condition and not(loss or trail or ranged or timed)
            changed_days+=int(condition!=bool(p['exit_on_regime_change'] and current!=active))
            reason=('loss' if loss else 'trailing' if trail else 'range' if ranged else 'time' if timed
                    else 'regime' if condition else 'hold')
            if reason!='hold':
                regime_exits+=int(reason=='regime')
                currentbull_exits+=int(reason=='regime' and active=='bull' and current=='bull')
                holding=False
                route=None
                last=reason
        elif eligible:
            reason='entry' if passed else 'confirmation_rejected'
            if passed:
                holding=True
                route=current
                age=0
                anchor=peak=prices.iloc[i]
                last=None
        assert bool(row.regime_exit_condition)==condition and bool(row.regime_exit_trigger)==trigger
        assert row.signal_reason==reason and row.target_position==float(holding)
    return {'status':'PASS','condition_changed_holding_days':changed_days,'regime_exits':regime_exits,
        'bull_regime_exits_on_current_rawbull':currentbull_exits,
        'oracle':'Independent boundClose rawACF20/ranges/regime/rolling3 bearcount, unchangedentry and fullroute/age/anchor/peak/exit priority; preentry states included, majority mayexit on rawbull.'}


def main():
    assert read(RUNS/'matrix.json')['status']=='COMPLETE'
    assert all(r['status']=='SUCCEEDED' for r in read(RUNS/'matrix.json')['rows'])
    plan=read(PROTOCOLS/'plan.json')
    prior_refs={e:read(ROOT/f'research/S013/assets/runs/{e}/account_references.json') for e in ('EX015_20261011','EX017_20261011','EX024_20261011')}
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
            row['protection_audit']=audit_protection(bound,history,config['payload']['parameters'])
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
    comparisons=[paired(rows['B0-TIME'],rows['N0'],'Continuous3 exit versus original'),paired(rows['B0-TIME'],rows['N1'],'Majority3 exit versus original'),paired(rows['E2-EXIT'],rows['N0'],'Continuous3 versus old2 exit'),paired(rows['R3-ALL'],rows['N1'],'Exitonly majority versus fullroute majority'),paired(rows['N0'],rows['N1'],'Majority3 versus continuous3')]
    write(RUNS/'analysis.json' ,ledger.plain({'status':'PASS','rows':rows,'cells':cells,
        'paired_comparisons':comparisons,'control_reuse':reuse,'benchmark_ledgers':'EXACT_EQUAL all 5 accounts',
        'new_business_configurations':2,'new_account_evaluations':3,'historical_controls_reused':3,
        'data_scope':'existing S013 only, already seen development pool; no independent validation',
        'qualification_policy':'four original economic gates only; deleted-coordinate equality is not a robustness result',
        'provider_calls':read(RUNS/'matrix.json')['provider_calls']}))
    print({'analysis':'PASS','summary':[{k:r[k] for k in ('label','net_cagr','drawdown','closed_trades','qualified','gates')} for r in rows.values()]},flush=True)

if __name__=='__main__':
    main()
