from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_FLOOR
from strategy_runtime.contracts import OrderSide, OrderType
from strategy_runtime.replay_contracts import ReplayOrder


def step(ctx, state):
    bars = ctx.history.to_frame(tail=66)
    close = bars["Close"]
    dates = [stamp.astimezone(ZoneInfo("America/New_York")) for stamp in bars["Date"]]
    active = ctx.position.active
    orders = ()
    if active is not None:
        held = sum(stamp >= active.entry_interval.start for stamp in dates)
        month_only = state.cycle.values.get("month_only")
        extended = state.cycle.values.get("extended")
        if held == 5:
            extended = bool(close.iloc[-1] * active.quantity > active.buy_cost)
        time_stop = bool(held == 2 and close.iloc[-1] <= close.iloc[-2] and close.iloc[-1] * active.quantity <= active.buy_cost)
        target = float(held < (10 if extended else 5) and not time_stop)
        facts = {"completed_holding_sessions": held, "month_only": month_only, "extended": extended, "time_stop": time_stop}
    else:
        ret = close.pct_change()
        r5 = close.pct_change(5)
        sigma5 = ret.shift().rolling(60).std() * 5 ** .5
        m007 = bool(ret.iloc[-3:].lt(0).all())
        m015 = bool(r5.iloc[-1] > sigma5.iloc[-1] and r5.iloc[-2] <= sigma5.iloc[-2]
                    and close.iloc[-1] > close.iloc[-20:].mean())
        m022 = bool(dates[-1].month != dates[-2].month)
        facts = {"m007": m007, "m015": m015, "m022": m022}
        target = float(m007 or m015 or m022)
        month_only = m022 and not (m007 or m015)
        extended = False
        fraction = Decimal("0.5") if m015 and not (m007 or m022) else Decimal(".75") if m022 and not (m007 or m015) else Decimal(1)
        if target and fraction < 1:
            tick = Decimal("0.01")
            reference = Decimal(str(float(close.iloc[-1]))) * Decimal(str(ctx.portfolio.reference_price_scale))
            limit = (reference * Decimal("1.01") / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
            half_cash = Decimal(str(ctx.account.available_cash)) * fraction
            quantity = int(half_cash / (limit * Decimal("1.001")))
            if quantity:
                orders = (ReplayOrder(OrderSide.BUY, quantity, OrderType.LIMIT, float(limit)),)
            else:
                target = 0.0
    return AccountStepResult(AccountDecision.from_facts(target, "five sessions with one profitable month-only extension",
        facts=facts, orders=orders, next_watch="next completed daily bar", capital_mode="full_available_cash"),
        cycle_values=StateRecord((("month_only", month_only), ("extended", extended))) if active is not None or target else None)
