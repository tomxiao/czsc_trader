"""S011-v1 V5 candidate for same-version upgrade review."""

from datetime import date, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

import pandas as pd
from strategy_runtime import (AccountDecision, AccountStepResult, SignalBasisSnapshot,
                              SignalExplanationSnapshot, StateRecord, StepDataWindow)


ZONE = ZoneInfo('Asia/Shanghai')
FIRST_OBSERVATION = date(2024, 12, 26)


def rank(series):
    current = series.iloc[-1]
    values = [value for value in series if isfinite(value)]
    if not isfinite(current) or len(values) < 20:
        raise ValueError('S011 压力评分可用样本少于冻结版要求')
    return ((sum(value < current for value in values)
             + .5 * sum(value == current for value in values)) / len(values) - .5)


def explain(target, reason, score, age, params):
    judgment, summary = {
        'PRESSURE_ENTRY': ('触发入场', '压力评分达到入场线，触发买入信号。'),
        'CASH': ('继续空仓', '压力评分低于入场线，继续空仓。'),
        'HOLD': ('延续目标仓位', '压力评分仍高于退出线，且信号未到期。'),
        'PRESSURE_RELEASED': ('目标清仓', '压力评分降至退出线或以下，触发退出。'),
        'SIGNAL_EXPIRED': ('目标清仓', '压力评分尚未触发退出，但持有信号已到期。'),
    }[reason]
    details = (f'压力评分 {score:.6g}，入场线 {params["entry"]:.6g}，退出线 {params["exit"]:.6g}。'
               f'信号已持续 {age} 个交易日，有效期上限 {params["max_days"]} 个交易日。')
    weight = '本轮以开仓周期锁定的股数为准。' if target else '目标空仓。'
    basis = (SignalBasisSnapshot('summary', summary), SignalBasisSnapshot('conditions', details),
             SignalBasisSnapshot('target_weight', weight))
    return AccountDecision(target, SignalExplanationSnapshot('target', 'long' if target else 'flat',
        judgment, basis, '下一交易日复核压力评分和信号有效期。', ' '.join((summary, details, weight))))


def step(ctx, state):
    params = ctx.parameters
    length = params['lookback']
    day = ctx.point.observed_through.astimezone(ZONE).date()

    def fetch(name, start, end=day):
        return ctx.dfls.fetch(StepDataWindow(name, start, end))

    calendar_start = max(FIRST_OBSERVATION, day - timedelta(days=219))
    calendar = fetch('calendar', calendar_start)
    if not pd.DatetimeIndex(calendar.Date).equals(pd.date_range(calendar_start, day)):
        raise ValueError('S011 交易日历区间不完整')
    sessions = pd.DatetimeIndex(calendar.loc[calendar.IsOpen.eq(1), 'Date'].iloc[-length - 1:])
    if not len(sessions) or sessions[-1].date() != day:
        raise ValueError('S011 缺少信号日历')
    if len(sessions) < length + 1 and calendar_start != FIRST_OBSERVATION:
        raise ValueError('S011 回看窗口缺少交易日')
    lookback = sessions[-length:]

    daily = fetch('daily', sessions[-5].date())
    bars = fetch('bars', lookback[0].date())
    market = fetch('market', sessions[0].date())
    spx = fetch('spx', lookback[0].date() - timedelta(days=10), day - timedelta(days=1))
    if list(daily.Date) != list(sessions[-5:]) or list(market.Date) != list(sessions):
        raise ValueError('S011 日线窗口不完整')
    clocks = bars.Date.dt.strftime('%H:%M')
    tails = bars.loc[clocks.isin(('13:30', '15:00')), ['Date', 'Close']].copy()
    tails['session'] = tails.Date.dt.normalize()
    tails['clock'] = clocks.loc[tails.index]
    close = tails.pivot(index='session', columns='clock', values='Close')
    if not close.index.equals(lookback) or close.isna().any().any():
        raise ValueError('S011 尾盘行情不完整')
    idx = spx.Date.searchsorted(lookback, side='left') - 1
    if min(idx) < 0 or ((lookback - pd.DatetimeIndex(spx.Date.iloc[idx])).days > 10).any():
        raise ValueError('S011 缺少符合时点要求的 SPX 行情')
    if not ((daily.High - daily.Low) / daily.Close).map(isfinite).all():
        raise ValueError('S011 风险检查缺少有效 ETF 日线')
    w, spx_w = params['tail_weight'], params['spx_weight']
    score = (w * -rank(close['15:00'] / close['13:30'] - 1.)
             + (1 - w) * -rank(market.Close.pct_change(fill_method=None).iloc[-length:])
             + spx_w * rank(spx.PercentChange.iloc[idx])) / (1 + spx_w)

    prior = dict(state.account.values)
    target, age = prior['target'], prior['age']
    if target not in (0, 1) or not 0 <= age <= params['max_days']:
        raise ValueError('S011 信号状态超出约定范围')
    reason = 'CASH'
    if target:
        age += 1
        reason = 'HOLD'
        if score <= params['exit'] or age >= params['max_days']:
            target, reason = 0, 'PRESSURE_RELEASED' if score <= params['exit'] else 'SIGNAL_EXPIRED'
    elif score >= params['entry']:
        target, age, reason = 1, 0, 'PRESSURE_ENTRY'
    decision = explain(target, reason, score, age, params)
    return AccountStepResult(decision, StateRecord((('target', target), ('age', age))), StateRecord())
