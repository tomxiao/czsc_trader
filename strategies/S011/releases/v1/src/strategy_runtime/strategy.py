"""S011 pressure signal: HFQ observations and current-account-equity targets."""
import pandas as pd
from strategy_runtime import AccountDecision, AccountStepResult, StateRecord
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


def step(ctx, state):
    inputs = {'daily': local_frame(ctx.history, daily=True),
        'bars': local_frame(ctx.auxiliary_histories['intraday']),
        'market': local_frame(ctx.observations['market'], daily=True),
        'spx': local_frame(ctx.observations['spx'], timezone='America/New_York', daily=True)}
    history = signal_history(inputs, ctx.parameters)
    row = history.iloc[-1]
    decision = AccountDecision.from_facts(float(row.target_position), str(row.reason),
        facts={'signal_day': history.index[-1].date().isoformat(), 'score': float(row.score),
            'intent_age': int(row.intent_age), 'entry_threshold': ctx.parameters['entry'],
            'exit_threshold': ctx.parameters['exit'], 'max_signal_days': ctx.parameters['max_days'],
            'tail': float(row['tail']), 'market': float(row.market), 'spx': float(row.spx),
            'spx_source_date': str(row.spx_source_time), 'spx_staleness_days': int(row.spx_staleness_days)},
        next_watch='下一交易日压力评分或信号持有期限变化')
    return AccountStepResult(decision, cycle_values=StateRecord())
