"""Controlled exit-mechanism variants with confirmed holding state."""
from zoneinfo import ZoneInfo
from bisect import bisect_left
import numpy as np
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


_NY = ZoneInfo("America/New_York")


def _daily_days(windows):
    return tuple(row["Date"].astimezone(_NY).date() for row in windows[0])


def _daily_atr(windows):
    rows = windows[0]
    high = np.array([row["High"] for row in rows], dtype=float)
    low = np.array([row["Low"] for row in rows], dtype=float)
    close = np.array([row["Close"] for row in rows], dtype=float)
    previous = np.concatenate(([np.nan], close[:-1]))
    ranges = np.maximum.reduce([high - low, np.abs(high - previous), np.abs(low - previous)])
    value = float(np.mean(ranges[-14:]))
    if not np.isfinite(value) or value <= 0:
        raise ValueError("Positive prior daily ATR required")
    return value


def _entry_daily(windows, down_days, participation_days):
    mu, sector = windows
    if len(mu) != 65 or tuple(row["Date"] for row in mu) != tuple(row["Date"] for row in sector):
        raise ValueError("Aligned daily warmup required")
    closes = np.array([row["Close"] for row in mu], dtype=float)
    sector_closes = np.array([row["Close"] for row in sector], dtype=float)
    m = np.diff(closes) / closes[:-1]
    s = np.diff(sector_closes) / sector_closes[:-1]
    variance = np.var(s[:-1], ddof=1)
    if variance <= 0 or not np.isfinite(variance):
        raise ValueError("Industry variance must be finite and positive")
    common = float(np.cov(m[:-1], s[:-1], ddof=1)[0, 1] / variance * s[-1])
    anchor = float(closes[-(down_days + 1)])
    down = bool(np.all(np.diff(closes[-(down_days + 1):]) < 0))
    relative = float((closes[-1] / closes[-64]) / (sector_closes[-1] / sector_closes[-64]) - 1)
    previous = float(np.median([row["Volume"] for row in mu[-(participation_days + 1):-1]]))
    if previous <= 0:
        raise ValueError("Positive previous daily volume reference required")
    prior = float(mu[-1]["Volume"] / previous)
    return common, anchor, down, relative, prior, mu[-1]["Date"].astimezone(_NY).date()


def _opening_volume(windows, session_date, participation_days):
    first = {}
    for row in windows[0]:
        day = row["Date"].astimezone(_NY).date()
        if day < session_date:
            first.setdefault(day, row["Volume"])
    previous = list(first.values())[-participation_days:]
    if len(previous) != participation_days:
        raise ValueError("Declared prior opening-volume observations required")
    scale = float(np.median(previous))
    if scale <= 0:
        raise ValueError("Declared prior opening-volume observations required")
    return scale


def participation_linear_factor(ratio: float, threshold: float, quiet_fraction: float,
                                half_width: float) -> float:
    """Continuous participation multiplier with a positive low-participation floor."""
    if not all(np.isfinite(x) for x in (ratio, threshold, quiet_fraction, half_width)):
        raise ValueError("Participation inputs must be finite")
    if ratio < 0 or threshold <= 0 or half_width <= 0:
        raise ValueError("Nonnegative participation and positive threshold/half-width required")
    if not 0 < quiet_fraction <= 1:
        raise ValueError("Participation floor must be in (0, 1]")
    transition = float(np.clip((ratio / threshold - (1 - half_width)) / (2 * half_width), 0, 1))
    return float(quiet_fraction + (1 - quiet_fraction) * transition)


