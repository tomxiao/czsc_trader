from decimal import Decimal, ROUND_FLOOR
from strategy_runtime.contracts import OrderSide, OrderType
from strategy_runtime.replay_contracts import ReplayOrder
import numpy as np
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


def step(ctx, state):
    raw = ctx.history.to_frame(tail=63)
    mu = ctx.auxiliary_histories['mu_hfq'].to_frame(tail=63)
    sector = ctx.auxiliary_histories['soxx_hfq'].to_frame(tail=63)
    assert mu.Date.tolist() == sector.Date.tolist() == raw.Date.tolist()
    assert max(mu.AvailableDate.max(), sector.AvailableDate.max()) <= ctx.point.decision_at
    p = ctx.parameters
    price = float(mu.Close.iloc[-1])
    m = np.diff(np.log(mu.Close.to_numpy()))
    s = np.diff(np.log(sector.Close.to_numpy()))
    beta = float(np.cov(m[-62:-2], s[-62:-2], ddof=1)[0, 1] / np.var(s[-62:-2], ddof=1))
    total = float(m[-2:].sum())
    common = beta * float(s[-2:].sum())
    two_down = bool(mu.Close.iloc[-1] < mu.Close.iloc[-2] < mu.Close.iloc[-3])
    common_group = p['common_share'] is None or common < p['common_share'] * total
    allocation = p['common_budget'] if common_group else p['other_budget']
    enter = two_down and allocation > 0
    orders = ()
    active = ctx.position.active
    if active is None:
        anchor = price
        target, reason = float(enter), 'entry' if enter else 'no opportunity'
        if enter and allocation < 1:
            tick = Decimal('0.01')
            reference = Decimal(str(float(raw.Close.iloc[-1]))) * Decimal(str(ctx.portfolio.reference_price_scale))
            limit = (reference * Decimal('1.01') / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
            cash = Decimal(str(ctx.account.available_cash)) * Decimal(str(allocation))
            quantity = int(cash / (limit * Decimal('1.001')))
            if quantity:
                orders = (ReplayOrder(OrderSide.BUY, quantity, OrderType.LIMIT, float(limit)),)
            else:
                target = 0.
    else:
        anchor = state.cycle.values.get('anchor')
        held = sum(t >= active.entry_interval.start for t in raw.Date)
        done = held >= p['max_hold'] or (held >= p['review_after'] and price <= anchor)
        target, reason = float(not done), 'complete' if done else 'hold'
    return AccountStepResult(AccountDecision.from_facts(target, reason,
        facts={'anchor': anchor, 'observed_signal': enter, 'beta': beta,
               'common2': common, 'total2': total, 'price_basis': 'HFQ',
               'common_group': common_group, 'entry_allocation': allocation},
        next_watch='next completed daily bar', capital_mode='full_available_cash', orders=orders),
        cycle_values=StateRecord((('anchor', anchor),)) if active is not None or target else None)
