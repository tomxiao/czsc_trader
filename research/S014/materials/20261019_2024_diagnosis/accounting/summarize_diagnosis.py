"""Existing actual account arithmetic; fixed Z>2 coverage is not a new policy replay."""
import csv
from hashlib import sha256
import json
from pathlib import Path

import reconcile_accounts as r

OUT=Path(__file__).resolve().parent


def rows(name):
    with (OUT/name).open(encoding='utf-8',newline='') as stream:
        return list(csv.DictReader(stream))


def num(row,key):
    return float(row[key])


def total(items,key):
    return sum(num(x,key) for x in items)


def main():
    annual=rows('policy_year_accounting_bridge.csv')
    cycle_year=rows('actual_cycle_year_contributions.csv')
    cycles=rows('actual_cycle_facts_2020_25.csv')
    atoms=rows('daily_accounting_atoms_2020_25.csv')
    cycle_lookup={(x['policy_id'],x['cycle_id']):x for x in cycles}
    boundary=rows('calendar_year_boundary_positions.csv')
    opportunity=[]
    summaries=[]
    facts2024=[]
    states=[]
    accounts=[]
    for index,policy in r.POLICIES.items():
        account,ref=r.authenticate(index,policy)
        accounts.append(ref)
        ledgers=account['runs'][0]['ledgers']
        decisions={r.day(x['signal_date']):x for x in ledgers['decisions']['data']}
        # No outcomes accompany this whole-D fixed-predicate coverage table.
        for D,d in decisions.items():
            if not '2020-01-01'<=D<=r.END:
                continue
            known=bool(d['shock_known']) and d['z5'] is not None
            zhigh=known and d['z5']>2
            mandatory=bool(d['pending_inherited'] or d['deadline_exit'])
            eligible=bool(d['held_at_close']) and not mandatory
            if zhigh and (d['entry_signal'] or eligible):
                opportunity.append({'policy_id':policy,'D':D,'valid_E':r.day(d['valid_session']),
                                    'year':int(D[:4]),'D_posture':r.posture(d),'entry_signal':d['entry_signal'],
                                    'held_at_close':d['held_at_close'],'mandatory_already':mandatory,
                                    'held_discretionary':eligible,'known':known,'z5':d['z5'],
                                    'net_profit':d['net_profit'],'original_profit_exit_selected':d['selected_profit_exit'],
                                    'entry_index':d['entry_index'],'deadline_index':d['deadline_index'],
                                    'reservation_index':d['reservation_index'],'holding_age':d['holding_age']})
        for row in [a for a in annual if a['policy_id']==policy]:
            year=row['year']
            opening=num(row,'opening_equity')
            ca=[x for x in cycle_year if x['policy_id']==policy and x['year']==year]
            negatives=[x for x in ca if num(x,'net_pnl')<0]
            positives=[x for x in ca if num(x,'net_pnl')>0]
            neg_total=total(negatives,'net_pnl')
            ranked=sorted(negatives,key=lambda x:num(x,'net_pnl'))
            relevant=[cycle_lookup[(policy,x['cycle_id'])] for x in ca]
            entry_cycles=[x for x in cycles if x['policy_id']==policy and x['entry_year']==year]
            arows=[x for x in atoms if x['policy_id']==policy and x['year']==year]
            peak=opening
            peak_date='YEAR_OPENING'
            worst=0.
            worst_peak_date=worst_trough_date=None
            for a in arows:
                equity=num(a,'closing_equity')
                if equity>peak:
                    peak=equity
                    peak_date=a['E']
                dd=1-equity/peak
                if dd>worst:
                    worst=dd
                    worst_peak_date,worst_trough_date=peak_date,a['E']
            op=[x for x in opportunity if x['year']==int(year) and x['policy_id']==policy]
            entry_nonpositive=[x for x in entry_cycles if x['never_positive_D_mark_before_exit_or_cap']=='True']
            summary={'policy_id':policy,'year':int(year),'own_year_opening':opening,
                     'closing_equity':num(row,'closing_equity'),'annual_return':num(row,'own_period_return'),
                     **{k+'_pp':100*num(row,k)/opening for k in ['entry_day_mark_pnl','continued_holding_mark_pnl','exit_to_actual_fill_pnl','actual_fees']},
                     'buyhold_return':num(row,'buyhold_annual_contribution_pp')/100,
                     'max_drawdown':worst,'max_drawdown_peak_E':worst_peak_date,'max_drawdown_trough_E':worst_trough_date,
                     'actual_new_entries':len(entry_cycles),'calendar_year_contributing_cycles':len(ca),
                     'negative_calendar_cycle_contributors':len(negatives),'negative_contributor_net_money':neg_total,
                     'positive_calendar_cycle_contributors':len(positives),'positive_contributor_net_money':total(positives,'net_pnl'),
                     'top2_loss_share_of_all_negative_contributions':total(ranked[:2],'net_pnl')/neg_total if neg_total else None,
                     'top5_loss_share_of_all_negative_contributions':total(ranked[:5],'net_pnl')/neg_total if neg_total else None,
                     'new_entry_cycles_never_positive_D_mark_to_cap':len(entry_nonpositive),
                     'new_entry_cycles_positive_D_mark_then_loss_to_cap':sum(x['positive_D_mark_then_ended_loss']=='True' for x in entry_cycles),
                     'fixed_Z_entry_signal_D_count':sum(bool(x['entry_signal']) for x in op),
                     'fixed_Z_held_discretionary_D_count':sum(x['held_discretionary'] for x in op),
                     'fixed_Z_held_nonpositive_P_D_count':sum(x['held_discretionary'] and x['net_profit'] is not None and x['net_profit']<=0 for x in op),
                     'closed_contributing_cycle_blocked_sell_attempts':sum(int(x['blocked_sell_attempts']) for x in relevant if x['actual_exit_date'])}
            r.number('cycle calendar annual sum',total(ca,'net_pnl'),num(row,'net_pnl'))
            summaries.append(summary)
            if year!='2024':
                continue
            for rank,x in enumerate(sorted(ca,key=lambda x:num(x,'net_pnl')),1):
                fact=cycle_lookup[(policy,x['cycle_id'])]
                signal=decisions[fact['entry_signal_D']]
                facts2024.append({**fact,'calendar_2024_loss_rank':rank,
                                  'calendar_2024_net_pnl':num(x,'net_pnl'),
                                  'calendar_2024_contribution_pp':num(x,'net_annual_contribution_pp'),
                                  'calendar_2024_entry_mark_pnl':num(x,'entry_day_mark_pnl'),
                                  'calendar_2024_continued_holding_pnl':num(x,'continued_holding_mark_pnl'),
                                  'calendar_2024_exit_to_fill_pnl':num(x,'exit_to_actual_fill_pnl'),
                                  'calendar_2024_fees':num(x,'actual_fees'),
                                  'entry_signalD_z5':signal['z5'],'entry_signalD_shock_known':signal['shock_known'],
                                  'entry_signalD_held':signal['held_at_close'],
                                  'entry_signalD_entry_signal':signal['entry_signal']})
        for D in ['2024-01-26','2024-01-29','2024-10-08','2024-10-09','2024-10-10','2024-10-17','2024-12-31']:
            dec=decisions[D]
            states.append({'policy_id':policy,**{k:dec[k] for k in [
                'signal_date','valid_session','entry_signal','held_at_close','z5','shock_known','net_profit',
                'entry_index','deadline_index','reservation_index','holding_age','support_break',
                'entry_grace_applied','selected_profit_exit','exit_pending','pending_inherited','deadline_exit']}})
    outputs={
        'cross_year_accounting':r.write_csv('cross_year_accounting_comparison.csv',summaries),
        'full2024_actual_cycle_facts':r.write_csv('actual_2024_cycle_attribution.csv',facts2024),
        'fixed_predicate_D_coverage_no_outcomes':r.write_csv('fixed_Z_D_opportunity_coverage.csv',opportunity),
        'selected_actual_D_states':r.write_json('selected_actual_D_states.json',states)}
    frozen='ENTRY_GRACE/SHOCK_PROFIT'
    target=next(x for x in summaries if x['policy_id']==frozen and x['year']==2024)
    target_cycles=[x for x in facts2024 if x['policy_id']==frozen]
    monthly=rows('policy_month_accounting_bridge.csv')
    halves=[sum(num(x,'net_annual_contribution_pp') for x in monthly if x['policy_id']==frozen and x['month'].startswith('2024') and (int(x['month'][5:7])<=6)==first) for first in [True,False]]
    matches=rows('matched_actual_entry_cycles.csv')
    findings={
        'status':'PASS_EXISTING_ACTUAL_ACCOUNT_DESCRIPTIVE_DIAGNOSIS','accounts':accounts,'economic_end':'2025-12-31',
        '2024_frozen':target,'2024_frozen_half_year_annual_contribution_pp':{'H1':halves[0],'H2':halves[1]},
        '2024_frozen_top5_negative_calendar_contributors':target_cycles[:5],
        '2024_frozen_calendar_boundary':next(x for x in boundary if x['policy_id']==frozen and x['year']=='2024'),
        'actual_entry_alignment':{'union_entry_dates':len(matches),'matched_entry_dates':sum(x['same_actual_entry_date']=='True' for x in matches),
                                  'matched_entry_price_dates':sum(x['same_actual_entry_price']=='True' for x in matches),
                                  'different_exit_dates':sum(x['different_actual_exit_date']=='True' for x in matches),
                                  '2024_different_exit_dates':[x['entry_date'] for x in matches if x['entry_date'].startswith('2024') and x['different_actual_exit_date']=='True']},
        'interpretation':[
            '2024 is the only2020-25 calendar year with negative total actual entry-day mark for either original account. This is an observed reversal after filled entry, not proof of an ex-ante avoidable bad entry.',
            'The largest January loss has non-extreme Z at the original buy decision. October has Z>2 at original flat buy D10/8, then Z>2 with already-negative net P on held D10/9 and10/10. Entry avoidance and removing the positive-P exit domain address different information/action sets.',
            'These two largest negative calendar contributors exceed the final annual net loss only because other cycles offset losses. Concentration must use all negative contributions, not call it more than100% of gross loss.',
            'No blocked SELL explains the observed closed2024-cycle losses. This does not establish that a different earlier sale was knowable or would improve downstream participation.',
            'Original and frozen policies share all122 actual entry dates/prices in2020-25, despite39 different exit dates and different capital quantities. Annual policy difference is not a pure same-capital sale-effect estimate.',
            'A fixed2x2 with ENTRY_GRACE/SHOCK_PROFIT as fresh control can distinguish entry-Z suppression from expanded held-Z exit domain, provided full funds/fees/reservation paths are evaluated. It cannot be declared sufficient from these two original trajectories.'
        ],
        'limitations':[
            'Actual phases and cycle profits are retrospective accounting. Coverage predicates use only source D values; no new future action-value or counterfactual labels are produced.',
            'Cycle counts are actual distinct cycles. Repeated D opportunities in one cycle are not independent observations.',
            'New-entry-cycle whole outcomes can cross calendar boundaries and are capped2025; natural-year bridge contains only that calendar year. Do not substitute those counts for annual return.',
            '2024 is already seen and motivated the candidate mechanisms. All years2020-25 remain shared development evidence, not untouched validation.',
            '2026 is excluded from economics; the ending2024 held position remains marked with no invented sale fee. Its real2025 sale is reported separately in original full-cycle facts.',
            'Profit peak and drawdown attribution are descriptive observed paths, not executable peak-sale alternatives.'
        ],
        'outputs':outputs,'source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'reconciliation_review':{'path':'research/S014/materials/20261019_2024_diagnosis/accounting/accounting_reconciliation_final.json',
                                 'sha256':sha256((OUT/'accounting_reconciliation_final.json').read_bytes()).hexdigest()},
        'check_count':sum(r.CHECKS.values()),'max_money_error':r.MAX_ERROR,
        'new_fits':0,'new_accounts':0,'new_replays':0,'new_counterfactual_labels':0,'new_supplier_calls':0,'prepared_fetches':0,'raw_market_exports':0}
    report=r.write_json('diagnosis_findings.json',findings)
    print(json.dumps({'report':report,'outputs':outputs,'2024':target,'halves':halves},ensure_ascii=False))


if __name__=='__main__':
    main()
