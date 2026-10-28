"""Describe C0013's actual entries against C0043's contemporaneous real state.

Read existing public EvidenceRefs with SHA/identity validation. Reuse the fixed
SPY20 interpretation and compare original primary products, economic contracts
and BH paths. No account replay, diagnosis invocation, new condition or price
read. The existing COMPUTED C0043/C0013 public diagnosis is retained by path/SHA
and exact ordered source refs, and its reconciliations check endpoint accounting.

Partition ONLY C0013's original 68 CLOSED cycles by TRUE/FALSE/UNKNOWN SPY facts
at the actual BUY decision. Independently classify C0043 as already held, flat
with stock-ready entry blocked by market, flat-and-allowed, stock-not-ready or
unknown. Held facts must match the preceding actual account-point quantity.
Every actual fill joins its order and decision with matching execution bounds.
UNKNOWN is retained. Cycle net returns use original ledger values; quantiles are
linear and are not portfolio returns. Annual groupings use actual entry dates.

List both accounts' actual cycles intersecting 2025, including each terminal OPEN
cycle. Closed net_pnl and net_return are original trade fields. OPEN net_pnl and
exit remain null: only separately labelled terminal marked value minus actual
entry cost is displayed, including paid buy fees but no hypothetical sell fee.
Cycle PnL spanning a year boundary is not that year's account return. Annual
equity changes use the actual continuous account's year-end points.

These conditional descriptions reflect earlier holdings, cash, quantities and
available opportunities. A FALSE group's historical PnL is NOT the causal value
of filtering it. Do not delete a group, add back fees, synthesize a replacement
portfolio, claim hindsight year rules, or pre-judge a crossday ORB combination.
"""
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
import math
from pathlib import Path
import sys

from czsc_trader.research_tools import ExperimentRef

from analyze import load_accounts, verify_contracts, verify_hold_path
from run import ROOT, WORK, EXPERIMENT, read, save

# Read-only reuse of authenticated fact interpretation; never call its main().
sys.path.append(str(ROOT/'research/S017/experiments/EX011_20261029/src'))
from describe_entry_context import (bind_source, verify_market_source, classify_context,
                                    aggregate, groups, check_partition)
from describe_exits import at, index_unique, equal, ZONE


