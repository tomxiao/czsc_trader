"""Authenticated original C9461/cost/BH 2026 accounting, no new replay or fit."""
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import socket

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
END = '2026-10-15'
CHECKS = Counter()
MAX_ERROR = 0.


def deny(*args, **kwargs):
    raise RuntimeError('Original-account-only diagnosis: no market/network/evaluation call')


socket.socket.connect = deny
socket.create_connection = deny


def day(value):
    return str(value)[:10]


def read(path):
    return json.loads(path.read_bytes())


def check(name, value):
    assert value, name
    CHECKS[name] += 1


def equal(name, actual, expected):
    global MAX_ERROR
    error = abs(actual - expected)
    MAX_ERROR = max(MAX_ERROR, error)
    check(name, error <= 1e-7)


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def published(value):
    evidence = EvidenceRef.from_dict(value)
    content = evidence.resolve(ROOT).read_bytes()
    check('S014 formal exact EvidenceRef', evidence.experiment.strategy_id == 'S014' and sha256(content).hexdigest() == evidence.sha256)
    return json.loads(content)


def save(name, value, is_csv=False):
    path = OUT / name
    if is_csv:
        stream = io.StringIO(newline='')
        fields = list(dict.fromkeys(k for r in value for k in r))
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(value)
        content = stream.getvalue().encode('utf-8')
    else:
        content = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if path.exists():
        check('existing output exact recomputation only', path.read_bytes() == content)
    else:
        with path.open('xb') as stream:
            stream.write(content)
    return {**ref(path), **({'rows': len(value)} if is_csv else {})}


def load_accounts():
    paths = {'C9461': ROOT / 'research/S014/materials/20261020_preentry_diagnosis/accounting/pause_account_001_independent_review.json',
             'COST_BASE': ROOT / 'research/S014/materials/20261019_2024_diagnosis/accounting/account_004_independent_review.json'}
    accounts, sources = {}, []
    for name, path in paths.items():
        report = read(path)
        account = published(report['account_ref'])
        check('existing authenticated actual PASS result', report['status'] == 'PASS' and report['result_hash'] == account['result_hash'])
        accounts[name] = account
        sources.append({'policy': name, 'account_ref': report['account_ref'], 'result_hash': account['result_hash'], 'original_audit': ref(path), 'source_sha256': report['source_sha256']})
    check('fixed C9461 source and parameters', sources[0]['source_sha256'] == '5e775c5b27bfd7b1ac5bec9c2839ce24ae62f32f1829c21a13091868a174b846' and read(paths['C9461'])['parameters'] == {'pause_profile': 'AFTER_NET_LOSS_SKIP1'})
    check('same original benchmark ledger', accounts['C9461']['runs'][0]['buyhold']['account_daily'] == accounts['COST_BASE']['runs'][0]['buyhold']['account_daily'])
    return accounts, sources


SUMS = ['entryday_gross', 'continued_hold_gross', 'exit_to_actual_fill_gross', 'buy_fee', 'sell_fee', 'net_pnl',
        'strategy_contribution_pp', 'buyhold_contribution_pp', 'relative_buyhold_contribution_pp']


def grouped(rows, keys):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in keys)].append(row)
    return [{**dict(zip(keys, values)), 'sessions': len(members),
             **{k: sum(r[k] for r in members) for k in SUMS}} for values, members in sorted(groups.items())]


