"""Actual funded lifecycle oracle derived from frozen EX046 independent audit.
Only SHOCK actual selection changes; raw condition and own loss pause remain.
"""
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd() / 'research/S014/materials/20261020_preentry_diagnosis/accounting'))
import audit_pause_accounts as Q  # noqa: E402

A = Q.A
sign = Q.sign
EVENTS = Q.EVENTS + ['shock_action_suppressed']
DERIVED_FROM_SHA256 = '9950b9ae7c04142632ebe39cfa5aab954326762fc3966b06bca6e7605dd72f40'
assert sha256(Path(Q.__file__).read_bytes()).hexdigest() == DERIVED_FROM_SHA256


def lifecycle(account, frozen, shock_profile):
    profile = "AFTER_NET_LOSS_SKIP1"
    enabled = shock_profile == "SHOCK_ON"
    ledgers = account['runs'][0]['ledgers']
    rows = ledgers['decisions']['data']
    daily = {A.day(r['date']): r for r in ledgers['account_daily']['data']}
    fills = {A.day(r['fill_time']): r for r in ledgers['fills']['data']}
    trades = {r['cycle_id']: r for r in ledgers['trades']['data']}
    old = {A.day(r['signal_date']): r for r in frozen['runs'][0]['ledgers']['decisions']['data']}
    anchor = account['request_identity']['pricing']['anchor_factor']
    entry = peak = active_buy = None
    previous = None
    reservation = planned_until = -1
    armed = False
    last_net = None
    last_sign = 0
    annual = defaultdict(Counter)
    events = []
    completed = []
    for i, row in enumerate(rows):
        D, E = A.day(row['signal_date']), A.day(row['valid_session'])
        fill = fills.get(D)
        bought, sold = bool(fill and fill['side'] == 'BUY'), bool(fill and fill['side'] == 'SELL')
        held = bool(D in daily and daily[D]['quantity'] > 0)
        for key, value in [('held_at_close', held), ('buy_filled_today', bought), ('sell_filled_today', sold)]:
            A.check('actual positive funded D alignment ' + key, bool(row[key]) == value)
        failed = bool(previous and previous['entry_signal'] and not bought)
        A.check('actual failed BUY only', bool(row['failed_buy_reset']) == failed)
        for key in ['ready', 'support_ok', 'support_floor', 'support_break', 'warmup_sessions', 'ma20_prior', 'ma20_prior_lag5', 'atr20_prior', 'ret5_log', 'sigma20_pre5', 'z5', 'ma_known', 'atr_known', 'atr_positive', 'sigma20_known', 'sigma20_positive', 'shock_known']:
            A.check('original market feature exact ' + key, row[key] == old[D][key])
        net_today = None
        sign_today = 0
        if bought:
            A.check('real entry no existing active inventory', active_buy is None and fill['quantity'] > 0)
            active_buy = fill
            entry = fill['price'] * anchor
            peak = None
            reservation, planned_until = i + 10, -1
        if sold:
            A.check('completed own actual positive funded cycle', active_buy is not None and active_buy['cycle_id'] == fill['cycle_id'] and active_buy['quantity'] == fill['quantity'] and fill['quantity'] > 0)
            per_unit = fill['price'] * .999 - active_buy['price'] * 1.001
            net_cash = fill['quantity'] * fill['price'] - fill['fees'] - active_buy['quantity'] * active_buy['price'] - active_buy['fees']
            trade = trades[fill['cycle_id']]
            net_today = fill['price'] * anchor * .999 - entry * 1.001
            sign_today = sign(net_cash)
            A.check('strict actual completion sign perunit money trade source', sign_today == sign(per_unit) == sign(trade['net_return']) == sign(row['completed_net_unit']) and trade['status'] == 'CLOSED')
            A.check('actual completed trade date', A.day(trade['exit_date']) == D)
            A.number('source completed perunit projection', row['completed_net_unit'], net_today, True)
            last_net, last_sign = net_today, sign_today
            armed = bool((profile == 'AFTER_NET_LOSS_SKIP1' and sign_today < 0) or (profile == 'AFTER_NET_PROFIT_SKIP1' and sign_today > 0))
            completed.append({'D': D, 'cycle_id': fill['cycle_id'], 'actual_net_cash': net_cash, 'actual_net_return': trade['net_return'], 'actual_unit_net_ledger_basis': per_unit, 'runtime_unit_net': row['completed_net_unit'], 'strict_sign': sign_today, 'complete_years_2020_25': D <= '2025-12-31', 'original_goal_window': True})
            active_buy = entry = peak = None
        A.check('no fake completed raw value', sold or row['completed_net_unit'] is None)
        A.check('stored completed known and sign', bool(row['completed_net_known']) == (last_net is not None) and row['last_completed_sign'] == last_sign)
        if last_net is None:
            A.check('no completed outcome imputation', row['last_completed_net_unit'] is None)
        else:
            A.number('own last completed perunit retained', row['last_completed_net_unit'], last_net, True)
        before = reservation
        armed_before = armed
        candidate = bool(not held and not failed and row['ready'] and row['support_ok'] and i >= before)
        consume = bool(candidate and armed_before)
        if consume:
            reservation, planned_until, armed = i + 11, i + 11, False
        expected = {'shock_action_enabled': enabled, 'shock_action_suppressed': False, 'original_entry_candidate': candidate, 'candidate_shock': candidate and bool(row['shock_known']) and row['z5'] > 2,
                    'entry_guard_active': False, 'entry_guard_blocked': False, 'exit_domain_any': False, 'cost_stop_active': True,
                    'pause_loss_profile': profile == 'AFTER_NET_LOSS_SKIP1', 'pause_profit_profile': profile == 'AFTER_NET_PROFIT_SKIP1',
                    'completed_cycle_today': sold, 'completed_loss_today': sold and sign_today < 0,
                    'completed_profit_today': sold and sign_today > 0, 'completed_zero_today': sold and sign_today == 0,
                    'pause_armed_before_candidate': armed_before, 'pause_armed': armed, 'pause_slot_consumed': consume,
                    'planned_slot_active': not held and planned_until >= 0 and i < planned_until}
        A.check('exact own prospective slot clock', row['reservation_before_pause'] == before and row['reservation_index'] == reservation and row['planned_slot_until'] == planned_until)
        A.check('BUY only eligible unpaused candidate', bool(row['entry_signal']) == bool(candidate and not consume))
        if consume:
            A.check('virtual slot no fake holding/entry/fee/failedBUY', not held and row['target_position'] == 0 and row['entry_index'] == row['deadline_index'] == -1 and not failed)
        inherited = bool(held and previous and previous['exit_pending'] and not sold)
        expired = bool(held and row['warmup_sessions'] >= row['deadline_index'])
        eligible = bool(held and not inherited and not expired)
        expected.update(pending_inherited=inherited, deadline_exit=expired, profit_exit_eligible=eligible)
        if held:
            A.check('held has positive actual funded entry', active_buy is not None)
            close = daily[D]['close'] * anchor
            peak = close if bought else max(peak, close)
            net = close * .999 / (entry * 1.001) - 1
            loss = entry * 1.001 - close * .999
            for key, value in [('entry_fill_price', entry), ('peak_close', peak), ('peak_net_gain_price', peak * .999 - entry * 1.001), ('giveback_price', peak - close), ('cost_loss_price', loss)]:
                A.number('actual anchored feature ' + key, row[key], value, True)
            A.number('current fee-adjusted net P', row['net_profit'], net)
            if row['atr_positive']:
                A.number('priorATR net loss ratio', row['cost_loss_atr'], loss / row['atr20_prior'])
            else:
                A.check('unknown ratio remains null', row['cost_loss_atr'] is None)
            shock = bool(eligible and row['shock_known'] and net > 0 and row['z5'] > 2)
            accel = bool(eligible and row['shock_known'] and row['z5'] > 2)
            cost = bool(eligible and row['atr_positive'] and loss >= row['atr20_prior'])
            chosen_shock = shock and enabled
            risk = chosen_shock or cost
            grace = bool(eligible and bought and row['support_break'])
            ordinary = bool(eligible and row['support_break'] and not grace)
            suppressed = bool(eligible and row['support_break'] and grace and not risk)
            expected.update(shock_condition=shock, selected_profit_exit=shock, acceleration_condition=accel,
                            shock_action_suppressed=shock and not enabled,
                            selected_shock_exit=chosen_shock, selected_cost_exit=cost, selected_risk_exit=risk,
                            cost_stop_condition=cost, shock_exit_added_vs_positive=False,
                            cost_exit_added_vs_baseline=cost and not (shock or ordinary), risk_exit_added_vs_baseline=risk and not (shock or ordinary),
                            cost_support_overlap=cost and bool(eligible and row['support_break']), cost_grace_override=cost and grace,
                            entry_grace_eligible=grace, entry_grace_applied=grace and not risk, support_exit_suppressed=suppressed,
                            support_protection_applied=suppressed, original_support_exit=bool(eligible and row['support_break']), ordinary_support_exit=ordinary, peak_known=True)
            A.check('original pending/expiry > risk > grace > support', bool(row['exit_pending']) == bool(inherited or expired or risk or ordinary))
            A.check('actual original holding age', row['holding_age'] == row['warmup_sessions'] - row['entry_index'])
            A.check('fixed no trend protection', not row['trend_cycle_active'] and not row['trend_cycle_activated'])
        else:
            A.check('flat clears entry cost peak', all(row[k] is None for k in ['entry_fill_price', 'peak_close', 'net_profit', 'cost_loss_price', 'cost_loss_atr']) and not row['peak_known'])
        for key, value in expected.items():
            A.check('independent actual own-state ' + key, bool(row[key]) == bool(value))
        if '2020-01-01' <= D <= '2026-10-15':
            annual[D[:4]]['D_rows'] += 1
            annual[D[:4]]['actual_held_D'] += held
            for key in EVENTS:
                annual[D[:4]][key] += int(bool(row[key]))
            if any(row[k] for k in EVENTS):
                events.append({'D': D, 'E': E, 'entry_index': row['entry_index'], 'net_profit': row['net_profit'], 'z5': row['z5'],
                               'reservation_before_pause': before, 'reservation_after_pause': reservation, 'planned_slot_until': planned_until,
                               'completed_net_unit': row['completed_net_unit'], 'last_completed_sign': last_sign,
                               'pause_armed_before_candidate': armed_before, **{k: row[k] for k in EVENTS}})
        previous = row
    return {'annual_D_counts': dict(annual), 'events': events, 'actual_completed_cycles': completed,
            'actual_vs_runtime_D_alignment': 'EXACT_ALL1642_D', 'strict_actual_sign_checked': len(completed), 'shadow_affordability_assumed': False}
