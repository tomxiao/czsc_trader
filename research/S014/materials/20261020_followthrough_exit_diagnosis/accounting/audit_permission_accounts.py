"""Independent EX052 whole funded accounts; all seven original years remain gates."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

import permission_account_common as C
import sys
import math
sys.path.insert(0, str(Path.cwd() / 'research/S014/materials/20261020_shock_state_diagnosis/accounting'))
import permission_lifecycle as L
import local_input_reader as I
import diagnose_actual_2026 as D

ROOT, OUT, EX = C.ROOT, C.OUT, C.EX
A, H, Q = C.A, C.H, C.Q


def origin():
    receipt = A.read(ROOT / 'research/S014/experiments/EX050_20261020/others/accounts/run-002.json')
    account = A.published(receipt['evidence'])
    A.check('correct fixed C9502 actual control', account['result_hash'] == receipt['result_hash'] == '63b4ce767292ebdfaa71e23f56981eda61e08f5bbf2e6de6c8814bd6da5a2757' and receipt['evidence']['sha256'] == '83327564961b13c1bc8e36cdf4e5c78ad35896a7e26f8595b6c3215889533ac9')
    return account, receipt


def boundary2026(account):
    ledger = account['runs'][0]['ledgers']
    days = {A.day(r['date']): r for r in ledger['account_daily']['data']}
    opening, ending = days['2025-12-31'], days['2026-10-15']
    buys = [r for r in ledger['fills']['data'] if r['side'] == 'BUY' and A.day(r['fill_time']) <= '2025-12-31']
    carry = buys[-1] if opening['quantity'] else None
    return {'opening_calendar_date': '2025-12-31', 'opening_cash': opening['cash'], 'opening_quantity': opening['quantity'], 'opening_equity': opening['equity'],
            'carry_actual_entry_D': A.day(carry['signal_date']) if carry else None, 'carry_actual_entry_E': A.day(carry['fill_time']) if carry else None,
            'carry_actual_entry_price': carry['price'] if carry else None, 'cutoff_E': '2026-10-15',
            'ending_cash': ending['cash'], 'ending_quantity': ending['quantity'], 'ending_equity': ending['equity'],
            'ending_uncompleted_inventory': ending['quantity'] > 0, 'last_source_D': A.day(ledger['decisions']['data'][-1]['signal_date']),
            'last_source_D_exit_pending': ledger['decisions']['data'][-1]['exit_pending'],
            'last_source_D_reservation': ledger['decisions']['data'][-1]['reservation_index'],
            'post_E_cutoff_source_D_not_replayed': True}


def suppressed_cycles(account):
    ledger = account['runs'][0]['ledgers']
    fills = {A.day(r['fill_time']): r for r in ledger['fills']['data']}
    entry_cycles = {r['entry_index']: fills[A.day(r['signal_date'])]['cycle_id'] for r in ledger['decisions']['data'] if r['buy_filled_today']}
    trades = {r['cycle_id']: r for r in ledger['trades']['data']}
    orders = {r['cycle_id']: r for r in ledger['orders']['data'] if r['side'] == 'SELL' and r['status'] == 'FILLED'}
    decisions = {A.day(r['signal_date']): r for r in ledger['decisions']['data']}
    result = []
    for row in ledger['decisions']['data']:
        if not row['shock_action_suppressed']:
            continue
        cycle = entry_cycles[row['entry_index']]
        trade, sale = trades[cycle], orders.get(cycle)
        exit_dec = decisions[A.day(sale['signal_date'])] if sale else None
        result.append({'D': A.day(row['signal_date']), 'cycle_id': cycle, 'actual_entry_E': A.day(trade['entry_date']),
                       'D_raw_shock_condition': row['shock_condition'], 'D_actual_selected_shock_exit': row['selected_shock_exit'],
                       'D_target': row['target_position'], 'D_other_support_exit': row['ordinary_support_exit'], 'D_other_cost_exit': row['selected_cost_exit'],
                       'D_deadline': row['deadline_exit'], 'D_pending_inherited': row['pending_inherited'],
                       'actual_eventual_exit_D': A.day(sale['signal_date']) if sale else None,
                       'actual_eventual_exit_E': A.day(trade['exit_date']) if trade['exit_date'] else None,
                       'actual_eventual_exit_flags': {k: exit_dec[k] for k in ['pending_inherited', 'deadline_exit', 'selected_shock_exit', 'selected_cost_exit', 'ordinary_support_exit']} if exit_dec else None,
                       'actual_trade_status': trade['status'], 'full_actual_trade_net_return': trade['net_return']})
    return result


def audit_one(index):
    destination = OUT / f'permission_account_{index:03d}_independent_review.json'
    A.check('refuse existing report overwrite', not destination.exists())
    record = A.read(EX / f'others/accounts/run-{index:03d}.json')
    A.check('actual successful engine and internal audit', record['status'] == 'SUCCEEDED' and record['audit']['status'] == 'PASS')
    account = A.published(record['evidence'])
    A.check('actual exact result and FULL run', account['result_hash'] == record['result_hash'] and len(account['runs']) == 1 and account['execution_mode'] == 'FULL')
    frozen, prior = origin()
    binding, lock_ref = C.identity(record, account, frozen, prior)
    A.equal_baseline(frozen, account)
    frames = H.fetch_execution(binding, account['request_identity']['pricing'])
    approved, boundaries = Q.O.exact_execution_prices(account, frames)
    accounting = Q.F.audit_daily(account, True, approved)
    if index == 0:
        A.noop_equivalence(frozen, account)
    else:
        control = A.read(OUT / 'permission_account_000_independent_review.json')
        A.check('fresh policy independent exact C9502 control PASS', control['status'] == 'PASS' and control['source_sha256'] == C.SOURCE_SHA)
    _, state_frames, input_proof = I.load()
    required_fields = ['permission_trend_profile', 'permission_required_today', 'permission_s1_evaluated', 'permission_s1_known', 'permission_s1_true', 'permission_granted', 'permission_refused', 'permission_age_qualified', 'permission_first_index']
    for row in account['runs'][0]['ledgers']['decisions']['data']:
        for key in required_fields:
            A.check('formal new permission observation exists finite ' + key, key in row and type(row[key]) in (int, float) and math.isfinite(row[key]))
    state = L.lifecycle(account, frozen, record['parameters']['permission_profile'], state_frames['adjusted_daily'])
    prefix = C.divergence(account, frozen, index)
    H.execution_constraints(account, frames)
    annual, summary = H.annual_and_summary(account, frozen)
    for row in annual:
        row['return_difference_vs_C9502'] = row.pop('return_difference_vs_original')
        row['technical_only'] = False
        row['partial_year_not_annualized'] = row['year'] == 2026
    A.check('original seven calendar years retained', [r['year'] for r in annual] == list(range(2020, 2027)))
    summary['nannual_return_pass_2020_26'] = summary['nannual_return_pass_original_full_contract']
    summary['nannual_drawdown_pass_2020_26'] = summary['nannual_drawdown_pass_original_full_contract']
    summary['nannual_joint_pass_2020_26'] = sum(r['return_pass'] and r['drawdown_pass'] for r in annual)
    summary['all_original_economic_goals_pass'] = summary['nannual_joint_pass_2020_26'] == 7 and summary['original_frequency_pass']
    suppressed = suppressed_cycles(account)
    prefix['first_actual_SHOCK_suppression_D'] = suppressed[0]['D'] if suppressed else None
    hashes = H.econ_hashes(account, frozen)
    projection = [{k: r[k] for k in ['date', 'cash', 'cash_before', 'equity', 'quantity', 'quantity_before']} for r in account['runs'][0]['ledgers']['account_daily']['data']]
    hashes['funded_wealth_sha256'] = H.hash_value(projection)
    hashes['funded_wealth_2020_25_sha256'] = H.hash_value([r for r in projection if A.day(r['date']) <= '2025-12-31'])
    atoms, phase, cycles = D.process(account, record['mode'])
    result = {'status': 'PASS', 'index': index, 'policy_id': record['mode'], 'diagID': record['candidate'], 'parameters': record['parameters'],
              'account_ref': record['evidence'], 'result_hash': record['result_hash'], 'source_sha256': C.SOURCE_SHA,
              'baseline_ref': prior['evidence'], 'source_NOOP_exact_C9502': index == 0, 'independent_state_input_proof': input_proof,
              'actual_dispatch_source_lock_ref': lock_ref, 'source_lock_sha256': lock_ref['sha256'],
              'accounting': accounting, 'lifecycle': state, 'prefix': prefix, 'original_annual_goal_audit': annual, 'summary': summary,
              'boundary2026_actuals': boundary2026(account), 'economic_path_hashes': hashes,
              'actual_suppressed_SHOCK_rows': suppressed,
              'actual_suppressed_SHOCK_counts': {'all_window_D': len(suppressed), 'all_distinct_actual_cycles': len({r['cycle_id'] for r in suppressed}),
                                                'year2026_D': sum(r['D'][:4] == '2026' for r in suppressed),
                                                'year2026_distinct_actual_cycles': len({r['cycle_id'] for r in suppressed if r['D'][:4] == '2026'})},
              'actual2026_phase_summary': {k: v for k, v in phase.items() if k != 'last_issued_D_state'},
              'actual2026_daily_atoms': atoms, 'actual2026_calendar_cycle_contributions': cycles,
              'checks': sum(A.COUNTS.values()), 'check_counts': dict(A.COUNTS), 'phase_checks': sum(D.CHECKS.values()),
              'maximum_arithmetic_error': A.ERRORS, 'derived_currency_absolute_tolerance': A.MONEY_TOLERANCE,
              'derived_ratio_absolute_tolerance': A.RATIO_TOLERANCE, 'NOOP_projection_tolerance': 0, 'automatic_tolerance_expansion': False,
              'exact_public_fill_oracle': {'matched_actual_fills': len(approved), 'original_roundoff_boundaries': boundaries, 'new_epsilon': 0},
              'audit_implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'common_helper_sha256': sha256((OUT / 'permission_account_common.py').read_bytes()).hexdigest(),
              'lifecycle_helper_sha256': sha256((OUT / 'permission_lifecycle.py').read_bytes()).hexdigest(),
              'financial_helper_sha256': sha256(Path(Q.F.__file__).read_bytes()).hexdigest(),
              'new_fits': 0, 'new_strategy_replays': 0, 'auditor_dispatches': 0, 'new_supplier_calls': 0, 'new_preparations': 0,
              'limits': ['All seven original years include partial2026, not annualized.', 'Whole policy may diverge since2020; not the fixed original21 component outcomes. Each profile has its own annual opening and actual completed-loss history.', 'RawSHOCK suppression count is not number of distinct actual trades or independently realized gains.', 'No automatic registration, eligibility edit or stage promotion.']}
    H.write(destination, result)
    print(json.dumps({'index': index, 'status': 'PASS', 'checks': result['checks'], 'review_sha256': sha256(destination.read_bytes()).hexdigest()}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=int, required=True, choices=(0, 1))
    args = parser.parse_args()
    try:
        audit_one(args.index)
    except Exception as exc:
        failure = OUT / f'permission_account_{args.index:03d}_independent_failure.json'
        if not failure.exists():
            H.write(failure, {'status': 'FAIL', 'index': args.index, 'exception': repr(exc), 'check_counts': dict(A.COUNTS),
                              'no_tolerance_expansion': True, 'audit_implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest()})
        raise


if __name__ == '__main__':
    main()
