"""Native V4 three-down transition and independent five-session signal clock."""
import pandas as pd
from strategy_runtime import AccountStepResult
from strategy_runtime.equity_replay import StateRecord
from .signal_math import _calculate_target_history
from .cycle_planner import plan_cycle


def signal_history(observations, rule):
    daily = observations['adjusted_daily'].to_frame()
    dates = pd.to_datetime(daily.Date)
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    daily['Date'] = dates.dt.normalize()
    return _calculate_target_history(daily, symbol='510500.SH', signal=rule['signal'],
                                     portfolio=rule['portfolio_rule'])


def step(ctx, state):
    rule = ctx.parameters['rule']
    history = signal_history(ctx.observations, rule)
    row = history.iloc[-1]
    day = history.index[-1]
    raw_day = pd.Timestamp(ctx.history.last()['Date']).tz_convert('Asia/Shanghai').normalize().tz_localize(None)
    if day != raw_day:
        raise ValueError('S002 signal and execution reference sessions differ')
    target = float(row.target_position)
    decision, locked = plan_cycle(ctx, signal_target=target, execution=rule['execution'],
        locked_quantity=state.account.get('locked_quantity'), had_position=state.account.get('had_position'), reason=str(row.action),
        facts={'signal_day': day.date().isoformat(), 'signal_state': str(row.signal_state),
               'entry_transition': bool(row.entry_transition), 'held_sessions': int(row.held_sessions),
               'holding_sessions': int(rule['portfolio_rule']['holding_sessions']),
               'factor_score': float(row.factor_score)})
    return AccountStepResult(decision, StateRecord((('locked_quantity', locked),
        ('had_position', bool(ctx.account.quantity)))), StateRecord())
