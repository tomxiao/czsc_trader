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
        month_only = state.cycle.values.get("month_only")
        extended = state.cycle.values.get("extended")
        if held == 5 and month_only:
            extended = bool(close.iloc[-1] * active.quantity > active.buy_cost)
        target = float(held < (10 if extended else 5))
        facts = {"completed_holding_sessions": held, "month_only": month_only, "extended": extended}
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
    return AccountStepResult(AccountDecision.from_facts(target, "five sessions with one profitable month-only extension",
        facts=facts, next_watch="next completed daily bar", capital_mode="full_available_cash"),
        cycle_values=StateRecord((("month_only", month_only), ("extended", extended))) if active is not None or target else None)
