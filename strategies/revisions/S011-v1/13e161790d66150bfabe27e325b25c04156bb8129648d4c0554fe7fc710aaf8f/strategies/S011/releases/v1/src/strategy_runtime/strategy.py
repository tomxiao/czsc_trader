"""S011 pressure signal: HFQ observations and current-account-equity targets."""
from types import SimpleNamespace
import pandas as pd
from strategy_runtime import (AccountDecision, AccountStepResult, StateRecord,
    SignalBasisSnapshot, SignalExplanationSnapshot)
from .signal_math import features, policy


def local_frame(view, *, timezone='Asia/Shanghai', daily=False):
    frame = pd.DataFrame([dict(row) for row in view])
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
             SignalBasisSnapshot('target_weight', '本轮以开仓周期锁定的股数为准。' if target else '目标空仓。'))
    return AccountDecision(target, SignalExplanationSnapshot(
        'target', 'long' if target else 'flat', judgment, basis, watch,
        ' '.join(item.text for item in basis)))


def financial_signal(windows, entry, exit_, lookback, max_days, spx_weight, tail_weight):
    inputs = dict(zip(('market', 'spx', 'price_daily', 'price_intraday'), windows, strict=True))
    parameters = dict(zip(('entry', 'exit', 'lookback', 'max_days', 'spx_weight', 'tail_weight'), (entry, exit_, lookback, max_days, spx_weight, tail_weight), strict=True))
    observed = {'daily': local_frame(inputs['price_daily'], daily=True),
        'bars': local_frame(inputs['price_intraday']),
        'market': local_frame(inputs['market'], daily=True),
        'spx': local_frame(inputs['spx'], timezone='America/New_York', daily=True)}
    row = signal_history(observed, parameters).iloc[-1]
    return float(row.target_position), str(row.reason), float(row.score), int(row.intent_age)


def step(ctx, state):
    for name, count in {'market': 16384, 'spx': 16384, 'price_daily': 16384, 'price_intraday': 131072}.items():
        if len(ctx.observations[name]) > count:
            raise ValueError('Canonical observation exceeds declared history: ' + name)
    row = SimpleNamespace(**dict(zip(('target_position', 'reason', 'score', 'intent_age'), ctx.market_feature('financial_signal'), strict=True)))
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
