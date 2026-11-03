from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


def step(ctx, state):
    close = ctx.history.to_frame(tail=80)["Close"].to_list()
    last = float(close[-1])
    prior_high = float(max(close[-21:-1]))
    prior_low = float(min(close[-11:-1]))
    recent_average = sum(close[-60:]) / 60
    earlier_average = sum(close[:60]) / 60
    trend = last > recent_average and recent_average > earlier_average
    holding = ctx.position.active is not None
    if holding:
        target = float(last >= prior_low)
        reason = "retain while prior ten-day closing support holds" if target else "break prior ten-day closing support"
    else:
        target = float(last > prior_high and (trend or not ctx.parameters["trend_filter"]))
        reason = "enter on daily breakout" if target else "wait for eligible daily breakout"
    return AccountStepResult(AccountDecision.from_facts(target, reason,
        facts={"close": last, "prior_high": prior_high, "prior_low": prior_low, "trend": trend},
        next_watch="next completed daily bar", capital_mode="full_available_cash"),
        cycle_values=StateRecord() if holding or target else None)
