"""Shared causal order planning for every execution channel."""
from dataclasses import replace
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_FLOOR
import math
from zoneinfo import ZoneInfo
from ..contracts import (AccountSnapshot, AccountExecutionPlan, ReplayPoint,
                         ReplayOrder, ReplayLeg, SellRemainderPolicy, CycleBudget)
from ..entry_cycle import EntryCyclePhase
from ..daily_execution import DAILY_TARGET_TRIGGER, INTERVAL_TARGET_TRIGGER, TARGET_TRIGGERS, ENTRY_CASH_FRACTION, DailyExecutionTrigger, PreviousDailyExecution
from ..instruments import BarFrequency
from ..execution_intervals import ExecutionInterval
from ..session_contracts import OrderSide, OrderType
from ..policy import ResearchExecutionSpec, ExecutionPolicy
from ..identity import equity_hash, _thaw_json
from .intent import TradeIntent
from .session_rules import ExecutionRuleInput, build_frozen_execution_plan
from .result import PlanningResult, PlanningStatus, PlanningConstraint


def _order(record):
    side, kind = OrderSide(record['side']), OrderType(record['order_type'])
    quantity = int(record['quantity'])
    return ReplayOrder(side, quantity, kind, float(record['limit_price']) if kind is OrderType.LIMIT else None)


def _buy_limit(reference, spec):
    tick = Decimal(str(spec.price_tick))
    premium = Decimal(str(spec.buy_premium))
    return (Decimal(str(reference)) * (1 + premium) / tick).to_integral_value(rounding=ROUND_FLOOR) * tick


