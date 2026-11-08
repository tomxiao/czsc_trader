"""S001 completed-week financial signals expressed only as equity target weights."""
import pandas as pd
from strategy_runtime import AccountDecision, AccountStepResult, StateRecord
from .signal_math import calculate_s001_history


def local_frame(view, *, daily=False):
    frame = view.to_frame()
    dates = pd.to_datetime(frame['Date'])
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    frame['Date'] = dates.dt.normalize() if daily else dates
    return frame


def signal_history(observations, rule):
    daily = local_frame(observations['adjusted_daily'], daily=True)
    intraday = local_frame(observations['adjusted_30m'])
    weekly = local_frame(observations['adjusted_weekly'], daily=True)
    if daily.Date.iloc[0] != pd.Timestamp('2020-11-16'):
        raise ValueError('S001 requires its frozen canonical history from 2020-11-16')
    return calculate_s001_history(intraday, daily, weekly, rule, '588080.SH')


def step(ctx, state):
    rule = ctx.parameters['rule']
    history = signal_history(ctx.observations, rule)
    row = history.iloc[-1]
    day = history.index[-1]
    observation_day = pd.Timestamp(ctx.history.last()['Date']).tz_convert('Asia/Shanghai').normalize().tz_localize(None)
    if day != observation_day:
        raise ValueError('S001 signal and primary observation sessions differ')
    target = float(row.target_position)
    decision = AccountDecision.from_facts(target, '持有信号' if target else '空仓信号',
        facts={'signal_day': day.date().isoformat(), 'factor_score': float(row.factor_score),
               'regime': str(row.regime), 'entry_threshold': float(rule['entry_threshold']),
               'exit_threshold': float(rule['exit_threshold']), 'signal_history_start': '2020-11-16',
               'signal_target': target},
        next_watch='下一交易日收盘更新已完成周期信号与目标仓位')
    return AccountStepResult(decision, cycle_values=StateRecord())
