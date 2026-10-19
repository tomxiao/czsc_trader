"""Independent EX040 public-account audit. No account dispatch, matching or upstream calls.

Run at repository root. Index schema: records with index/mode/candidate/status/
evidence/result_hash. A new output path is mandatory; prior audits are never overwritten.
"""
import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
import math
from pathlib import Path
import socket

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
MONEY_TOLERANCE = 1e-7
RATIO_TOLERANCE = 1e-10
TERMINAL = '2025-12-31'
MODES = ['NOOP', 'SKIP_BUY_ONCE', 'FORCE_SELL_ONCE']
NODES = {'SKIP_BUY_ONCE': '2025-06-18', 'FORCE_SELL_ONCE': '2025-06-19'}
ID_KEYS = {'decision_id', 'cycle_id', 'fill_id', 'order_id'}
COUNTS = Counter()
ERRORS = {'currency': 0., 'ratio': 0.}
IDENTITY_MAPS = {}

def block(*args, **kwargs):
    raise RuntimeError('Independent audit forbids network and account dispatch')

socket.socket.connect = block
socket.create_connection = block

def check(category, value, detail=''):
    if not value:
        raise AssertionError(category + ': ' + detail)
    COUNTS[category] += 1

def number(category, actual, expected, currency=False):
    error = abs(float(actual) - float(expected))
    unit = 'currency' if currency else 'ratio'
    ERRORS[unit] = max(ERRORS[unit], error)
    check(category, math.isfinite(float(actual)) and error <= (MONEY_TOLERANCE if currency else RATIO_TOLERANCE),
          repr((actual, expected, error)))

def day(value):
    return str(value)[:10]

def read(path):
    return json.loads(path.read_bytes())

def published(value):
    ref = EvidenceRef.from_dict(value)
    check('S014 references only', ref.experiment.strategy_id == 'S014')
    raw = ref.resolve(ROOT).read_bytes()
    check('published content SHA', sha256(raw).hexdigest() == ref.sha256)
    return json.loads(raw)

def public_bytes(value):
    ref = EvidenceRef.from_dict(value)
    check('S014 source references only', ref.experiment.strategy_id == 'S014')
    raw = ref.resolve(ROOT).read_bytes()
    check('published source content SHA', sha256(raw).hexdigest() == ref.sha256)
    return raw

def audit_identity(record, account, original):
    base = ROOT / 'research/S014/experiments/EX040_20261019'
    lock = published(read(base / 'protocols/revision02/published_lock.json'))
    planned = next(r for r in lock['runs'] if r['index'] == record['index'])
    for key in ['mode', 'parameters', 'candidate', 'runtime_sha256', 'payload_sha256']:
        check('locked account identity ' + key, record[key] == planned[key])
    payload = published(record['published_payload_ref'])
    binding = published(record['binding_ref'])
    public_bytes(record['published_source_ref'])
    check('payload SHA equals frozen reference', record['payload_sha256'] == record['published_payload_ref']['sha256'])
    check('public runtime source is locked corrected code', record['published_source_ref']['sha256'] == lock['source_hashes']['src/revision02/strategy_runtime/strategies/repair_action_review.py'])
    check('runtime implementation closure lock', record['runtime_implementation_sha256'] == lock['runtime_implementation_sha256'] == payload['runtime']['source_sha256'])
    check('public payload parameters exact', payload['parameters'] == record['parameters'] == {'variant': 'support_exit_reserve_H10', 'intervention_mode': record['mode'], 'intervention_decision_date': NODES.get(record['mode'], '')})
    check('public binding exact payload and candidate', binding['payload'] == payload and binding['candidate'] == record['candidate'])
    req = account['request_identity']
    check('public request content identity', req['content_sha256'] == record['request_content_sha256'])
    check('runtime binding receipt identity', account['runtime_binding_hash'] == record['runtime_binding_hash'] == req['runtime_binding_hash'])
    check('public preparation binding exact', req['input_bindings'] == binding['input_bindings'])
    check('account candidate bound to receipt', account['runs'][0]['candidate_id'] == record['candidate'].split('-')[-1])
    source = read(ROOT / 'research/S014/materials/20261019_2025_action_method_review/method/source_bindings.json')
    for key, source_key in [('execution_requests', 'original_execution_requests'), ('execution_identities', 'original_execution_identities'),
                            ('execution_fingerprint', 'original_execution_fingerprint'), ('execution_prepared', 'original_execution_prepared')]:
        check('same authenticated original ' + key, binding[key] == source[source_key])
    check('account execution content identity', req['data_identity'] == binding['execution_fingerprint'] == original['request_identity']['data_identity'])
    plan, old_plan = req['input_bindings']['full']['plan'], original['request_identity']['input_bindings']['full']['plan']
    check('input plan identity keys exact', plan.keys() == old_plan.keys())
    for key in plan:
        if key != 'strategy':
            check('original causal input clock/requests ' + key, plan[key] == old_plan[key])
    check('plan bound to new public runtime', plan['strategy']['reference_id'] == record['candidate'] and plan['strategy']['runtime_sha256'] == record['runtime_sha256'])
    check('new immutable strategy identity', plan['strategy']['release_hash'] == account['strategy_identity'] == req['strategy_identity'] and account['strategy_identity'] != original['strategy_identity'])
    return {'payload_sha256': record['payload_sha256'], 'runtime_implementation_sha256': record['runtime_implementation_sha256'],
            'runtime_sha256': record['runtime_sha256'], 'strategy_identity': account['strategy_identity'],
            'source_sha256': record['published_source_ref']['sha256'], 'binding_ref': record['binding_ref'],
            'candidate_alias_deviation': 'Frozen design C9710/11/12; actual lock and account C9700/01/02. Alias reused; immutable runtime/payload identities audited distinctly; no formal registration.'}

