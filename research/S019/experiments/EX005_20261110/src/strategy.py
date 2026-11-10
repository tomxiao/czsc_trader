"""Fixed structural controls for industry-pullback short holding."""
from zoneinfo import ZoneInfo

import numpy as np
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


def step(ctx, state):
    mode = ctx.parameters["mode"]
    if len(ctx.session.segments) != 1:
        raise ValueError("Prototype requires a single regular-session segment")
    segment = ctx.session.segments[0]
    slot = int((ctx.point.execution_interval.start - segment.start).total_seconds() // 1800)
    slots = int((segment.end - segment.start).total_seconds() // 1800)
    active = ctx.position.active
    values = None
    common = trend = None
    if active is not None:
        if state.cycle is None or state.cycle.cycle_id != active.cycle_id:
            raise ValueError("Confirmed holding requires matching cycle state")
        values = state.cycle.values
        entry_day = active.entry_interval.start.astimezone(ZoneInfo("America/New_York")).date()
        exit_due = ctx.session.session_date > entry_day or (
            mode == "adaptive_exit" and not values.get("uptrend") and slot == slots - 1)
        target = 0.0 if exit_due else 1.0
        reason = "到达预定退出时点，目标清仓" if exit_due else "持有至预定退出时点，延续满仓目标"
    elif slot == 1:
        mu = ctx.auxiliary_histories["mu_daily"].to_frame(tail=65)
        sector = ctx.auxiliary_histories["soxx_daily"].to_frame(tail=65)
        if len(mu) != 65 or mu.Date.tolist() != sector.Date.tolist():
            raise ValueError("Signal requires 65 aligned daily observations")
        if max(mu.AvailableDate.max(), sector.AvailableDate.max()) > ctx.point.decision_at:
            raise ValueError("Signal observations must be available")
        if mu.Date.iloc[-1].tz_convert("America/New_York").date() >= ctx.session.session_date:
            raise ValueError("Entry signal requires a prior completed daily bar")
        m = np.diff(mu.Close.to_numpy()) / mu.Close.to_numpy()[:-1]
        s = np.diff(sector.Close.to_numpy()) / sector.Close.to_numpy()[:-1]
        variance = np.var(s[:-1], ddof=1)
        if not np.isfinite(variance) or variance <= 0:
            raise ValueError("Industry return variance must be positive")
        common = float(np.cov(m[:-1], s[:-1], ddof=1)[0, 1] / variance * s[-1])
        trend = float(mu.Close.iloc[-1] / mu.Close.iloc[-64] - 1)
        enter = mode == "all" or (common <= 0 and (mode != "trend_filter" or trend > 0))
        target = 1.0 if enter else 0.0
        values = StateRecord((("uptrend", trend > 0),)) if enter else None
        reason = "入场条件满足，提交满仓目标" if enter else "入场条件未满足，继续空仓"
    else:
        target = 0.0
        reason = "等待下一交易日首30分钟完成，继续空仓"
    facts = {"mode": mode, "execution_slot": slot, "target_weight": target,
        "common": common, "trend63": trend,
        "entry_uptrend": values.get("uptrend") if values is not None else None}
    decision = AccountDecision.from_facts(target, reason, facts=facts,
        next_watch="关注成交回报，并按交易日历检查下一入场或退出时点。")
    return AccountStepResult(decision, cycle_values=values)
