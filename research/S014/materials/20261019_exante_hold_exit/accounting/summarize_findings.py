"""Derive concise interpretation facts from complete audited nine-policy tables."""
import csv
from hashlib import sha256
import json
from pathlib import Path

BASE=Path(__file__).resolve().parent

def table(name):
    with (BASE/name).open(encoding='utf-8',newline='') as stream:
        return list(csv.DictReader(stream))

def main():
    rows=table('policy_yearly_summary.csv')
    summaries=table('policy_summary.csv')
    annual={(r['policy_id'],int(r['year'])):r for r in rows}
    summary={r['policy_id']:r for r in summaries}
    best='ENTRY_GRACE/SHOCK_PROFIT'
    original='BASE/BASE'
    b25=annual[best,2025]
    b21=annual[best,2021]
    r21=annual[original,2021]
    y24=[r for r in rows if r['year']=='2024']
    y22=[r for r in rows if r['year']=='2022']
    total=json.loads((BASE/'independent_policy_audit_summary.json').read_bytes())
    assert len(rows)==54 and len(summaries)==9 and total['status']=='PASS_ALL_NINE_FIXED_POLICIES_INDEPENDENTLY_AUDITED'
    assert all(float(r['return'])<0 and r['return_pass']=='False' for r in y24)
    facts={
        'audit_status':{'actual_dispatches':9,'SUCCEEDED':9,'FAILED':0,'UNKNOWN':0,'new_fits':0,
                        'independent_account_checks':total['total_independent_account_checks'],
                        'runtime_actual_inventory_buy_sell_all1642D_each_policy':'PASS',
                        'new_source_NOOP_exact_original':'PASS','execution_rule_and_fee_audit_all_policies':'PASS',
                        'unique_execution_economic_paths':total['unique_execution_economic_paths'],
                        'economic_equivalence_classes':total['execution_economic_equivalence_classes']},
        'original_2020_25':{'annual_return_pass_count':int(summary[original]['nannual_return_pass_2020_25']),
                            'annual_drawdown_pass_count':int(summary[original]['nannual_drawdown_pass_2020_25']),
                            'return_failed_years':[y for y in range(2020,2026) if annual[original,y]['return_pass']=='False']},
        'ENTRY_GRACE_SHOCK_PROFIT':{'annual_return_pass_count':int(summary[best]['nannual_return_pass_2020_25']),
                                  'annual_drawdown_pass_count':int(summary[best]['nannual_drawdown_pass_2020_25']),
                                  'return_failed_years':[y for y in range(2020,2026) if annual[best,y]['return_pass']=='False'],
                                  '2025_actual_return':float(b25['return']),'2025_required_return':float(b25['required_return']),
                                  '2025_return_margin_pp':100*(float(b25['return'])-float(b25['required_return'])),
                                  '2025_drawdown':float(b25['max_drawdown']),'2025_own_opening':float(b25['opening_equity']),
                                  '2025_closing_equity':float(b25['closing_equity']),
                                  '2021_actual_return':float(b21['return']),'2021_original_return':float(r21['return']),
                                  '2021_difference_vs_R_pp':100*(float(b21['return'])-float(r21['return'])),
                                  '2021_still_passes_original_return_goal':b21['return_pass']=='True',
                                  '2020_24_continuous_return':float(summary[best]['development_without2025_continuous_return_from100000']),
                                  '2020_24_original_continuous_return':float(summary[original]['development_without2025_continuous_return_from100000']),
                                  '2020_24_cumulative_return_difference_pp':100*(float(summary[best]['development_without2025_continuous_return_from100000'])-float(summary[original]['development_without2025_continuous_return_from100000']))},
        '2022_counterexamples':{'all_nine_return_rows':y22,
                               'ENTRY_GRACE_all_three_positive':all(float(r['return'])>0 for r in y22 if r['hold_rule']=='ENTRY_GRACE'),
                               'BASE_and_TREND_all_six_still_negative':all(float(r['return'])<0 for r in y22 if r['hold_rule']!='ENTRY_GRACE'),
                               'limit':'Pure SHOCK and GIVEBACK have no newly selected profit exits in D2022 on BASE/TREND paths. Changes in annual results can reflect earlier decisions and positions carried across the year boundary, not new2022 risk triggers. BASE/SHOCK exits on D2021-12-24/E12-27 and enters2022 flat, whereas R holds50800 research units at2021-12-31.'},
        '2024_common_failure':{'all_nine_negative':True,'best_return':max(float(r['return']) for r in y24),
                              'worst_return':min(float(r['return']) for r in y24),'required_return':float(y24[0]['required_return']),
                              'same_contract_BuyHold_return':float(y24[0]['buyhold_return']),
                              'ENTRY_GRACE_SHOCK_triggered_profit_exits':total['annual_D_trigger_and_cycle_counts'][best]['annual_D_counts']['2024']['selected_profit_exit'],
                              'all_nine_return_rows':y24},
        'frequency':{policy:{key:float(row[key]) for key in ['frequency_full_contract','frequency_completeyears_diagnostic']} for policy,row in summary.items()},
        'all_original_goals_fully_passed_policy_count':sum(int(r['nannual_return_pass_2020_25'])==6 and int(r['nannual_drawdown_pass_2020_25'])==6 and r['original_frequency_pass']=='True' for r in summaries)
    }
    result={'status':'COMPLETE_NINE_POLICY_FACTS_AND_RESEARCH_LIMITS','facts':facts,
            'judgment':[
                'The entry-day-only grace and positive-profit shock exit have historically useful complementary behavior: the combined recurring policy passes2022 and2025 original annual-return goals, unlike R. It still fails2024, so no qualifying strategy has been found.',
                'The strongest cross-year cost is2021: the combined policy gives up68.2835 percentage points versus R while still passing that year original goals. This is an economic tradeoff, not a new no-harm rejection rule.',
                'Without2025, the combined policy cumulative2020-24 return is slightly below R. Its strongest result therefore cannot be presented as uniform historical dominance or genuinely heldout validation.',
                'TREND_CYCLE protection activates only one cycle in2020 and one in2023, and none in2025. Small later-year return differences when no protection triggers can come from the prior funded path; they are not evidence of a new same-year hold decision.',
                'All nine2024 paths remain negative despite several selected profit exits. The current mechanisms do not resolve the main remaining year; moving a threshold to reproduce selected2024 examples would be a new development revision.',
                'Every source shadow holding flag was matched to the actual cash-funded account and actual BUY/SELL fills, with original T+1, blocked-sale pending, fees, deadline and reservation checked. No actual/shadow inventory discrepancy was found.',
                'Nine distinct economic hashes mean no exact account path repetitions in this family. The configurations nevertheless share one observed history and cannot be treated as nine independent validations.'
            ],
            'limits':['Every2020-25 year is already seen.2020-24 excluding2025 is development reaggregation, not pristine heldout.',
                      'Own annual opening equities differ; the older common2025-opening fixed-date diagnostic denominator is not valid for these recurring policies.',
                      '2026 is technical full-contract tail only; no2026 economic selection.',
                      'No local counterfactual action-wealth labels or model fits were created; actual whole-account yearly returns and raw trigger/cycle counts support the conclusions.',
                      'CI/sample size/concentration and year-to-year no-harm are not added hard gates. Original economic goals are unchanged.'],
            'evidence_sha256':{name:sha256((BASE/name).read_bytes()).hexdigest() for name in ['independent_policy_audit_summary.json','policy_yearly_summary.csv','policy_summary.csv','policy_year_end_positions.csv','policy_trigger_events.csv','original_opportunity_state.csv']},
            'source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
            'next_step':'Main research should explain the remaining2024 failure and these cross-year tradeoffs before proposing another concrete mechanism; no automatic threshold/date search or phase advancement is implied.'}
    with (BASE/'research_findings.json').open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    print(sha256((BASE/'research_findings.json').read_bytes()).hexdigest())

if __name__=='__main__':
    main()