def economic_rows(left, right, category, cutoff=None, date_key=None, omit=None):
    if cutoff is not None:
        left = [r for r in left if day(r[date_key]) <= cutoff]
        right = [r for r in right if day(r[date_key]) <= cutoff]
    check(category + ' row count', len(left) == len(right))
    ignored = ID_KEYS | set(omit or [])
    for index, (old, new) in enumerate(zip(left, right, strict=True)):
        for key, value in old.items():
            if key in ID_KEYS:
                mapping, reverse = IDENTITY_MAPS.setdefault(key, ({}, {}))
                current = new[key]
                check(category + ' identity null consistency', (value is None) == (current is None))
                check(category + ' identity one-to-one mapping', mapping.get(value, current) == current and reverse.get(current, value) == value)
                mapping[value], reverse[current] = current, value
            elif key not in ignored:
                check(category + ' exact economic value', key in new and new[key] == value, str((index, key, value, new.get(key))))

def equal_baseline(original, account):
    old, new = original['runs'][0]['buyhold'], account['runs'][0]['buyhold']
    check('original benchmark contract exact', old['benchmark'] == new['benchmark'])
    for name in ['account_daily', 'fills', 'orders', 'attempts']:
        economic_rows(old[name]['data'], new[name]['data'], 'benchmark ' + name)
    check('benchmark metric values exact', old['metrics'] == new['metrics'])

def yearly(daily):
    by_year = {}
    previous = 100000.
    for row in daily:
        y = int(day(row['date'])[:4])
        bucket = by_year.setdefault(y, {'opening': previous, 'values': [previous], 'dates': []})
        bucket['values'].append(row['equity'])
        bucket['dates'].append(day(row['date']))
        previous = row['equity']
    output = {}
    for y, item in by_year.items():
        peak = item['values'][0]
        mdd = 0.
        for wealth in item['values'][1:]:
            peak = max(peak, wealth)
            mdd = max(mdd, 1 - wealth / peak)
        output[y] = {'opening_equity': item['opening'], 'closing_equity': item['values'][-1],
                     'return': item['values'][-1] / item['opening'] - 1, 'max_drawdown': mdd,
                     'sessions': len(item['dates'])}
    return output

def audit_daily(account):
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
                check('original limit BUY no worse than limit', fill['price'] <= order['limit_price'])
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

def noop_equivalence(original, account):
    old, new = original['runs'][0], account['runs'][0]
    for name in ['account_daily', 'decisions', 'orders', 'fills', 'trades']:
        economic_rows(old['ledgers'][name]['data'], new['ledgers'][name]['data'], 'NOOP ' + name)
    economic_rows(old['signals']['data'], new['signals']['data'], 'NOOP source signals')

