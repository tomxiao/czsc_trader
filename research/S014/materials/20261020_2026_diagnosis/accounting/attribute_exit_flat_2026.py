"""Actual SELL flags and actual flat-day reason accounting; no alternate exits."""
from collections import defaultdict
import csv
import json
from pathlib import Path

import diagnose_actual_2026 as A

ROOT, OUT = A.ROOT, A.OUT


def main():
    accounts, sources = A.load_accounts()
    with (OUT / 'actual_2026_daily_atoms.csv').open(encoding='utf-8', newline='') as stream:
        atoms = list(csv.DictReader(stream))
    exits, flat = [], []
    signature_groups = defaultdict(list)
    for policy, account in accounts.items():
        ledger = account['runs'][0]['ledgers']
        decisions = {A.day(r['signal_date']): r for r in ledger['decisions']['data']}
        orders = {A.day(r['signal_date']): r for r in ledger['orders']['data']}
        fills = {r['order_id']: r for r in ledger['fills']['data']}
        buys = [r for r in ledger['fills']['data'] if r['side'] == 'BUY']
        trades = {r['cycle_id']: r for r in ledger['trades']['data']}
        own = [r for r in atoms if r['policy'] == policy]
        for atom in own:
            D, E = atom['D'], atom['E']
            dec = decisions[D]
            order = orders.get(D)
            if dec['held_at_close'] and dec['exit_pending']:
                A.check('actual SELL intent has original saved SELL order', order is not None and order['side'] == 'SELL' and A.day(order['execution_date']) == E)
                fill = fills.get(order['order_id'])
                flags = {k: dec[k] for k in ['pending_inherited', 'deadline_exit', 'selected_shock_exit', 'selected_cost_exit', 'ordinary_support_exit',
                                            'original_support_exit', 'support_break', 'entry_grace_eligible', 'entry_grace_applied', 'profit_exit_eligible']}
                signature = '|'.join(f'{k}={int(bool(v))}' for k, v in flags.items() if k in ['pending_inherited', 'deadline_exit', 'selected_shock_exit', 'selected_cost_exit', 'ordinary_support_exit'])
                next_buy = next((r for r in buys if A.day(r['fill_time']) > E), None)
                cap = A.day(next_buy['fill_time']) if next_buy else A.END
                gap = [r for r in own if r['actual_phase'] == 'WHOLE_SESSION_FLAT' and E < r['E'] and (r['E'] < cap if next_buy else r['E'] <= cap)]
                record = {'policy': policy, 'D': D, 'planned_E': E, 'actual_order_id': order['order_id'], 'cycle_id': order['cycle_id'],
                          'actual_order_status': order['status'], 'actual_order_reason': order['reason'],
                          'actual_fill_E': A.day(fill['fill_time']) if fill else None, 'actual_fill_price': fill['price'] if fill else None,
                          'actual_fill_quantity': fill['quantity'] if fill else None, 'actual_fill_fee': fill['fees'] if fill else None,
                          'exit_flag_combination': signature, **flags, 'holding_age': dec['holding_age'], 'D_net_profit': dec['net_profit'],
                          'D_z5': dec['z5'], 'D_cost_loss_atr': dec['cost_loss_atr'], 'D_entry_index': dec['entry_index'],
                          'D_deadline_index': dec['deadline_index'], 'D_reservation_index': dec['reservation_index'],
                          'D_market_index': dec['warmup_sessions'], 'known_reservation_minus_D_index': dec['reservation_index'] - dec['warmup_sessions'],
                          'actual_full_cycle_return_POSTHOC': trades[order['cycle_id']]['net_return'] if fill else None,
                          'next_actual_entry_E': A.day(next_buy['fill_time']) if next_buy else None,
                          'post_exit_observed_whole_flat_sessions': len(gap),
                          'post_exit_observed_flat_BH_net_pp': sum(float(r['buyhold_contribution_pp']) for r in gap),
                          'post_exit_observed_flat_BH_up_pp': sum(float(r['buyhold_contribution_pp']) for r in gap if r['close_direction_POSTHOC'] == 'UP'),
                          'post_exit_observed_flat_BH_down_pp': sum(float(r['buyhold_contribution_pp']) for r in gap if r['close_direction_POSTHOC'] == 'DOWN'),
                          'no_alternative_exit_or_hold_return': True}
                exits.append(record)
                signature_groups[(policy, signature)].append(record)
            if atom['actual_phase'] != 'WHOLE_SESSION_FLAT':
                continue
            A.check('whole flat E has flat D', not dec['held_at_close'])
            if dec['entry_signal']:
                A.check('flat after true BUY intent means original unfilled BUY', order is not None and order['side'] == 'BUY' and order['status'] != 'FILLED')
                reason = 'TRUE_BUY_INTENT_UNFILLED_POSTHOC'
            elif dec.get('pause_slot_consumed', False):
                reason = 'PAUSE_CONSUMED_ON_D'
            elif dec.get('planned_slot_active', False):
                reason = 'VIRTUAL_PAUSE_RESERVATION_ACTIVE'
            elif dec['warmup_sessions'] < dec['reservation_index']:
                reason = 'ORIGINAL_ACTUAL_BUY_RESERVATION_WAIT'
            elif dec['failed_buy_reset']:
                reason = 'ORIGINAL_FAILED_BUY_RESET'
            elif not dec['ready']:
                reason = 'ORIGINAL_NOT_READY'
            elif not dec['support_ok']:
                reason = 'ORIGINAL_SUPPORT_NOT_ELIGIBLE'
            else:
                raise AssertionError('unclassified true flat source D state')
            flat.append({'policy': policy, 'D': D, 'E': E, 'D_state_or_actual_failed_order_reason': reason,
                         'close_direction_POSTHOC': atom['close_direction_POSTHOC'], 'BH_contribution_pp': float(atom['buyhold_contribution_pp']),
                         'own_strategy_contribution_pp': float(atom['strategy_contribution_pp']), 'ready': dec['ready'], 'support_ok': dec['support_ok'],
                         'failed_buy_reset': dec['failed_buy_reset'], 'D_market_index': dec['warmup_sessions'], 'D_reservation': dec['reservation_index'],
                         'planned_slot_until': dec.get('planned_slot_until'), 'original_entry_candidate': dec['original_entry_candidate']})
    grouped = defaultdict(list)
    for row in flat:
        grouped[(row['policy'], row['D_state_or_actual_failed_order_reason'])].append(row)
    flat_summary = [{ 'policy': policy, 'D_state_or_actual_failed_order_reason': reason, 'sessions': len(members),
                     'actual_BH_net_contribution_pp': sum(r['BH_contribution_pp'] for r in members),
                     'actual_BH_up_contribution_pp': sum(r['BH_contribution_pp'] for r in members if r['close_direction_POSTHOC'] == 'UP'),
                     'actual_BH_down_contribution_pp': sum(r['BH_contribution_pp'] for r in members if r['close_direction_POSTHOC'] == 'DOWN'),
                     'strategy_contribution_pp': sum(r['own_strategy_contribution_pp'] for r in members)} for (policy, reason), members in sorted(grouped.items())]
    combinations = [{'policy': policy, 'flag_combination': signature, 'actual_SELL_intents': len(members),
                     'actual_filled_SELL': sum(r['actual_fill_E'] is not None for r in members),
                     'actual_unfilled_SELL': sum(r['actual_fill_E'] is None for r in members),
                     'post_exit_observed_flat_BH_net_pp': sum(r['post_exit_observed_flat_BH_net_pp'] for r in members)}
                    for (policy, signature), members in sorted(signature_groups.items())]
    for policy in accounts:
        A.check('all actual sell dates mapped', sum(r['policy'] == policy and r['actual_fill_E'] is not None for r in exits) == sum(r['policy'] == policy and r['actual_phase'] == 'ACTUAL_SELL' for r in atoms))
        A.equal('all observed flat BH net covered', sum(r['BH_contribution_pp'] for r in flat if r['policy'] == policy),
                sum(float(r['buyhold_contribution_pp']) for r in atoms if r['policy'] == policy and r['actual_phase'] == 'WHOLE_SESSION_FLAT'))
    outputs = [A.save('actual_2026_exit_decisions.csv', exits, True), A.save('actual_2026_exit_flag_combinations.csv', combinations, True),
               A.save('actual_2026_flat_D_states.csv', flat, True), A.save('actual_2026_flat_reason_summary.csv', flat_summary, True)]
    result = {'status': 'PASS_ACTUAL_D_STATES_AND_ORDERS_ONLY', 'sources': sources, 'implementation': A.ref(Path(__file__).resolve()),
              'outputs': outputs, 'checks': dict(A.CHECKS), 'check_count': sum(A.CHECKS.values()), 'max_money_error': A.MAX_ERROR,
              'exit_flag_combinations': combinations, 'flat_reasons': flat_summary,
              'definitions': ['Exclusive flat reason priority is classification of observed source state, not a new decision rule or causal share.',
                              'Failed-order classification is E-known; all remaining eligibility/clock flags are original D-known.',
                              'Post-exit-to-next-actual-entry gap may mix original reservation, entry qualification and a later pause; no hypothetical hold-to-next-buy PnL computed.',
                              'SHOCK selected alongside support remains both flags; mandatory deadline/pending preempts discretionary exits.',
                              'All same observed flat-day BH changes retain up and down directions; not only missed positive days.'],
              'resources': {'new_accounts': 0, 'strategy_replays': 0, 'fits': 0, 'new_data_calls': 0, 'counterfactual_labels': 0}}
    print(json.dumps({'review': A.save('actual_2026_exit_flat_review.json', result), 'combinations': combinations, 'flat': flat_summary}))


if __name__ == '__main__':
    main()