def process(account, name):
    run = account['runs'][0]
    ledgers = run['ledgers']
    all_daily = {day(r['date']): r for r in ledgers['account_daily']['data']}
    daily = [r for D, r in all_daily.items() if '2026-01-01' <= D <= END]
    decisions = {day(r['signal_date']): r for r in ledgers['decisions']['data']}
    fills = {day(r['fill_time']): r for r in ledgers['fills']['data']}
    bh = {day(r['date']): r for r in run['buyhold']['account_daily']['data']}
    opening = all_daily['2025-12-31']['equity']
    bh_opening = bh['2025-12-31']['equity']
    prev = all_daily['2025-12-31']
    prev_bh = bh['2025-12-31']
    earlier_buys = [r for r in ledgers['fills']['data'] if r['side'] == 'BUY' and day(r['fill_time']) <= '2025-12-31']
    active = earlier_buys[-1]['cycle_id'] if prev['quantity'] else None
    initial_cycle = active
    atoms = []
    check('original187 partial2026 sessions', len(daily) == 187)
    for row in daily:
        E, D = day(row['date']), day(row['signal_date'])
        dec = decisions[D]
        fill = fills.get(E)
        check('original next session clock and actual D holding', day(dec['valid_session']) == E and bool(dec['held_at_close']) == bool(row['quantity_before']))
        equal('original shared close representation', row['close'], bh[E]['close'])
        entry = holding = sale = buyfee = sellfee = 0.
        if fill and fill['side'] == 'BUY':
            active = fill['cycle_id']
            entry = fill['quantity'] * (row['close'] - fill['price'])
            buyfee = fill['fees']
            phase = 'ACTUAL_BUY'
        elif fill:
            check('actual same held cycle sold', fill['side'] == 'SELL' and active == fill['cycle_id'])
            sale = fill['quantity'] * (fill['price'] - prev['close'])
            sellfee = fill['fees']
            phase = 'ACTUAL_SELL'
        elif row['quantity_before']:
            holding = row['quantity_before'] * (row['close'] - prev['close'])
            phase = 'WHOLE_SESSION_HELD'
        else:
            phase = 'WHOLE_SESSION_FLAT'
        net = entry + holding + sale - buyfee - sellfee
        equal('daily economic wealth bridge', net, row['equity'] - prev['equity'])
        bh_net = bh[E]['equity'] - prev_bh['equity']
        direction = 'UP' if row['close'] > prev['close'] else 'DOWN' if row['close'] < prev['close'] else 'UNCHANGED'
        atom = {'policy': name, 'D': D, 'E': E, 'month': E[:7], 'quarter': E[:4] + 'Q' + str((int(E[5:7]) - 1) // 3 + 1),
                'actual_phase': phase, 'close_direction_POSTHOC': direction, 'cycle_id': active,
                'own2026_opening': opening, 'own_buyhold2026_opening': bh_opening,
                'equity_before': prev['equity'], 'equity_after': row['equity'], 'cash_before': row['cash_before'], 'cash_after': row['cash'],
                'quantity_before': row['quantity_before'], 'quantity_after': row['quantity'], 'ledger_close_before': prev['close'], 'ledger_close_after': row['close'],
                'D_monetary_exposure': row['quantity_before'] * prev['close'], 'D_exposure_fraction_of_own_equity': row['quantity_before'] * prev['close'] / prev['equity'],
                'entryday_gross': entry, 'continued_hold_gross': holding, 'exit_to_actual_fill_gross': sale, 'buy_fee': buyfee, 'sell_fee': sellfee,
                'net_pnl': net, 'strategy_contribution_pp': 100 * net / opening, 'buyhold_contribution_pp': 100 * bh_net / bh_opening,
                'relative_buyhold_contribution_pp': 100 * (net / opening - bh_net / bh_opening),
                'D_entry_signal': dec['entry_signal'], 'D_exit_pending': dec['exit_pending'], 'D_original_candidate': dec['original_entry_candidate'],
                'D_reservation_index': dec['reservation_index'], 'D_selected_shock_exit': dec['selected_shock_exit'], 'D_selected_cost_exit': dec['selected_cost_exit'],
                'D_ordinary_support_exit': dec['ordinary_support_exit'], 'D_deadline_exit': dec['deadline_exit'], 'D_holding_age': dec['holding_age'],
                'D_net_profit': dec['net_profit'], 'D_z5': dec['z5'], 'actual_fill_price': fill['price'] if fill else None,
                'actual_fill_trigger_POSTHOC': fill['trigger'] if fill else None}
        atoms.append(atom)
        if fill and fill['side'] == 'SELL':
            active = None
        prev, prev_bh = row, bh[E]
    total = sum(r['net_pnl'] for r in atoms)
    equal('partial2026 actual net bridge', total, daily[-1]['equity'] - opening)
    prices = [opening] + [r['equity'] for r in daily]
    bhprices = [bh_opening] + [bh[day(r['date'])]['equity'] for r in daily]
    def mdd(values):
        peak, worst = values[0], 0.
        for value in values[1:]:
            peak = max(peak, value)
            worst = max(worst, 1 - value / peak)
        return worst
    bh_return = bhprices[-1] / bh_opening - 1
    strategy_return = prices[-1] / opening - 1
    required = 1.5 * bh_return if bh_return > 0 else 0.
    summary = {'policy': name, 'opening_equity': opening, 'closing_equity': prices[-1], 'return': strategy_return, 'max_drawdown': mdd(prices),
               'buyhold_opening_equity': bh_opening, 'buyhold_return': bh_return, 'buyhold_drawdown': mdd(bhprices), 'required_return': required,
               'return_pass': strategy_return >= required if bh_return > 0 else strategy_return > 0, 'drawdown_pass': mdd(prices) < mdd(bhprices),
               'gap_to_required_pp': 100 * (required - strategy_return), 'underperformance_vs_BH_pp': 100 * (bh_return - strategy_return),
               'additional_original_1point5_BH_requirement_pp': 100 * (required - bh_return),
               'entryday_gross': sum(r['entryday_gross'] for r in atoms), 'continued_hold_gross': sum(r['continued_hold_gross'] for r in atoms),
               'exit_to_actual_fill_gross': sum(r['exit_to_actual_fill_gross'] for r in atoms), 'actual_fees': sum(r['buy_fee'] + r['sell_fee'] for r in atoms),
               'net_pnl': total, 'opening_carry_cycle_id': initial_cycle, 'opening_quantity': all_daily['2025-12-31']['quantity'],
               'opening_cash': all_daily['2025-12-31']['cash'], 'ending_cash': daily[-1]['cash'], 'ending_quantity': daily[-1]['quantity'],
               'last_issued_D_state': decisions[day(daily[-1]['signal_date'])],
               'last_issued_D': day(daily[-1]['signal_date']), 'last_execution_E': END,
               'post_cutoff_D_rule_not_recomputed': True, 'sessions': len(daily), 'partial_year_not_annualized': True}
    cycle_rows = []
    trades = {r['cycle_id']: r for r in ledgers['trades']['data']}
    for cid in dict.fromkeys(r['cycle_id'] for r in atoms if r['cycle_id'] is not None):
        members = [r for r in atoms if r['cycle_id'] == cid]
        trade = trades[cid]
        cycle_rows.append({'policy': name, 'cycle_id': cid, 'original_entry_E': day(trade['entry_date']), 'actual_exit_E': day(trade['exit_date']) if trade['exit_date'] else None,
                           'calendar2026_carry_in': day(trade['entry_date']) < '2026-01-01', 'source_trade_status_at_original_cutoff': trade['status'],
                           'source_trade_net_return_NOT_year_contribution': trade['net_return'],
                           **{key: sum(r[key] for r in members) for key in SUMS},
                           'actual_entry_price': trade['entry_price'], 'actual_exit_price': trade['exit_price'], 'quantity': trade['quantity'],
                           'exit_D': members[-1]['D'], 'exit_D_shock': members[-1]['D_selected_shock_exit'], 'exit_D_cost': members[-1]['D_selected_cost_exit'],
                           'exit_D_support': members[-1]['D_ordinary_support_exit'], 'exit_D_deadline': members[-1]['D_deadline_exit']})
    return atoms, summary, cycle_rows


def trace_slots(account, base, atoms):
    ledgers = account['runs'][0]['ledgers']
    rows = ledgers['decisions']['data']
    economic = [r for r in rows if '2026-01-01' <= day(r['signal_date']) <= END]
    buys = [r for r in ledgers['fills']['data'] if r['side'] == 'BUY']
    orders = {day(r['signal_date']): r for r in ledgers['orders']['data']}
    base_orders = {day(r['signal_date']): r for r in base['runs'][0]['ledgers']['orders']['data']}
    base_decisions = {day(r['signal_date']): r for r in base['runs'][0]['ledgers']['decisions']['data']}
    slots, trace = [], []
    for row in economic:
        if not row['pause_slot_consumed']:
            continue
        D = day(row['signal_date'])
        until = row['planned_slot_until']
        later = [r for r in buys if day(r['fill_time']) > D]
        next_buy = later[0] if later else None
        buy_E = day(next_buy['fill_time']) if next_buy else None
        cap = buy_E or END
        member = [r for r in economic if D <= day(r['signal_date']) < cap]
        expired = next((r for r in member if r['warmup_sessions'] >= until), None)
        buy_intent = next((r for r in member if r['entry_signal']), None)
        base_order = base_orders.get(D)
        slot = {'slot_D': D, 'planned_first_E': day(row['valid_session']), 'slot_market_index': row['warmup_sessions'], 'reservation_before': row['reservation_before_pause'],
                'planned_until_index': until, 'last_completed_net_unit_known_D': row['last_completed_net_unit'], 'actual_candidate_D': row['original_entry_candidate'],
                'first_observed_D_at_or_after_expiry': day(expired['signal_date']) if expired else None,
                'first_actual_BUY_intent_D_after_pause': day(buy_intent['signal_date']) if buy_intent else None,
                'next_actual_BUY_E': buy_E, 'next_actual_buy_price': next_buy['price'] if next_buy else None,
                'expiry_beyond_original_cutoff': until > economic[-1]['warmup_sessions'], 'next_entry_right_censored_by_cutoff': next_buy is None,
                'baseline_sameD_real_posture': 'PLAN_BUY' if base_decisions[D]['entry_signal'] else 'HELD' if base_decisions[D]['held_at_close'] else 'FLAT',
                'baseline_sameD_actual_order_side': base_order['side'] if base_order else None,
                'baseline_sameD_order_status_POSTHOC': base_order['status'] if base_order else None,
                'baseline_sameD_order_reason_POSTHOC': base_order['reason'] if base_order else None,
                'no_counterfactual_skipped_trade_return': True}
        window = [r for r in atoms if D < r['E'] and (r['E'] < buy_E if buy_E else r['E'] <= END)]
        check('observed paused-to-entry window is actually full flat', all(r['actual_phase'] == 'WHOLE_SESSION_FLAT' for r in window))
        slot['observed_flat_sessions_until_next_entry_or_cutoff'] = len(window)
        slot['actual_BH_up_contribution_pp_in_observed_flat_window'] = sum(r['buyhold_contribution_pp'] for r in window if r['close_direction_POSTHOC'] == 'UP')
        slot['actual_BH_down_contribution_pp_in_observed_flat_window'] = sum(r['buyhold_contribution_pp'] for r in window if r['close_direction_POSTHOC'] == 'DOWN')
        slots.append(slot)
        for state in member:
            T = day(state['signal_date'])
            own_order = orders.get(T)
            trace.append({'slot_D': D, 'D': T, 'valid_E': day(state['valid_session']), 'market_index': state['warmup_sessions'],
                          'original_candidate': state['original_entry_candidate'], 'ready': state['ready'], 'support_ok': state['support_ok'],
                          'failed_buy_reset': state['failed_buy_reset'], 'entry_signal': state['entry_signal'], 'buy_filled_today': state['buy_filled_today'],
                          'held_at_close': state['held_at_close'], 'reservation_index': state['reservation_index'], 'planned_slot_active': state['planned_slot_active'],
                          'own_real_order_status_POSTHOC': own_order['status'] if own_order else None})
    return slots, trace


def main():
    accounts, sources = load_accounts()
    atoms, summaries, cycles = [], [], []
    by_policy = {}
    for name, account in accounts.items():
        rows, summary, cycle_rows = process(account, name)
        atoms.extend(rows)
        summaries.append(summary)
        cycles.extend(cycle_rows)
        by_policy[name] = rows
    slots, trace = trace_slots(accounts['C9461'], accounts['COST_BASE'], by_policy['C9461'])
    actual_orders = [{ 'policy': name, **{k: v for k, v in r.items()}} for name, account in accounts.items()
                     for r in account['runs'][0]['ledgers']['orders']['data'] if '2026-01-01' <= day(r['execution_date']) <= END]
    outputs = [save('actual_2026_daily_atoms.csv', atoms, True), save('actual_2026_phase_direction.csv', grouped(atoms, ['policy', 'actual_phase', 'close_direction_POSTHOC']), True),
               save('actual_2026_phase.csv', grouped(atoms, ['policy', 'actual_phase']), True), save('actual_2026_monthly.csv', grouped(atoms, ['policy', 'month']), True),
               save('actual_2026_cycle_contributions.csv', cycles, True), save('actual_2026_pause_slots.csv', slots, True),
               save('actual_2026_pause_candidate_trace.csv', trace, True), save('actual_2026_orders.csv', actual_orders, True)]
    result = {'status': 'PASS_ORIGINAL_ACCOUNT_ONLY', 'sources': sources, 'implementation': ref(Path(__file__).resolve()),
              'economic_scope': ['2026-01-01', END], 'new_permission_2026_economic_diagnosis': True, 'original_mandate_unchanged': True,
              'annual_actuals': summaries, 'outputs': outputs, 'checks': dict(CHECKS), 'check_count': sum(CHECKS.values()), 'max_money_bridge_error': MAX_ERROR,
              'definitions': {'WHOLE_SESSION_FLAT': 'No fill on E and Q_before=Q_after=0. BH up contribution is observed forgone upward exposure; BH negative contribution is observed risk avoided. Neither was D-known.',
                              'WHOLE_SESSION_HELD': 'No fill on E and actual inventory retained. Relative contributions reflect own evolving capital/quantity, not proof an exit action was wrong.',
                              'BUY_and_SELL': 'Only actual fill-to-close / previous-close-to-fill price exposure earns actual account PnL; fees separate. Same-day BH includes full previous-close-to-close exposure.',
                              'gap_identity': 'required-strategy = (BH-strategy)+(required-BH), with required=1.5BH if BH positive. Per-phase relative differences sum to BH-strategy, not entire extra target premium.',
                              'cycles': 'Calendar2026 atoms include cross-year carry from original2025 closing valuation; source full trade return is not assigned wholesale to2026.',
                              'slots': 'Only actual declared pause windows and observed next candidates/orders/fills; right-censored at original cutoff. No deleted-trade wealth or imagined fill.',
                              'D_known': 'Only original D states, actual prior completion and existing original source features; E direction/fill/Close are attribution outcomes.'},
              'resources': {'new_accounts': 0, 'strategy_replays': 0, 'fits': 0, 'new_market_calls': 0, 'prepared_fetches': 0, 'new_counterfactual_labels': 0},
              'limits': ['Seen2026 is now authorized development diagnosis; no independent holdout assertion.', 'Original C9461 source/parameters and2020-25 closed evidence retained unchanged.']}
    result_ref = save('actual_2026_accounting_review.json', result)
    print(json.dumps({'review': result_ref, 'annual': [{k: r[k] for k in ['policy', 'return', 'max_drawdown', 'gap_to_required_pp', 'entryday_gross', 'continued_hold_gross', 'exit_to_actual_fill_gross', 'actual_fees']} for r in summaries], 'checks': result['check_count']}))


if __name__ == '__main__':
    main()