def prefix_and_intervention(original, account, mode):
    if mode == 'NOOP':
        return None
    D = NODES[mode]
    old, new = original['runs'][0], account['runs'][0]
    for name, key in [('account_daily', 'date'), ('orders', 'execution_date'), ('fills', 'fill_time')]:
        economic_rows(old['ledgers'][name]['data'], new['ledgers'][name]['data'], mode + ' original economic prefix', D, key)
    # D row intentionally changes one instruction; all preceding decisions remain original.
    old_dec, new_dec = old['ledgers']['decisions']['data'], new['ledgers']['decisions']['data']
    before = max(day(r['signal_date']) for r in old_dec if day(r['signal_date']) < D)
    economic_rows(old_dec, new_dec, mode + ' preceding decisions', before, 'signal_date')
    old_node = next(r for r in old_dec if day(r['signal_date']) == D)
    new_node = next(r for r in new_dec if day(r['signal_date']) == D)
    interventions = [r for r in new_dec if bool(r.get('intervention_today', False))]
    check('exactly one fixed intervention', len(interventions) == 1 and day(interventions[0]['signal_date']) == D)
    allowed = {'action', 'target_position', 'entry_signal', 'holding_horizon'} if mode == 'SKIP_BUY_ONCE' else {'action', 'target_position', 'exit_pending'}
    for key, value in old_node.items():
        if key not in ID_KEYS | allowed:
            check('D unchanged original state', new_node[key] == value, str((key, new_node[key], value)))
    if mode == 'SKIP_BUY_ONCE':
        check('SKIP original accepted flat BUY', bool(old_node['entry_signal']) and not old_node['held_at_close'])
        check('SKIP removes only one intended entry', not new_node['entry_signal'] and new_node['target_position'] == 0 and not new_node['failed_buy_reset']
              and new_node['entry_index'] == -1 and new_node['deadline_index'] == -1 and new_node['reservation_index'] == old_node['reservation_index'])
    else:
        check('FORCE original held HOLD eligibility', bool(old_node['held_at_close']) and not old_node['entry_signal'] and not old_node['exit_pending'] and old_node['target_position'] == 1)
        check('FORCE pending preserves original anchors', bool(new_node['exit_pending']) and new_node['target_position'] == 0
              and all(new_node[k] == old_node[k] for k in ['entry_index', 'deadline_index', 'reservation_index']))
    return D

def disposition_base(account, D, terminal):
    run = account['runs'][0]
    daily = {day(r['date']): r for r in run['ledgers']['account_daily']['data']}
    initial, end = daily[D], daily[terminal]
    quantity, residual = initial['quantity'], initial['cash']
    check('held-node existing inventory positive', quantity > 0)
    fills = run['ledgers']['fills']['data']
    buys = [f for f in fills if f['side'] == 'BUY' and day(f['fill_time']) <= D]
    origin = max(buys, key=lambda f: f['fill_time'])
    check('original held inventory matches June19 fill', day(origin['fill_time']) == D and origin['quantity'] == quantity)
    sales = [f for f in fills if f['cycle_id'] == origin['cycle_id'] and f['side'] == 'SELL' and D < day(f['fill_time']) <= terminal]
    check('at most one full original-inventory sale before T', len(sales) <= 1)
    if sales:
        sale = sales[0]
        after = daily[day(sale['fill_time'])]
        check('current-inventory full disposition', sale['quantity'] == quantity and after['quantity'] == 0)
        base = after['cash']
        number('original inventory disposition cash', base, residual + quantity * sale['price'] - sale['fees'], True)
        state = 'ACTUAL_SALE_CASH_FROZEN'
        sale_fact = {k: sale[k] for k in ['cycle_id', 'fill_time', 'price', 'quantity', 'fees', 'order_id']}
    else:
        check('unsold original position retained at T', end['quantity'] == quantity and end['cash'] == residual)
        base = residual + quantity * end['close']
        state, sale_fact = 'UNSOLD_MARK_NOT_CASH', None
    residual_participation = end['equity'] - base
    number('disposition plus participation identity', base + residual_participation, end['equity'], True)
    return {'base_type': state, 'base_terminal_currency': base, 'post_disposition_participation_currency': residual_participation,
            'actual_original_inventory_sale': sale_fact, 'terminal_wealth': end['equity']}

def terminal_state(account):
    ledgers = account['runs'][0]['ledgers']
    end = next(r for r in ledgers['account_daily']['data'] if day(r['date']) == TERMINAL)
    dec = next(r for r in ledgers['decisions']['data'] if day(r['signal_date']) == TERMINAL)
    return {'T': TERMINAL, 'cash': end['cash'], 'quantity': end['quantity'], 'close': end['close'], 'equity': end['equity'],
            'decision_known_at_T': dec,
            'next_session_instruction_only': [
                {k: o[k] for k in ['side', 'order_type', 'quantity', 'limit_price', 'signal_date', 'execution_date']}
                for o in ledgers['orders']['data'] if day(o['signal_date']) == TERMINAL],
            'uncompleted_position_at_T': end['quantity'] > 0,
            'next_session_actual_fill_or_status_excluded': True}

