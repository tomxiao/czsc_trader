"""Interpret the full fixed five-arm tables, with no new policy selection or replay."""
import csv
from hashlib import sha256
import json
from pathlib import Path

P=Path(__file__).resolve().parent


def read(name):
    return json.loads((P/name).read_bytes())


def table(name):
    with (P/name).open(encoding='utf-8',newline='') as stream:
        return list(csv.DictReader(stream))


def main():
    audit=read('independent_ex044_audit_summary.json')
    annual=table('policy_yearly_summary.csv')
    summary=table('policy_summary.csv')
    assert len(annual)==30 and len(summary)==5
    reports=[read(f'account_{i:03d}_independent_review.json') for i in range(5)]
    assert all(x['status']=='PASS' for x in reports)
    cost=reports[4]['lifecycle']
    costevents=[x for x in cost['events'] if x['cost_exit_added_vs_baseline']]
    rows=[]
    for report,s in zip(reports,summary,strict=True):
        policy=report['policy_id']
        rows.append({'policy_id':policy,'parameters':report['parameters'],
                     'annual_returns_percent':{x['year']:100*float(x['return']) for x in annual if x['policy_id']==policy},
                     'annual_return_failed_years':[int(x['year']) for x in annual if x['policy_id']==policy and x['return_pass']=='False'],
                     'annual_return_pass_count':int(s['nannual_return_pass_2020_25']),
                     'annual_drawdown_pass_count':int(s['nannual_drawdown_pass_2020_25']),
                     'original_frequency':float(s['frequency_full_contract']),
                     'completeyears_frequency_diagnostic':float(s['frequency_completeyears_diagnostic']),
                     'terminal2024_equity':float(s['development_without2025_end2024_equity']),
                     'terminal2025_equity':float(s['terminal2025_equity']),
                     'continuous2020_24_return_percent':100*float(s['development_without2025_continuous_return_from100000']),
                     'continuous2020_25_return_percent':100*float(s['continuous2020_2025_return_from100000']),
                     'first_target_divergence_D':report['prefix']['first_target_divergence_D']})
    result={'status':'COMPLETE_FIXED_FIVE_REAL_ACCOUNT_DIAGNOSIS_NOT_FULL_ORIGINAL_GOAL_ACHIEVEMENT',
            'technical_status':'PASS all5;815749 independent checks; freshNOOP strictEX043004; full1642D funded-shadow alignment; original fees/price limits/status/clock/reservation',
            'resources':{'actual_dispatches':5,'SUCCEEDED':5,'FAILED':0,'UNKNOWN':0,'retries':0,'source_specific_NOOP_controls':1,
                         'distinct_full_economic_paths':audit['unique_execution_economic_paths'],'new_fits':0,'threshold_searches':0,
                         'new_supplier_calls':0,'new_counterfactual_action_labels':0,'auditor_dispatches':0,'raw_market_exports':0},
            'five_policy_facts':rows,
            'economic_repeats':audit['execution_economic_equivalence_classes'],
            'completeyears_all_original_goals_pass_count':sum(r['annual_return_pass_count']==6 and r['annual_drawdown_pass_count']==6 and r['original_frequency']>=3 for r in rows),
            'cost_action_attribution':{
                'annual_selected_cost_D':{y:c.get('selected_cost_exit',0) for y,c in cost['annual_D_counts'].items()},
                'annual_added_cost_exit_D':{y:c.get('cost_exit_added_vs_baseline',0) for y,c in cost['annual_D_counts'].items()},
                'annual_added_cost_distinct_cycles':{y:c.get('cost_exit_added_vs_baseline',0) for y,c in cost['annual_distinct_held_cycles'].items()},
                '2024_selected_cost_D':9,'2024_selected_cost_distinct_cycles':9,'2024_support_overlap':6,'2024_added_cost_cycles':3,'2024_grace_overrides':0,
                'actual_added_cost_events':[x for x in costevents if x['D'].startswith('2024')],
                'interpretation':'Most selected cost exits coincide with already planned ordinary support exits; count only3new2024 exits, not9new independent rescues. B separately examines ATR-shrink/no-new-decline transitions.'},
            'four_cell_2025_endpoint_interaction_money':audit['four_cell_2025_terminal_interaction_money'],
            'judgment':[
                'UniformZ entry blocking repairs2024 in this complete path but loses original target achievement in2021,2022,2025. Return-pass count drops5of6 to3of6. A successful2024 is not full-strategy acceptance.',
                'Removing positiveP has a real independent held-risk responsibility, but improves2024 by only0.9291896percentagepoints, still negative20.2281451%. With entryguard enabled it makes no economic-path change at all in this original window.',
                'NET currentpriorATR1 improves2024 by8.7848798percentagepoints and improves2020-24 continuous terminal wealth, while costing2023 2.6693649percentagepoints. It retains5of6 annual-return passes;2024 still fails at negative12.3724550%.',
                'Costrisk gives new exits on2024Jan30,Jul15,Oct9, after their observable costs/marks. It cannot undo entryday loss or guarantee nextE prices. CurrentATR can change without a new decline; do not call it a fixed currency stop-loss cap.',
                'Every policy meets completeyears drawdown and original fullwindow frequency goals. The binding unresolved economic goal is annual return; no extra sample-size or annualnonharm veto is imposed.',
                'Do not combine standalone improvements arithmetically. The entryguard plusANY_P is exactly the entryguard path, showing overlap through changed participation rather than two independent gains.',
                'The next useful research question is remaining2024 adverse-entry exposure after preserving the distinct cost-risk responsibility. These observations do not support selecting a weakerATR/Z threshold from the failed cases.'
            ],
            'scope_limits':['All2020-25 are already seen;2020-24without2025 is a shared development reaggregation, not heldout.',
                            'Each annualreturn uses its own yearopening; common100000 only for continuous wealth. Cross-policy terminal capital does not isolate one2025 action.',
                            '2026 remains original full-contract technical accounting and frequency audit only, with no2026economic rule selection.',
                            'RepeatedD and selected triggers are not independent samples;5configurations only4complete economic paths.'],
            'references':{name:{'path':(P/name).relative_to(Path.cwd()).as_posix(),'sha256':sha256((P/name).read_bytes()).hexdigest()} for name in [
                'independent_ex044_audit_summary.json','policy_yearly_summary.csv','policy_summary.csv','policy_trigger_events.csv','policy_year_end_positions.csv',
                'initial_reconciliation_source_archive.json']},
            'implementation_sha256':sha256(Path(__file__).read_bytes()).hexdigest()}
    path=P/'ex044_research_findings.json'
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')
    print(path.relative_to(Path.cwd()).as_posix(),sha256(path.read_bytes()).hexdigest())


if __name__=='__main__':
    main()
