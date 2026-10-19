"""Independent EX046 actual-funded audit; no replay, prepare or dispatch."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path

import pause_financial_audit as F
import clock_execution_oracle as O

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
EX = ROOT / 'research/S014/experiments/EX046_20261020'
P, H, A = F.P, F.P.H, F.P.A
FIXED = A.read(OUT.parent / 'design_decision.json')['fixed_parameters']
SOURCE_SHA = '5e775c5b27bfd7b1ac5bec9c2839ce24ae62f32f1829c21a13091868a174b846'
PAUSE_FIELDS = ['completed_cycle_today', 'completed_loss_today', 'completed_profit_today', 'completed_zero_today',
                'completed_net_known', 'last_completed_sign', 'pause_armed_before_candidate', 'pause_armed',
                'pause_slot_consumed', 'planned_slot_active', 'planned_slot_until', 'reservation_before_pause',
                'completed_net_unit', 'last_completed_net_unit']
EVENTS = ['selected_shock_exit', 'selected_cost_exit', 'selected_risk_exit', 'entry_grace_applied',
          'support_exit_suppressed', 'completed_cycle_today', 'completed_loss_today', 'completed_profit_today',
          'completed_zero_today', 'pause_armed', 'pause_slot_consumed']


def sign(value):
    return -1 if value < 0 else 1 if value > 0 else 0


def origin():
    receipt = A.read(ROOT / 'research/S014/experiments/EX044_20261019/others/accounts/run-004.json')
    account = A.published(receipt['evidence'])
    A.check('correct original cost account', account['result_hash'] == receipt['result_hash'] == 'a784d786c0fae2f64651275a653f8cdfc28c28e53048431f4d9151d2ffe07f05')
    return account, receipt


def run_lock(record):
    preflight = A.published(record['preflight_ref'])
    lock_sha = preflight['source_lock']
    reviewed = [A.read(p) for p in OUT.glob('pause_public_lock_review*.json')]
    matching = [r for r in reviewed if r['status'] == 'PASS' and r['source_lock_ref']['sha256'] == lock_sha]
    A.check('actual per-record dispatch lock independently reviewed', len(matching) == 1)
    ref = matching[0]['source_lock_ref']
    return A.published(ref), ref


def identity(record, account, frozen, prior):
    source_review = A.read(OUT / 'pause_source_review.json')
    runner_review = A.read(OUT / 'pause_runner_pre_review.json')
    A.check('independent source/runner PASS', source_review['status'] == runner_review['status'] == 'PASS')
    A.check('reviewed source identity', source_review['source_sha256'] == runner_review['source_sha256'] == SOURCE_SHA)
    lock, lock_ref = run_lock(record)
    locked = next(r for r in lock['runs'] if r['index'] == record['index'])
    for key in ['mode', 'parameters', 'candidate', 'runtime_sha256', 'payload_sha256']:
        A.check('locked immutable ' + key, record[key] == locked[key])
    A.check('fixed canonical parameters', record['parameters'] == FIXED[record['index']] and set(record['parameters']) == {'pause_profile'})
    payload, binding = A.published(record['published_payload_ref']), A.published(record['binding_ref'])
    A.public_bytes(record['published_source_ref'])
    A.check('published source exact', record['published_source_ref']['sha256'] == SOURCE_SHA)
    A.check('implementation closure', record['runtime_implementation_sha256'] == lock['runtime_implementation_sha256'] == payload['runtime']['source_sha256'])
    A.check('payload exact binding', record['payload_sha256'] == record['published_payload_ref']['sha256'] and payload == binding['payload'])
    A.check('payload parameters/candidate', payload['parameters'] == record['parameters'] and binding['candidate'] == record['candidate'])
    req = account['request_identity']
    A.check('new experiment', req['experiment_id'] == 'EX046_20261020')
    for key in ['asset_type', 'benchmark', 'costs', 'data_cutoff', 'execution_mode', 'frequency_window_days', 'initial_cash', 'market_rules', 'metric_semantics_version', 'price_basis', 'pricing', 'symbol', 'windows']:
        A.check('original unchanged contract ' + key, req[key] == frozen['request_identity'][key])
    A.check('request and runtime bindings', req['content_sha256'] == record['request_content_sha256'] and account['runtime_binding_hash'] == req['runtime_binding_hash'] == record['runtime_binding_hash'])
    A.check('actual candidate', account['runs'][0]['candidate_id'] == record['candidate'].split('-')[-1])
    A.check('causal plan binding', req['input_bindings'] == binding['input_bindings'])
    previous = A.published(prior['binding_ref'])
    for key in ['execution_requests', 'execution_prepared', 'execution_identities', 'execution_fingerprint']:
        A.check('existing prepared asset identical ' + key, binding[key] == previous[key])
    A.check('actual data fingerprint', req['data_identity'] == binding['execution_fingerprint'] == frozen['request_identity']['data_identity'])
    plan, oldplan = req['input_bindings']['full']['plan'], frozen['request_identity']['input_bindings']['full']['plan']
    A.check('plan schema unchanged', plan.keys() == oldplan.keys())
    for key in plan:
        if key != 'strategy':
            A.check('original causal clock exact ' + key, plan[key] == oldplan[key])
    strategy = plan['strategy']
    A.check('new runtime identity', strategy['reference_id'] == record['candidate'] and strategy['runtime_sha256'] == record['runtime_sha256'] and strategy['release_hash'] == account['strategy_identity'] == req['strategy_identity'] and account['strategy_identity'] != frozen['strategy_identity'])
    return binding, lock_ref


def lifecycle(account, frozen, profile):
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
            completed.append({'D': D, 'cycle_id': fill['cycle_id'], 'actual_net_cash': net_cash, 'actual_net_return': trade['net_return'], 'actual_unit_net_ledger_basis': per_unit, 'runtime_unit_net': row['completed_net_unit'], 'strict_sign': sign_today, 'economic_window': D <= '2025-12-31'})
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
        expected = {'original_entry_candidate': candidate, 'candidate_shock': candidate and bool(row['shock_known']) and row['z5'] > 2,
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
            risk = shock or cost
            grace = bool(eligible and bought and row['support_break'])
            ordinary = bool(eligible and row['support_break'] and not grace)
            suppressed = bool(eligible and row['support_break'] and grace and not risk)
            expected.update(shock_condition=shock, selected_profit_exit=shock, acceleration_condition=accel,
                            selected_shock_exit=shock, selected_cost_exit=cost, selected_risk_exit=risk,
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
        if '2020-01-01' <= D <= '2025-12-31':
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


def divergence(account, frozen, index):
    old, new = frozen['runs'][0]['ledgers'], account['runs'][0]['ledgers']
    source_control = account if index == 0 else A.published(A.read(EX / 'others/accounts/run-000.json')['evidence'])
    control_rows = source_control['runs'][0]['ledgers']['decisions']['data']
    feedback = [A.day(r['signal_date']) for r in new['decisions']['data'] if r['completed_net_known'] or r['pause_armed_before_candidate'] or r['pause_armed']]
    feedback_difference = [A.day(r['signal_date']) for c, r in zip(control_rows, new['decisions']['data'], strict=True) if any(c[k] != r[k] for k in PAUSE_FIELDS)]
    armed_dates = [A.day(r['signal_date']) for r in new['decisions']['data'] if r['pause_armed_before_candidate'] or r['pause_armed']]
    state = [A.day(r['signal_date']) for c, r in zip(old['decisions']['data'], new['decisions']['data'], strict=True) if any(r[k] != v for k, v in c.items() if k not in A.ID_KEYS)]
    target = [A.day(r['signal_date']) for c, r in zip(old['decisions']['data'], new['decisions']['data'], strict=True) if c['target_position'] != r['target_position']]
    funded = [A.day(r['date']) for c, r in zip(old['account_daily']['data'], new['account_daily']['data'], strict=True) if any(c[k] != r[k] for k in ['cash', 'cash_before', 'quantity', 'quantity_before', 'equity'])]
    if not state:
        A.noop_equivalence(frozen, account)
    else:
        D = state[0]
        before = max(A.day(r['signal_date']) for r in new['decisions']['data'] if A.day(r['signal_date']) < D)
        for name, key, cutoff in [('decisions', 'signal_date', before), ('orders', 'signal_date', before), ('fills', 'fill_time', D), ('account_daily', 'date', D)]:
            A.economic_rows(old[name]['data'], new[name]['data'], 'exact original funded prefix ' + name, cutoff, key)
    return {'first_feedback_state_D': feedback[0] if feedback else None, 'first_original_state_divergence_D': state[0] if state else None,
            'first_target_divergence_D': target[0] if target else None, 'first_funded_state_E': funded[0] if funded else None,
            'first_armed_D': armed_dates[0] if armed_dates else None,
            'first_feedback_difference_vs_source_control_D': feedback_difference[0] if feedback_difference else None,
            'feedback_definition': 'First actual completion enters new known memory, including BASE; original state and wealth may remain exact.',
            'feedback_constant_profile_flags_excluded': True, 'old_columns_exact_until_first_original_state_D': True}


def audit_one(index):
    destination = OUT / f'pause_account_{index:03d}_independent_review.json'
    A.check('refuse overwrite', not destination.exists())
    record = A.read(EX / f'others/accounts/run-{index:03d}.json')
    A.check('actual successful engine account', record['status'] == 'SUCCEEDED')
    incident = record['audit']['status'] != 'PASS'
    if incident:
        A.check('only root-authorized retained original internal D/E expression incident', index == 0 and record['evidence']['sha256'] == '174a4f8d4ca11ccd14a44f8cfb439e046123de4e3df67da065846e323ea36ab4' and record['result_hash'] == 'c8762ae87e97b316c5fa82ff15b262e1ad27bcdf27d24f9530ab22f66680721f' and record['audit']['status'] == 'FAIL' and record['audit']['strict_control_against_EX044004'])
    account = A.published(record['evidence'])
    A.check('actual result identity', account['result_hash'] == record['result_hash'])
    A.check('one FULL account', len(account['runs']) == 1 and account['execution_mode'] == 'FULL')
    frozen, prior = origin()
    binding, lock_ref = identity(record, account, frozen, prior)
    A.equal_baseline(frozen, account)
    frames = H.fetch_execution(binding, account['request_identity']['pricing'])
    approved, boundaries = O.exact_execution_prices(account, frames)
    accounting = F.audit_daily(account, index != 0, approved)
    if index == 0:
        A.noop_equivalence(frozen, account)
    else:
        gate = A.read(OUT / 'pause_account_000_independent_review.json')
        A.check('fresh source control independently passed', gate['status'] == 'PASS' and gate['source_sha256'] == SOURCE_SHA)
    state = lifecycle(account, frozen, record['parameters']['pause_profile'])
    prefix = divergence(account, frozen, index)
    H.execution_constraints(account, frames)
    original, _ = P.origin(0)
    annual, summary = H.annual_and_summary(account, original)
    original_grace, _ = P.origin(4)
    grace_year = A.yearly(original_grace['runs'][0]['ledgers']['account_daily']['data'])
    cost_year = A.yearly(frozen['runs'][0]['ledgers']['account_daily']['data'])
    for row in annual:
        row['return_difference_vs_frozen'] = row['return'] - grace_year[row['year']]['return']
        row['return_difference_vs_cost_control'] = row['return'] - cost_year[row['year']]['return']
    hashes = H.econ_hashes(account, frozen)
    funded_projection = [{k: r[k] for k in ['date', 'cash', 'cash_before', 'equity', 'quantity', 'quantity_before']} for r in account['runs'][0]['ledgers']['account_daily']['data']]
    hashes['funded_wealth_sha256'] = H.hash_value(funded_projection)
    hashes['funded_wealth_2020_25_sha256'] = H.hash_value([r for r in funded_projection if A.day(r['date']) <= '2025-12-31'])
    result = {'status': 'PASS', 'index': index, 'policy_id': record['mode'], 'parameters': record['parameters'], 'candidate': record['candidate'],
              'account_ref': record['evidence'], 'result_hash': record['result_hash'], 'source_sha256': SOURCE_SHA, 'baseline_ref': prior['evidence'],
              'accounting': accounting, 'lifecycle': state, 'prefix': prefix, 'original_annual_goal_audit': annual, 'summary': summary,
              'terminal2025_asof': A.terminal_state(account), 'economic_path_hashes': hashes, 'source_NOOP_exact_EX044004': index == 0,
              'checks': sum(A.COUNTS.values()), 'check_counts': dict(A.COUNTS), 'maximum_arithmetic_error': A.ERRORS,
              'derived_currency_absolute_tolerance': A.MONEY_TOLERANCE, 'derived_ratio_absolute_tolerance': A.RATIO_TOLERANCE,
              'NOOP_economic_projection_tolerance': 0, 'automatic_tolerance_expansion': False,
              'source_lock_sha256': lock_ref['sha256'], 'actual_dispatch_source_lock_ref': lock_ref,
              'executor_original_internal_audit_status': record['audit']['status'],
              'retained_internal_audit_expression_incident': 'Known first internal D/E comparator/holding-map error; independent actual audit does not reuse it; active gate also requires corrected internal successor.' if incident else None,
              'audit_implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'financial_helper_sha256': sha256((OUT / 'pause_financial_audit.py').read_bytes()).hexdigest(),
              'public_exact_execution_oracle_sha256': sha256(Path(O.__file__).read_bytes()).hexdigest(),
              'exact_public_fill_oracle': {'matched_actual_fills': len(approved), 'original_roundoff_boundaries': boundaries, 'new_epsilon': 0},
              'new_fits': 0, 'new_strategy_replays': 0, 'auditor_dispatches': 0, 'new_supplier_calls': 0, 'new_preparations': 0,
              'limits': ['Seen2020-25 development;2026 technical only.', 'Opposite-sign policies have evolving own populations/capital; no causal information/timing decomposition.', 'Only user original economic goals are hard acceptance.']}
    H.write(destination, result)
    print(json.dumps({'index': index, 'status': 'PASS', 'checks': result['checks'], 'review_sha256': sha256(destination.read_bytes()).hexdigest()}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=int, required=True, choices=(0, 1, 2))
    args = parser.parse_args()
    try:
        audit_one(args.index)
    except Exception as exc:
        failure = OUT / f'pause_account_{args.index:03d}_independent_failure.json'
        if not failure.exists():
            H.write(failure, {'status': 'FAIL', 'index': args.index, 'exception': repr(exc), 'check_counts': dict(A.COUNTS), 'no_tolerance_expansion': True,
                              'audit_implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest()})
        raise


if __name__ == '__main__':
    main()
