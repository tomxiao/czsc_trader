"""S001 completed-week financial signals expressed only as equity target weights."""
import json
import pandas as pd
from strategy_runtime import (AccountDecision, AccountStepResult, StateRecord,
    SignalBasisSnapshot, SignalExplanationSnapshot)
from .signal_math import calculate_s001_history


def local_frame(rows, *, daily=False):
    frame = pd.DataFrame([dict(row) for row in rows])
    dates = pd.to_datetime(frame['Date'])
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    frame['Date'] = dates.dt.normalize() if daily else dates
    return frame


def financial_signal(windows, encoded_rule):
    observations = dict(zip(('adjusted_daily', 'adjusted_30m', 'adjusted_weekly'), windows, strict=True))
    rule = json.loads(encoded_rule)
    daily = local_frame(observations['adjusted_daily'], daily=True)
    intraday = local_frame(observations['adjusted_30m'])
    weekly = local_frame(observations['adjusted_weekly'], daily=True)
    if daily.Date.iloc[0] != pd.Timestamp('2020-11-16'):
        raise ValueError('S001 requires its frozen canonical history from 2020-11-16')
    history = calculate_s001_history(intraday, daily, weekly, rule, '588080.SH')
    row = history.iloc[-1]
    previous = bool(history.target_position.iloc[-2]) if len(history) > 1 else False
    score = float(row.factor_score) if pd.notna(row.factor_score) else None
    return history.index[-1].date(), float(row.target_position), previous, score, str(row.regime)


def _decision(target, judgment, summary, details, watch):
    basis = (SignalBasisSnapshot('summary', summary), SignalBasisSnapshot('conditions', details),
             SignalBasisSnapshot('target_weight', '本轮以开仓周期锁定的股数为准。' if target else '目标空仓。'))
    return AccountDecision(target, SignalExplanationSnapshot(
        'target', 'long' if target else 'flat', judgment, basis, watch,
        ' '.join(item.text for item in basis)))


def step(ctx, state):
    for name, count in {'adjusted_daily': 16384, 'adjusted_30m': 131072, 'adjusted_weekly': 4096}.items():
        if len(ctx.observations[name]) > count:
            raise ValueError('S001 canonical history exceeds its declared window: ' + name)
    rule = json.loads(ctx.parameters['rule'])
    day, target, previous, score, regime = ctx.market_feature('financial_signal')
    observation_day = pd.Timestamp(ctx.history.last()['Date']).tz_convert('Asia/Shanghai').date()
    if day != observation_day:
        raise ValueError('S001 signal and primary observation sessions differ')
    score = float('nan') if score is None else score
    entry, exit_ = float(rule['entry_threshold']), float(rule['exit_threshold'])
    regime = {'trend': '趋势', 'range': '震荡', 'warmup': '预热'}[regime]
    if target and not previous:
        judgment, summary = '触发入场', f'{regime}档综合评分达到入场线，确认条件已满足。'
    elif previous and not target:
        judgment, summary = '目标清仓', f'{regime}档评分触及退出线，持有期和退出确认已满足。'
    elif target:
        judgment = '延续目标仓位'
        summary = ('综合评分仍高于退出线，延续目标仓位。' if score > exit_
                   else '评分已触及退出线，最短持有或连续确认条件尚未满足。')
    else:
        judgment = '继续空仓'
        summary = ('综合评分低于入场线，继续空仓。' if score < entry
                   else '评分已达到入场线，连续确认条件尚未满足。')
    details = (f'{regime}档评分 {score:.6g}，入场线 {entry:.6g}，退出线 {exit_:.6g}。'
               f'入场须连续 {rule["confirm_days"]} 日达标；退出须满足最短持有 '
               f'{rule["min_hold_days"]} 日，并连续 {rule["exit_confirm_days"]} 日确认。'
               '周线因子使用已完成周线。')
    decision = _decision(target, judgment, summary, details, '下一交易日收盘后复核综合评分及确认条件。')
    return AccountStepResult(decision, cycle_values=StateRecord())