CONTROL = ExperimentRef('S017', 'EX003_20261028')
STATES = ('HELD_ALREADY', 'FLAT_MARKET_BLOCKS_ENTRY', 'FLAT_ALLOWED', 'FLAT_STOCK_NOT_READY', 'UNKNOWN')


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def ledger(payload):
    run = payload['runs']['candidate']
    decisions = index_unique(run['decisions'], 'decision_id')
    orders = index_unique(run['orders'], 'order_id')
    trades = index_unique(run['trades'], 'cycle_id')
    index_unique(run['fills'], 'fill_id')
    grouped = defaultdict(list)
    for fill in run['fills']:
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
    last = run['account_points'][-1]
    cycles = []
    for cycle_id, fills in grouped.items():
        buys = [fill for fill in fills if fill['side'] == 'BUY']
        sells = [fill for fill in fills if fill['side'] == 'SELL']
        if len(buys) != 1 or len(sells) > 1:
            raise ValueError('description requires original whole-entry/whole-exit contract')
        entry = buys[0]
        cost = entry['quantity']*entry['price']+entry['fees']
        decision = decisions[orders[entry['order_id']]['decision_id']]
        trade = trades.get(cycle_id)
        common = {'cycle_id': cycle_id, 'entry_at': entry['interval_start'],
            'entry_interval_end': entry['interval_end'], 'entry_time_precision': entry['time_precision'],
            'entry_local': at(entry['interval_start']).astimezone(ZONE).isoformat(),
            'entry_session': at(entry['interval_start']).astimezone(ZONE).date().isoformat(),
            'entry_decision_id': decision['decision_id'], 'entry_decision_at': decision['decision_at'],
            'entry_order_id': entry['order_id'], 'entry_fill_id': entry['fill_id'],
            'entry_quantity': entry['quantity'], 'entry_price': entry['price'], 'entry_cost': cost,
            'fees': math.fsum(fill['fees'] for fill in fills)}
        if trade is not None:
            if (trade['status'] != 'CLOSED' or len(sells) != 1 or sells[0]['quantity'] != entry['quantity']
                    or at(trade['entry_at']) != at(entry['interval_start'])
                    or at(trade['exit_at']) != at(sells[0]['interval_end'])):
                raise ValueError('closed cycle does not match actual whole fills')
            equal(cost, trade['cost'], 'recorded cycle entry cost')
            cycles.append({**common, 'status': 'CLOSED', 'exit_at': trade['exit_at'],
                'exit_fill_interval_start': sells[0]['interval_start'],
                'exit_fill_interval_end': sells[0]['interval_end'],
                'exit_time_precision': sells[0]['time_precision'],
                'exit_local_interval_start': at(sells[0]['interval_start']).astimezone(ZONE).isoformat(),
                'exit_local_interval_end': at(sells[0]['interval_end']).astimezone(ZONE).isoformat(),
                'exit_price': sells[0]['price'], 'net_pnl': trade['net_pnl'], 'net_return': trade['net_return'],
                'terminal_mark_pnl_after_paid_entry_fee': None})
        else:
            if sells or cycle_id != last['cycle_id'] or entry['quantity'] != last['quantity']:
                raise ValueError('unclosed cycle does not match terminal real holdings')
            cycles.append({**common, 'status': 'OPEN', 'exit_at': None,
                'exit_fill_interval_start': None, 'exit_fill_interval_end': None,
                'exit_time_precision': None, 'exit_local_interval_start': None, 'exit_local_interval_end': None,
                'exit_price': None, 'net_pnl': None, 'net_return': None,
                'terminal_mark_at': last['time'], 'terminal_mark_price': last['close'],
                'terminal_mark_pnl_after_paid_entry_fee': last['quantity']*last['close']-cost})
    closed = [row for row in cycles if row['status'] == 'CLOSED']
    opened = [row for row in cycles if row['status'] == 'OPEN']
    if len(closed) != len(trades) or len(closed) != run['metrics']['closed_cycles']:
        raise ValueError('cycle count differs from original account')
    residuals = {'all_fees_minus_metric': equal(math.fsum(row['fees'] for row in cycles),
                    run['metrics']['fees'], 'all cycle fees vs account'),
        'closed_plus_open_mark_minus_equity_change': equal(
            math.fsum(row['net_pnl'] for row in closed)+math.fsum(row['terminal_mark_pnl_after_paid_entry_fee'] for row in opened),
            last['equity']-payload['request']['initial_cash'], 'closed pnl plus actual terminal mark')}
    return cycles, residuals, decisions, orders


