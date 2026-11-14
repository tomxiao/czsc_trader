"""S015 repair signal with bounded DFLS reads and an explicit signal cycle."""
from datetime import date, timedelta
from math import exp
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from strategy_runtime import (
    AccountDecision, AccountStepResult, SignalBasisSnapshot,
    SignalExplanationSnapshot, StateRecord, StepDataWindow,
)

ZONE = ZoneInfo("Asia/Shanghai")
FIRST = date(2025, 1, 2)
TIMES = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
MAX_CALENDAR_DAYS = 40


def center(bars, session, kind):
    if tuple(bars.Date.dt.strftime("%H:%M")) != TIMES or set(bars.Date.dt.date) != {session}:
        raise ValueError("S015 日内行情必须包含当日完整的八根 30 分钟线")
    prices = bars[["Open", "High", "Low", "Close"]].to_numpy(float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError("S015 日内行情价格必须为有限正数")
    aggregate = {"median": np.median, "mean": np.mean}[kind]
    return float(aggregate(np.log(prices[:, 3])))


def features(data, session, parameters, last_signal_date):
    start = max(FIRST, session - timedelta(days=MAX_CALENDAR_DAYS - 1))
    calendar = data.fetch(StepDataWindow("calendar", start, session))
    if not pd.DatetimeIndex(calendar.Date).equals(pd.date_range(start, session)):
        raise ValueError("S015 交易日历区间不完整")
    sessions = calendar.loc[calendar.IsOpen.eq(1), "Date"].dt.date.tolist()
    if not sessions or sessions[-1] != session:
        raise ValueError("S015 缺少信号交易日")
    if last_signal_date is not None and (len(sessions) < 2 or sessions[-2].isoformat() != last_signal_date):
        raise ValueError("S015 前一交易日信号状态缺失，需从已核验检查点补齐")
    lookback = parameters["lookback"]
    if len(sessions) <= lookback:
        if start != FIRST:
            raise ValueError("S015 缺少回看交易日")
        return None
    daily = data.fetch(StepDataWindow("price_daily", session, session))
    if list(daily.Date.dt.date) != [session]:
        raise ValueError("S015 缺少当日日线")
    prices = daily[["Open", "High", "Low", "Close"]].to_numpy(float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError("S015 日线行情价格必须为有限正数")
    p = float(np.log(prices[:, 3])[0])
    kind = parameters["center_kind"]
    observations = []
    for day in (session, sessions[-lookback - 1]):
        observations.append(center(data.fetch(StepDataWindow("price_intraday", day, day)), day, kind))
    m, previous = observations
    return p, m, m - previous, float(np.expm1(m - p))


def decide(values, prior, params):
    active, repair_target, invalidation_origin = (prior[key] for key in (
        "active", "repair_target", "invalidation_origin"))
    minimum = params["minimum_repair_space"]
    if values is None:
        if active:
            raise ValueError("S015 缺少计算已激活信号所需的价格中心")
        judgment, summary = "继续空仓", "价格中心尚未完成预热。"
        conditions = "需取得当日与回看交易日的完整日内行情。"
    else:
        p, m, gain, space = values
        if active:
            if p >= repair_target or m <= invalidation_origin:
                active = False
                judgment = "目标清仓"
                summary = ("价格已达到本轮修复目标。" if p >= repair_target
                           else "价格中心已降至本轮信号失效线或以下。")
            else:
                judgment = "延续目标仓位"
                summary = "价格尚未达到本轮修复目标，中心仍高于失效线。"
        elif gain > 0 and p < m and space >= minimum:
            active, repair_target, invalidation_origin = True, m, m - gain
            judgment, summary = "触发入场", "价格低于上移的中心，且回到中心的空间达到入场门槛。"
        else:
            judgment = "继续空仓"
            if gain <= 0:
                summary = "价格中心未上移。"
            elif p >= m:
                summary = "收盘价未低于当前中心。"
            else:
                summary = "回到当前中心的空间低于入场门槛。"
        conditions = (f"中心变化 {gain:.6g}（对数价格），回到当前中心的空间 {space:.4%}，"
                      f"入场门槛 {minimum:.4%}。")
        if active or judgment == "目标清仓":
            conditions += (f" 后复权收盘 {exp(p):.6f}，修复目标 {exp(repair_target):.6f}，"
                           f"当前中心 {exp(m):.6f}，失效线 {exp(invalidation_origin):.6f}。")
    target = params["allocation"] if active else 0.0
    basis = (SignalBasisSnapshot("summary", summary), SignalBasisSnapshot("conditions", conditions))
    explanation = SignalExplanationSnapshot("target", "long" if active else "flat", judgment, basis,
        "下一交易日复核价格中心、修复目标和失效条件。", f"{summary} {conditions}")
    return AccountStepResult(AccountDecision(target, explanation), StateRecord((
        ("active", active), ("repair_target", repair_target), ("invalidation_origin", invalidation_origin),
    )), StateRecord())


def step(ctx, state):
    session = ctx.point.observed_through.astimezone(ZONE).date()
    prior = dict(state.account.values)
    values = features(ctx.dfls, session, ctx.parameters, prior["last_signal_date"])
    outcome = decide(values, prior, ctx.parameters)
    checkpoint = StateRecord((*outcome.account.values, ("last_signal_date", session.isoformat())))
    return AccountStepResult(outcome.decision, checkpoint, outcome.cycle_values)
