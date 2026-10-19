"""Fixed five audited actual accounts; no replay or new future action labels."""
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path

import audit_ex044_accounts as P

A=P.A
OUT=P.OUT
BASE=P.BASE
ROOT=Path.cwd()


def csv_write(name,rows,columns=None):
    path=OUT/name
    columns=columns or list(rows[0])
    with path.open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns,extrasaction='raise')
        writer.writeheader()
        writer.writerows(rows)
    return {'path':path.relative_to(ROOT).as_posix(),'sha256':sha256(path.read_bytes()).hexdigest(),'rows':len(rows)}


def main():
    indexref=A.read(BASE/'others/accounts_index_ref.json')
    index=A.published(indexref)
    A.check('latest public index is local exact aggregation',index==A.read(BASE/'others/accounts_index.json'))
    records=index['records']
    by_index={r['index']:r for r in records}
    dispatches={A.read(p)['index']:p for p in (BASE/'others/dispatches').glob('*.json')}
    A.check('all dispatches represented including FAILED UNKNOWN',len(by_index)==len(records) and set(by_index)==set(dispatches))
    A.check('five fixed actual successful configurations',len(records)==5 and set(by_index)==set(range(5)))
    resources=[]
    audits=[]
    yearly=[]
    summary=[]
    events=[]
    positions=[]
    paths={}
    economic=defaultdict(list)
    wealth=defaultdict(list)
    baseline_account=None
    source_sha=A.read(OUT/'independent_source_pre_review.json')['source_sha256']
    audit_sha=sha256((OUT/'audit_ex044_accounts.py').read_bytes()).hexdigest()
    for i,record in sorted(by_index.items()):
        A.check('per-run receipt exact',record==A.read(BASE/f'others/accounts/run-{i:03d}.json'))
        resources.append({k:record.get(k) for k in ['index','mode','parameters','candidate','status','evidence','result_hash','error','exception','payload_sha256','runtime_sha256','runtime_implementation_sha256']})
        path=OUT/f'account_{i:03d}_independent_review.json'
        report=A.read(path)
        A.check('independent full actual review PASS',report['status']=='PASS' and record['status']=='SUCCEEDED')
        A.check('review exact immutable actual result',report['account_ref']==record['evidence'] and report['result_hash']==record['result_hash'])
        A.check('single reviewed source',report['source_sha256']==source_sha and report['audit_implementation_sha256']==audit_sha)
        A.check('fixed five approved parameters',record['parameters']==P.FIXED[i])
        audits.append({'path':path.relative_to(ROOT).as_posix(),'sha256':sha256(path.read_bytes()).hexdigest(),'checks':report['checks']})
        account=A.published(record['evidence'])
        if i==0:
            baseline_account=account
        policy=record['mode']
        params={'hold_rule':'ENTRY_GRACE','exit_rule':'SHOCK_PROFIT',**record['parameters']}
        annual=report['original_annual_goal_audit']
        for row in annual:
            if row['year']<=2025:
                keys=['year','opening_equity','closing_equity','return','max_drawdown','buyhold_return','buyhold_drawdown','required_return','return_pass','drawdown_pass','return_difference_vs_original','return_difference_vs_frozen']
                yearly.append({'policy_id':policy,**params,**{k:row[k] for k in keys}})
        s=dict(report['summary'])
        s.pop('without2025_role')
        s.update(nannual_joint_pass_2020_25=sum(r['return_pass'] and r['drawdown_pass'] for r in annual if r['year']<=2025),
                 nannual_return_pass_development2020_24=sum(r['return_pass'] for r in annual if r['year']<=2024),
                 nannual_drawdown_pass_development2020_24=sum(r['drawdown_pass'] for r in annual if r['year']<=2024))
        summary.append({'policy_id':policy,**params,**s})
        for event in report['lifecycle']['events']:
            events.append({'policy_id':policy,**record['parameters'],**event})
        economic[report['economic_path_hashes']['execution_economics_sha256']].append(policy)
        wealth[report['economic_path_hashes']['daily_wealth_sha256']].append(policy)
        daily={A.day(r['date']):r for r in account['runs'][0]['ledgers']['account_daily']['data']}
        paths[policy]=daily
        decisions={A.day(r['signal_date']):r for r in account['runs'][0]['ledgers']['decisions']['data']}
        for year in range(2020,2026):
            D=max(d for d in daily if d.startswith(str(year)))
            d,dec=daily[D],decisions[D]
            positions.append({'policy_id':policy,**record['parameters'],'year':year,'last_session':D,
                              **{key:d[key] for key in ['cash','quantity','close','equity']},
                              'D_target_position':dec['target_position'],'D_exit_pending':dec['exit_pending'],
                              **{key:dec[key] for key in ['entry_index','deadline_index','reservation_index']},
                              'uncompleted_position':d['quantity']>0})
    A.check('30 complete-policy-year rows',len(yearly)==30)
    opportunities=[]
    seen=defaultdict(set)
    for d in baseline_account['runs'][0]['ledgers']['decisions']['data']:
        D=A.day(d['signal_date'])
        if not '2020-01-01'<=D<='2025-12-31':
            continue
        role='FLAT' if not d['held_at_close'] else 'MANDATORY_PENDING' if d['pending_inherited'] else 'MANDATORY_DEADLINE' if d['deadline_exit'] else 'DISCRETIONARY_SUPPORT_EXIT' if d['support_break'] else 'DISCRETIONARY_HOLD'
        row={'D':D,'planned_E':A.day(d['valid_session']),'next_E_beyond2025':A.day(d['valid_session'])>'2025-12-31',
             'baseline_role':role,'entry_index':d['entry_index'],'holding_age':d['holding_age'],
             **{k:d[k] for k in ['original_entry_candidate','candidate_shock','acceleration_condition','shock_condition','cost_stop_condition',
                                  'atr_known','atr_positive','shock_known','atr20_prior','z5','net_profit','cost_loss_atr']}}
        for key in ['acceleration_condition','cost_stop_condition']:
            row['first_cycle_'+key]=bool(d[key] and d['entry_index'] not in seen[key])
            if d[key]:
                seen[key].add(d['entry_index'])
        opportunities.append(row)
    A.check('whole baseline 1455 D states retained',len(opportunities)==1455)
    pathrows=[]
    for D in next(iter(paths.values())):
        if '2020-01-01'<=D<='2025-12-31':
            pathrows.append({'date':D,**{policy:rows[D]['equity'] for policy,rows in paths.items()}})
    outputs={'policy_yearly_summary':csv_write('policy_yearly_summary.csv',yearly),
             'policy_summary':csv_write('policy_summary.csv',summary),
             'policy_year_end_positions':csv_write('policy_year_end_positions.csv',positions),
             'policy_trigger_events':csv_write('policy_trigger_events.csv',events),
             'baseline_opportunity_state':csv_write('baseline_opportunity_state.csv',opportunities),
             'continuous_equity':csv_write('policy_daily_equity_2020_25.csv',pathrows)}
    cases={p:{'annual_return_failed_years':[r['year'] for r in yearly if r['policy_id']==p and not r['return_pass']],
              'annual_drawdown_failed_years':[r['year'] for r in yearly if r['policy_id']==p and not r['drawdown_pass']],
              'worse_than_frozen_years':[r['year'] for r in yearly if r['policy_id']==p and r['return_difference_vs_frozen']<0],
              'better_than_frozen_years':[r['year'] for r in yearly if r['policy_id']==p and r['return_difference_vs_frozen']>0]} for p in paths}
    # Four-cell interaction uses true common-original100000 terminal funds, not summed independent effects.
    ends=[summary[i]['terminal2025_equity'] for i in range(4)]
    interaction=ends[3]-ends[1]-ends[2]+ends[0]
    result={'status':'PASS_ALL_FIVE_FIXED_POLICIES_INDEPENDENTLY_AUDITED','source_sha256':source_sha,
            'fresh_NOOP_exact_EX043004':True,'resources':{'all_dispatched_including_FAILED_UNKNOWN':len(records),
              'status_counts':dict(Counter(r['status'] for r in records)),'records':resources,'public_index_ref':indexref,'formal_registrations':0},
            'account_reports':audits,'total_independent_account_checks':sum(r['checks'] for r in audits),'outputs':outputs,
            'execution_economic_equivalence_classes':dict(economic),'daily_wealth_equivalence_classes':dict(wealth),
            'unique_execution_economic_paths':len(economic),'unique_daily_wealth_paths':len(wealth),
            'baseline_opportunity_counts':{'D':len(opportunities),'roles':dict(Counter(r['baseline_role'] for r in opportunities))},
            'annual_counterexamples':cases,'four_cell_2025_terminal_interaction_money':interaction,
            'interaction_role':'Descriptive difference-of-differences of four actual continuous-funded endpoints; not independent effect addition or a new optimized endpoint.',
            'annual_D_and_actual_cycle_counts':{r['mode']:A.read(OUT/f"account_{r['index']:03d}_independent_review.json")['lifecycle'] for r in records},
            'new_fits':0,'new_strategy_replays':0,'new_dispatches_by_auditor':0,'new_supplier_calls':0,'raw_market_exports':0,
            'limits':['All2020-25 seen; without2025 remains development.','Original fullwindow frequency hard goal unchanged;2020-25 frequency diagnostic separately.',
                      'Yearly returns use own prior-year closing funds; original continuous endpoints use common100000.',
                      'D/cycle observations and5 policies are dependent.','2026 technical only.','No new local counterfactual action-value labels.'],
            'consolidation_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest()}
    path=OUT/'independent_ex044_audit_summary.json'
    P.H.write(path,result)
    print(json.dumps({'status':result['status'],'checks':result['total_independent_account_checks'],'outputs':outputs,'summary_sha256':sha256(path.read_bytes()).hexdigest()}))


if __name__=='__main__':
    main()
