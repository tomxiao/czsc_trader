from decimal import Decimal, ROUND_FLOOR
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord
from strategy_runtime.replay_contracts import ReplayOrder
from strategy_runtime.contracts import OrderSide, OrderType


def step(ctx, state):
    bars = ctx.history.to_frame()
    price = float(bars['Close'].iloc[-1])
    horizon = int(ctx.parameters['exit'])
    phase = int(ctx.parameters['entry'].split('_')[1])
    enter = (len(bars)-1) % (horizon+1) == phase
    active = ctx.position.active
    orders = ()
    if active is None:
        anchor, floor = price, float(bars['Low'].iloc[-1])
        target = float(enter)
        reason = 'entry' if enter else 'no opportunity'
        if enter:
            raw = Decimal(str(price))*Decimal(str(ctx.portfolio.reference_price_scale))
            limit = (raw*Decimal('1.01')/Decimal('0.01')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('0.01')
            orders = (ReplayOrder(OrderSide.BUY,1,OrderType.LIMIT,float(limit)),)
    else:
        anchor = state.cycle.values.get('anchor')
        floor = state.cycle.values.get('floor')
        held = sum(t >= active.entry_interval.start for t in bars['Date'])
        target = float(held < horizon)
        reason = 'hold' if target else 'complete'
    return AccountStepResult(
        AccountDecision.from_facts(target,reason,
            facts={'observed_signal':enter,'anchor':anchor,'floor':floor},
            next_watch='next complete daily bar',capital_mode='full_available_cash',orders=orders),
        cycle_values=StateRecord((('anchor',anchor),('floor',floor))) if active is not None or target else None)
