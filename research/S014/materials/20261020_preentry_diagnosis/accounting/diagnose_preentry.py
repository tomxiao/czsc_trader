"""Account-only EX044004 pre-entry diagnosis; no replay, fitting or data fetch.

Only actually closed prior cycles as of D enter historical-memory features.
The D-to-fill price bridge is NOT actual pre-entry account profit/loss.
"""
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import io
import json
import math
from pathlib import Path
import socket

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
EX = ROOT / 'research/S014/experiments/EX044_20261019'
CAP = '2025-12-31'
CHECKS = Counter()
MAX_ERROR = 0.0


def deny(*args, **kwargs):
    raise RuntimeError('Account-only diagnosis: network/dispatch/fetch prohibited')


socket.socket.connect = deny
socket.create_connection = deny


def check(name, condition):
    assert condition, name
    CHECKS[name] += 1


def near(name, actual, expected):
    global MAX_ERROR
    error = abs(actual - expected)
    MAX_ERROR = max(MAX_ERROR, error)
    check(name, math.isfinite(actual) and error <= 1e-7)


def day(value):
    return str(value)[:10]


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def public(ref):
    evidence = EvidenceRef.from_dict(ref)
    check('S014 only', evidence.experiment.strategy_id == 'S014')
    content = evidence.resolve(ROOT).read_bytes()
    check('EvidenceRef exact bytes', sha256(content).hexdigest() == evidence.sha256)
    return json.loads(content)


def output(name, value, is_csv=False):
    path = OUT / name
    if is_csv:
        stream = io.StringIO(newline='')
        columns = list(dict.fromkeys(k for row in value for k in row))
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(value)
        content = stream.getvalue().encode('utf-8')
    else:
        content = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if path.exists():
        check('existing output immutable/recomputed bytes equal', path.read_bytes() == content)
    else:
        path.write_bytes(content)
    return {**digest(path), **({'rows': len(value)} if is_csv else {})}


def aggregate(rows, keynames):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in keynames)].append(row)
    out = []
    for keys, members in sorted(groups.items()):
        fills = [m for m in members if m['filled']]
        closed = [m for m in fills if m['cycle_status'] == 'CLOSED_BY_2025_CAP']
        def avg(field):
            values = [m[field] for m in fills if m[field] is not None]
            return sum(values) / len(values) if values else None
        out.append({
            **dict(zip(keynames, keys)), 'actual_buy_intents': len(members),
            'filled_entries': len(fills), 'failed_buy_intents': len(members) - len(fills),
            'entryday_negative_net_count': sum(m['actual_entryday_net_pnl'] < 0 for m in fills),
            'entryday_gross_pnl': sum(m['actual_entryday_gross_pnl'] for m in fills),
            'actual_buy_fees': sum(m['actual_buy_fee'] for m in fills),
            'entryday_net_pnl': sum(m['actual_entryday_net_pnl'] for m in fills),
            'entryday_net_annual_contribution_pp': sum(m['entryday_net_annual_contribution_pp'] for m in fills),
            'Dclose_to_fill_price_bridge_money_NOT_account_pnl': sum(m['Dclose_to_fill_price_bridge_money_NOT_account_pnl'] for m in fills),
            'mean_Dclose_to_fill_return': avg('Dclose_to_fill_return'),
            'mean_fill_to_Eclose_return': avg('fill_to_Eclose_return'),
            'mean_D_support_distance_atr': avg('D_support_distance_atr'),
            'closed_next_cycles': len(closed),
            'closed_next_cycle_negative_count': sum(m['cycle_net_pnl_to_cap'] < 0 for m in closed),
            'closed_next_cycle_net_pnl': sum(m['cycle_net_pnl_to_cap'] for m in closed),
            'mean_closed_next_cycle_net_return': sum(m['cycle_net_return_to_cap'] for m in closed) / len(closed) if closed else None,
            'open_next_cycles_no_exit_fee': len(fills) - len(closed),
            'counterfactual_skip_wealth_computed': False,
        })
    return out


