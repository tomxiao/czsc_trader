"""S007 financial signals produce equity targets; EC owns execution and funding."""
import json
import pandas as pd
from strategy_runtime import (AccountDecision, AccountStepResult, StateRecord,
    SignalBasisSnapshot, SignalExplanationSnapshot)
from .signals import resolve_s007_feature_panel, calculate_s007_history


def signal_history(inputs, parameters, signal_date):
    rule = parameters['rule']
    selected = {'feature_seed': inputs['feature_seed']}
    if signal_date > pd.Timestamp('2026-09-02'):
        selected.update(inputs)
    panel = resolve_s007_feature_panel(selected, rule['score']).loc[:signal_date]
    return calculate_s007_history(panel, rule['normalization'], rule['score'])


def _decision(target, judgment, summary, details, watch):
    basis = (SignalBasisSnapshot('summary', summary), SignalBasisSnapshot('conditions', details),
             SignalBasisSnapshot('target_weight', '本轮以开仓周期锁定的股数为准。' if target else '目标空仓。'))
    return AccountDecision(target, SignalExplanationSnapshot(
        'target', 'long' if target else 'flat', judgment, basis, watch,
        ' '.join(item.text for item in basis)))


def financial_signal(windows, rule):
    inputs = dict(zip(('feature_seed', 'incremental_shibor_daily', 'incremental_chinext_daily_basic', 'incremental_etf_share_size', 'incremental_spx_daily', 'price_daily'), windows, strict=True))
    market = pd.DataFrame([dict(row) for row in inputs.pop('price_daily')])
    dates = pd.to_datetime(market.Date)
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    market['Date'] = dates.dt.normalize()
    day = market.Date.iloc[-1]
    frames = {name: pd.DataFrame([dict(row) for row in rows]) for name, rows in inputs.items()}
    frames['adjusted_daily'] = market
    history = signal_history(frames, {'rule': json.loads(rule)}, day)
    if day not in history.index:
        raise ValueError('S007 signal session is missing')
    row = history.loc[day]
    base = None if pd.isna(row.base_score) else float(row.base_score)
    confirmation = None if pd.isna(row.confirmation_score) else float(row.confirmation_score)
    return float(row.target_position), base, confirmation, str(row.action)


def step(ctx, state):
    for name, count in {'feature_seed': 16384, 'incremental_shibor_daily': 16384, 'incremental_chinext_daily_basic': 16384, 'incremental_etf_share_size': 16384, 'incremental_spx_daily': 16384, 'price_daily': 16384}.items():
        if len(ctx.observations[name]) > count:
            raise ValueError('Canonical observation exceeds declared history: ' + name)
    target, base, confirmation, action = ctx.market_feature('financial_signal')
    base = float('nan') if base is None else base
    confirmation = float('nan') if confirmation is None else confirmation
    score = json.loads(ctx.parameters['rule'])['score']
    entry, exit_, confirm = (float(score[key]) for key in
                             ('entry_threshold', 'exit_threshold', 'confirmation_threshold'))
    if action == 'ENTER':
        judgment, summary = '触发入场', '主评分与确认评分均达到各自的买入门槛。'
    elif action == 'EXIT':
        judgment, summary = '目标清仓', '主评分已降至退出线或以下。'
    elif action == 'HOLD_POSITION':
        judgment = '延续目标仓位'
        summary = ('主评分高于退出线，延续目标仓位。' if pd.notna(base)
                   else '主评分暂不可用，策略延续已有目标仓位。')
    else:
        judgment = '继续空仓'
        if pd.isna(base):
            summary = '主评分暂不可用，继续空仓。'
        elif base < entry:
            summary = '主评分低于入场线，继续空仓。'
        else:
            summary = ('确认评分暂不可用，继续空仓。' if pd.isna(confirmation)
                       else '确认评分低于确认线，继续空仓。')
    base_text = f'{base:.6g}' if pd.notna(base) else '不可用'
    confirm_text = f'{confirmation:.6g}' if pd.notna(confirmation) else '不可用'
    details = (f'主评分 {base_text}，入场线 {entry:.6g}、退出线 {exit_:.6g}。'
               f'确认评分 {confirm_text}，入场确认线 {confirm:.6g}。')
    decision = _decision(target, judgment, summary, details, '下一交易日收盘后更新主评分与确认评分。')
    return AccountStepResult(decision, StateRecord(), StateRecord())
