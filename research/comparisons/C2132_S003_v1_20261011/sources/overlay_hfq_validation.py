"""Strict read-only supplemental proof; never changes the public audit result.

The public intraday audit applies an HFQ tick grid and requires every planned
rotation to fill. This checker independently enforces the existing SRT raw-grid
limit and TXE dependency semantics while preserving the original public FAIL.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_FLOOR
from math import isfinite

import numpy as np
import pandas as pd
from strategy_evaluator import ReplayEvidence, audit_replay

TOLERANCE = 1e-7
KNOWN_PUBLIC_REASONS = frozenset(('INTRADAY_ORDER_NOT_FILLED',
                                'INVALID_INTRADAY_ORDER_PAIR', 'INTRADAY_FILL_MISMATCH'))


def _floor_tick(value):
    return float((Decimal(str(value)) / Decimal('.001')).to_integral_value(rounding=ROUND_FLOOR) * Decimal('.001'))


def _quantity(budget, limit, fee, lot):
    raw = int(Decimal(str(budget)) / (Decimal(str(limit)) * (1 + Decimal(str(fee)))))
    return raw // lot * lot


def _metrics(replay):
    equity = pd.Series([float(row['equity']) for row in replay.account_daily], dtype=float)
    total = float(equity.iloc[-1] / replay.initial_cash - 1.)
    dd = float(equity.div(equity.cummax().clip(lower=replay.initial_cash)).sub(1.).min())
    annual = float((equity.iloc[-1] / replay.initial_cash) ** (252 / len(equity)) - 1)
    previous = equity.shift(1)
    previous.iloc[0] = replay.initial_cash
    returns = equity.div(previous).sub(1.)
    volatility = float(returns.std(ddof=1))
    closed = pd.Series([float(row['net_return']) for row in replay.trades if row['status'] == 'CLOSED'], dtype=float)
    wins, losses = closed[closed.gt(0)], closed[closed.lt(0)]
    state = 'NO_CLOSED_TRADES' if closed.empty else 'NO_WINS' if wins.empty else 'NO_LOSSES' if losses.empty else 'VALID'
    return {'return': total, 'max_drawdown': dd,
            'calmar': annual / abs(dd) if abs(dd) > 1e-12 else None,
            'sharpe': float(np.sqrt(252.) * returns.mean() / volatility) if isfinite(volatility) and volatility > 0 else None,
            'closed_trades': len(closed), 'win_rate': float(len(wins) / len(closed)) if len(closed) else None,
            'win_loss_ratio': float(wins.mean() / abs(losses.mean())) if wins.size and losses.size else None,
            'win_loss_ratio_status': state}


def _strict_replay(replay):
    findings, checks, limits, blocked = [], [], [], []

    def require(condition, code, detail=None):
        if not bool(condition):
            findings.append({'code': code, 'detail': detail})

    def near(actual, wanted):
        return isfinite(float(actual)) and isfinite(float(wanted)) and abs(float(actual) - float(wanted)) <= TOLERANCE

    spec = replay.execution_spec
    require(spec.get('mode') == 'CORE_EVENT_INTRADAY_ROTATION' and spec.get('order_semantics') == 'SRT_PLAN', 'WRONG_REPLAY_CONTRACT')
    require(spec.get('pricing', {}).get('basis') == 'HFQ_RESEARCH', 'WRONG_PRICE_BASIS')
    require(spec.get('entry_checkpoint') == 'OPEN' and spec.get('exit_checkpoint') == '11:30_CLOSE'
            and spec.get('t_plus_one_inventory_rotation') is True, 'WRONG_CHECKPOINT_CONTRACT')
    fee, lot = float(spec['fee_rate']), int(spec['lot_size'])
    require(isfinite(fee) and 0 <= fee < 1 and lot > 0, 'INVALID_FEE_LOT')
    require(0 < spec['core_fraction'] < 1 and 0 < spec['event_fraction'] < 1, 'INVALID_FRACTIONS')
    sessions = tuple(replay.evaluation_sessions)
    require(bool(sessions) and tuple(sorted(set(sessions))) == sessions, 'INVALID_SESSIONS')
    require(tuple(str(row['date'])[:10] for row in replay.account_daily) == sessions, 'ACCOUNT_COVERAGE')
    daily = {str(row['date'])[:10]: row for row in replay.execution_daily}
    require(len(daily) == len(replay.execution_daily), 'DUPLICATE_DAILY')
    require(tuple(daily) == tuple(sorted(daily)), 'DAILY_ORDER')
    require(set(sessions).issubset(daily), 'DAILY_COVERAGE')
    for row in replay.execution_daily:
        require(all(type(row[key]) in (int, float) and isfinite(row[key]) and row[key] > 0
                    for key in ('close', 'unadjusted_close', 'price_scale')), 'INVALID_EXECUTION_PRICE', row['date'])
        require(near(row['close'], row['unadjusted_close'] * row['price_scale']), 'EXECUTION_SCALE', row['date'])
    bars = {str(row['time'])[:16]: row for row in replay.execution_intraday}
    require(len(bars) == len(replay.execution_intraday), 'DUPLICATE_INTRADAY')
    for day in sessions:
        require(day + 'T09:35' in bars and day + 'T11:30' in bars, 'MISSING_CHECKPOINT', day)
    decisions = {row['decision_id']: row for row in replay.decisions}
    require(len(decisions) == len(replay.decisions), 'DUPLICATE_DECISION')
    require(len({str(row['valid_session'])[:10] for row in replay.decisions}) == len(replay.decisions), 'MULTIPLE_DAY_DECISIONS')
    core = [row for row in replay.decisions if row['plan_mode'] == 'CORE_SETUP']
    require(len(core) == 1 and str(core[0]['valid_session'])[:10] == sessions[0], 'CORE_SETUP_COVERAGE')
    previous_sessions = {day: previous for previous, day in zip(tuple(daily)[:-1], tuple(daily)[1:], strict=True)}
    for row in replay.decisions:
        day, signal = str(row['valid_session'])[:10], str(row['signal_date'])[:10]
        require(day in sessions and previous_sessions.get(day) == signal and signal < day, 'CAUSAL_T_PLUS_ONE', row['decision_id'])
    checks.append('COMPLETE_SESSION_PRICE_SCALE_AND_CAUSAL_COVERAGE')

    orders = {row['order_id']: row for row in replay.orders}
    fills = {row['order_id']: row for row in replay.fills}
    require(len(orders) == len(replay.orders) and len(fills) == len(replay.fills), 'DUPLICATE_ORDER_FILL')
    require(len({row['fill_id'] for row in replay.fills}) == len(replay.fills), 'DUPLICATE_FILL_ID')
    require(set(fills).issubset(orders), 'ORPHAN_FILL')
    groups = defaultdict(list)
    fills_by_day = defaultdict(list)
    for row in replay.fills:
        fills_by_day[str(row['fill_time'])[:10]].append(row)
    accounts = {str(row['date'])[:10]: row for row in replay.account_daily}
    for order in replay.orders:
        decision_id = order['decision_id']
        require(decision_id in decisions, 'ORDER_DECISION', order['order_id'])
        decision = decisions[decision_id]
        day, signal_day = str(order['execution_date'])[:10], str(order['signal_date'])[:10]
        require(day == str(decision['valid_session'])[:10] and signal_day == str(decision['signal_date'])[:10], 'ORDER_CAUSAL_DATE', order['order_id'])
        require(type(order['quantity']) is int and order['quantity'] > 0 and order['quantity'] % lot == 0, 'ORDER_LOT', order['order_id'])
        groups[decision_id].append(order)
    require(set(groups) == set(decisions), 'UNRECORDED_DECISION_PLAN')
    core_quantity = None
    for decision in replay.decisions:
        day = str(decision['valid_session'])[:10]
        signal = daily[str(decision['signal_date'])[:10]]
        linked = groups[decision['decision_id']]
        setup = decision['plan_mode'] == 'CORE_SETUP'
        require(setup or decision['plan_mode'] == 'CORE_EVENT_INTRADAY_ROTATION', 'INVALID_PLAN_MODE')
        if not setup:
            require(decision.get('action') == 'INTRADAY_LONG_OVERLAY', 'INVALID_OVERLAY_ACTION')
        buy = linked[0]
        limit = _floor_tick(float(signal['unadjusted_close']) * 1.10) * float(signal['price_scale'])
        wrong_public_limit = _floor_tick(float(signal['close']) * 1.10)
        require(buy['side'] == 'BUY' and buy['checkpoint'] == 'OPEN' and buy['order_type'] == 'LIMIT'
                and buy['role'] == ('CORE_SETUP' if setup else 'ROTATION_ENTRY'), 'INVALID_BUY_LEG', buy)
        require(near(buy['limit_price'], limit), 'RAW_GRID_HFQ_LIMIT', buy['order_id'])
        if not near(buy['limit_price'], wrong_public_limit):
            limits.append({'order_id': buy['order_id'], 'signal_date': buy['signal_date'], 'execution_date': buy['execution_date'],
                           'raw_close': signal['unadjusted_close'], 'signal_price_scale': signal['price_scale'],
                           'actual_limit': buy['limit_price'], 'correct_raw_grid_hfq_limit': limit,
                           'public_hfq_grid_limit': wrong_public_limit, 'has_fill': buy['order_id'] in fills})
        account = accounts[day]
        budget = Decimal(str(account['cash_before'])) * Decimal(str(spec['core_fraction'])) if setup else Decimal(str(account['cash_before']))
        affordable = _quantity(budget, limit, fee, lot)
        expected_quantity = affordable if setup else min(core_quantity, affordable)
        require(buy['quantity'] == expected_quantity and expected_quantity > 0, 'PLANNED_QUANTITY', buy['order_id'])
        opening = float(bars[day + 'T09:35']['open'])
        require(isfinite(opening) and opening > 0, 'INVALID_OPEN_QUOTE', day)
        price_allowed = opening <= float(buy['limit_price'])
        cash_allowed = buy['quantity'] * opening * (1 + fee) <= float(account['cash_before']) + 1e-8
        can_fill = price_allowed and cash_allowed
        require(buy['status'] == ('FILLED' if can_fill else 'UNFILLED'), 'BUY_FILL_ELIGIBILITY', buy['order_id'])
        require((buy['order_id'] in fills) == can_fill, 'BUY_FILL_PRESENCE', buy['order_id'])
        if setup:
            require(len(linked) == 1 and can_fill, 'CORE_SETUP_SINGLE_FILLED_LEG')
            core_quantity = buy['quantity']
        elif can_fill:
            require(len(linked) == 2, 'FILLED_ENTRY_REQUIRES_DEPENDENT_EXIT', decision['decision_id'])
            sell = linked[1]
            require(sell['side'] == 'SELL' and sell['checkpoint'] == '11:30_CLOSE' and sell['order_type'] == 'MARKET'
                    and sell['role'] == 'ROTATION_EXIT' and sell['quantity'] == buy['quantity'] and sell['cycle_id'] == buy['cycle_id'], 'INVALID_DEPENDENT_EXIT', sell)
            require(near(sell['limit_price'], signal['close']), 'SELL_PLAN_REFERENCE', sell['order_id'])
            require(sell['status'] == 'FILLED' and sell['order_id'] in fills, 'MARKET_EXIT_MUST_FILL', sell['order_id'])
        else:
            require(len(linked) == 1 and not fills_by_day[day]
                    and not any(str(row['entry_date'])[:10] == day for row in replay.trades), 'UNFILLED_DEPENDENCY_BLOCK', decision['decision_id'])
            require(near(account['cash_before'], account['cash']) and account['quantity_before'] == account['quantity'], 'UNFILLED_CHANGED_ACCOUNT', day)
            blocked.append({'decision_id': decision['decision_id'], 'date': day, 'order_id': buy['order_id'],
                            'quantity': buy['quantity'], 'actual_limit': buy['limit_price'], 'correct_limit': limit,
                            'opening_quote': opening, 'price_allowed': price_allowed, 'cash_allowed': cash_allowed,
                            'no_fill_no_closed_trade': not fills_by_day[day], 'cash_quantity_preserved': True,
                            'dependent_exit_state': 'BLOCKED_NOT_SUBMITTED'})
        for order in linked:
            fill = fills.get(order['order_id'])
            if fill is None:
                continue
            buy_side = order['side'] == 'BUY'
            quote = opening if buy_side else float(bars[day + 'T11:30']['close'])
            expected_time = day + ('T09:30' if buy_side else 'T11:30')
            require(fill['side'] == order['side'] and fill['quantity'] == order['quantity']
                    and fill['decision_id'] == order['decision_id'] and fill['cycle_id'] == order['cycle_id']
                    and str(fill['signal_date'])[:10] == str(order['signal_date'])[:10], 'FILL_IDENTITY_QUANTITY_SIDE', order['order_id'])
            require(pd.Timestamp(fill['fill_time']) == pd.Timestamp(expected_time) and fill['trigger'] == order['checkpoint'], 'FILL_TIME_TRIGGER', order['order_id'])
            require(near(fill['price'], quote), 'CHECKPOINT_FILL_PRICE', order['order_id'])
            require(near(fill['fees'], order['quantity'] * quote * fee), 'FILL_FEE', order['order_id'])
    checks.append('EVERY_RAW_GRID_HFQ_LIMIT_ORDER_QUANTITY_PRICE_FEE_TIME_DEPENDENCY')

    cash, quantity = replay.initial_cash, 0
    for row in replay.account_daily:
        day = str(row['date'])[:10]
        require(near(row['cash_before'], cash) and row['quantity_before'] == quantity, 'ACCOUNT_OPENING', day)
        for fill in sorted(fills_by_day[day], key=lambda item: item['fill_time']):
            side = 1 if fill['side'] == 'BUY' else -1
            cash -= side * fill['quantity'] * fill['price'] + fill['fees']
            quantity += side * fill['quantity']
            require(cash >= -TOLERANCE and quantity >= 0, 'INTRADAY_NEGATIVE_BALANCE', fill['order_id'])
        require(near(row['cash'], cash) and row['quantity'] == quantity == core_quantity, 'ACCOUNT_CLOSE_STATE', day)
        require(near(row['close'], daily[day]['close']) and near(row['equity'], cash + quantity * row['close']), 'ACCOUNT_MARKED_EQUITY', day)
        require(near(row['target_position'], spec['core_fraction']), 'ACCOUNT_CORE_TARGET', day)
    checks.append('COMPLETE_CASH_QUANTITY_CORE_AND_MARKED_EQUITY_LEDGER')
    cycles = defaultdict(list)
    for fill in replay.fills:
        if decisions[fill['decision_id']]['plan_mode'] != 'CORE_SETUP':
            cycles[fill['cycle_id']].append(fill)
    trades = {row['cycle_id']: row for row in replay.trades}
    require(len(trades) == len(replay.trades) and set(trades) == set(cycles), 'TRADE_COVERAGE')
    for key, pair in cycles.items():
        pair = sorted(pair, key=lambda row: row['fill_time'])
        require(len(pair) == 2 and [row['side'] for row in pair] == ['BUY', 'SELL'], 'TRADE_PAIR', key)
        buy, sell = pair
        trade = trades[key]
        expected_return = sell['price'] * (1 - fee) / (buy['price'] * (1 + fee)) - 1
        require(trade['status'] == 'CLOSED' and trade['quantity'] == buy['quantity'] == sell['quantity']
                and trade['entry_date'] == buy['fill_time'] and trade['exit_date'] == sell['fill_time']
                and near(trade['entry_price'], buy['price']) and near(trade['exit_price'], sell['price'])
                and near(trade['net_return'], expected_return), 'TRADE_VALUE_DATE_QUANTITY', key)
    checks.append('EVERY_CLOSED_CYCLE_PAIR_VALUE_DATE_AND_OPEN_CORE_PRESERVED')
    expected_metrics = _metrics(replay)
    require(set(expected_metrics) == set(replay.metrics), 'METRIC_SCHEMA')
    for key, wanted in expected_metrics.items():
        actual = replay.metrics.get(key)
        require(actual is None if wanted is None else actual == wanted if type(wanted) is str else actual is not None and near(actual, wanted), 'METRIC_VALUE', key)
    checks.append('ALL_NATIVE_RETURN_DRAWDOWN_CALMAR_SHARPE_CLOSED_WIN_METRICS')
    return {'status': 'PASS' if not findings else 'FAIL', 'checks': checks, 'findings': findings,
            'raw_grid_limit_differences': limits, 'raw_grid_limit_difference_count': len(limits),
            'strict_unfilled_dependencies': blocked, 'strict_unfilled_dependency_count': len(blocked),
            'metric_recalculation': expected_metrics,
            'counts': {key: len(getattr(replay, key)) for key in
                       ['evaluation_sessions', 'decisions', 'orders', 'fills', 'account_daily', 'trades']}}


def validate_overlay_hfq(value: dict) -> dict:
    """Retain public native audit and independently prove admitted HFQ overlay facts.

    Published bytes and whole TDR reserialization/strong identity adaptation must
    additionally be authenticated by the caller. This function cannot replace
    validate_evaluation_evidence and never labels public validation as PASS.
    """
    if type(value) is not dict or value.get('schema_version') != 6 or value.get('source_kind') != 'published_result':
        raise ValueError('An original schema6 published evaluation object is required')
    runs = []
    for item in value['runs']:
        replay = ReplayEvidence.from_dict(item['replay_evidence'])
        public = audit_replay(replay).to_dict()
        try:
            strict = _strict_replay(replay)
        except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
            strict = {'status': 'FAIL', 'checks': [], 'findings': [{'code': 'MALFORMED_STRICT_INPUT', 'detail': str(exc)}]}
        unknown = sorted(set(public['reason_codes']) - KNOWN_PUBLIC_REASONS)
        if unknown:
            strict['status'] = 'FAIL'
            strict['findings'].append({'code': 'UNEXPLAINED_PUBLIC_REASON', 'detail': unknown})
        # Every retained known public failure is tied to concrete proof facts.
        if public['status'] == 'FAIL' and strict['status'] == 'PASS':
            evidence_counts = {
                'INTRADAY_FILL_MISMATCH': sum(row['has_fill'] for row in strict['raw_grid_limit_differences']),
                'INTRADAY_ORDER_NOT_FILLED': strict['strict_unfilled_dependency_count'],
                'INVALID_INTRADAY_ORDER_PAIR': strict['strict_unfilled_dependency_count'],
            }
            if any(evidence_counts.get(reason, 0) == 0 for reason in public['reason_codes']):
                strict['status'] = 'FAIL'
                strict['findings'].append({'code': 'PUBLIC_REASON_NOT_CONCRETELY_EXPLAINED'})
        else:
            evidence_counts = {}
        runs.append({'window_id': item['window_id'], 'scenario_id': item['scenario_id'],
                     'native_public_audit': public, 'supplemental': strict,
                     'native_reason_evidence_counts': evidence_counts})
    passed = bool(runs) and all(row['supplemental']['status'] == 'PASS' for row in runs)
    public_failed = any(row['native_public_audit']['status'] == 'FAIL' for row in runs)
    return {'status': 'PASS' if passed else 'FAIL',
            'public_validation': 'FAIL_WITH_SUPPLEMENTAL_HFQ_PROOF' if passed and public_failed else 'NATIVE_REPLAY_PASS' if passed else 'FAIL_UNRESOLVED',
            'request_hash': value['request_hash'], 'result_hash': value['result_hash'], 'runs': runs,
            'scope': 'Read-only strict execution/account proof, not a replacement public validation. Caller must bind published SHA and independently authenticate whole public TDR reserialization/projections/identities.',
            'account_evaluations': 0, 'account_preparations': 0, 'platform_changes': 0,
            'replay_mutations': 0, 'public_audit_preserved': True}
