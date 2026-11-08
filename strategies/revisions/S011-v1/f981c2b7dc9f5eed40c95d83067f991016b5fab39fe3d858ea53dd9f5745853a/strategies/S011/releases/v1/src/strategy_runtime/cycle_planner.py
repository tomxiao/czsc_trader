"""Native V4 expression of the frozen entry-cycle order rules.

The signal is independent of confirmed holdings. Full-cash strategies lock
quantity; signal-cash strategies additionally lock the initial cash allocation.
This file is copied into each authenticated candidate source closure.
"""
from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING, ROUND_HALF_UP
from hashlib import sha256

from strategy_runtime import AccountDecision, CycleBudget, EntryCyclePhase, OrderSide, OrderType, ReplayOrder


def _tick(value, tick, mode):
    unit = Decimal(str(tick))
    return float((Decimal(str(value)) / unit).to_integral_value(rounding=mode) * unit)


def plan_cycle(ctx, *, signal_target, execution, locked_quantity, reason, facts, allocation=1.0, had_position=False):
    """Return (native decision, next quantity lock); caller persists the lock.

An empty explicit order tuple means automatic planning to V4. Therefore idle
and fully-funded holds use full_available_cash with the actual holding target,
while pending signal-cash budgets remain attached for executor accounting.
"""
    if ctx.planning is None:
        raise ValueError('frozen cycle requires declared planning context')
    if signal_target not in (0, 1) or type(locked_quantity) is not int or locked_quantity < -1:
        raise ValueError('binary signal and quantity lock (-1 means absent) required')
    instrument, capital = execution['instrument'], execution['capital']
    entry, exit_rule = execution['entry'], execution['exit']
    mode = capital['mode']
    if mode not in ('full_available_cash', 'available_cash_fraction', 'signal_cash_fraction'):
        raise ValueError('unsupported frozen cycle allocation')
    if capital['target_scope'] != 'entry_cycle':
        raise ValueError('frozen cycle scope changed')
    lot, tick = int(instrument['lot_size']), float(instrument['price_tick'])
    maximum = int(instrument['maximum_order_quantity'])
    actual, sellable = ctx.account.quantity, ctx.account.sellable_quantity
    cash, fee = Decimal(str(ctx.account.available_cash)), Decimal(str(ctx.planning.fee_rate))
    reference = float(ctx.history.last()['Close'])
    scale = ctx.portfolio.reference_price_scale
    requested = _tick(reference * (1 + float(entry['limit_parameter'])), tick, ROUND_FLOOR)
    guard = _tick(_tick(reference * (1 + float(instrument['price_limit_ratio'])), tick, ROUND_FLOOR) - tick, tick, ROUND_HALF_UP)
    price = min(requested, guard) * scale
    unit = Decimal(str(price)) * (1 + fee)
    previous = ctx.budget if mode == 'signal_cash_fraction' else None
    after = previous
    target_lock = -1 if had_position and not actual else locked_quantity
    effective = bool(signal_target)
    if mode == 'signal_cash_fraction':
        if previous is None:
            if actual:
                raise ValueError('holding requires the original signal cash budget')
            if effective:
                fraction = Decimal(str(allocation))
                budget_cash = cash * fraction
                amount = int((budget_cash / (unit * lot)).to_integral_value(rounding=ROUND_FLOOR)) * lot
                if amount:
                    cycle_id = sha256(('entry:' + ctx.point.decision_at.isoformat()).encode()).hexdigest()
                    after = CycleBudget(cycle_id, amount, fraction, budget_cash, Decimal(0), EntryCyclePhase.ACTIVE)
        elif not effective or previous.phase is EntryCyclePhase.EXITING:
            after = replace(previous, phase=EntryCyclePhase.EXITING)
        effective = after is not None and after.phase is EntryCyclePhase.ACTIVE
        target_lock = 0 if after is None else after.target_quantity
        available = min(cash, max(Decimal(0), after.cash_budget - after.buy_cost_including_fees)) if effective else cash
    else:
        fraction = Decimal(str(capital.get('allocation_fraction', 1.0)))
        available = cash * fraction
        if effective and target_lock == -1:
            target_lock = actual + int((available / (unit * lot)).to_integral_value(rounding=ROUND_FLOOR)) * lot
        if not effective:
            target_lock = (actual if target_lock == -1 else target_lock) if actual else -1
    orders = []
    if effective:
        affordable = max(0, int((available / (unit * lot)).to_integral_value(rounding=ROUND_FLOOR)) * lot)
        remaining = min(max(0, target_lock - actual), affordable)
        side, order_type, limit = OrderSide.BUY, OrderType(entry['order_type']), price
    else:
        remaining = min(actual, sellable)
        kind = exit_rule['order_type']
        if execution.get('virtual_fill', {}).get('sell') == 'marketable_limit_at_open':
            kind = 'MARKET'
        side, order_type = OrderSide.SELL, OrderType(kind)
        limit = None if order_type is OrderType.MARKET else _tick(
            _tick(reference * (1 - float(exit_rule['limit_ratio'])), tick, ROUND_CEILING) + tick, tick, ROUND_HALF_UP) * scale
    while remaining:
        amount = min(remaining, maximum)
        orders.append(ReplayOrder(side, amount, order_type, limit if order_type is OrderType.LIMIT else None))
        remaining -= amount
    kwargs = {'capital_mode': 'full_available_cash'}
    target = float(effective) if orders else float(actual > 0)
    if mode == 'signal_cash_fraction' and after is not None:
        kwargs = {'capital_mode': mode, 'cycle_before': previous, 'cycle_after': after}
        target = float(effective)
    decision = AccountDecision.from_facts(target, reason,
        facts={**facts, 'signal_target': int(signal_target), 'locked_quantity': target_lock,
               'actual_quantity': actual, 'raw_reference': reference,
               'fee_rate': float(fee), 'entry_limit': price},
        next_watch='下一信号日及订单确认成交', orders=tuple(orders), **kwargs)
    return decision, target_lock
