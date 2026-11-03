from decimal import Decimal, ROUND_FLOOR
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.contracts import OrderSide, OrderType
from strategy_runtime.equity_replay import StateRecord
from strategy_runtime.replay_contracts import ReplayOrder


def step(ctx, state):
    bars = ctx.history.to_frame(tail=21)
    c = bars["Close"]
    o = bars["Open"]
    h = bars["High"]
    l = bars["Low"]
    price = float(c.iloc[-1])
    prev = float(c.iloc[-2])
    opening = float(o.iloc[-1])
    high = float(h.iloc[-1])
    low = float(l.iloc[-1])
    midpoint = (high + low) / 2
    prior_range = float((h-l).iloc[-11:-1].median())
    p = ctx.parameters
    down = price < prev
    recovered = price > midpoint
    oversold = down and prev - low >= prior_range
    trend = prev > float(c.iloc[-21:-1].median())
    direction = price > prev and recovered
    accelerating = direction and price > float(h.iloc[-2])
    gap_down = opening < prev
    gap_up = opening > prev
    lower_close = prev < float(c.iloc[-3]) and down
    signals = {
        "oversold": oversold, "absorb": oversold and recovered,
        "weak": oversold and not recovered, "two_down": lower_close,
        "trend_pullback": trend and lower_close,
        "strength": direction, "break": accelerating,
        "strength_no_break": direction and not accelerating,
        "gap_repair": gap_down and price > prev,
        "gap_fail": gap_up and price < opening and direction,
        "trend_strength": direction and trend,
        "pullback_or_strength": (trend and lower_close) or accelerating,
        "trend_absorb": oversold and recovered and trend,
    }
    enter = signals[p["entry"]]
    active = ctx.position.active
    orders = ()
    if active is None:
        floor = low
        anchor = prev
        reason = "entry" if enter else "no opportunity"
        target = float(enter)
        if enter and p["allocation"] < 1:
            tick = Decimal("0.01")
            reference = Decimal(str(price)) * Decimal(str(ctx.portfolio.reference_price_scale))
            limit = (reference * Decimal("1.01") / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
            cash = Decimal(str(ctx.account.available_cash)) * Decimal(str(p["allocation"]))
            quantity = int(cash / (limit * Decimal("1.001")))
            if quantity:
                orders = (ReplayOrder(OrderSide.BUY, quantity, OrderType.LIMIT, float(limit)),)
            else:
                target = 0.
    else:
        floor = state.cycle.values.get("floor")
        anchor = state.cycle.values.get("anchor")
        held = sum(stamp >= active.entry_interval.start for stamp in bars["Date"])
        mode = p["exit"]
        if mode == "repair":
            done = price >= anchor
            failed = price < floor
        elif mode == "trend":
            done = False
            failed = price < float(l.iloc[-3:-1].min())
        elif mode == "follow":
            done = False
            failed = price < prev and price < midpoint
        else:
            done = held >= int(mode)
            failed = False
        reason = "failed" if failed else "complete" if done else "hold"
        target = float(reason == "hold")
    return AccountStepResult(AccountDecision.from_facts(target, reason,
        facts={"anchor": anchor, "floor": floor, "observed_signal": enter},
        next_watch="next complete daily bar", capital_mode="full_available_cash", orders=orders),
        cycle_values=StateRecord((("anchor", anchor), ("floor", floor))) if active is not None or target else None)
