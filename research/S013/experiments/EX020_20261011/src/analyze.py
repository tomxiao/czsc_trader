"""Reconcile twelve bull-state accounts and four reused controls."""
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

def main():
    assert read(RUNS/'matrix.json')['status']=='COMPLETE'
    assert all(r['status']=='SUCCEEDED' for r in read(RUNS/'matrix.json')['rows'])
    plan=read(PROTOCOLS/'plan.json')
    prior_refs={e:read(ROOT/f'research/S013/assets/runs/{e}/account_references.json') for e in ('EX015_20261011',)}
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
        if config['mechanism'] in ('NEW_BULL_CLOSE_UP','NEW_BULL_BODY_UP'):
            boundary=history.regime.eq('bull') & history.previous_regime.eq('bear')
            opportunities=history.confirmation_opportunity.astype(bool)
            row['boundary_diagnostic']={'raw_bear_to_bull_sessions':int(boundary.sum()),
                'flat_eligible_boundary_opportunities':int((boundary & opportunities).sum()),
                'original_score_passing_boundary_opportunities':int((boundary & opportunities & history.confirmation_pass.astype(bool)).sum()),
                'boundary_price_rejections':int(history.signal_reason.eq('entry_direction_rejected').sum()),
                'boundary_nonrising_close_sessions':int((boundary & history.entry_signal_close.le(history.previous_signal_close)).sum()),
                'scope':'Raw boundary flag is not an actual entry opportunity; stable bull can enter next day even if price keeps falling.'}
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
    comparisons=[]
    for mechanism in ('NEW_BULL_CLOSE_UP','NEW_BULL_BODY_UP'):
        center=next(c for c in cells if c['background']=='B0' and c['mechanism']==mechanism)
        for cell in cells:
            if cell['mechanism']==mechanism:
                original=rows[cell['background']+'-TIME']
                comparisons.append({**paired(original,rows[cell['label']],'mechanism versus original'),
                    'background':cell['background'],'mechanism':mechanism})
                if cell['background']!='B0':
                    comparisons.append({**paired(rows[center['label']],rows[cell['label']],'local parameter response'),
                        'background':cell['background'],'mechanism':mechanism})
    write(RUNS/'analysis.json',ledger.plain({'status':'PASS','rows':rows,'cells':cells,
        'paired_comparisons':comparisons,'control_reuse':reuse,'benchmark_ledgers':'EXACT_EQUAL all 6 accounts',
        'new_business_configurations':4,'new_account_evaluations':5,'historical_controls_reused':2,
        'data_scope':'existing S013 only, already seen development pool; no independent validation',
        'qualification_policy':'four original economic gates only; deleted-coordinate equality is not a robustness result',
        'provider_calls':read(RUNS/'matrix.json')['provider_calls']}))
    print({'analysis':'PASS','summary':[{k:r[k] for k in ('label','net_cagr','drawdown','closed_trades','qualified','gates')} for r in rows.values()]},flush=True)

if __name__=='__main__':
    main()
