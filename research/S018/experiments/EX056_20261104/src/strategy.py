from decimal import Decimal, ROUND_FLOOR
import numpy as np
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.contracts import OrderSide, OrderType
from strategy_runtime.replay_contracts import ReplayOrder
from strategy_runtime.equity_replay import StateRecord


def buy_order(ctx, raw_close, cash):
    reference = Decimal(str(raw_close)) * Decimal(str(ctx.portfolio.reference_price_scale))
    limit = (reference * Decimal('1.01') / Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR) * Decimal('.01')
    cash = min(Decimal(str(ctx.account.available_cash)), max(Decimal(0), cash))
    quantity = int(cash / (limit * Decimal('1.001')))
    return (ReplayOrder(OrderSide.BUY, quantity, OrderType.LIMIT, float(limit)),) if quantity else ()


def step(ctx, state):
    raw = ctx.history.to_frame(tail=63)
    mu = ctx.auxiliary_histories['mu_hfq'].to_frame(tail=63)
    sector = ctx.auxiliary_histories['soxx_hfq'].to_frame(tail=63)
    assert mu.Date.tolist() == sector.Date.tolist() == raw.Date.tolist()
    assert max(mu.AvailableDate.max(), sector.AvailableDate.max()) <= ctx.point.decision_at
    p=ctx.parameters
    price, sector_price = float(mu.Close.iloc[-1]), float(sector.Close.iloc[-1])
    m,s = np.diff(np.log(mu.Close.to_numpy())),np.diff(np.log(sector.Close.to_numpy()))
    beta=float(np.cov(m[-62:-2],s[-62:-2],ddof=1)[0,1]/np.var(s[-62:-2],ddof=1))
    common=beta*float(s[-2:].sum())
    total=float(m[-2:].sum())
    group=common < p['common_share']*total
    allocation=p['common_budget'] if group else p['other_budget']
    enter=bool(mu.Close.iloc[-1] < mu.Close.iloc[-2] < mu.Close.iloc[-3])
    active=ctx.position.active
    orders=()
    confirmation=False
    if active is None:
        anchor,sector_anchor=price,sector_price
        budget=float(Decimal(str(ctx.account.available_cash))*Decimal(str(allocation)))
        target,reason=float(enter),'entry' if enter else 'no opportunity'
        if enter:
            orders=buy_order(ctx,float(raw.Close.iloc[-1]),Decimal(str(budget))*Decimal(str(p['initial_fraction'])))
            if not orders:
                target=0.
    else:
        anchor=state.cycle.values.get('anchor')
        sector_anchor=state.cycle.values.get('sector_anchor')
        budget=state.cycle.values.get('entry_budget')
        held=sum(t >= active.entry_interval.start for t in raw.Date)
        done=held >= p['max_hold'] or (held >= p['review_after'] and price <= anchor)
        target,reason=float(not done),'complete' if done else 'hold'
        mode=p['add_mode']
        if mode=='repair':
            confirmation=price > anchor
        elif mode=='repair_both':
            confirmation=price > anchor and sector_price > sector_anchor
        elif mode=='scheduled':
            confirmation=True
        elif mode=='weakness':
            confirmation=price <= anchor
        else:
            assert mode=='never'
        if not done and active.buy_fills==1 and p['initial_fraction']<1 and held >= p['earliest_add'] and confirmation:
            remaining=Decimal(str(budget))-Decimal(str(active.buy_cost))
            orders=buy_order(ctx,float(raw.Close.iloc[-1]),remaining)
            if orders:
                reason='add after '+mode
    return AccountStepResult(AccountDecision.from_facts(target,reason,
        facts={'anchor':anchor,'sector_anchor':sector_anchor,'entry_budget':budget,
            'observed_signal':enter,'common_group':group,'entry_allocation':allocation,
            'confirmation':confirmation,'initial_fraction':p['initial_fraction']},
        next_watch='next completed daily bar',capital_mode='full_available_cash',orders=orders),
        cycle_values=StateRecord((('anchor',anchor),('sector_anchor',sector_anchor),('entry_budget',budget)))
            if active is not None or target else None)
