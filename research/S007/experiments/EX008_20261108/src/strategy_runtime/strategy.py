"""S007 financial signals produce equity targets; EC owns execution and funding."""
import pandas as pd
from strategy_runtime import AccountDecision, AccountStepResult, StateRecord
from .signals import resolve_s007_feature_panel, calculate_s007_history


def signal_history(inputs, parameters, signal_date):
    rule = parameters['rule']
    selected = {'feature_seed': inputs['feature_seed']}
    if signal_date > pd.Timestamp('2026-09-02'):
        selected.update(inputs)
    panel = resolve_s007_feature_panel(selected, rule['score']).loc[:signal_date]
    return calculate_s007_history(panel, rule['normalization'], rule['score'])


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
    decision = AccountDecision.from_facts(float(current.target_position), str(current.action),
        facts={'base_score': str(current.base_score), 'confirmation_score': str(current.confirmation_score),
               'signal_date': day.date().isoformat()}, next_watch='下一已完成信号日')
    return AccountStepResult(decision, StateRecord(), None)