def plan_account_decision(decision, point, account, reference, spec, *, owner,
                          implementation, fee_rate, sell_remainder_policy,
                          execution_policy, cycle_budget=None, locked_quantity=None,
                          suppressed=False, previous_daily_execution=None, execution_interval=None):
    """Translate position intent to channel-owned funding, quotes and orders.

    The reference is explicitly prepared in the channel's execution price basis.
    No pricing, sizes, orders or mutable budgets are read from the explanation.
    """
    if type(decision) is not TradeIntent:
        raise TypeError('account planning requires TradeIntent')
    if type(point) is not ReplayPoint or type(account) is not AccountSnapshot or type(spec) is not ResearchExecutionSpec:
        raise TypeError('account planning requires typed point, account and execution contract')
    if type(execution_policy) is not ExecutionPolicy:
        raise TypeError('account planning requires a frozen ExecutionPolicy')
    if cycle_budget is not None and type(cycle_budget) is not CycleBudget:
        raise TypeError('account cycle budget must be typed')
    if locked_quantity is not None and (type(locked_quantity) is not int or locked_quantity <= 0):
        raise ValueError('locked quantity requires positive integer units')
    spec.require_instrument(account.instrument)
    if account.currency != spec.account.currency:
        raise ValueError('account currency differs from execution contract')
    if type(reference) not in (float,int) or not math.isfinite(reference) or reference <= 0:
        raise ValueError('planning reference must be finite positive price')
    if type(fee_rate) not in (float,int) or not math.isfinite(fee_rate) or not 0 <= fee_rate < 1:
        raise ValueError('planning fee must be finite in [0,1)')
    if type(sell_remainder_policy) is not SellRemainderPolicy:
        raise TypeError('automatic planning requires declared sell remainder policy')
    if type(suppressed) is not bool:
        raise TypeError('suppressed observation must be explicit bool')
    settings = _thaw_json(execution_policy.settings)
    kind = execution_policy.policy_type
    trigger = None
    policy_trigger = settings.get('execution_trigger')
    if policy_trigger == INTERVAL_TARGET_TRIGGER:
        if (type(execution_interval) is not ExecutionInterval
                or (execution_interval.window.start, execution_interval.end)
                    != (point.execution_start, point.execution_end)
                or point.decision_at < execution_interval.start):
            raise ValueError('plan requires the declared execution interval and causal decision time')
    if policy_trigger in TARGET_TRIGGERS:
        zone = ZoneInfo(account.instrument.timezone)
        session = point.execution_start.astimezone(zone).date()
        if (point.session_id != session.isoformat() or point.execution_end.astimezone(zone).date() != session
                or (policy_trigger == DAILY_TARGET_TRIGGER and spec.decision_clock is not BarFrequency.DAILY)):
            raise ValueError('target execution window differs from the declared market session or clock')
        if previous_daily_execution is not None and type(previous_daily_execution) is not PreviousDailyExecution:
            raise TypeError('daily target execution requires typed previous execution facts')
        if not suppressed:
            trigger = (DailyExecutionTrigger.INITIAL_TARGET if previous_daily_execution is None
                       else previous_daily_execution.trigger(decision.target))
    elif previous_daily_execution is not None:
        raise ValueError('previous execution requires a declared target trigger')
    orders, legs = (), ()
    before = after = cycle_budget
    mode, desired = 'target_equity_fraction', account.quantity
    lock = locked_quantity
    planning_mode = 'TARGET_FRACTION'
    reasons = []
    entry_cash = None
    if settings.get('capital_mode') == ENTRY_CASH_FRACTION:
        if cycle_budget is not None:
            raise ValueError('entry cash allocation cannot inherit a fixed-quantity cycle budget')
        if account.quantity:
            entry_cash = None if previous_daily_execution is None else previous_daily_execution.entry_cash
        elif decision.target and not suppressed:
            entry_cash = Decimal(str(account.available_cash))
    if suppressed or trigger is DailyExecutionTrigger.UNCHANGED_TARGET:
        if cycle_budget is not None:
            mode = 'signal_cash_fraction'
        elif settings.get('capital_mode') == ENTRY_CASH_FRACTION:
            mode = ENTRY_CASH_FRACTION
        planning_mode = 'EXPLICIT_ORDERS'
    elif kind == 'TARGET_POSITION':
        mode = settings.get('capital_mode', 'target_equity_fraction')
        if cycle_budget is not None:
            raise ValueError('TARGET_POSITION requires an explicit supported capital mode without cycle budget')
        if mode == 'full_available_cash' and decision.target not in (0,1):
            raise ValueError('full_available_cash supports flat/long only')
        step = spec.quantity_step
        price = None
        if decision.target == 0:
            desired = 0
        elif mode == ENTRY_CASH_FRACTION:
            # Positive targets are cumulative spending limits for staged entry.
            prior_target = 0 if previous_daily_execution is None else previous_daily_execution.target
            if not account.quantity or decision.target >= prior_target:
                if entry_cash is None:
                    raise ValueError('held position requires its original entry cash baseline')
                spent = previous_daily_execution.buy_cost if account.quantity else Decimal(0)
                remaining = max(Decimal(0), entry_cash * Decimal(str(decision.target)) - spent)
                price = _buy_limit(reference, spec)
                if price > 0:
                    desired += int(remaining / (price * (1 + Decimal(str(fee_rate)))) / step) * step
                else:
                    reasons.append(PlanningConstraint.BELOW_PRICE_TICK)
        else:
            quote = Decimal(str(reference))
            equity = Decimal(str(account.cash)) + Decimal(str(account.receivable)) + account.quantity * quote
            desired = int(equity * Decimal(str(decision.target)) / quote / step) * step
        if mode == 'full_available_cash' and account.quantity and decision.target:
            desired = account.quantity
        if decision.target > 0 and not account.quantity and desired == 0 and not reasons:
            reasons.append(PlanningConstraint.BELOW_MINIMUM_UNIT)
        if desired > account.quantity:
            if price is None:
                price = _buy_limit(reference, spec)
            if price <= 0:
                reasons.append(PlanningConstraint.BELOW_PRICE_TICK)
            affordable = (max(0, int(Decimal(str(account.available_cash)) / (price * (1+Decimal(str(fee_rate)))) / step) * step)
                          if price > 0 else 0)
            amount = min(desired-account.quantity, affordable) // step * step
            if price > 0 and amount < desired-account.quantity:
                reasons.append(PlanningConstraint.INSUFFICIENT_CASH)
            if amount:
                orders = (ReplayOrder(OrderSide.BUY, amount, OrderType.LIMIT, float(price)),)
        elif desired < account.quantity:
            amount = min(account.quantity-desired, account.sellable_quantity)
            if amount < account.quantity or sell_remainder_policy is SellRemainderPolicy.STRICT_STEP:
                amount = amount // step * step
            if account.sellable_quantity < account.quantity-desired:
                reasons.append(PlanningConstraint.INSUFFICIENT_SELLABLE_QUANTITY)
            if not amount and not reasons:
                reasons.append(PlanningConstraint.BELOW_MINIMUM_UNIT)
            if amount:
                orders = (ReplayOrder(OrderSide.SELL, amount, OrderType.MARKET),)
    elif kind in {'FROZEN_RULE', 'INTRADAY_OVERLAY'}:
        planning_mode = 'EXPLICIT_ORDERS'
        mode = 'full_available_cash'
        cash = Decimal(str(account.available_cash))
        target = decision.target
        if kind == 'FROZEN_RULE':
            instrument = settings['instrument']
            if (int(instrument['lot_size']), float(instrument['price_tick'])) != (spec.quantity_step, spec.price_tick):
                raise ValueError('frozen execution units differ from channel specification')
            capital = settings['capital']
            capital['fee_rate'] = fee_rate
            original_mode = capital['mode']
            if original_mode == 'target_equity_fraction':
                mode = original_mode
            elif original_mode == 'signal_cash_fraction':
                mode = original_mode
                if cycle_budget is None and account.quantity:
                    raise ValueError('new cycle allocation requires flat confirmed account')
                if cycle_budget is not None:
                    lock = cycle_budget.target_quantity
                    after = replace(cycle_budget, phase=EntryCyclePhase.EXITING) if not target else cycle_budget
                    cash = min(cash, max(Decimal(0), after.cash_budget-after.buy_cost_including_fees)) if after.phase is EntryCyclePhase.ACTIVE else cash
                    target = float(after.phase is EntryCyclePhase.ACTIVE)
                else:
                    cash *= Decimal(str(target))
                    target = float(target > 0)
                capital.update(mode='available_cash_fraction', allocation_fraction=1.)
        else:
            settings['one_way_cost'] = fee_rate
            if int(settings['lot_size']) != spec.quantity_step:
                raise ValueError('overlay quantity unit differs from channel specification')
        request = ExecutionRuleInput(kind, settings, {'cycle_target_quantity':lock},
            float(cash), account.quantity, target, reference, reference)
        raw = build_frozen_execution_plan(request)
        lock = int(raw['cycle_target_quantity']) or None
        desired = int(raw['target_quantity'])
        if kind == 'FROZEN_RULE':
            desired = int(raw['cycle_target_quantity']) if target else 0
        if raw.get('planning_blocked_reason'):
            reasons.append(PlanningConstraint(raw['planning_blocked_reason']))
        if mode == 'signal_cash_fraction' and before is None and target:
            if lock:
                after = CycleBudget(equity_hash({'owner':owner,'point':repr(point)}), lock,
                    Decimal(str(decision.target)), cash, Decimal(0), EntryCyclePhase.ACTIVE)
        if target > 0 and not account.quantity and not raw.get('orders') and not raw.get('plan_legs'):
            reasons.append(PlanningConstraint.BELOW_MINIMUM_UNIT)
        if kind == 'FROZEN_RULE' and int(raw['target_quantity']) < desired:
            reasons.append(PlanningConstraint.INSUFFICIENT_CASH)
        sellable = account.sellable_quantity
        selected = []
        for row in raw.get('orders',()):
            order = _order(row)
            if order.side is OrderSide.SELL:
                amount = min(order.quantity, sellable)
                if amount < account.quantity or sell_remainder_policy is SellRemainderPolicy.STRICT_STEP:
                    amount = amount // spec.quantity_step * spec.quantity_step
                if amount < order.quantity:
                    reasons.append(PlanningConstraint.INSUFFICIENT_SELLABLE_QUANTITY)
                if not amount:
                    continue
                sellable -= amount
                order = replace(order, quantity=amount)
            selected.append(order)
        orders = tuple(selected)
        if raw.get('plan_legs'):
            zone = ZoneInfo('Asia/Shanghai' if spec.market_id.value == 'CN' else 'America/New_York')
            session = point.execution_start.astimezone(zone).date()
            legs = tuple(ReplayLeg(int(row['sequence']), _order(row['order']),
                row['checkpoint'], datetime.combine(session,time.fromisoformat(row['submit_after']),zone),
                datetime.combine(session,time.fromisoformat(row['submit_before']),zone)+timedelta(microseconds=1),
                row.get('dependency_sequence'),row.get('dependency_required_status')) for row in raw['plan_legs'])
            planning_mode = 'DEPENDENCY_LEGS'
            if sum(leg.order.quantity for leg in legs if leg.order.side is OrderSide.SELL) > account.sellable_quantity:
                # Do not buy a rotation leg whose required exit lacks confirmed inventory.
                legs = ()
                reasons.extend((PlanningConstraint.INSUFFICIENT_SELLABLE_QUANTITY,
                                PlanningConstraint.DEPENDENCY_UNAVAILABLE))
    else:
        raise ValueError('unsupported execution policy: '+kind)
    instructions = orders if orders or not legs else tuple(leg.order for leg in legs)
    target_quantity = account.quantity
    if instructions:
        target_quantity += sum(order.quantity * (1 if order.side is OrderSide.BUY else -1) for order in instructions)
    if target_quantity < 0:
        raise ValueError('orders exceed confirmed holdings')
    reasons = tuple(dict.fromkeys(reasons))
    status = (PlanningStatus.SUPPRESSED if suppressed else
              PlanningStatus.CONSTRAINED if reasons and instructions else
              PlanningStatus.BLOCKED if reasons else
              PlanningStatus.READY if instructions else PlanningStatus.NO_CHANGE)
    planning_result = PlanningResult(status,reasons,desired,target_quantity)
    evidence = {'planning_mode':planning_mode, 'sizing':'TARGET_FRACTION' if planning_mode=='TARGET_FRACTION' else 'EXPLICIT_ORDERS',
        'desired_quantity':desired, 'target':float(decision.target), 'explanation':decision.explanation.to_dict(),
        'reference_price':reference, 'implementation':implementation, 'fee_rate':fee_rate,
        'specification_hash':spec.fingerprint, 'locked_quantity':lock,
        'planning_result':planning_result.to_dict(),
        'execution_policy':{'policy_type':kind,'settings':_thaw_json(execution_policy.settings)}}
    if suppressed:
        evidence['signal_status'] = 'SUPPRESSED_UNOBSERVED_BAR'
    if trigger is not None:
        evidence['execution_trigger'] = trigger.value
    if policy_trigger == INTERVAL_TARGET_TRIGGER:
        evidence['execution_interval'] = {
            'start': execution_interval.start.isoformat(), 'end': execution_interval.end.isoformat(),
            'submit_after': execution_interval.window.start.isoformat(),
        }
    if entry_cash is not None:
        evidence['entry_cash'] = str(entry_cash)
    identity = equity_hash({'owner':owner,'point':repr(point),'revision':account.revision,
        'orders':repr(orders),'legs':repr(legs),'cycle_before':repr(before),'cycle_after':repr(after),'evidence':evidence})
    return AccountExecutionPlan(identity, owner, point, account.revision, target_quantity,
                                orders, legs, mode, before, after, evidence)
