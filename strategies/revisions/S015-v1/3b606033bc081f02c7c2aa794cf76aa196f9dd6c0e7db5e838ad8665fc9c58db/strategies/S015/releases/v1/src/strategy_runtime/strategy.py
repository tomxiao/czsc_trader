"""S015 repair signal using HFQ daily/30m observations, target equity allocation."""
from math import exp
import pandas as pd
from strategy_runtime import (AccountDecision, AccountStepResult, StateRecord,
    SignalBasisSnapshot, SignalExplanationSnapshot)
from .signal_math import causal_features, intentions


def local_frame(view, *, daily=False):
    frame = view.to_frame()
    dates = pd.to_datetime(frame.Date)
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    frame['Date'] = dates.dt.normalize() if daily else dates
    return frame


def signal_history(hfq, intraday, parameters):
    hfq = hfq.loc[hfq.Date >= '2024-09-09'].copy()
    intraday = intraday.loc[intraday.Date >= '2025-01-02'].copy()
    return intentions(causal_features(hfq, intraday, parameters['lookback'], parameters['center_kind']), parameters)


def _decision(target, judgment, summary, details, watch):
    basis = (SignalBasisSnapshot('summary', summary), SignalBasisSnapshot('conditions', details),
             SignalBasisSnapshot('target_weight', f'目标仓位为账户权益的 {target:.2%}。'))
    return AccountDecision(target, SignalExplanationSnapshot(
        'target', 'long' if target else 'flat', judgment, basis, watch,
        ' '.join(item.text for item in basis)))


def step(ctx, state):
    history = signal_history(local_frame(ctx.history, daily=True),
        local_frame(ctx.auxiliary_histories['intraday']), ctx.parameters)
    row = history.iloc[-1]
    target = float(row.target_position) * float(ctx.parameters['allocation'])
    minimum = ctx.parameters['minimum_repair_space']
    if row.entry_signal:
        judgment, summary = '触发入场', '价格低于上移的中心，且回到中心的空间达到入场门槛。'
    elif row.exit_signal:
        judgment = '目标清仓'
        summary = ('价格已达到本轮修复目标，触发退出。' if row.p >= row.repair_target
                   else '中心已降至本轮失效线或以下，触发退出。')
    elif target:
        judgment, summary = '延续目标仓位', '价格尚未达到本轮修复目标，中心也未触及失效线。'
    else:
        judgment = '继续空仓'
        if not row.feature_ready:
            summary = '中心信号尚未完成预热，继续空仓。'
        elif row.center_gain <= 0:
            summary = '价格中心未上移，继续空仓。'
        elif row.p >= row.m:
            summary = '价格未低于当前中心，继续空仓。'
        else:
            summary = '回到中心的空间低于入场门槛，继续空仓。'
    details = (f'回到当前中心的空间 {row.repair_space:.4%}，入场门槛 {minimum:.4%}。'
               f'中心变化 {row.center_gain:.6g}（对数价格）。') if row.feature_ready else '当前中心所需的观察数据不足。'
    if target or row.exit_signal:
        details += (f'后复权收盘 {exp(row.p):.4f}，本轮修复目标 {exp(row.repair_target):.4f}；'
                    f'当前中心 {exp(row.m):.4f}，本轮中心失效线 {exp(row.invalidation_origin):.4f}。')
    decision = _decision(target, judgment, summary, details, '下一交易日复核价格中心、修复目标和失效条件。')
    return AccountStepResult(decision, cycle_values=StateRecord())
