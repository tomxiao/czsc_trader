"""Successor cash/order audit using exact original public resolver return for BUY prices.

Original clock financial helper retained except a required public-price oracle
argument and replacement of the over-strong float price<=limit shortcut.
The original resolver contract is unchanged and no new audit epsilon is used.
No strategy replay, order construction, market-data export or dispatch.
"""
import audit_ex044_accounts as P

check=P.A.check
number=P.A.number
day=P.A.day

ORIGINAL_LEDGER_HELPER_SHA256="b069a1c2e2df876db555265b216e3d525b01b160b77418bd2b9af4cd1a6ddffb"

def audit_daily(account, reserve_blocked_slots, approved_fill_prices):
    run = account['runs'][0]
    ledgers = run['ledgers']
    daily = ledgers['account_daily']['data']
    fills = ledgers['fills']['data']
    orders = ledgers['orders']['data']
    decisions = ledgers['decisions']['data']
    by_date = {day(r['date']): r for r in daily}
    by_fill = {day(r['fill_time']): r for r in fills}
    by_order = {r['order_id']: r for r in orders}
    by_decision = {r['decision_id']: r for r in decisions}
    check('original 1642 daily records', len(daily) == len(by_date) == len(decisions) == 1642)
    check('dates sorted', list(by_date) == sorted(by_date))
    check('one actual fill per day', len(by_fill) == len(fills))
    check('unique order and decision IDs', len(by_order) == len(orders) and len(by_decision) == len(decisions))
    prev_cash, prev_q, prev_wealth, prev_close = 100000., 0, 100000., None
    pending_sell = False
    entry_index = None
    deadline_index = None
    reservation = -1
    last_planned_buy = False
    intervention_count = 0
    for i, row in enumerate(daily):
        E = day(row['date'])
        dec = decisions[i]
        D = day(dec['signal_date'])
        check('strict original D/E clock', D < E and day(dec['valid_session']) == E and (i == 0 or D == day(daily[i-1]['date'])))
        check('daily signal identity', D == day(row['signal_date']))
        check('cash and quantity continuity', row['cash_before'] == prev_cash and row['quantity_before'] == prev_q)
        number('wealth identity', row['equity'], row['cash'] + row['quantity'] * row['close'], True)
        fill = by_fill.get(E)
        fee = 0.
        mark = 0.
        if fill:
            fee = fill['fees']
            check('fill linked to actual order', fill['order_id'] in by_order)
            order = by_order[fill['order_id']]
            check('filled order source clock and side', order['status'] == 'FILLED' and order['side'] == fill['side']
                  and order['decision_id'] == fill['decision_id'] and day(order['execution_date']) == E
                  and day(order['signal_date']) == day(fill['signal_date']) and day(fill['signal_date']) < E)
            check('fill quantity and cycle link', fill['quantity'] == order['quantity'] and fill['cycle_id'] == order['cycle_id'])
            check('positive original integer lot', isinstance(fill['quantity'], int) and fill['quantity'] > 0 and fill['quantity'] % 100 == 0)
            number('exact fee-rate arithmetic', fee, fill['quantity'] * fill['price'] * .001, True)
            if fill['side'] == 'BUY':
                check('BUY price exactly original public resolver return', fill['price'] == approved_fill_prices[fill['order_id']])
                check('full-position buy from flat', prev_q == 0 and row['quantity'] == fill['quantity'])
                number('cash after buy', row['cash'], prev_cash - fill['quantity'] * fill['price'] - fee, True)
                mark = fill['quantity'] * (row['close'] - fill['price'])
            else:
                check('full-position sale', fill['side'] == 'SELL' and prev_q == fill['quantity'] and row['quantity'] == 0)
                number('cash after sell', row['cash'], prev_cash + fill['quantity'] * fill['price'] - fee, True)
                mark = fill['quantity'] * (fill['price'] - prev_close)
        else:
            check('no-fill position/cash unchanged', row['quantity'] == prev_q and row['cash'] == prev_cash)
            if prev_q:
                mark = prev_q * (row['close'] - prev_close)
        number('daily marked PnL and fees', row['equity'] - prev_wealth, mark - fee, True)
        # Decisions describe the preceding D. Reconstruct its actual filled state, not a private matcher.
        fill_D = by_fill.get(D)
        check('observed D actual BUY fill flag', bool(dec['buy_filled_today']) == bool(fill_D and fill_D['side'] == 'BUY'))
        check('observed D actual SELL fill flag', bool(dec['sell_filled_today']) == bool(fill_D and fill_D['side'] == 'SELL'))
        if fill_D and fill_D['side'] == 'BUY':
            entry_index, deadline_index, reservation = i, i+9, i+10
            pending_sell = False
        elif fill_D and fill_D['side'] == 'SELL':
            entry_index, deadline_index, pending_sell = None, None, False
        # The sole new clock contract: a blocked prospective slot has no real entry.
        if reserve_blocked_slots and bool(dec['gate_slot_consumed']):
            check('virtual slot consumes only blocked flat intent', bool(dec['entry_guard_blocked']) and prev_q == 0
                  and not dec['entry_signal'] and not dec['failed_buy_reset']
                  and dec['entry_index'] == -1 and dec['deadline_index'] == -1)
            reservation = i + 11
        held_D = prev_q > 0
        check('observed D holding exact', bool(dec['held_at_close']) == held_D)
        check('observed original anchors', dec['entry_index'] == (-1 if entry_index is None else entry_index)
              and dec['deadline_index'] == (-1 if deadline_index is None else deadline_index)
              and dec['reservation_index'] == reservation)
        if bool(dec.get('intervention_today', False)):
            intervention_count += 1
        check('D target matches holding/intent', dec['target_position'] == float(bool(dec['entry_signal']) or (held_D and not bool(dec['exit_pending']))))
        check('daily E target from D', row['target_position'] == dec['target_position'])
        if pending_sell and not (fill_D and fill_D['side'] == 'SELL'):
            check('blocked SELL intent remains pending', bool(dec['exit_pending']))
        if held_D and bool(dec['exit_pending']):
            pending_sell = True
        planned_side = 'BUY' if dec['entry_signal'] else 'SELL' if held_D and dec['exit_pending'] else None
        own_orders = [o for o in orders if o['decision_id'] == dec['decision_id']]
        check('one order for each intended action', len(own_orders) == (0 if planned_side is None else 1))
        if own_orders:
            check('planned side and date exact', own_orders[0]['side'] == planned_side and day(own_orders[0]['signal_date']) == D
                  and day(own_orders[0]['execution_date']) == E)
        if not held_D:
            check('no new BUY before original reservation', not dec['entry_signal'] or i >= reservation)
        if i and last_planned_buy and not (fill_D and fill_D['side'] == 'BUY'):
            check('real failed BUY reset', bool(dec['failed_buy_reset']))
        last_planned_buy = bool(dec['entry_signal'])
        prev_cash, prev_q, prev_wealth, prev_close = row['cash'], row['quantity'], row['equity'], row['close']
    for order in orders:
        check('order refers to saved decision', order['decision_id'] in by_decision)
    trades = ledgers['trades']['data']
    check('unique actual trade cycles', len({t['cycle_id'] for t in trades}) == len(trades))
    for trade in trades:
        cycle = [f for f in fills if f['cycle_id'] == trade['cycle_id']]
        buys = [f for f in cycle if f['side'] == 'BUY']
        sales = [f for f in cycle if f['side'] == 'SELL']
        check('one actual entry per trade', len(buys) == 1)
        buy = buys[0]
        check('trade original actual entry', day(trade['entry_date']) == day(buy['fill_time']) and trade['quantity'] == buy['quantity'])
        number('trade aggregated entry price', trade['entry_price'], buy['price'], True)
        if trade['status'] == 'CLOSED':
            check('closed trade actual sale', len(sales) == 1)
            sale = sales[0]
            check('trade original actual exit', day(trade['exit_date']) == day(sale['fill_time']) and sale['quantity'] == buy['quantity'])
            number('trade aggregated exit price', trade['exit_price'], sale['price'], True)
            number('closed trade fee-adjusted return', trade['net_return'], (sale['quantity'] * sale['price'] - sale['fees']) / (buy['quantity'] * buy['price'] + buy['fees']) - 1)
        else:
            check('open trade explicit unsold mark', trade['status'] == 'MARKED_OPEN_NO_EXIT_FEE' and not sales)
            number('open trade no fictive exit fee', trade['net_return'], daily[-1]['close'] / (buy['price'] * 1.001) - 1)
    return {'intervention_count': intervention_count, 'order_count': len(orders), 'fill_count': len(fills)}
