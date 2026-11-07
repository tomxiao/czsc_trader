"""Shared causal order planning for all execution channels."""
from decimal import Decimal, ROUND_FLOOR
import math
from ..contracts import AccountSnapshot, AccountExecutionPlan, ReplayPoint, ReplayOrder, SellRemainderPolicy
from ..session_contracts import OrderSide, OrderType
from ..policy import ResearchExecutionSpec
from ..identity import equity_hash
from .intent import TradeIntent

def plan_account_decision(decision, point, account, reference, spec, *, owner, implementation, fee_rate, sell_remainder_policy, suppressed=False):
    """Resolve a desired fraction using confirmed cash, legal units and price tick."""
    if type(decision) is not TradeIntent:
        raise TypeError('account planning requires TradeIntent')
    if type(point) is not ReplayPoint or type(account) is not AccountSnapshot or type(spec) is not ResearchExecutionSpec:
        raise TypeError('account planning requires typed point, account and execution contract')
    spec.require_instrument(account.instrument)
    if account.currency!=spec.account.currency:
        raise ValueError('account currency differs from execution contract')
    if type(reference) not in (float,int) or not math.isfinite(reference) or reference<=0:
        raise ValueError('planning reference must be finite positive price')
    if type(fee_rate) not in (float,int) or not math.isfinite(fee_rate) or not 0<=fee_rate<1:
        raise ValueError('planning fee must be finite in [0,1)')

    if type(sell_remainder_policy) is not SellRemainderPolicy:
        raise TypeError('automatic planning requires declared sell remainder policy')
    if type(suppressed) is not bool:
        raise TypeError('suppressed observation must be explicit bool')
    if suppressed:
        identity = equity_hash({'owner': owner, 'point': repr(point),
                               'revision': account.revision, 'suppressed': True})
        return AccountExecutionPlan(identity, owner, point, account.revision, account.quantity,
            evidence={'signal_status': 'SUPPRESSED_UNOBSERVED_BAR', 'target': float(account.quantity > 0),
                      'sizing': 'EXPLICIT_ORDERS', 'planning_mode': 'EXPLICIT_ORDERS',
                      'reference_price': reference, 'specification_hash': spec.fingerprint,
                      'fee_rate': fee_rate})
    step = spec.quantity_step
    orders, legs = decision.orders, decision.legs
    mode = 'DEPENDENCY_LEGS' if legs else 'EXPLICIT_ORDERS' if orders else 'TARGET_FRACTION'
    desired = None
    if not orders and not legs:
        if decision.capital_mode == 'full_available_cash' and decision.target not in (0,1):
            raise ValueError('full_available_cash supports flat/long only')
        equity = Decimal(str(account.cash)) + Decimal(str(account.receivable)) + Decimal(account.quantity) * Decimal(str(reference))
        desired = int(equity * Decimal(str(decision.target)) / Decimal(str(reference)) / step) * step
        if decision.capital_mode == 'full_available_cash' and account.quantity and decision.target:
            desired = account.quantity
        if decision.capital_mode == 'signal_cash_fraction':
            budget = decision.cycle_after or decision.cycle_before
            if budget is None:
                raise ValueError('cycle allocation requires explicit budget facts')
            desired = budget.target_quantity if decision.target else 0
        if desired > account.quantity:
            tick = Decimal(str(spec.price_tick))
            price = ((Decimal(str(reference)) * (1+Decimal(str(spec.buy_premium))) / tick).to_integral_value(rounding=ROUND_FLOOR) * tick)
            available = Decimal(str(account.available_cash))
            if decision.capital_mode == 'signal_cash_fraction':
                available = min(available, budget.cash_budget-budget.buy_cost_including_fees)
            affordable = max(0, int(available / (price * (1+Decimal(str(fee_rate)))) / step) * step)
            amount = min(desired-account.quantity, affordable) // step * step
            if amount:
                orders = (ReplayOrder(OrderSide.BUY, amount, OrderType.LIMIT, float(price)),)
        elif desired < account.quantity:
            amount = min(account.quantity-desired, account.sellable_quantity)
            # Partial reductions use the declared unit. Full liquidation may
            # legally dispose of an integer split remainder under an explicit rule.
            if amount < account.quantity or sell_remainder_policy is SellRemainderPolicy.STRICT_STEP:
                amount = amount // step * step
            if amount:
                orders = (ReplayOrder(OrderSide.SELL, amount, OrderType.MARKET),)
    instructions = orders if orders else tuple(leg.order for leg in legs)
    target = account.quantity + sum(order.quantity * (1 if order.side is OrderSide.BUY else -1) for order in instructions)
    if target < 0:
        raise ValueError('orders exceed confirmed holdings')
    evidence = {'planning_mode': mode, 'sizing': 'TARGET_FRACTION' if mode == 'TARGET_FRACTION' else 'EXPLICIT_ORDERS',
                'desired_quantity': desired, 'target': float(decision.target), 'explanation': decision.explanation.to_dict(),
                'reference_price': reference, 'implementation': implementation, 'fee_rate': fee_rate,
                'specification_hash': spec.fingerprint}
    identity = equity_hash({'owner': owner, 'point': {'observed_through': point.observed_through,
        'decision_at': point.decision_at, 'start': point.execution_start, 'end': point.execution_end},
        'revision': account.revision, 'target': target, 'orders': [(x.side.value,x.quantity,x.order_type.value,x.limit_price) for x in orders],
        'legs': [(x.sequence,x.checkpoint,x.submit_after,x.submit_before,x.order.side.value,x.order.quantity,
                  x.order.order_type.value,x.order.limit_price,x.dependency_sequence,x.dependency_required_status) for x in legs],
        'capital_mode': decision.capital_mode,
        'cycle_before': None if decision.cycle_before is None else repr(decision.cycle_before),
        'cycle_after': None if decision.cycle_after is None else repr(decision.cycle_after), 'evidence':evidence})
    return AccountExecutionPlan(identity, owner, point, account.revision, target, orders, legs,
        decision.capital_mode, decision.cycle_before, decision.cycle_after, evidence)