def execute(index_path, output, csv_path):
    index = read(index_path)
    check('explicit records index schema', isinstance(index['records'], list))
    records = index['records']
    check('attempt indices unique', len({r['index'] for r in records}) == len(records))
    resource = {'total_dispatched_records_including_failures_unknown': len(records), 'status_counts': dict(Counter(r['status'] for r in records)),
                'failure_or_unknown_records_preserved': [r for r in records if r['status'] != 'SUCCEEDED']}
    origin_record = read(ROOT / 'research/S014/experiments/EX023_20261018/others/account_results.json')['records'][0]
    original = published(origin_record['evidence'])
    check('original C0056 result identity', original['result_hash'] == '423a1ccf05574d17eb4fa3d5984de02dc869c7387cbe66bf4f502b54c7510ef6')
    result = {'original_account_evidence': origin_record['evidence'], 'resources': resource, 'audited_accounts': [],
              'action_wealth_2025_terminal_only': {}, 'tolerances': {'economic_NOOP_and_prefix': 'EXACT_NUMERIC_EQUALITY_EXCLUDING_IDENTITY_KEYS',
                 'derived_currency_arithmetic_absolute': MONEY_TOLERANCE, 'derived_ratio_arithmetic_absolute': RATIO_TOLERANCE,
                 'automatic_tolerance_expansion': False},
              'limitations': ['2026 annual return/drawdown is technical/full-contract audit only, not a chosen action-economic endpoint.',
                              'Seven annual goals are the original strict/equal conditions; no extra cross-year stability gate.',
                              'D-normalized effects concern different nodes and information sets; cannot be added or ranked as one common-state action.',
                              'Disposition/participation differences are exact accounting after actual fills, not causal alpha components.'],
              'new_account_dispatches_by_auditor': 0, 'new_market_data_calls_by_auditor': 0, 'new_model_fits': 0}
    completed = {}
    for record in records:
        if record['status'] != 'SUCCEEDED':
            continue
        mode = record['mode']
        IDENTITY_MAPS.clear()
        check('one successful fixed mode each', mode in MODES and mode not in completed)
        account = published(record['evidence'])
        identity = audit_identity(record, account, original)
        check('account result matches receipt', account['result_hash'] == record['result_hash'])
        check('one FULL account run', len(account['runs']) == 1 and account['execution_mode'] == 'FULL')
        req, old_req = account['request_identity'], original['request_identity']
        for key in ['asset_type', 'benchmark', 'costs', 'data_cutoff', 'execution_mode', 'frequency_window_days', 'initial_cash',
                    'market_rules', 'metric_semantics_version', 'price_basis', 'pricing', 'symbol', 'windows']:
            check('original evaluation contract ' + key, req[key] == old_req[key])
        check('new diagnostic experiment', req['experiment_id'] == 'EX040_20261019')
        equal_baseline(original, account)
        accounting = audit_daily(account)
        if mode == 'NOOP':
            noop_equivalence(original, account)
            check('NOOP intervention count zero', accounting['intervention_count'] == 0)
        else:
            check('NOOP independent audit precedes treatment', 'NOOP' in completed)
            prefix_and_intervention(original, account, mode)
            check('one intervention per treatment', accounting['intervention_count'] == 1)
        run = account['runs'][0]
        yearly_strategy = yearly(run['ledgers']['account_daily']['data'])
        yearly_bh = yearly(run['buyhold']['account_daily']['data'])
        annuals = []
        for y, row in yearly_strategy.items():
            b = yearly_bh[y]
            required = 1.5 * b['return'] if b['return'] > 0 else 0.
            annuals.append({'year': y, **row, 'buyhold_return': b['return'], 'buyhold_drawdown': b['max_drawdown'],
                            'required_return': required,
                            'return_pass': row['return'] >= required if b['return'] > 0 else row['return'] > 0,
                            'drawdown_pass': row['max_drawdown'] < b['max_drawdown'],
                            '2026_role': 'TECHNICAL_FULL_WINDOW_ONLY' if y == 2026 else 'ORIGINAL_ANNUAL_GOAL_AUDIT'})
        closed = sum(t['status'] == 'CLOSED' for t in run['ledgers']['trades']['data'])
        frequency = 60 * closed / len(run['ledgers']['account_daily']['data'])
        result['audited_accounts'].append({'mode': mode, 'candidate': record['candidate'], 'evidence': record['evidence'],
                'immutable_identity': identity,
                'result_hash': account['result_hash'], 'accounting': accounting, 'original_annual_goals': annuals,
                'terminal_2025_asof_state': terminal_state(account),
                'closed_trades': closed, 'frequency_per_60': frequency, 'frequency_pass': frequency >= 3})
        completed[mode] = account
    old_daily = {day(x['date']): x for x in original['runs'][0]['ledgers']['account_daily']['data']}
    year_opening = old_daily['2024-12-31']['equity']
    X_T = old_daily[TERMINAL]['equity']
    result['original_terminal_2025_asof_state'] = terminal_state(original)
    csv_columns = ['date', 'ORIGINAL_R', *completed]
    daily_maps = {'ORIGINAL_R': old_daily, **{mode: {day(x['date']): x for x in acc['runs'][0]['ledgers']['account_daily']['data']} for mode, acc in completed.items()}}
    with csv_path.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=csv_columns)
        writer.writeheader()
        for date in old_daily:
            if date.startswith('2025-'):
                writer.writerow({'date': date, **{mode: mapping[date]['equity'] for mode, mapping in daily_maps.items()}})
    result['daily_2025_csv'] = {'path': str(csv_path.resolve().relative_to(ROOT)), 'sha256': sha256(csv_path.read_bytes()).hexdigest(),
                              'unit': 'original anchored HFQ_RESEARCH currency wealth', 'original_2025_opening_equity': year_opening,
                              'first_daily_close_is_not_opening_denominator': True}
    for mode in ['SKIP_BUY_ONCE', 'FORCE_SELL_ONCE']:
        if mode not in completed:
            continue
        account = completed[mode]
        daily = {day(x['date']): x for x in account['runs'][0]['ledgers']['account_daily']['data']}
        D = NODES[mode]
        check('same original node wealth', daily[D]['equity'] == old_daily[D]['equity'])
        check('common same-price terminal mark', daily[TERMINAL]['close'] == old_daily[TERMINAL]['close'])
        delta = daily[TERMINAL]['equity'] - X_T
        item = {'D': D, 'T': TERMINAL, 'original_D_wealth': old_daily[D]['equity'], 'original_year_opening_wealth': year_opening,
                'original_terminal_wealth': X_T, 'treatment_terminal_wealth': daily[TERMINAL]['equity'], 'difference_currency': delta,
                'D_normalized_effect': delta / old_daily[D]['equity'], 'original_2025_return_difference': delta / year_opening,
                'terminal_cash': daily[TERMINAL]['cash'], 'terminal_quantity': daily[TERMINAL]['quantity'],
                'terminal_price': daily[TERMINAL]['close']}
        if mode == 'SKIP_BUY_ONCE':
            C = old_daily[D]['cash']
            check('flat original decision cash equals wealth', old_daily[D]['quantity'] == 0 and C == old_daily[D]['equity'])
            item['frozen_original_cash_reference'] = C
            item['treatment_post_D_participation_vs_cash'] = daily[TERMINAL]['equity'] - C
            item['original_post_D_participation_vs_cash'] = X_T - C
            number('flat total-path attribution identity', delta, item['treatment_post_D_participation_vs_cash'] - item['original_post_D_participation_vs_cash'], True)
        else:
            original_base = disposition_base(original, D, TERMINAL)
            treatment_base = disposition_base(account, D, TERMINAL)
            base_difference = treatment_base['base_terminal_currency'] - original_base['base_terminal_currency']
            participation_difference = treatment_base['post_disposition_participation_currency'] - original_base['post_disposition_participation_currency']
            number('held total-path attribution identity', delta, base_difference + participation_difference, True)
            item['original_disposition'] = original_base
            item['treatment_disposition'] = treatment_base
            item['original_position_disposition_difference_currency'] = base_difference
            item['post_disposition_participation_difference_currency'] = participation_difference
        result['action_wealth_2025_terminal_only'][mode] = item
    result.update(status='PASS_ALL_THREE_FIXED_MODES' if set(completed) == set(MODES) else 'PARTIAL_COMPLETED_MODE_AUDIT',
                  completed_modes=list(completed), check_counts=dict(COUNTS), maximum_derived_arithmetic_errors=ERRORS,
                  index_path=str(index_path.relative_to(ROOT)) if index_path.is_absolute() else str(index_path),
                  index_sha256=sha256(index_path.read_bytes()).hexdigest(),
                  audit_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': result['status'], 'completed_modes': list(completed), 'resources': resource,
                      'checks': sum(COUNTS.values()), 'output_sha256': sha256(output.read_bytes()).hexdigest()}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New audit file; never overwrite')
    parser.add_argument('--csv', type=Path, required=True, help='New 2025 daily equity wide CSV; never overwrite')
    args = parser.parse_args()
    execute(args.index, args.output, args.csv)
