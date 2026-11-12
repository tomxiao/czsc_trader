"""S007 financial signals produce equity targets; EC owns execution and funding."""
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
             SignalBasisSnapshot('target_weight', f'目标仓位为账户权益的 {target:.2%}。'))
    return AccountDecision(target, SignalExplanationSnapshot(
        'target', 'long' if target else 'flat', judgment, basis, watch,
        ' '.join(item.text for item in basis)))


def step(ctx, state):
    market = ctx.history.to_frame()
    market['Date'] = pd.to_datetime(market.Date).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None).dt.normalize()
    day = market.Date.iloc[-1]
    inputs = {name: view.to_frame() for name, view in ctx.observations.items()}
    inputs['adjusted_daily'] = market
    history = signal_history(inputs, ctx.parameters, day)
    if day not in history.index:
        raise ValueError('S007 signal session is missing')
    current = history.loc[day]
    target = float(current.target_position)
    score = ctx.parameters['rule']['score']
    base, confirmation = float(current.base_score), float(current.confirmation_score)
    entry, exit_, confirm = (float(score[key]) for key in
                             ('entry_threshold', 'exit_threshold', 'confirmation_threshold'))
    action = str(current.action)
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
