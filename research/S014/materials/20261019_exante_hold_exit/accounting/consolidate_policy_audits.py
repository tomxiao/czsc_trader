"""Reaggregate nine audited EX043 ledgers; no replay, fit or new account."""
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path

import audit_policy_accounts as P

A=P.A
ROOT=Path.cwd()
OUT=Path(__file__).resolve().parent
BASE=P.BASE

def csv_write(name,columns,rows):
    path=OUT/name
    with path.open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns,extrasaction='raise')
        writer.writeheader()
        writer.writerows(rows)
    return {'path':str(path.relative_to(ROOT)),'sha256':sha256(path.read_bytes()).hexdigest(),'rows':len(rows)}

def verify_index():
    ref=A.read(BASE/'others/accounts_index_ref.json')
    index=A.published(ref)
    A.check('public latest index exact local aggregation',index==A.read(BASE/'others/accounts_index.json'))
    by_index={r['index']:r for r in index['records']}
    dispatches={A.read(p)['index']:p for p in (BASE/'others/dispatches').glob('*.json')}
    A.check('record indices unique',len(by_index)==len(index['records']))
    A.check('all dispatched receipts represented including UNKNOWN',set(by_index)==set(dispatches))
    resources=[]
    for i,row in sorted(by_index.items()):
        A.check('immutable per-run receipt exact',row==A.read(BASE/f'others/accounts/run-{i:03d}.json'))
        resources.append({k:row.get(k) for k in ['index','mode','parameters','candidate','status','evidence','result_hash','error','exception','payload_sha256','runtime_sha256','runtime_implementation_sha256']})
    return index,resources,ref

