"""S007 V5 decision using a rolling feature window and saved signal intent."""
import json
from datetime import timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from strategy_runtime import AccountDecision, AccountStepResult, SignalBasisSnapshot, SignalExplanationSnapshot, StateRecord, StepDataWindow
from .signals import _FROZEN_HISTORY_START, _FROZEN_HISTORY_END, calculate_scores, materialize_s007_features

ZONE = ZoneInfo('Asia/Shanghai')
CALENDAR_DAYS = 450
LIVE_WARMUP_START = pd.Timestamp('2026-08-01')
LIVE_SPX_START = pd.Timestamp('2026-07-25')


def feature_window(data, day, length, previous, features):
    stamp = pd.Timestamp(day)
    start = max(_FROZEN_HISTORY_START.date(), day - timedelta(days=CALENDAR_DAYS - 1))
    calendar = data.fetch(StepDataWindow('calendar', start, day))
    if not pd.DatetimeIndex(calendar.Date).equals(pd.date_range(start, day)):
        raise ValueError('S007 交易日历区间不完整')
    sessions = pd.DatetimeIndex(calendar.loc[calendar.IsOpen.eq(1), 'Date'])
    if len(sessions) == 0 or sessions[-1] != stamp:
        raise ValueError('S007 缺少信号交易日')
    if previous is not None and (len(sessions) < 2 or sessions[-2].date().isoformat() != previous):
        raise ValueError('S007 前一交易日信号状态缺失')
    if start > _FROZEN_HISTORY_START.date() and len(sessions) < length + 20:
        raise ValueError('S007 交易日历未覆盖评分窗口和预热')
    wanted = sessions[-length:]
    seed_days = wanted[wanted <= _FROZEN_HISTORY_END]
    live_days = wanted[wanted > _FROZEN_HISTORY_END]
    segments = []
    if len(seed_days):
        seed = data.fetch(StepDataWindow('feature_seed', seed_days[0].date(), seed_days[-1].date()))
        seed = seed.set_index('Date').loc[:, features]
        if not seed.index.equals(seed_days):
            raise ValueError('S007 冻结特征切片不完整')
        segments.append(seed)
    if len(live_days):
        i = sessions.get_loc(live_days[0])
        warmup = max(LIVE_WARMUP_START, sessions[max(0, i - 20)])
        market = data.fetch(StepDataWindow('price_daily', warmup.date(), day))
        if not pd.DatetimeIndex(market.Date).equals(sessions[sessions >= warmup]):
            raise ValueError('S007 后复权日线切片不完整')
        # Each daily feature only needs its own warmup. Align using the
        # trading sessions retained in the price window.
        inputs = {'adjusted_daily': market}
        for name, lower, upper in (
            ('incremental_shibor_daily', max(warmup, sessions[i-9]), stamp),
            ('incremental_chinext_daily_basic', max(warmup, sessions[i-19]), stamp),
            ('incremental_etf_share_size', max(warmup, sessions[i-6]), sessions[-2]),
            ('incremental_spx_daily', max(LIVE_SPX_START, live_days[0] - pd.Timedelta(days=14)), stamp - pd.Timedelta(days=1)),
        ):
            inputs[name] = data.fetch(StepDataWindow(name, lower.date(), upper.date()))
        if not (inputs['incremental_spx_daily'].Date < live_days[0]).any():
            raise ValueError('S007 缺少首个增量交易日之前的标普500记录')
        segments.append(materialize_s007_features(inputs).loc[live_days, features])
    return pd.concat(segments) if len(segments) == 2 else segments[0]


def explain(target, base, confirmation, action, score):
    entry, exit_, confirm = (float(score[key]) for key in
                             ('entry_threshold', 'exit_threshold', 'confirmation_threshold'))
    if action == 'ENTER':
        judgment, summary = '触发入场', '主评分与确认评分均达到买入门槛。'
    elif action == 'EXIT':
        judgment, summary = '目标清仓', '主评分已降至退出线或以下。'
    elif action == 'HOLD_POSITION':
        judgment = '延续目标仓位'
        summary = ('主评分高于退出线。' if np.isfinite(base) else '主评分暂不可用，延续已有目标仓位。')
    else:
        judgment = '继续空仓'
        if not np.isfinite(base):
            summary = '主评分暂不可用。'
        elif base < entry:
            summary = '主评分低于入场线。'
        elif not np.isfinite(confirmation):
            summary = '确认评分暂不可用。'
        else:
            summary = '确认评分低于确认线。'
    base_text = f'{base:.6g}' if np.isfinite(base) else '不可用'
    confirmation_text = f'{confirmation:.6g}' if np.isfinite(confirmation) else '不可用'
    conditions = (f'主评分 {base_text}，入场线 {entry:.6g}，退出线 {exit_:.6g}。'
                  f'确认评分 {confirmation_text}，确认线 {confirm:.6g}。')
    basis = (SignalBasisSnapshot('summary', summary), SignalBasisSnapshot('conditions', conditions))
    return AccountDecision(float(target), SignalExplanationSnapshot(
        'target', 'long' if target else 'flat', judgment, basis,
        '下一交易日收盘后复核主评分与确认评分。', f'{summary} {conditions}'))


def step(ctx, state):
    day = ctx.point.observed_through.astimezone(ZONE).date()
    rule = json.loads(ctx.parameters['rule'])
    prior = dict(state.account.values)
    panel = feature_window(ctx.dfls, day, rule['normalization']['lookback_sessions'],
                           prior['last_signal_date'], sorted(rule['score']['orientations']))
    base, confirmation = (float(series.iloc[-1]) for series in
                          calculate_scores(panel, rule['normalization'], rule['score']))
    target = prior['target']
    action = 'HOLD_POSITION' if target else 'HOLD_CASH'
    if target and base <= rule['score']['exit_threshold']:
        target, action = 0, 'EXIT'
    elif not target and base >= rule['score']['entry_threshold'] and confirmation >= rule['score']['confirmation_threshold']:
        target, action = 1, 'ENTER'
    decision = explain(target, base, confirmation, action, rule['score'])
    return AccountStepResult(decision, StateRecord((('target', target),
        ('last_signal_date', day.isoformat()))), StateRecord())
