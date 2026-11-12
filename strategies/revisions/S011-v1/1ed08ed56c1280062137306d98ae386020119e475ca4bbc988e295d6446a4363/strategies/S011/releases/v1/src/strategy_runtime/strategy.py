"""S011 pressure signal: HFQ observations and current-account-equity targets."""
import pandas as pd
from strategy_runtime import (AccountDecision, AccountStepResult, StateRecord,
    SignalBasisSnapshot, SignalExplanationSnapshot)
from .signal_math import features, policy


def local_frame(view, *, timezone='Asia/Shanghai', daily=False):
    frame = view.to_frame()
    stamp = pd.to_datetime(frame.Date)
    if stamp.dt.tz is not None:
        stamp = stamp.dt.tz_convert(timezone).dt.tz_localize(None)
    frame['Date'] = stamp.dt.normalize() if daily else stamp
    return frame


def signal_history(inputs, parameters):
    for name in ('daily', 'market', 'bars'):
        first = pd.Timestamp(inputs[name].Date.iloc[0]).normalize()
        if first != pd.Timestamp('2024-12-26'):
            raise ValueError('S011 canonical history is missing: ' + name)
    panel = features(inputs)
    sessions = panel.index[panel.index >= pd.Timestamp('2025-02-05')]
    if len(sessions) == 0 or sessions[0] != pd.Timestamp('2025-02-05'):
        raise ValueError('S011 canonical signal start is missing')
    return policy(panel, parameters, sessions)


def _decision(target, judgment, summary, details, watch):
    basis = (SignalBasisSnapshot('summary', summary), SignalBasisSnapshot('conditions', details),
             SignalBasisSnapshot('target_weight', f'目标仓位为账户权益的 {target:.2%}。'))
    return AccountDecision(target, SignalExplanationSnapshot(
        'target', 'long' if target else 'flat', judgment, basis, watch,
        ' '.join(item.text for item in basis)))


def step(ctx, state):
    inputs = {'daily': local_frame(ctx.history, daily=True),
        'bars': local_frame(ctx.auxiliary_histories['intraday']),
        'market': local_frame(ctx.observations['market'], daily=True),
        'spx': local_frame(ctx.observations['spx'], timezone='America/New_York', daily=True)}
    history = signal_history(inputs, ctx.parameters)
    row = history.iloc[-1]
    target = float(row.target_position)
    reason = str(row.reason)
    judgment, summary = {
        'PRESSURE_ENTRY': ('触发入场', '压力评分达到入场线，触发买入信号。'),
        'CASH': ('继续空仓', '压力评分低于入场线，继续空仓。'),
        'HOLD': ('延续目标仓位', '压力评分仍高于退出线，且信号未到期。'),
        'PRESSURE_RELEASED': ('目标清仓', '压力评分降至退出线或以下，触发退出。'),
        'SIGNAL_EXPIRED': ('目标清仓', '压力评分尚未触发退出，但持有信号已到期。'),
    }[reason]
    details = (f'压力评分 {row.score:.6g}，入场线 {ctx.parameters["entry"]:.6g}，'
               f'退出线 {ctx.parameters["exit"]:.6g}。信号已持续 {int(row.intent_age)} 个交易日，'
               f'有效期上限 {ctx.parameters["max_days"]} 个交易日。')
    decision = _decision(target, judgment, summary, details, '下一交易日复核压力评分和信号有效期。')
    return AccountStepResult(decision, cycle_values=StateRecord())
