from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


def step(ctx, state):
    bars = ctx.history.to_frame(tail=21)
    close = bars["Close"]
    price = float(close.iloc[-1])
    anchor = float(close.iloc[-11:-1].median())
    floor = float(close.iloc[-21:-11].median())
    p = ctx.parameters
    mode = p["exit"]
    active = ctx.position.active
    fast = float(close.iloc[-3:].median())
    prior = float(close.iloc[-13:-3].median())
    range_floor = float(close.iloc[-11:-1].min())
    discount = range_floor < price and anchor / price > 1.01 * 1.001 / .999
    broke = float(bars["Low"].iloc[-1]) < range_floor
    observed_signal = discount and broke if p["entry"] == "reclaim" else discount and not broke if p["entry"] == "intact" else False
    if p["entry"] in ("reward_ge_risk", "reward_lt_risk"):
        quoted_limit = int(price * 101) / 100
        reward = anchor * .999 - quoted_limit * 1.001
        risk = quoted_limit * 1.001 - range_floor * .999
        favorable = reward >= risk
        observed_signal = discount and not broke and (favorable == (p["entry"] == "reward_ge_risk"))
    if p["entry"] == "prior_range":
        range_floor = float(bars["Low"].iloc[-2])
        anchor = float(close.iloc[-2])
        observed_signal = float(bars["Low"].iloc[-1]) >= range_floor and anchor / price > 1.01 * 1.001 / .999
    if active is None:
        if p["entry"] == "repair":
            enter = anchor > floor and floor < price and anchor / price > 1.01 * 1.001 / .999
        elif p["entry"] in ("reclaim", "intact", "prior_range", "reward_ge_risk", "reward_lt_risk"):
            floor = range_floor
            enter = observed_signal
        elif p["entry"] == "range_repair":
            floor = float(close.iloc[-11:-1].min())
            enter = floor < price and anchor / price > 1.01 * 1.001 / .999
        elif p["entry"] == "fast_trend":
            enter = fast > prior
        elif p["entry"] == "discount":
            enter = anchor / price > 1.01 * 1.001 / .999
        else:
            enter = price > float(close.iloc[-11:-1].max())
        target = float(enter)
        reason = "entry" if enter else "no opportunity"
    else:
        anchor = state.cycle.values.get("anchor")
        floor = state.cycle.values.get("floor")
        held = int(sum(stamp >= active.entry_interval.start for stamp in bars["Date"]))
        current_center = float(close.iloc[-10:].median())
        reached = price >= anchor
        failed = (current_center <= floor if mode not in ("price_fail", "price_failure_only") else price <= floor)
        if mode == "fixed":
            reason = "time limit" if held >= 5 else "hold"
        elif mode in ("failure_only", "price_failure_only"):
            reason = "invalidated" if failed else "hold"
        elif mode == "fast_trend":
            reason = "trend failed" if fast <= prior else "hold"
        elif mode == "trend":
            reason = "trend failed" if price < float(close.iloc[-11:-1].median()) else "hold"
        else:
            reason = "target reached" if reached else "invalidated" if failed and mode != "target_only" else "hold"
        target = float(reason == "hold")
    return AccountStepResult(AccountDecision.from_facts(target, reason,
        facts={"anchor": anchor, "floor": floor, "reason": reason, "observed_signal": observed_signal},
        next_watch="next complete daily bar", capital_mode="full_available_cash"),
        cycle_values=StateRecord((("anchor", anchor), ("floor", floor))) if active is not None or target else None)