def main():
    index,resources,indexref=verify_index()
    A.check('all nine declared configurations actually dispatched',len(resources)==9)
    reports=[]
    accounts={}
    yearly,summary,events,positions,paths=[],[],[],[],{}
    repeated=defaultdict(list)
    wealth_repeated=defaultdict(list)
    for record in index['records']:
        i=record['index']
        reportpath=OUT/f'account_{i:03d}_independent_review.json'
        report=A.read(reportpath)
        A.check('all nine independently PASS',record['status']=='SUCCEEDED' and report['status']=='PASS')
        A.check('independent report bound exact public account',report['account_ref']==record['evidence'] and report['result_hash']==record['result_hash'])
        A.check('audit source byte identity',report['audit_implementation_sha256']==sha256((OUT/'audit_policy_accounts.py').read_bytes()).hexdigest())
        reports.append({'path':str(reportpath.relative_to(ROOT)),'sha256':sha256(reportpath.read_bytes()).hexdigest(),'checks':report['checks']})
        account=A.published(record['evidence'])
        accounts[i]=account
        policy=record['mode']
        params=record['parameters']
        for y in report['original_annual_goal_audit']:
            if y['year']<=2025:
                keys=['year','opening_equity','closing_equity','return','max_drawdown','buyhold_return','buyhold_drawdown','required_return','return_pass','drawdown_pass','return_difference_vs_original']
                yearly.append({'policy_id':policy,**params,**{k:y[k] for k in keys}})
        s=dict(report['summary'])
        annual=report['original_annual_goal_audit']
        s['nannual_joint_pass_2020_25']=sum(y['return_pass'] and y['drawdown_pass'] for y in annual if y['year']<=2025)
        s['nannual_return_pass_development2020_24']=sum(y['return_pass'] for y in annual if y['year']<=2024)
        s['nannual_drawdown_pass_development2020_24']=sum(y['drawdown_pass'] for y in annual if y['year']<=2024)
        s.pop('without2025_role')
        summary.append({'policy_id':policy,**params,**s})
        for event in report['lifecycle']['trigger_events']:
            events.append({'policy_id':policy,**params,**event})
        repeated[report['economic_path_hashes']['execution_economics_sha256']].append(policy)
        wealth_repeated[report['economic_path_hashes']['daily_wealth_sha256']].append(policy)
        days={A.day(r['date']):r for r in account['runs'][0]['ledgers']['account_daily']['data']}
        paths[policy]=days
        decisions={A.day(r['signal_date']):r for r in account['runs'][0]['ledgers']['decisions']['data']}
        for year in range(2020,2026):
            last=max(day for day in days if day.startswith(str(year)))
            row=days[last]
            dec=decisions[last]
            positions.append({'policy_id':policy,**params,'year':year,'last_session':last,
                              **{k:row[k] for k in ['cash','quantity','close','equity']},
                              'D_target_position':dec['target_position'],'D_exit_pending':dec['exit_pending'],
                              'entry_index':dec['entry_index'],'deadline_index':dec['deadline_index'],'reservation_index':dec['reservation_index'],
                              'uncompleted_position':row['quantity']>0})
    # Original-state coverage contains no future realized prices/returns or counterfactual labels.
    baseline=accounts[0]
    days={A.day(r['date']):r for r in baseline['runs'][0]['ledgers']['account_daily']['data']}
    seen=defaultdict(set)
    opportunity=[]
    previous=None
    keys=['shock_condition','giveback_condition','entry_grace_eligible','trend_cycle_eligible']
    for row in baseline['runs'][0]['ledgers']['decisions']['data']:
        D=A.day(row['signal_date'])
        inherited=bool(previous and previous['exit_pending'] and not row['sell_filled_today'] and row['held_at_close'])
        previous=row
        if not '2020-01-01'<=D<='2025-12-31':
            continue
        held=bool(row['held_at_close'])
        role='FLAT' if not held else 'MANDATORY_PENDING' if inherited else 'MANDATORY_DEADLINE' if row['deadline_exit'] else 'DISCRETIONARY_SUPPORT_EXIT' if row['support_break'] else 'DISCRETIONARY_HOLD'
        value={'D':D,'planned_E':A.day(row['valid_session']),'next_E_beyond2025':A.day(row['valid_session'])>'2025-12-31',
               'original_role':role,'entry_index':row['entry_index'],'holding_age':row['holding_age'],'actual_D_quantity':days[D]['quantity'],
               **{k:row[k] for k in ['support_break','ma_known','atr_known','shock_known','ma20_prior','ma20_prior_lag5','atr20_prior','sigma20_pre5','z5','net_profit','entry_fill_price','peak_close','peak_net_gain_price','giveback_price',*keys]}}
        for key in keys:
            value['first_cycle_'+key]=bool(row[key] and row['entry_index'] not in seen[key])
            if row[key]:
                seen[key].add(row['entry_index'])
        opportunity.append(value)
    roles=Counter(r['original_role'] for r in opportunity)
    A.check('complete original1455D coverage',len(opportunity)==1455)
    A.check('original668held639discretionary population retained',sum(r['original_role']!='FLAT' for r in opportunity)==668 and roles['DISCRETIONARY_HOLD']+roles['DISCRETIONARY_SUPPORT_EXIT']==639)
    columns=['policy_id','hold_rule','exit_rule','year','opening_equity','closing_equity','return','max_drawdown','buyhold_return','buyhold_drawdown','required_return','return_pass','drawdown_pass','return_difference_vs_original']
    outputs={'policy_yearly_summary':csv_write('policy_yearly_summary.csv',columns,yearly),
             'policy_summary':csv_write('policy_summary.csv',list(summary[0]),summary),
             'year_end_positions':csv_write('policy_year_end_positions.csv',list(positions[0]),positions),
             'trigger_events':csv_write('policy_trigger_events.csv',list(events[0]),events),
             'original_opportunity_state':csv_write('original_opportunity_state.csv',list(opportunity[0]),opportunity)}
    pathrows=[]
    baseline_days=paths['BASE/BASE']
    for day in baseline_days:
        if '2020-01-01'<=day<='2025-12-31':
            pathrows.append({'date':day,**{policy:rows[day]['equity'] for policy,rows in paths.items()}})
    outputs['continuous_equity']=csv_write('policy_daily_equity_2020_25.csv',['date',*paths],pathrows)
    adverse=sorted([r for r in yearly if r['return_difference_vs_original']<0],key=lambda r:r['return_difference_vs_original'])
    favorable=sorted([r for r in yearly if r['return_difference_vs_original']>0],key=lambda r:-r['return_difference_vs_original'])
    cases={policy:{'worse_than_R_years':[r['year'] for r in yearly if r['policy_id']==policy and r['return_difference_vs_original']<0],
                   'better_than_R_years':[r['year'] for r in yearly if r['policy_id']==policy and r['return_difference_vs_original']>0],
                   'annual_return_failed_years':[r['year'] for r in yearly if r['policy_id']==policy and not r['return_pass']],
                   'annual_drawdown_failed_years':[r['year'] for r in yearly if r['policy_id']==policy and not r['drawdown_pass']]} for policy in paths}
    result={'status':'PASS_ALL_NINE_FIXED_POLICIES_INDEPENDENTLY_AUDITED','source_sha256':P.SOURCE_SHA,'source_NOOP_exact_original':True,
            'resources':{'all_dispatched_including_FAILED_UNKNOWN':len(resources),'status_counts':dict(Counter(r['status'] for r in resources)),
                         'records':resources,'public_index_ref':indexref,'formal_candidate_registrations':0},
            'account_reports':reports,'outputs':outputs,'total_independent_account_checks':sum(r['checks'] for r in reports),
            'execution_economic_equivalence_classes':dict(repeated),'daily_wealth_equivalence_classes':dict(wealth_repeated),
            'unique_execution_economic_paths':len(repeated),'unique_daily_wealth_paths':len(wealth_repeated),
            'original_opportunity_counts':{'D':len(opportunity),'role_counts':dict(roles)},
            'annual_counterexamples':{'all_policy_year_signs':cases,'strongest_adverse_vs_original':adverse[:12],'strongest_favorable_vs_original':favorable[:12]},
            'annual_D_trigger_and_cycle_counts':{r['mode']:A.read(OUT/f"account_{r['index']:03d}_independent_review.json")['lifecycle'] for r in index['records']},
            'new_fits':0,'new_strategy_replays':0,'new_account_dispatches_by_auditor':0,'new_market_supplier_calls':0,
            'limits':['All2020-25 history shared-seen; without2025 is2020-24 development reaggregation, not heldout.',
                      'Each annual return uses own prior-year closing equity; continuous path uses common original100000.',
                      'Original full-window frequency remains original hard criterion;2020-25 frequency is separately diagnostic.',
                      'Trigger D counts and cycle counts are dependent state observations; nine configurations are not independent samples.',
                      'Actual cycle profitability after a trigger is not an isolated local action-advantage label; no new local counterfactual labels calculated.',
                      '2026 remains original-contract technical tail only.'],
            'consolidation_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest()}
    writepath=OUT/'independent_policy_audit_summary.json'
    P.write(writepath,result)
    print(json.dumps({'status':result['status'],'checks':result['total_independent_account_checks'],'unique_economic_paths':len(repeated),'summary_sha256':sha256(writepath.read_bytes()).hexdigest(),'outputs':outputs}))

if __name__=='__main__':
    main()