def main():
    receipt_path = EX / 'others/accounts/run-004.json'
    receipt = read(receipt_path)
    audit_path = ROOT / 'research/S014/materials/20261019_2024_diagnosis/accounting/account_004_independent_review.json'
    audit = read(audit_path)
    account = public(receipt['evidence'])
    check('audited actual successful cost arm', receipt['status'] == 'SUCCEEDED' and audit['status'] == 'PASS')
    check('audited exact account/result', audit['account_ref'] == receipt['evidence'] and audit['result_hash'] == account['result_hash'] == receipt['result_hash'])
    check('cost arm exact parameters', receipt['parameters'] == {'entry_guard': 'BASE', 'exit_domain': 'POSITIVE_P', 'cost_stop': 'NET_LOSS_1ATR'})
    source_ref = receipt['published_source_ref']
    source = EvidenceRef.from_dict(source_ref)
    check('original source bytes', sha256(source.resolve(ROOT).read_bytes()).hexdigest() == 'e176e01873d67fff2c869915373f36b35f1f507524a5583c49b138b3c146b527')
    run = account['runs'][0]
    ledgers = run['ledgers']
    daily = {day(r['date']): r for r in ledgers['account_daily']['data'] if day(r['date']) <= CAP}
    decisions = {day(r['signal_date']): r for r in ledgers['decisions']['data']}
    fills = [r for r in ledgers['fills']['data'] if day(r['fill_time']) <= CAP]
    by_order = {r['order_id']: r for r in fills}
    by_cycle = defaultdict(list)
    for fill in fills:
        by_cycle[fill['cycle_id']].append(fill)
    cycles = {}
    for cycle_id, events in by_cycle.items():
        buy = next(f for f in events if f['side'] == 'BUY')
        sells = [f for f in events if f['side'] == 'SELL']
        check('one actual buy and at most one sell each cycle', len(events) == 1 + len(sells) and len(sells) <= 1)
        sell = sells[0] if sells else None
        end_price = sell['price'] if sell else daily[CAP]['close']
        exit_fee = sell['fees'] if sell else 0.0
        net = buy['quantity'] * (end_price - buy['price']) - buy['fees'] - exit_fee
        cost = buy['quantity'] * buy['price'] + buy['fees']
        cycles[cycle_id] = {'cycle_id': cycle_id, 'entry_D': day(buy['signal_date']), 'entry_E': day(buy['fill_time']),
                            'exit_E': day(sell['fill_time']) if sell else None,
                            'cycle_status': 'CLOSED_BY_2025_CAP' if sell else 'OPEN_MARK_NO_EXIT_FEE',
                            'cycle_net_pnl_to_cap': net, 'cycle_net_return_to_cap': net / cost}
    closed = sorted((v for v in cycles.values() if v['exit_E']), key=lambda c: c['exit_E'])
    year_open = {}
    previous = account['request_identity'].get('initial_cash', 100000.0)
    for E, row in sorted(daily.items()):
        year_open.setdefault(int(E[:4]), previous)
        previous = row['equity']
    factor = account['request_identity']['pricing']['anchor_factor']
    check('same anchored HFQ research units', factor == 5.892 and account['request_identity']['pricing']['quantity_unit'] == 'RESEARCH_UNIT')
    attempts = []
    for order in ledgers['orders']['data']:
        D, E = day(order['signal_date']), day(order['execution_date'])
        if order['side'] != 'BUY' or E > CAP:
            continue
        dec, Drow, Erow = decisions[D], daily[D], daily[E]
        check('true D flat buy intent and E mapping', bool(dec['entry_signal']) and not dec['held_at_close'] and day(dec['valid_session']) == E and Erow['quantity_before'] == 0)
        known = [c for c in closed if c['exit_E'] <= D]
        prior = known[-1] if known else None
        group = 'NO_PRIOR_CLOSED' if prior is None else 'PREVIOUS_NET_LOSS' if prior['cycle_net_pnl_to_cap'] < 0 else 'PREVIOUS_NET_PROFIT' if prior['cycle_net_pnl_to_cap'] > 0 else 'PREVIOUS_EXACT_ZERO'
        loss_streak = 0
        for c in reversed(known):
            if c['cycle_net_pnl_to_cap'] >= 0:
                break
            loss_streak += 1
        fill = by_order.get(order['order_id'])
        check('buy FILLED status agrees actual fill', (order['status'] == 'FILLED') == (fill is not None))
        atr = dec['atr20_prior'] / factor if dec['atr20_prior'] is not None else None
        support = dec['support_floor'] / factor if dec['support_floor'] is not None else None
        row = {'year': int(E[:4]), 'D': D, 'E': E, 'order_id': order['order_id'],
               'cycle_id': order['cycle_id'], 'status': order['status'], 'reason': order['reason'], 'filled': fill is not None,
               'prior_closed_group': group, 'known_closed_cycles': len(known), 'known_consecutive_closed_losses': loss_streak,
               'previous_closed_cycle_id': prior['cycle_id'] if prior else None,
               'previous_closed_exit_E': prior['exit_E'] if prior else None,
               'previous_closed_net_pnl': prior['cycle_net_pnl_to_cap'] if prior else None,
               'previous_closed_net_return': prior['cycle_net_return_to_cap'] if prior else None,
               'D_equity': Drow['equity'], 'own_year_opening_equity': year_open[int(E[:4])],
               'D_close': Drow['close'], 'D_support_floor_ledger_unit': support, 'D_atr20_prior_ledger_unit': atr,
               'D_support_distance_atr': (Drow['close'] - support) / atr if atr and support else None,
               'D_z5': dec['z5'], 'D_support_ok': dec['support_ok'], 'D_reservation_index': dec['reservation_index'],
               'D_warmup_sessions': dec['warmup_sessions'], 'planned_limit_ledger_unit': order['limit_price'],
               'planned_limit_vs_Dclose_return': order['limit_price'] / Drow['close'] - 1,
               'planned_limit_minus_support_atr': (order['limit_price'] - support) / atr if atr and support else None,
               'actual_E_fill_price': fill['price'] if fill else None, 'actual_E_trigger_POSTHOC': fill['trigger'] if fill else 'UNFILLED',
               'E_close_POSTHOC': Erow['close'], 'actual_quantity': fill['quantity'] if fill else 0,
               'Dclose_to_fill_return': fill['price'] / Drow['close'] - 1 if fill else None,
               'fill_to_Eclose_return': Erow['close'] / fill['price'] - 1 if fill else None,
               'Dclose_to_fill_price_bridge_money_NOT_account_pnl': fill['quantity'] * (fill['price'] - Drow['close']) if fill else None,
               'actual_entryday_gross_pnl': fill['quantity'] * (Erow['close'] - fill['price']) if fill else None,
               'actual_buy_fee': fill['fees'] if fill else None,
               'actual_entryday_net_pnl': fill['quantity'] * (Erow['close'] - fill['price']) - fill['fees'] if fill else None,
               'entryday_net_annual_contribution_pp': 100 * (Erow['equity'] - Drow['equity']) / year_open[int(E[:4])] if fill else None,
               'cycle_status': cycles[fill['cycle_id']]['cycle_status'] if fill else 'NO_ACTUAL_CYCLE_CREATED',
               'cycle_net_pnl_to_cap': cycles[fill['cycle_id']]['cycle_net_pnl_to_cap'] if fill else None,
               'cycle_net_return_to_cap': cycles[fill['cycle_id']]['cycle_net_return_to_cap'] if fill else None}
        if fill:
            near('D-fill-E price bridge', row['Dclose_to_fill_price_bridge_money_NOT_account_pnl'] + row['actual_entryday_gross_pnl'], fill['quantity'] * (Erow['close'] - Drow['close']))
            near('actual entryday own wealth difference', row['actual_entryday_net_pnl'], Erow['equity'] - Drow['equity'])
            check('known prior cycle strictly completed by D', prior is None or prior['exit_E'] <= D < E)
        attempts.append(row)
    check('all actual 2020-25 BUY fills represented exactly', sum(r['filled'] for r in attempts) == sum(f['side'] == 'BUY' for f in fills))
    check('no duplicate attempts', len({r['order_id'] for r in attempts}) == len(attempts))
    outputs = [output('preentry_actual_attempts.csv', attempts, True),
               output('preentry_actual_cycles.csv', list(cycles.values()), True),
               output('preentry_yearly_prior_group.csv', aggregate(attempts, ['year', 'prior_closed_group']), True),
               output('preentry_prior_group.csv', aggregate(attempts, ['prior_closed_group']), True),
               output('preentry_yearly_loss_streak.csv', aggregate(attempts, ['year', 'known_consecutive_closed_losses']), True),
               output('preentry_yearly_trigger.csv', aggregate(attempts, ['year', 'actual_E_trigger_POSTHOC']), True),
               output('preentry_yearly.csv', aggregate(attempts, ['year']), True)]
    summary = {'status': 'PASS', 'source_account_ref': receipt['evidence'], 'result_hash': account['result_hash'],
               'inputs': [digest(receipt_path), digest(audit_path), digest(source.resolve(ROOT))], 'implementation': digest(Path(__file__).resolve()),
               'economic_window': ['2020-01-01', CAP], 'same_seen_development_history': True,
               'population': {'actual_buy_intents': len(attempts), 'actual_filled_entries': sum(r['filled'] for r in attempts),
                              'actual_failed_buys': sum(not r['filled'] for r in attempts), 'known_prior_group_counts': dict(Counter(r['prior_closed_group'] for r in attempts)),
                              'closed_actual_cycles': len(closed), 'open_actual_cycles_no_exit_fee': len(cycles) - len(closed)},
               'definitions': {'prior_memory': 'Actual closed cycle net of both actual fees, actual SELL execution_date <= D. Zero exact; never rounded into loss/profit.',
                               'D_known': ['previous completed real cycle outcomes', 'consecutive completed real losses', 'D close', 'prior20 ATR', 'prior5 support floor', 'D Z5', 'reservation', 'planned limit'],
                               'not_D_known': ['E fill or failure', 'E fill trigger', 'E actual fill price', 'E close', 'current prospective cycle later return'],
                               'price_bridge': 'Q*(Eclose-Dclose) = Q*(fill-Dclose)+Q*(Eclose-fill). First term is not account profit/loss before purchase.',
                               'actual_entryday_net': 'Q*(Eclose-fill)-actual buy fee; zero prior inventory.',
                               'open_cycle': 'Mark to original 2025 last Close, subtract actual entry fee only. Never a completed prior outcome.',
                               'streak_grouping': 'Full natural integer counts; no threshold/parameter sweep, no skip-account wealth, no new strategy or future label replay.'},
               'resources': {'new_accounts': 0, 'new_replays': 0, 'new_fits': 0, 'new_market_calls': 0, 'prepared_fetches': 0, 'new_counterfactual_wealth_labels': 0},
               'checks': dict(CHECKS), 'check_count': sum(CHECKS.values()), 'max_money_identity_error': MAX_ERROR, 'outputs': outputs}
    ref = output('preentry_accounting_summary.json', summary)
    print(json.dumps({'summary': ref, 'population': summary['population'], 'check_count': summary['check_count']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
