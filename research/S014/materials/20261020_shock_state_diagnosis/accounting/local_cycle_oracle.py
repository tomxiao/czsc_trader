"""Independent remainder-cycle arithmetic from original inputs, never C outputs.

No function executes on import. Calling OFF is reserved for after the frozen
source and all original ON controls pass the separate evaluation gate.
"""
from datetime import datetime, time
from math import isfinite

import numpy as np
import pandas as pd
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill


def day(value):
    return str(value)[:10]


def original_maps(account):
    ledger = account['runs'][0]['ledgers']
    decisions = {day(r['signal_date']): r for r in ledger['decisions']['data']}
    fills = {r['fill_id']: r for r in ledger['fills']['data']}
    return decisions, fills


def causal_states(D, original, frames):
    """Use original market features and direct pinned runtime HFQ closes only."""
    close = frames['adjusted_daily']['Close']
    index = close.index.get_loc(pd.Timestamp(D))
    assert isinstance(index, int) or isinstance(index, np.integer)
    m, lag = original['ma20_prior'], original['ma20_prior_lag5']
    previous = float(close.iloc[index - 1]) if index >= 1 else None
    trend_known = bool(index >= 1 and m is not None and lag is not None and all(isfinite(v) for v in [m, lag, previous]))
    trend = bool(m > lag and previous >= m) if trend_known else None
    current = float(close.iloc[index])
    first = float(close.iloc[index - 5]) if index >= 5 else None

    def term(a, b):
        if a is None or b is None or not all(isfinite(v) and v > 0 for v in (a, b)):
            return None
        with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
            value = float(np.log(a / b))
        return value if isfinite(value) else None

    r1, r4 = term(current, previous), term(previous, first)
    shape_known = r1 is not None and r4 is not None
    shape = bool(r1 <= r4) if shape_known else None
    return {'PRIOR_TREND_ESTABLISHED': trend, 'NON_FINAL_DAY_DOMINATED': shape,
            'trend_known': trend_known, 'shape_known': shape_known, 'ma20_prior': m, 'ma20_prior_lag5': lag,
            'source_close_D_minus1': previous, 'r1_log': r1, 'r4_log': r4,
            'source_close_D': current, 'source_close_D_minus5': first}


def market_sell(E, quantity, frames, entry_E):
    assert E > entry_E and quantity > 0 and quantity % 100 == 0
    stamp = pd.Timestamp(E)
    status = frames['trading_status'].loc[stamp, 'Status']
    if status == 'SUSPENDED':
        return {'filled': False, 'reason': 'SUSPENDED', 'price': None, 'fee': None, 'trigger': None}
    assert status == 'TRADING', ('Unknown existing status', E, status)
    quote = frames['projected_execution'].loc[stamp]
    limits = frames['price_limits'].loc[stamp]
    scale = float(quote.Close / frames['execution_daily'].loc[stamp, 'Close'])
    rules = SessionPriceLimits(stamp.date(), float(limits.DownLimit * scale), float(limits.UpLimit * scale), float(.01 * scale))
    result = resolve_fill(OrderSpec('SELL', 'MARKET', quantity), session_open=float(quote.Open),
                          session_time=datetime.combine(stamp.date(), time(9, 30)), intraday_touches=(),
                          daily_quote=DailyQuote(float(quote.Low), float(quote.High)), session_limits=rules)
    return {'filled': result.filled, 'reason': result.reason, 'price': result.price,
            'fee': quantity * result.price * .001 if result.filled else None, 'trigger': result.trigger,
            'session_limits': {'down': rules.down_limit, 'up': rules.up_limit, 'tick': rules.price_tick}}


def reconstruct(event, original_account, frames, mode):
    assert mode in {'ON', 'OFF_LOCAL_CYCLE'}
    decisions, fills = original_maps(original_account)
    entry_E, shock_D = event['actual_entry_fill_E'], event['D']
    entry_fill = fills[event['actual_entry_fill_id']]
    actual_sale = fills[event['actual_exit_fill_id']]
    entry_row = decisions[entry_E]
    entry_i = entry_row['entry_index']
    deadline = entry_i + 9
    quantity = entry_fill['quantity']
    # Original real-entry checkpoint is admissible; never reuse a later entry.
    basis = entry_row['entry_fill_price']
    assert basis is not None and quantity > 0
    pending = False
    trace = []
    attempts = []
    sale = None
    for D in sorted(d for d in decisions if entry_E <= d <= '2026-10-14'):
        original = decisions[D]
        E, i = day(original['valid_session']), original['warmup_sessions']
        assert E <= '2026-10-15'
        close = float(frames['adjusted_daily'].loc[pd.Timestamp(D), 'Close'])
        age = i - entry_i
        expired = i >= deadline
        inherited = pending
        eligible = not inherited and not expired
        profit = close * .999 / (basis * 1.001) - 1
        cost_loss = basis * 1.001 - close * .999
        shock = bool(eligible and original['shock_known'] and profit > 0 and original['z5'] > 2)
        cost = bool(eligible and original['atr_positive'] and cost_loss >= original['atr20_prior'])
        support_break = bool(original['support_floor'] is not None and close < original['support_floor'])
        grace = bool(eligible and D == entry_E and support_break)
        support = bool(eligible and support_break and not grace)
        # Both modes are identical until first original selected-SHOCK D.
        selected_shock = bool(shock and (mode == 'ON' or D < shock_D))
        pending = bool(inherited or expired or selected_shock or cost or support)
        record = {'D': D, 'valid_E': E, 'entry_index': entry_i, 'deadline_index': deadline, 'reservation_index': entry_i + 10,
                  'holding_age': age, 'target_position': 0. if pending else 1., 'exit_pending': pending,
                  'pending_inherited': inherited, 'deadline_exit': expired, 'profit_exit_eligible': eligible,
                  'shock_condition': shock, 'selected_profit_exit': shock, 'selected_shock_exit': selected_shock,
                  'selected_cost_exit': cost, 'selected_risk_exit': selected_shock or cost,
                  'ordinary_support_exit': support, 'entry_grace_eligible': grace, 'entry_grace_applied': grace and not (selected_shock or cost),
                  'net_profit': profit, 'cost_loss_price': cost_loss, 'source_close_RUNTIME_HFQ': close}
        trace.append(record)
        if not pending:
            continue
        result = market_sell(E, quantity, frames, entry_E)
        attempts.append({'D': D, 'E': E, **result})
        if result['filled']:
            sale = {'D': D, 'E': E, 'price': result['price'], 'quantity': quantity, 'fee': result['fee'], 'trigger': result['trigger']}
            break
    censored = sale is None
    denominator = quantity * entry_fill['price'] + entry_fill['fees']
    advantage_cash = (quantity * sale['price'] - sale['fee']) - (quantity * actual_sale['price'] - actual_sale['fees']) if sale else None
    advantage = advantage_cash / denominator if sale else None
    sign = (1 if advantage_cash > 0 else -1 if advantage_cash < 0 else 0) if sale else None
    return {'mode': mode, 'event_id': event['event_id'], 'cycle_id': event['cycle_id'], 'trace': trace, 'attempts': attempts, 'sale': sale,
            'censored': censored, 'entry_total_cost': denominator, 'incremental_liquidation_cash': advantage_cash,
            'incremental_liquidation_normalized': advantage, 'advantage_sign': sign,
            'source_prices_and_features_independent_of_C_component_outputs': True}