def actual_other_state(origin, matches, other_run, other_orders, other_fills):
    if len(matches) != 1:
        return 'UNKNOWN', {'reason': 'MISSING_OR_DUPLICATE_EXACT_OTHER_DECISION'}
    decision = matches[0]
    explanation = decision.get('explanation') or {}
    facts = {item['key']: item['text'] for item in explanation.get('basis', [])}
    points = other_run['account_points']
    point_times = [at(point['time']) for point in points]
    index = bisect_right(point_times, at(origin['decision_at']))-1
    if index < 0:
        return 'UNKNOWN', {'reason': 'NO_PRIOR_ACTUAL_ACCOUNT_POINT'}
    point = points[index]
    if at(point['time']) > at(decision['execution_start']):
        raise ValueError('future account state entered the description')
    held = point['quantity'] > 0
    if facts.get('held') != str(held):
        raise ValueError('recorded held fact differs from prior actual account quantity')
    context_orders = [order for order in other_orders.values() if order['decision_id'] == decision['decision_id']]
    order_ids = {order['order_id'] for order in context_orders}
    state = {'decision_id': decision['decision_id'], 'held': held, 'prior_account_point_at': point['time'],
             'quantity': point['quantity'], 'cash': point['cash'], 'equity': point['equity'],
             'base_target': facts.get('base_target'), 'market_allowed': facts.get('market_allowed'),
             'target': decision['target'], 'orders': context_orders,
             'actual_fills': [fill for fill in other_fills if fill['order_id'] in order_ids]}
    if held:
        return 'HELD_ALREADY', state
    if facts.get('base_target') == 'False':
        return 'FLAT_STOCK_NOT_READY', state
    if facts.get('base_target') == 'True' and facts.get('market_allowed') == 'False' and decision['target'] == 0:
        return 'FLAT_MARKET_BLOCKS_ENTRY', state
    if facts.get('base_target') == 'True' and facts.get('market_allowed') == 'True' and decision['target'] == 1:
        return 'FLAT_ALLOWED', state
    return 'UNKNOWN', {**state, 'reason': 'INCONSISTENT_OR_MISSING_STATE_FACTS'}


def state_groups(rows):
    return {state: aggregate([row for row in rows if row['c0043_state'] == state]) for state in STATES}


