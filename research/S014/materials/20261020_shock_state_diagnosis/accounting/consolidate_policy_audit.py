"""Consolidate three fixed EX050 actual accounts; no replay or alternate-date label."""
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import io
import json
from pathlib import Path

import policy_account_common as C
import diagnose_actual_2026 as D

ROOT, OUT, EX, A, H = C.ROOT, C.OUT, C.EX, C.A, C.H


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def csv_output(name, rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
    writer.writeheader()
    writer.writerows([{k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in rows])
    path = OUT / name
    with path.open('xb') as target:
        target.write(stream.getvalue().encode('utf-8'))
    return {**ref(path), 'rows': len(rows)}


def exit_flat(account, atoms, policy):
    ledger = account['runs'][0]['ledgers']
    decisions = {A.day(r['signal_date']): r for r in ledger['decisions']['data']}
    orders = {A.day(r['signal_date']): r for r in ledger['orders']['data']}
    fills = {r['order_id']: r for r in ledger['fills']['data']}
    trades = {r['cycle_id']: r for r in ledger['trades']['data']}
    flags = ['pending_inherited', 'deadline_exit', 'selected_shock_exit', 'selected_cost_exit', 'ordinary_support_exit']
    exits, flat = [], []
    for atom in atoms:
        day, execution = atom['D'], atom['E']
        state, order = decisions[day], orders.get(day)
        if state['held_at_close'] and state['exit_pending']:
            A.check('actual held SELL maps original D/E order', order is not None and order['side'] == 'SELL' and A.day(order['execution_date']) == execution)
            fill = fills.get(order['order_id'])
            exits.append({'policy_profile': policy, 'D': day, 'E': execution, 'actual_order_status': order['status'],
                          'actual_order_reason': order['reason'], 'actual_fill_price': fill['price'] if fill else None,
                          'actual_fill_quantity': fill['quantity'] if fill else None, 'actual_fill_fee': fill['fees'] if fill else None,
                          'cycle_id': order['cycle_id'], 'holding_age': state['holding_age'], 'D_net_profit': state['net_profit'],
                          'D_z5': state['z5'], 'D_cost_loss_atr': state['cost_loss_atr'],
                          'raw_shock_condition': state['shock_condition'], 'raw_legacy_selected_profit_exit': state['selected_profit_exit'],
                          'shock_action_suppressed': state['shock_action_suppressed'], **{k: state[k] for k in flags},
                          'D_reservation': state['reservation_index'], 'D_market_index': state['warmup_sessions'],
                          'actual_full_cycle_return_POSTHOC': trades[order['cycle_id']]['net_return'] if fill else None})
        if atom['actual_phase'] != 'WHOLE_SESSION_FLAT':
            continue
        A.check('whole flat E has original D zero position', not state['held_at_close'])
        if state['entry_signal']:
            A.check('whole flat after true BUY intent is real unfilled order', order is not None and order['side'] == 'BUY' and order['status'] != 'FILLED')
            reason = 'TRUE_BUY_INTENT_UNFILLED_POSTHOC'
        elif state['pause_slot_consumed']:
            reason = 'PAUSE_CONSUMED_ON_D'
        elif state['planned_slot_active']:
            reason = 'VIRTUAL_PAUSE_RESERVATION_ACTIVE'
        elif state['warmup_sessions'] < state['reservation_index']:
            reason = 'ORIGINAL_ACTUAL_BUY_RESERVATION_WAIT'
        elif state['failed_buy_reset']:
            reason = 'ORIGINAL_FAILED_BUY_RESET'
        elif not state['ready']:
            reason = 'ORIGINAL_NOT_READY'
        elif not state['support_ok']:
            reason = 'ORIGINAL_SUPPORT_NOT_ELIGIBLE'
        else:
            raise AssertionError('Unclassified actual flat state')
        flat.append({'policy_profile': policy, 'D': day, 'E': execution, 'observed_reason': reason,
                     'BH_contribution_pp': atom['buyhold_contribution_pp'], 'direction_POSTHOC': atom['close_direction_POSTHOC']})
    A.check('all actual2026 SELL fills classified', sum(r['actual_fill_price'] is not None for r in exits) == sum(r['actual_phase'] == 'ACTUAL_SELL' for r in atoms))
    return exits, flat


def main():
    index_ref = A.read(EX / 'others/accounts_index_ref.json')
    records = A.published(index_ref)['records']
    dispatches = sorted((EX / 'others/dispatches').glob('*.json'))
    status = Counter(r['status'] for r in records)
    A.check('all actual dispatches including failed unknown retained', len(dispatches) == len(records) == 3 and sorted(r['index'] for r in records) == [0, 1, 2])
    reports, report_refs = [], []
    first_events = []
    yearly, policies, events, completed, suppressed, atoms, cycles, exits, flat = ([] for _ in range(9))
    classes = defaultdict(list)
    for i, params in enumerate(C.FIXED):
        record = next(r for r in records if r['index'] == i)
        path = OUT / f'policy_account_{i:03d}_independent_review.json'
        report = A.read(path)
        A.check('both fixed successful and independent PASS', record['status'] == 'SUCCEEDED' and report['status'] == 'PASS')
        A.check('immutable independent actual identity', report['account_ref'] == record['evidence'] and report['result_hash'] == record['result_hash'] and report['parameters'] == params)
        _, lock_ref = C.run_lock(record)
        A.check('actual dispatch source lock and source match', report['source_lock_sha256'] == lock_ref['sha256'] and report['source_sha256'] == C.SOURCE_SHA)
        for key, filename in [('audit_implementation_sha256', 'audit_policy_accounts.py'), ('common_helper_sha256', 'policy_account_common.py'), ('lifecycle_helper_sha256', 'policy_lifecycle.py')]:
            A.check('independent implementation unchanged ' + filename, report[key] == ref(OUT / filename)['sha256'])
        reports.append(report)
        report_refs.append(ref(path))
        meta = {'policy_profile': record['mode'], 'diagID': record['candidate']}
        annual = report['original_annual_goal_audit']
        A.check('all original seven years incl partial2026', [r['year'] for r in annual] == list(range(2020, 2027)))
        yearly.extend({**meta, **r} for r in annual)
        policies.append({**meta, **{k: v for k, v in report['summary'].items() if k != 'without2025_role'},
                         'terminal_original_cutoff_equity': report['boundary2026_actuals']['ending_equity'],
                         'continuous2020_original_cutoff_return_from100000': report['boundary2026_actuals']['ending_equity'] / 100000 - 1})
        events.extend({**meta, **r} for r in report['lifecycle']['events'])
        completed.extend({**meta, **r} for r in report['lifecycle']['actual_completed_cycles'])
        suppressed.extend({**meta, **r} for r in report['actual_suppressed_SHOCK_rows'])
        atoms.extend(report['actual2026_daily_atoms'])
        cycles.extend(report['actual2026_calendar_cycle_contributions'])
        account = A.published(report['account_ref'])
        trade_map = {r['cycle_id']: r for r in account['runs'][0]['ledgers']['trades']['data']}
        for event in report['lifecycle']['first_own_SHOCK_events']:
            trade = trade_map[event['cycle_id']]
            first_events.append({**meta, **event, 'actual_cycle_status': trade['status'],
                                 'actual_exit_E': trade['exit_date'], 'actual_full_cycle_net_return_POSTHOC': trade['net_return']})
        x, f = exit_flat(account, report['actual2026_daily_atoms'], record['mode'])
        exits.extend(x)
        flat.extend(f)
        classes[report['economic_path_hashes']['execution_economics_sha256']].append(record['mode'])
        for key in ['return', 'max_drawdown']:
            value = next(r[key] for r in annual if r['year'] == 2026)
            A.check('independent actual phase2026 matches original annual ' + key, abs(report['actual2026_phase_summary'][key] - value) <= A.RATIO_TOLERANCE)
    A.check('21 annual and3 summary rows', len(yearly) == 21 and len(policies) == 3)
    flat_groups = defaultdict(list)
    for r in flat:
        flat_groups[(r['policy_profile'], r['observed_reason'])].append(r)
    flat_summary = [{'policy_profile': policy, 'observed_reason': reason, 'sessions': len(members),
                     'actual_BH_net_pp': sum(r['BH_contribution_pp'] for r in members),
                     'actual_BH_up_pp': sum(r['BH_contribution_pp'] for r in members if r['direction_POSTHOC'] == 'UP'),
                     'actual_BH_down_pp': sum(r['BH_contribution_pp'] for r in members if r['direction_POSTHOC'] == 'DOWN')}
                    for (policy, reason), members in sorted(flat_groups.items())]
    outputs = [csv_output('full_policy_yearly_summary.csv', yearly), csv_output('full_policy_summary.csv', policies),
               csv_output('full_policy_trigger_events.csv', events), csv_output('full_policy_actual_completed_cycles.csv', completed),
               csv_output('full_policy_actual_suppressed_rows.csv', suppressed), csv_output('full_policy_2026_daily_atoms.csv', atoms),
               csv_output('full_policy_2026_phase_summary.csv', [r['actual2026_phase_summary'] for r in reports]),
               csv_output('full_policy_2026_phase_direction.csv', D.grouped(atoms, ['policy', 'actual_phase', 'close_direction_POSTHOC'])),
               csv_output('full_policy_2026_phase.csv', D.grouped(atoms, ['policy', 'actual_phase'])),
               csv_output('full_policy_2026_calendar_cycle_contributions.csv', cycles), csv_output('full_policy_2026_actual_exit_decisions.csv', exits),
               csv_output('full_policy_2026_flat_D_states.csv', flat), csv_output('full_policy_2026_flat_reason_summary.csv', flat_summary),
               csv_output('full_policy_2026_opening_ending.csv', [{'policy_profile': r['policy_id'], **r['boundary2026_actuals']} for r in reports])]
    outputs.append(csv_output('full_policy_first_SHOCK_actual_cycles.csv', first_events))
    result = {'status': 'PASS', 'experiment': 'EX050_20261020', 'source_sha256': C.SOURCE_SHA,
              'source_lock_ref': A.read(EX / 'protocols/published_lock.json'), 'formal_accounts_index_ref': index_ref,
              'account_reports': report_refs, 'outputs': outputs, 'policy_summary': policies,
              'resource_accounting': {'actual_dispatched': len(dispatches), 'SUCCEEDED': status['SUCCEEDED'], 'FAILED': status['FAILED'], 'UNKNOWN': status['UNKNOWN'],
                                      'other_status': {k: v for k, v in status.items() if k not in {'SUCCEEDED', 'FAILED', 'UNKNOWN'}},
                                      'retries': len(records) - len({r['index'] for r in records}), 'source_specific_control_accounts': 1, 'new_active_profiles': 2,
                                      'independent_failure_records': [ref(p) for p in sorted(OUT.glob('policy_account_*_independent_failure*.json'))],
                                      'fits': 0, 'new_supplier_calls': 0, 'auditor_dispatches': 0, 'strategy_replays_by_auditor': 0},
              'independent_actual_checks': sum(r['checks'] for r in reports), 'independent_phase_checks': sum(r['phase_checks'] for r in reports),
              'consolidation_checks': sum(A.COUNTS.values()), 'four_divergence_dates': {r['policy_id']: r['prefix'] for r in reports},
              'full_execution_economic_equivalence_classes': [{'sha256': k, 'profiles': v} for k, v in classes.items()],
              'actual_suppressed_SHOCK_counts': {r['policy_id']: r['actual_suppressed_SHOCK_counts'] for r in reports},
              'implementation': ref(Path(__file__).resolve()),
              'limits': ['All seven original annual gates retain partial2026 through10/15 without annualization; original frequency unchanged.',
                         'Fixed first-SHOCK policies have own entries/funding/completed-loss history; original21 component labels cannot become policy outcomes.',
                         'Suppressed row count is not distinct cycle count or independently earned profit. Raw legacyselected_profit_exit is not an OFF actual exit.',
                         'All years have been seen; fullgoal audit is historical diagnostic evidence, not heldout validation or automatic formal registration.',
                         'Flat BH up/down and cycle returns are observed attribution; no imagined hold/entry returns or recoverable128/93/60pp claim.']}
    path = OUT / 'independent_policy_audit_summary.json'
    H.write(path, result)
    print(json.dumps({'summary': ref(path), 'resources': result['resource_accounting'], 'checks': result['independent_actual_checks'], 'tables': outputs[:2]}))


if __name__ == '__main__':
    main()
