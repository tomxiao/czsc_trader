"""Describe actual entry/exit interaction; no counterfactual filtering or replay."""
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime
from math import fsum, isclose


def at(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def indexed(rows, key):
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError('duplicate ledger identity: ' + key)
    return result


def facts(decision):
    rows = decision['explanation']['basis']
    result = {row['key']: row['text'] for row in rows}
    if len(result) != len(rows):
        raise ValueError('duplicate explanation fact')
    return result


def describe(payload):
    account = payload['runs']['candidate']
    sequence = account['decisions']
    times = [at(row['decision_at']) for row in sequence]
    assert times == sorted(times)
    decisions = indexed(sequence, 'decision_id')
    orders = indexed(account['orders'], 'order_id')
    trades = indexed(account['trades'], 'cycle_id')
    indexed(account['fills'], 'fill_id')
    grouped = defaultdict(list)
    for fill in account['fills']:
        order = orders[fill['order_id']]
        decision = decisions[order['decision_id']]
        if (order['status'] != 'FILLED' or fill['side'] != order['side'] or order['side'] != decision['side']
                or fill['quantity'] != order['quantity']
                or at(fill['interval_start']) != at(order['valid_start'])
                or at(fill['interval_end']) != at(order['valid_end'])
                or at(fill['interval_start']) != at(decision['execution_start'])
                or at(fill['interval_end']) != at(decision['execution_end'])):
            raise ValueError('fill/order/decision linkage differs')
        grouped[fill['cycle_id']].append(fill)
    rows = []
    for cycle, fills in grouped.items():
        buys = [item for item in fills if item['side'] == 'BUY']
        sells = [item for item in fills if item['side'] == 'SELL']
        if len(buys) != 1 or len(sells) > 1:
            raise ValueError('requires actual whole-entry and whole-exit cycles')
        buy = buys[0]
        decision = decisions[orders[buy['order_id']]['decision_id']]
        observed = facts(decision)
        assert decision['target'] == 1 and observed['held'] == 'False'
        close, threshold = float(observed['close']), float(observed['exit_threshold'])
        start = bisect_left(times, at(buy['interval_end']))
        next_held = sequence[start] if start < len(sequence) else None
        if next_held is not None and facts(next_held)['held'] != 'True':
            raise ValueError('first decision after completed buy must use actual held state')
        trade = trades.get(cycle)
        sell_decision = decisions[orders[sells[0]['order_id']]['decision_id']] if sells else None
        if trade is not None:
            if (trade['status'] != 'CLOSED' or len(sells) != 1
                    or sells[0]['quantity'] != buy['quantity']
                    or at(trade['entry_at']) != at(buy['interval_start'])
                    or at(trade['exit_at']) != at(sells[0]['interval_end'])):
                raise ValueError('closed trade does not match actual fills')
            mark = None
        else:
            end = account['account_points'][-1]
            if sells or end['cycle_id'] != cycle or end['quantity'] != buy['quantity']:
                raise ValueError('open cycle does not match terminal position')
            mark = end['quantity'] * end['close'] - buy['quantity'] * buy['price'] - buy['fees']
        rows.append({'cycle_id': cycle, 'entry_decision_id': decision['decision_id'],
            'entry_at': buy['interval_start'], 'entry_interval_end': buy['interval_end'],
            'actual_entry_price': buy['price'],
            'actual_price_minus_signal_close': buy['price'] - close,
            'entry_signal_close': close, 'entry_existing_exit_threshold': threshold,
            'entry_at_or_below_existing_exit': close <= threshold,
            'first_held_decision_id': None if next_held is None else next_held['decision_id'],
            'first_held_target': None if next_held is None else next_held['target'],
            'exit_requested_at_first_held_decision': None if next_held is None else next_held['target'] == 0,
            'exit_decision_at': None if sell_decision is None else sell_decision['decision_at'],
            'status': 'CLOSED' if trade else 'OPEN',
            'net_pnl': trade['net_pnl'] if trade else None,
            'net_return': trade['net_return'] if trade else None,
            'fees': fsum(fill['fees'] for fill in fills),
            'terminal_mark_after_paid_buy_fee': mark})
    closed = [row for row in rows if row['status'] == 'CLOSED']
    opened = [row for row in rows if row['status'] == 'OPEN']
    assert len(closed) == len(trades) == account['metrics']['closed_cycles']
    reconstructed = fsum(row['net_pnl'] for row in closed) + fsum(row['terminal_mark_after_paid_buy_fee'] for row in opened)
    equity_change = account['account_points'][-1]['equity'] - payload['request']['initial_cash']
    assert isclose(reconstructed, equity_change, abs_tol=1e-6, rel_tol=1e-10)
    assert isclose(fsum(row['fees'] for row in rows), account['metrics']['fees'], abs_tol=1e-6, rel_tol=1e-10)
    groups = {}
    for key in ('entry_at_or_below_existing_exit', 'exit_requested_at_first_held_decision'):
        groups[key] = {('UNOBSERVED' if flag is None else str(flag)): {
            'closed_cycles': len(selected := [row for row in closed if row[key] == flag]),
            'closed_net_pnl': fsum(row['net_pnl'] for row in selected),
            'closed_fees': fsum(row['fees'] for row in selected),
            'open_cycles': sum(row[key] == flag for row in opened)} for flag in (False, True, None)}
    return {'status': 'PASS', 'closed_cycles': len(closed), 'open_cycles': len(opened),
        'reconciliation_residual': reconstructed - equity_change, 'groups': groups, 'cycles': rows,
        'limits': 'Actual path description only. Signal close versus the contemporaneous exit line is not execution-price classification. Closed cycle PnL is not annual return or the causal value of removing a group. First-held decisions are observations, not exact intrabar execution timestamps; no later decision is UNOBSERVED, never False. OPEN retains actual mark and paid buy fee only.'}