def step(ctx, state):
    p = ctx.parameters
    participation_policy = p["participation_policy"]
    participation_width = p["participation_width"]
    if participation_policy not in {"hard", "linear"}:
        raise ValueError("Unknown participation policy")
    if not np.isfinite(participation_width) or participation_width <= 0:
        raise ValueError("Positive finite participation half-width required")
    policy = p["exit_policy"]
    if policy not in {"hard", "none", "confirm", "ramp", "daily_close", "rolling_atr", "ramp_rebuild"}:
        raise ValueError("Unknown exit policy")
    if p["exit_width"] <= 0 or p["confirm_bars"] < 1:
        raise ValueError("Positive exit width and confirmation count required")
    if len(ctx.session.segments) != 1:
        raise ValueError("Single regular-session segment required")
    slot = int((ctx.point.execution_interval.start - ctx.session.segments[0].start).total_seconds() // 1800)
    price = float(ctx.history.last()["Close"])
    active = ctx.position.active
    values = None
    facts = {"slot": slot, "price": price, "exit_mode": p["exit_mode"], "require_sector": p["require_sector"],
             "participation_policy": participation_policy, "participation_width": participation_width}
    if active is not None:
        if state.cycle is None or state.cycle.cycle_id != active.cycle_id:
            raise ValueError("Confirmed holding requires matching state")
        old = state.cycle.values
        anchor = old.get("anchor")
        allocation = old.get("allocation")
        entry_day = active.entry_interval.start.astimezone(ZoneInfo("America/New_York")).date()
        days = ctx.market_feature("daily_days")
        held = len(days) - bisect_left(days, entry_day)
        recovered = price >= anchor
        old_high = float(old.get("high_water"))
        high_water = old_high if policy == "daily_close" and slot != 0 else max(old_high, price)
        entry_atr = float(old.get("entry_atr"))
        risk_atr = ctx.market_feature("daily_atr") if policy == "rolling_atr" else entry_atr
        trail_price = high_water - p["trail_atr"] * risk_atr
        touched = price <= trail_price
        breach_count = int(old.get("breach_count")) + 1 if touched else 0
        risk_fraction = float(old.get("risk_fraction"))
        if policy == "none":
            stopped = False
        elif policy == "confirm":
            stopped = breach_count >= p["confirm_bars"]
        elif policy == "daily_close":
            stopped = slot == 0 and touched
        elif policy in {"ramp", "ramp_rebuild"}:
            distance = (high_water - price) / risk_atr
            fraction = float(np.clip((p["trail_atr"] + p["exit_width"] / 2 - distance) / p["exit_width"], 0, 1))
            risk_fraction = fraction if policy == "ramp_rebuild" else min(risk_fraction, fraction)
            stopped = risk_fraction == 0
        else:
            stopped = touched
        exiting = bool(old.get("exiting") or stopped or held >= p["hold_days"] or (p["exit_mode"] == "repair" and recovered))
        target = 0.0 if exiting else allocation * risk_fraction
        values = StateRecord((("anchor", anchor), ("allocation", allocation), ("exiting", exiting),
            ("high_water", high_water), ("entry_atr", entry_atr), ("risk_fraction", risk_fraction), ("breach_count", breach_count)))
        reason = ("达到固定持有期限，退出" if held >= p["hold_days"] else "修复目标已完成，退出") if exiting else ("等待固定价位修复，继续持有" if p["exit_mode"] == "repair" else "继续持有，观察回升延续")
        if stopped and held < p["hold_days"]:
            reason = "跟踪退出条件成立，退出"
        elif not exiting and risk_fraction < 1:
            reason = "峰值回落进入风险区间，保留较低仓位"
        if policy == "ramp_rebuild" and old.get("exiting") and held < p["hold_days"]:
            reason = "已触发退出，继续完成清仓"
        facts.update(anchor=anchor, held=held, recovered=recovered, high_water=high_water,
            entry_atr=entry_atr, risk_atr=risk_atr, trail_price=trail_price, stopped=stopped,
            touched=touched, exit_policy=policy, risk_fraction=risk_fraction, breach_count=breach_count)
    elif slot == 1:
        common, anchor, down2, relative63, prior_participation, signal_day = ctx.market_feature("entry_daily")
        if signal_day >= ctx.session.session_date:
            raise ValueError("Prior completed daily signal required")
        opening = ctx.history.last()
        recovery = bool(opening["Close"] > opening["Open"])
        enter = down2 and price < anchor and (not p["require_sector"] or common <= 0) and (not p["confirm"] or recovery)
        industry = ctx.auxiliary_histories["soxx_open"].last()
        if industry["Date"] != opening["Date"] or industry["AvailableDate"] > ctx.point.decision_at:
            raise ValueError("Contemporaneous completed industry opening bar required")
        sector_return = float(industry["Close"] / industry["Open"] - 1)
        mu_return = float(opening["Close"] / opening["Open"] - 1)
        strong = sector_return > 0 if p["information"] == "sector" else mu_return > sector_return
        enter = enter and (p["treatment"] != "gate" or strong)
        long_strong = relative63 > 0
        allocation = 1.0 if long_strong else p["weak_fraction"]
        if p["risk_basis"] == "joint":
            allocation *= 1.0 if strong else .5
        opening_scale = ctx.market_feature("opening_volume")
        participation = float(opening["Volume"] / opening_scale)
        if participation_policy == "hard":
            opening_factor = 1.0 if participation >= p["participation_threshold"] else p["quiet_fraction"]
            prior_factor = 1.0 if prior_participation >= p["participation_threshold"] else p["quiet_fraction"]
        else:
            opening_factor = participation_linear_factor(participation, p["participation_threshold"],
                p["quiet_fraction"], participation_width)
            prior_factor = participation_linear_factor(prior_participation, p["participation_threshold"],
                p["quiet_fraction"], participation_width)
        if p["joint_rule"] == "minimum":
            participation_factor = min(opening_factor, prior_factor)
        elif p["joint_rule"] == "maximum":
            participation_factor = max(opening_factor, prior_factor)
        elif p["joint_rule"] == "product":
            participation_factor = opening_factor * prior_factor
        elif p["joint_rule"] == "mean":
            participation_factor = (opening_factor + prior_factor) / 2
        else:
            raise ValueError("Unknown participation combination")
        allocation *= participation_factor
        enter = enter and allocation > 0
        entry_atr = ctx.market_feature("daily_atr")
        target = allocation if enter else 0.0
        values = StateRecord((("anchor", anchor), ("allocation", allocation), ("exiting", False),
            ("high_water", price), ("entry_atr", entry_atr), ("risk_fraction", 1.0), ("breach_count", 0))) if enter else None
        reason = "下跌后入场条件成立，参与后续上涨" if enter else "当前缺少未完成修复机会，空仓"
        facts.update(anchor=anchor, participation=participation, participation_days=p["participation_days"], prior_participation=prior_participation, opening_factor=opening_factor, prior_factor=prior_factor, joint_rule=p["joint_rule"], participation_factor=participation_factor, participation_threshold=p["participation_threshold"], entry_atr=entry_atr, trail_atr=p["trail_atr"], allocation=allocation, relative63=relative63, long_strong=long_strong, risk_basis=p["risk_basis"], information=p["information"], treatment=p["treatment"], industry_return=sector_return, mu_return=mu_return, strong=bool(strong), down2=down2, common=common, opening_recovery=recovery, down_days=p["down_days"])
    else:
        target = 0.0
        reason = "等待首30分钟完成，空仓"
    facts["target_weight"] = target
    return AccountStepResult(AccountDecision.from_facts(target, reason, facts=facts,
        next_watch="检查成交和已声明的持有退出条件。"), cycle_values=values)
