"""Native V4 execution of both frozen S001 weight sets."""
import pandas as pd
from strategy_runtime import AccountStepResult
from strategy_runtime.equity_replay import StateRecord
from .signal_math import calculate_s001_history
from .cycle_planner import plan_cycle


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
    raw_day = pd.Timestamp(ctx.history.last()['Date']).tz_convert('Asia/Shanghai').normalize().tz_localize(None)
    if day != raw_day:
        raise ValueError('S001 signal and execution reference sessions differ')
    target = float(row.target_position)
    decision, locked = plan_cycle(ctx, signal_target=target, execution=rule['execution'],
        locked_quantity=state.account.get('locked_quantity'), had_position=state.account.get('had_position'),
        reason='持有信号' if target else '空仓信号',
        facts={'signal_day': day.date().isoformat(), 'factor_score': float(row.factor_score),
               'regime': str(row.regime), 'entry_threshold': float(rule['entry_threshold']),
               'exit_threshold': float(rule['exit_threshold']),
               'signal_history_start': '2020-11-16'})
    return AccountStepResult(decision, StateRecord((('locked_quantity', locked),
        ('had_position', bool(ctx.account.quantity)))), StateRecord())