def describe():
    """Return the authenticated description without writing or evaluating an account."""
    own, own_refs = load_accounts(CONTROL.resolve(ROOT), CONTROL, ('C0013',))
    other, other_refs = load_accounts(WORK, EXPERIMENT, ('C0043',), exact=True)
    payloads, refs = {**own, **other}, {**own_refs, **other_refs}
    contract_checks, bh_checks = verify_contracts(payloads), verify_hold_path(payloads)
    _, source13 = bind_source(CONTROL.resolve(ROOT), CONTROL, 'C0013', own['C0013'])
    definition, source43 = bind_source(WORK, EXPERIMENT, 'C0043', other['C0043'])
    market_binding = verify_market_source(other['C0043'], definition)
    diagnostic_path = WORK/'others/diagnostics/C0043_vs_C0013.json'
    diagnostic = read(diagnostic_path)
    if (diagnostic['status'] != 'COMPUTED' or diagnostic['issues']
            or diagnostic['sources'] != [asdict(refs['C0013']), asdict(refs['C0043'])]):
        raise ValueError('existing public diagnosis does not authenticate this exact ordered pair')
    accounts = {}
    all_cycles = {}
    decisions = {}
    orders = {}
    for key, payload in payloads.items():
        all_cycles[key], reconciliation, decisions[key], orders[key] = ledger(payload)
        current = payload['runs']['candidate']
        public = next(item for item in diagnostic['reconciliation'] if item['evaluation_id'] == payload['evaluation_id'])
        equal(public['opening_equity'], payload['request']['initial_cash'], 'public diagnostic opening')
        equal(public['closing_equity'], current['account_points'][-1]['equity'], 'public diagnostic closing')
        equal(public['equity_change'], public['decomposed_change'], 'existing public diagnostic decomposition')
        prior = [row for row in current['account_daily'] if row['session'].startswith('2024')][-1]
        end = [row for row in current['account_daily'] if row['session'].startswith('2025')][-1]
        cycles2025 = [row for row in all_cycles[key] if row['entry_session'] <= '2025-12-31'
                      and (row['exit_at'] is None or at(row['exit_at']).astimezone(ZONE).date().isoformat() >= '2025-01-01')]
        accounts[key] = {'full_closed_cycles': sum(row['status'] == 'CLOSED' for row in all_cycles[key]),
            'full_open_cycles': sum(row['status'] == 'OPEN' for row in all_cycles[key]),
            'cycle_ledger_reconciliation': reconciliation, 'public_diagnostic_reconciliation': public,
            'opening_2025_equity': prior['equity'], 'closing_2025_equity': end['equity'],
            'opening_2025_quantity': prior['quantity'],
            'actual_2025_equity_change': end['equity']-prior['equity'],
            'terminal_quantity': end['quantity'], 'terminal_cash': end['cash'],
            'actual_cycles_intersecting_2025': cycles2025}
        if prior['quantity'] != 0 or any(not row['entry_session'].startswith('2025') for row in cycles2025):
            raise ValueError('this exact 2025 path bridge requires the observed flat year-start accounts')
        accounts[key]['actual_2025_closed_cycle_net_pnl'] = math.fsum(
            row['net_pnl'] for row in cycles2025 if row['status'] == 'CLOSED')
        accounts[key]['actual_2025_terminal_open_mark_pnl'] = math.fsum(
            row['terminal_mark_pnl_after_paid_entry_fee'] for row in cycles2025 if row['status'] == 'OPEN')
        equal(accounts[key]['actual_2025_closed_cycle_net_pnl']+accounts[key]['actual_2025_terminal_open_mark_pnl'],
              accounts[key]['actual_2025_equity_change'], 'actual 2025 closed/open-mark path bridge')
    context_times = defaultdict(list)
    for decision in other['C0043']['runs']['candidate']['decisions']:
        context_times[at(decision['decision_at'])].append(decision)
    rows, open_entries = [], []
    for cycle in all_cycles['C0013']:
        decision = decisions['C0013'][cycle['entry_decision_id']]
        matches = context_times[at(decision['decision_at'])]
        group, facts, reason = classify_context(decision, matches, 432000)
        state, other_state = actual_other_state(decision, matches,
            other['C0043']['runs']['candidate'], orders['C0043'], other['C0043']['runs']['candidate']['fills'])
        described = {**cycle, 'entry_market': group, 'market_facts': facts, 'market_classification_basis': reason,
                     'c0043_state': state, 'c0043_actual_state': other_state}
        (rows if cycle['status'] == 'CLOSED' else open_entries).append(described)
    if len(rows) != 68:
        raise ValueError('original 68 C0013 closed cycles must all be retained')
    total, grouped, states = aggregate(rows), groups(rows), state_groups(rows)
    cross = {group: state_groups([row for row in rows if row['entry_market'] == group])
             for group in ('TRUE', 'FALSE', 'UNKNOWN')}
    years = {str(year): {'total': aggregate([row for row in rows if row['entry_session'].startswith(str(year))]),
        'market_groups': groups([row for row in rows if row['entry_session'].startswith(str(year))]),
        'c0043_state_groups': state_groups([row for row in rows if row['entry_session'].startswith(str(year))])}
        for year in range(2019, 2026)}
    residuals = {'market': check_partition(list(grouped.values()), total, 'market groups'),
        'state': check_partition(list(states.values()), total, 'actual state groups'),
        'cross': check_partition([item for value in cross.values() for item in value.values()], total, 'market/state cross'),
        'years': check_partition([value['total'] for value in years.values()], total, 'entry years')}
    for year, value in years.items():
        residuals[year+'_market'] = check_partition(list(value['market_groups'].values()), value['total'], year+'/market')
        residuals[year+'_state'] = check_partition(list(value['c0043_state_groups'].values()), value['total'], year+'/state')
    differences = {field: accounts['C0043'][field]-accounts['C0013'][field]
        for field in ('opening_2025_equity', 'closing_2025_equity', 'actual_2025_equity_change',
                      'actual_2025_closed_cycle_net_pnl', 'actual_2025_terminal_open_mark_pnl',
                      'terminal_quantity', 'terminal_cash')}
    equal(differences['opening_2025_equity']+differences['actual_2025_equity_change'],
          differences['closing_2025_equity'], 'actual 2025 wealth difference bridge')
    report = {'schema': 'S017_C0013_ENTRY_STATE_DIFFERENCE_V1', 'status': 'PASS',
        'script_sha256': digest(Path(__file__)), 'source_accounts': {key: ref.to_dict() for key, ref in refs.items()},
        'frozen_sources': {'C0013': source13, 'C0043': source43},
        'same_contract_and_primary': contract_checks, 'same_bh_path': bh_checks,
        'market_source_and_holding_independence': market_binding,
        'existing_public_diagnostic': {'path': diagnostic_path.relative_to(ROOT).as_posix(),
            'sha256': digest(diagnostic_path), 'status': diagnostic['status'], 'sources': diagnostic['sources'],
            'reconciliation': diagnostic['reconciliation'], 'new_diagnosis_invocations': 0},
        'closed_cycle_totals': total, 'by_entry_market': grouped, 'by_c0043_actual_state': states,
        'market_by_actual_state': cross, 'by_entry_year': years, 'reconciliation_residuals': residuals,
        'unknown_market_reasons': dict(Counter(row['market_classification_basis'] for row in rows if row['entry_market'] == 'UNKNOWN')),
        'c0013_closed_cycles': rows, 'c0013_unclosed_entries_separate_from_68': open_entries,
        'actual_entry_alignment': {
            'c0013_closed_cycles': len(rows),
            'c0013_closed_entry_points_with_c0043_actual_buy_fill': sum(
                any(fill['side'] == 'BUY' for fill in row['c0043_actual_state'].get('actual_fills', [])) for row in rows),
            'c0043_closed_entries_at_other_decision_times': sum(
                row['status'] == 'CLOSED' and at(row['entry_decision_at']) not in {
                    at(original['entry_decision_at']) for original in rows} for row in all_cycles['C0043']),
            'interpretation': 'A_BLOCKED_ORIGINAL_ENTRY_IS_NOT_A_PERMANENTLY_REMOVED_CYCLE'},
        'accounts_actual_2025_paths': accounts, 'c0043_minus_c0013_actual_wealth_bridge': differences,
        'method_sources': [{'path': str(path.relative_to(ROOT).as_posix()), 'sha256': digest(path)} for path in (
            ROOT/'research/S017/experiments/EX011_20261029/src/describe_entry_context.py',
            ROOT/'research/S017/experiments/EX011_20261029/src/describe_exits.py')],
        'limitations': ['CONDITIONAL_ORIGINAL_TRADES_NOT_FILTER_COUNTERFACTUAL',
            'REAL_C0043_HOLDINGS_CASH_AND_OPPORTUNITIES_EXPLICITLY_SEPARATED',
            'FALSE_GROUP_PNL_IS_NOT_CAUSAL_FILTER_CONTRIBUTION', 'UNKNOWN_RETAINED',
            'OPEN_CYCLE_NET_PNL_NULL_TERMINAL_MARK_SEPARATE_NO_HYPOTHETICAL_EXIT_FEE',
            'CYCLE_RETURNS_NOT_PORTFOLIO_RETURN_YEAR_TABLE_NOT_TRADING_RULE',
            'NO_REPLAY_NO_NEW_PUBLIC_DIAGNOSIS_NO_NEW_THRESHOLD_NO_2026_PRICE']}
    return report


def main():
    report = describe()
    save(WORK/'others/entry_difference_description.json', report)
    print('MARKET', report['by_entry_market'], flush=True)
    print('STATES', report['by_c0043_actual_state'], flush=True)
    print('ACTUAL_WEALTH_BRIDGE', report['c0043_minus_c0013_actual_wealth_bridge'], flush=True)
    for key, account in report['accounts_actual_2025_paths'].items():
        print(key, '2025_CYCLES', [{field: cycle[field] for field in ('status','entry_local','exit_local_interval_start',
            'net_pnl','fees','entry_quantity','entry_price','terminal_mark_pnl_after_paid_entry_fee')}
            for cycle in account['actual_cycles_intersecting_2025']], flush=True)


if __name__ == '__main__':
    main()
