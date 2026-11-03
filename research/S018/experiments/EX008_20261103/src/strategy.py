from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord
from zoneinfo import ZoneInfo


def step(ctx, state):
    bars = ctx.history.to_frame(tail=66)
    close = bars["Close"]
    dates = [stamp.astimezone(ZoneInfo("America/New_York")) for stamp in bars["Date"]]
    active = ctx.position.active
    if active is not None:
        held = sum(stamp >= active.entry_interval.start for stamp in dates)
        target = float(held < 5)
        facts = {"completed_holding_sessions": held}
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
    return AccountStepResult(AccountDecision.from_facts(target, "fixed three-mechanism five-session policy",
        facts=facts, next_watch="next completed daily bar", capital_mode="full_available_cash"),
        cycle_values=StateRecord() if active is not None or target else None)
