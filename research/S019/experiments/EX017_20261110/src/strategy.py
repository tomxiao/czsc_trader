"""Opening recovery with explicitly declared holding windows."""
from zoneinfo import ZoneInfo
import numpy as np
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


def step(ctx, state):
    p = ctx.parameters
    if len(ctx.session.segments) != 1:
        raise ValueError("Single regular-session segment required")
    slot = int((ctx.point.execution_interval.start - ctx.session.segments[0].start).total_seconds() // 1800)
    mu = ctx.auxiliary_histories["mu_daily"].to_frame(tail=65)
    price = float(ctx.history.to_frame(tail=1).Close.iloc[-1])
    short_strong = bool(mu.Close.iloc[-1] > mu.Close.iloc[-p["risk_days"]:].mean())
    risk_factor = 1.0 if short_strong else p["risk_fraction"]
    active = ctx.position.active
    values = None
    facts = {"slot": slot, "price": price, "exit_mode": p["exit_mode"], "require_sector": p["require_sector"]}
    if active is not None:
        if state.cycle is None or state.cycle.cycle_id != active.cycle_id:
            raise ValueError("Confirmed holding requires matching state")
        old = state.cycle.values
        anchor = old.get("anchor")
        allocation = old.get("allocation")
        entry_day = active.entry_interval.start.astimezone(ZoneInfo("America/New_York")).date()
        held = int((mu.Date.dt.tz_convert("America/New_York").dt.date >= entry_day).sum())
        recovered = price >= anchor
        exiting = bool(old.get("exiting") or held >= p["hold_days"] or (p["exit_mode"] == "repair" and recovered))
        target = 0.0 if exiting else allocation * risk_factor
        values = StateRecord((("anchor", anchor), ("allocation", allocation), ("exiting", exiting)))
        reason = ("达到固定持有期限，退出" if held >= p["hold_days"] else "修复目标已完成，退出") if exiting else ("等待固定价位修复，继续持有" if p["exit_mode"] == "repair" else "继续持有，观察回升延续")
        facts.update(anchor=anchor, held=held, recovered=recovered)
    elif slot == 1:
        sector = ctx.auxiliary_histories["soxx_daily"].to_frame(tail=65)
        if len(mu) != 65 or mu.Date.tolist() != sector.Date.tolist():
            raise ValueError("Aligned daily warmup required")
        if max(mu.AvailableDate.max(), sector.AvailableDate.max()) > ctx.point.decision_at:
            raise ValueError("Signal inputs must already be available")
        if mu.Date.iloc[-1].tz_convert("America/New_York").date() >= ctx.session.session_date:
            raise ValueError("Prior completed daily signal required")
        closes = mu.Close.to_numpy()
        m = np.diff(closes) / closes[:-1]
        s = np.diff(sector.Close.to_numpy()) / sector.Close.to_numpy()[:-1]
        variance = np.var(s[:-1], ddof=1)
        if variance <= 0 or not np.isfinite(variance):
            raise ValueError("Industry variance must be finite and positive")
        common = float(np.cov(m[:-1], s[:-1], ddof=1)[0, 1] / variance * s[-1])
        anchor = float(closes[-(p["down_days"] + 1)])
        down2 = bool(np.all(np.diff(closes[-(p["down_days"] + 1):]) < 0))
        opening = ctx.history.to_frame(tail=1).iloc[-1]
        recovery = bool(opening.Close > opening.Open)
        enter = down2 and price < anchor and (not p["require_sector"] or common <= 0) and (not p["confirm"] or recovery)
        industry = ctx.auxiliary_histories["soxx_open"].to_frame(tail=1).iloc[-1]
        if industry.Date != opening.Date or industry.AvailableDate > ctx.point.decision_at:
            raise ValueError("Contemporaneous completed industry opening bar required")
        sector_return = float(industry.Close / industry.Open - 1)
        mu_return = float(opening.Close / opening.Open - 1)
        strong = sector_return > 0 if p["information"] == "sector" else mu_return > sector_return
        enter = enter and (p["treatment"] != "gate" or strong)
        relative63 = float((mu.Close.iloc[-1] / mu.Close.iloc[-64]) / (sector.Close.iloc[-1] / sector.Close.iloc[-64]) - 1)
        long_strong = relative63 > 0
        allocation = 1.0 if long_strong else p["weak_fraction"]
        if p["risk_basis"] == "joint":
            allocation *= 1.0 if strong else .5
        target = allocation * risk_factor if enter else 0.0
        values = StateRecord((("anchor", anchor), ("allocation", allocation), ("exiting", False))) if enter else None
        reason = "下跌后入场条件成立，参与后续上涨" if enter else "当前缺少未完成修复机会，空仓"
        facts.update(anchor=anchor, allocation=allocation, relative63=relative63, long_strong=long_strong, risk_basis=p["risk_basis"], information=p["information"], treatment=p["treatment"], industry_return=sector_return, mu_return=mu_return, strong=bool(strong), down2=down2, common=common, opening_recovery=recovery, down_days=p["down_days"])
    else:
        target = 0.0
        reason = "等待首30分钟完成，空仓"
    facts.update(risk_factor=risk_factor, short_strong=short_strong, risk_days=p["risk_days"])
    facts["target_weight"] = target
    return AccountStepResult(AccountDecision.from_facts(target, reason, facts=facts,
        next_watch="检查成交和已声明的持有退出条件。"), cycle_values=values)
