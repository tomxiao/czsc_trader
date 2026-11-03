from decimal import Decimal, ROUND_FLOOR
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.contracts import OrderSide, OrderType
from strategy_runtime.equity_replay import StateRecord
from strategy_runtime.replay_contracts import ReplayOrder


def step(ctx, state):
    bars = ctx.history.to_frame(tail=63)
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
    background = c.iloc[:-2]
    advance10 = float(background.iloc[-1]) > float(background.iloc[-11])
    advance20 = float(background.iloc[-5:].median()) > float(background.iloc[-15:-5].median())
    slope = float(background.iloc[-5:].median()) > float(background.iloc[-10:-5].median())
    price_support = price >= float(background.iloc[-10:].median())
    no_break = price > float(l.iloc[-12:-2].min())
    contained = float(background.iloc[-1]) - price < prior_range
    recent_floor = price > float(c.iloc[-7:-2].min())
    medium_up = float(background.iloc[-1]) > float(background.iloc[-21])
    long_up = float(background.iloc[-1]) > float(background.iloc[-61])
    long_center_up = float(background.iloc[-20:].median()) > float(background.iloc[-60:-20].median())
    slowdown = price / prev > prev / float(c.iloc[-3])
    reject_lows = price > midpoint
    higher_low = low >= float(l.iloc[-2])
    overnight = opening < prev and price > opening
    signals.update({name: lower_close and flag for name, flag in {
        "medium_up": medium_up, "medium_down": not medium_up,
        "long_up": long_up, "long_down": not long_up,
        "long_center_up": long_center_up, "long_center_down": not long_center_up,
        "slowdown": slowdown, "acceleration": not slowdown,
        "reject_lows": reject_lows, "accept_lows": not reject_lows,
        "higher_low": higher_low, "lower_low": not higher_low,
        "intraday_repair": overnight, "not_intraday_repair": not overnight,

        "up10": advance10, "not_up10": not advance10,
        "up_center": advance20, "not_up_center": not advance20,
        "up_recent_center": slope, "not_up_recent_center": not slope,
        "support": price_support, "not_support": not price_support,
        "no_break": no_break, "breakdown": not no_break,
        "contained": contained, "not_contained": not contained,
        "recent_floor": recent_floor, "not_recent_floor": not recent_floor,
        "up10_support": advance10 and price_support,
        "up10_no_break": advance10 and no_break,
        "up_center_no_break": advance20 and no_break,
    }.items()})
    delayed = prev < float(c.iloc[-3]) < float(c.iloc[-4])
    signals.update({
        "delay_all": delayed,
        "delay_up": delayed and price > prev,
        "delay_no_up": delayed and price <= prev,
        "delay_up_strong": delayed and price > prev and price > midpoint,
        "delay_up_weak": delayed and price > prev and price <= midpoint,
    })
    enter = signals[p["entry"]]
    active = ctx.position.active
    orders = ()
    if active is None:
        floor = low
        anchor = price if p["exit"] == "signal_line" else float(c.iloc[-3]) if p["exit"] == "predecline_line" else prev
        if p["entry"].startswith("delay_"):
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
        elif mode in ("signal_line", "predecline_line"):
            done = held >= 6 or (held >= 3 and price <= anchor)
            failed = False
        elif mode in ("winner", "cut", "winner_cut", "winner_trail"):
            profitable = price * active.quantity > active.buy_cost
            done = held >= 6 if mode != "cut" else held >= 3
            if mode != "cut":
                done = done or (held >= 3 and not profitable)
            failed = mode in ("cut", "winner_cut") and held == 2 and price <= prev and not profitable
            if mode == "winner_trail" and held >= 3:
                failed = price < float(l.iloc[-3:-1].min())
        else:
            done = held >= int(mode)
            failed = False
        reason = "failed" if failed else "complete" if done else "hold"
        target = float(reason == "hold")
    return AccountStepResult(AccountDecision.from_facts(target, reason,
        facts={"anchor": anchor, "floor": floor, "observed_signal": enter},
        next_watch="next complete daily bar", capital_mode="full_available_cash", orders=orders),
        cycle_values=StateRecord((("anchor", anchor), ("floor", floor))) if active is not None or target else None)
