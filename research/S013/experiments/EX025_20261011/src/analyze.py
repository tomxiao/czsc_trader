"""Reconcile two new bull-duration accounts and two reused controls."""
from statistics import mean
from hashlib import sha256
import json
import pandas as pd
import ledger_reference as ledger
from account_reference import verify_account
from analysis_reference import summarize,paired
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence,validate_evaluation_evidence
from common import ROOT,PROTOCOLS,RUNS,CACHE,read,write,cache_read

def audit_protection(history,p):
    holding=False
    route=None
    age=0
    anchor=peak=0.
    count=0
    for row in history.itertuples():
        condition=trigger=False
        if holding:
            age+=1
            peak=max(peak,row.close)
            rp=p[route]
            loss=rp['stop_loss'] is not None and row.close/anchor-1<=-rp['stop_loss']
            trail=rp['trailing_stop'] is not None and row.close/peak-1<=-rp['trailing_stop']
            condition=route=='bull' and age>=1 and row.close<anchor
            trigger=condition and not (loss or trail)
            timed=age>=rp['max_hold']
            changed=p['exit_on_regime_change'] and row.regime!=route
            ranged=row.range_position>=rp['exit']
            expected=('loss' if loss else 'trailing' if trail else 'bull_anchor_loss' if trigger else
                'range' if ranged else 'time' if timed else 'regime' if changed else 'hold')
            assert row.signal_reason==expected
            if expected!='hold':
                holding=False
                route=None
            count+=int(trigger)
        elif row.signal_reason=='entry':
            holding=True
            route=row.regime
            age=0
            anchor=peak=row.close
        assert row.entry_anchor_signal_close==anchor
        assert bool(row.bull_anchor_loss_condition)==condition
        assert bool(row.bull_anchor_loss_trigger)==trigger
        assert (row.signal_reason=='bull_anchor_loss')==trigger
        assert row.target_position==float(holding)
    return {'status':'PASS','protection_signals':count,
        'oracle':'Independent holding route/age/anchor/peak and full priority, original signal age not execution reset.',
        'units':'Signal entry HFQ Close, not actual execution break-even or net PnL; count is not causal profit contribution.'}


def main():
    assert read(RUNS/'matrix.json')['status']=='COMPLETE'
    assert all(r['status']=='SUCCEEDED' for r in read(RUNS/'matrix.json')['rows'])
    plan=read(PROTOCOLS/'plan.json')
    prior_refs={e:read(ROOT/f'research/S013/assets/runs/{e}/account_references.json') for e in ('EX015_20261011','EX020_20261011')}
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
            row['protection_audit']=audit_protection(history,config['payload']['parameters'])
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
    comparisons=[paired(rows['B0-TIME'],rows['N0'],'Pure bull anchor protection'),paired(rows['B0-BODY'],rows['N1'],'Protection with BODY'),paired(rows['N0'],rows['N1'],'BODY incremental with protection')]
    write(RUNS/'analysis.json' ,ledger.plain({'status':'PASS','rows':rows,'cells':cells,
        'paired_comparisons':comparisons,'control_reuse':reuse,'benchmark_ledgers':'EXACT_EQUAL all 4 accounts',
        'new_business_configurations':2,'new_account_evaluations':3,'historical_controls_reused':2,
        'data_scope':'existing S013 only, already seen development pool; no independent validation',
        'qualification_policy':'four original economic gates only; deleted-coordinate equality is not a robustness result',
        'provider_calls':read(RUNS/'matrix.json')['provider_calls']}))
    print({'analysis':'PASS','summary':[{k:r[k] for k in ('label','net_cagr','drawdown','closed_trades','qualified','gates')} for r in rows.values()]},flush=True)

if __name__=='__main__':
    main()
