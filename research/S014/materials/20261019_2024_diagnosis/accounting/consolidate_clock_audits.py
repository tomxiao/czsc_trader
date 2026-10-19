"""Two fixed clock audited actual accounts; no replay or new future action labels."""
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path

import audit_clock_accounts as P

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
    A.check('two fixed actual successful clock profiles',len(records)==2 and set(by_index)==set(range(2)))
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
    source_sha=A.read(OUT/'clock_source_pre_review.json')['source_sha256']
    implementations={0:'audit_clock_accounts.py',1:'audit_clock_accounts_v2.py'}
    report_names={0:'clock_account_000_independent_review.json',1:'clock_account_001_independent_review_v2.json'}
    reports_by_index={}
    for i,record in sorted(by_index.items()):
        A.check('per-run receipt exact',record==A.read(BASE/f'others/accounts/run-{i:03d}.json'))
        resources.append({k:record.get(k) for k in ['index','mode','parameters','candidate','status','evidence','result_hash','error','exception','payload_sha256','runtime_sha256','runtime_implementation_sha256']})
        path=OUT/report_names[i]
        report=A.read(path)
        A.check('independent full actual review PASS',report['status']=='PASS' and record['status']=='SUCCEEDED')
        A.check('review exact immutable actual result',report['account_ref']==record['evidence'] and report['result_hash']==record['result_hash'])
        audit_sha=sha256((OUT/implementations[i]).read_bytes()).hexdigest()
        A.check('single source with exact declared audit revision',report['source_sha256']==source_sha and report['audit_implementation_sha256']==audit_sha)
        A.check('fixed two approved clock profiles',record['parameters']==P.FIXED[i])
        audits.append({'path':path.relative_to(ROOT).as_posix(),'sha256':sha256(path.read_bytes()).hexdigest(),'checks':report['checks'],
                       'implementation_path':(OUT/implementations[i]).relative_to(ROOT).as_posix(),'implementation_sha256':audit_sha})
        reports_by_index[i]=report
        account=A.published(record['evidence'])
        if i==0:
            baseline_account=account
        policy=record['mode']
        params={'hold_rule':'ENTRY_GRACE','exit_rule':'SHOCK_PROFIT','entry_guard':'BLOCK_SHOCK','exit_domain':'POSITIVE_P','cost_stop':'BASE',**record['parameters']}
        annual=report['original_annual_goal_audit']
        for row in annual:
            if row['year']<=2025:
                keys=['year','opening_equity','closing_equity','return','max_drawdown','buyhold_return','buyhold_drawdown','required_return','return_pass','drawdown_pass','return_difference_vs_original','return_difference_vs_frozen','return_difference_vs_clock_control']
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
        wealth[report['economic_path_hashes']['funded_wealth_sha256']].append(policy)
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
    A.check('12 complete-clock-profile-year rows',len(yearly)==12)
    opportunities=[]
    seen=defaultdict(set)
    for d in baseline_account['runs'][0]['ledgers']['decisions']['data']:
        D=A.day(d['signal_date'])
        if not '2020-01-01'<=D<='2025-12-31':
            continue
        role='FLAT' if not d['held_at_close'] else 'MANDATORY_PENDING' if d['pending_inherited'] else 'MANDATORY_DEADLINE' if d['deadline_exit'] else 'DISCRETIONARY_SUPPORT_EXIT' if d['support_break'] else 'DISCRETIONARY_HOLD'
        row={'D':D,'planned_E':A.day(d['valid_session']),'next_E_beyond2025':A.day(d['valid_session'])>'2025-12-31',
             'baseline_role':role,'entry_index':d['entry_index'],'holding_age':d['holding_age'],
             'reservation_before_gate':d['reservation_before_gate'],'reservation_after_gate':d['reservation_index'],
             'gate_slot_consumed':d['gate_slot_consumed'],'planned_slot_until':d['planned_slot_until'],
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
    outputs={'policy_yearly_summary':csv_write('clock_policy_yearly_summary.csv',yearly),
             'policy_summary':csv_write('clock_policy_summary.csv',summary),
             'policy_year_end_positions':csv_write('clock_policy_year_end_positions.csv',positions),
             'policy_trigger_events':csv_write('clock_policy_trigger_events.csv',events),
             'baseline_opportunity_state':csv_write('clock_baseline_opportunity_state.csv',opportunities),
             'continuous_equity':csv_write('clock_policy_daily_equity_2020_25.csv',pathrows)}
    cases={p:{'annual_return_failed_years':[r['year'] for r in yearly if r['policy_id']==p and not r['return_pass']],
              'annual_drawdown_failed_years':[r['year'] for r in yearly if r['policy_id']==p and not r['drawdown_pass']],
              'worse_than_frozen_years':[r['year'] for r in yearly if r['policy_id']==p and r['return_difference_vs_frozen']<0],
              'better_than_frozen_years':[r['year'] for r in yearly if r['policy_id']==p and r['return_difference_vs_frozen']>0]} for p in paths}
    prior=A.read(OUT/'independent_ex044_audit_summary.json')
    prior_index=A.published(prior['resources']['public_index_ref'])
    A.check('all five prior frozen actual records retained',len(prior_index['records'])==5 and all(r['status']=='SUCCEEDED' for r in prior_index['records']))
    cumulative_paths=defaultdict(list)
    cumulative_funded=defaultdict(list)
    for r in prior_index['records']:
        report=A.read(OUT/f"account_{r['index']:03d}_independent_review.json")
        A.check('prior record identity retained',report['account_ref']==r['evidence'] and report['result_hash']==r['result_hash'])
        cumulative_paths[report['economic_path_hashes']['execution_economics_sha256']].append('EX044/'+r['mode'])
        account=A.published(r['evidence'])
        cumulative_funded[P.hashes_for(account,account)['funded_wealth_sha256']].append('EX044/'+r['mode'])
    for h,profiles in economic.items():
        cumulative_paths[h].extend('EX045/'+x for x in profiles)
    for h,profiles in wealth.items():
        cumulative_funded[h].extend('EX045/'+x for x in profiles)
    result={'status':'PASS_BOTH_FIXED_CLOCK_PROFILES_INDEPENDENTLY_AUDITED','source_sha256':source_sha,
            'fresh_NOOP_exact_EX044001':True,'resources':{'all_dispatched_including_FAILED_UNKNOWN':len(records),
              'status_counts':dict(Counter(r['status'] for r in records)),'records':resources,'public_index_ref':indexref,'formal_registrations':0},
            'account_reports':audits,'total_independent_account_checks':sum(r['checks'] for r in audits),'outputs':outputs,
            'execution_economic_equivalence_classes':dict(economic),'daily_wealth_equivalence_classes':dict(wealth),
            'unique_execution_economic_paths':len(economic),'unique_daily_wealth_paths':len(wealth),
            'cumulative_EX044_EX045_resources':{'actual_dispatches':len(prior_index['records'])+len(records),
                'status_counts':dict(Counter(r['status'] for r in prior_index['records']+records)),
                'economic_equivalence_classes':dict(cumulative_paths),'unique_economic_paths':len(cumulative_paths),
                'funded_wealth_equivalence_classes':dict(cumulative_funded),'unique_funded_wealth_paths':len(cumulative_funded),
                'source_specific_control_repeats':2,'new_fits':0},
            'baseline_opportunity_counts':{'D':len(opportunities),'roles':dict(Counter(r['baseline_role'] for r in opportunities))},
            'annual_counterexamples':cases,
            'clock_2025_endpoint_difference_money':summary[1]['terminal2025_equity']-summary[0]['terminal2025_equity'],
            'annual_D_and_actual_cycle_counts':{r['mode']:reports_by_index[r['index']]['lifecycle'] for r in records},
            'audit_expression_correction':{'count':1,'account_execution_failures':0,'account_reruns':0,'added_epsilon':0,
                'original_failure_path':(OUT/'clock_account_001_independent_failure.json').relative_to(ROOT).as_posix(),
                'original_failure_sha256':sha256((OUT/'clock_account_001_independent_failure.json').read_bytes()).hexdigest(),
                'investigation_path':(OUT/'clock_limit_boundary_investigation.json').relative_to(ROOT).as_posix(),
                'investigation_sha256':sha256((OUT/'clock_limit_boundary_investigation.json').read_bytes()).hexdigest(),
                'reason':'Original strict float<=limit audit shortcut is stronger than unchanged daily_quote resolver. Successor requires exact price equality to existing public resolver; original artifacts retained.'},
            'new_fits':0,'new_strategy_replays':0,'new_dispatches_by_auditor':0,'new_supplier_calls':0,'raw_market_exports':0,
            'limits':['All2020-25 seen; without2025 remains development.','Original fullwindow frequency hard goal unchanged;2020-25 frequency diagnostic separately.',
                      'Yearly returns use own prior-year closing funds; original continuous endpoints use common100000.',
                      'Virtual opportunity slots are not actual cycles; clock profiles are dependent seen-history contrasts.','2026 technical only.','No new local counterfactual action-value labels.'],
            'consolidation_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest()}
    path=OUT/'independent_clock_audit_summary.json'
    P.H.write(path,result)
    print(json.dumps({'status':result['status'],'checks':result['total_independent_account_checks'],'outputs':outputs,'summary_sha256':sha256(path.read_bytes()).hexdigest()}))


if __name__=='__main__':
    main()
