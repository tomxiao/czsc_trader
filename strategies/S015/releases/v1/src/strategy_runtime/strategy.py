"""S015 repair signal using HFQ daily/30m observations, target equity allocation."""
import pandas as pd
from strategy_runtime import AccountDecision, AccountStepResult, StateRecord
from .signal_math import causal_features, intentions


def local_frame(view, *, daily=False):
    frame = view.to_frame()
    dates = pd.to_datetime(frame.Date)
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    frame['Date'] = dates.dt.normalize() if daily else dates
    return frame


def signal_history(hfq, intraday, parameters):
    hfq = hfq.loc[hfq.Date >= '2024-09-09'].copy()
    intraday = intraday.loc[intraday.Date >= '2025-01-02'].copy()
    return intentions(causal_features(hfq, intraday, parameters['lookback'], parameters['center_kind']), parameters)


def step(ctx, state):
    history = signal_history(local_frame(ctx.history, daily=True),
        local_frame(ctx.auxiliary_histories['intraday']), ctx.parameters)
    row = history.iloc[-1]
    reason = 'entry' if row.entry_signal else 'exit' if row.exit_signal else 'hold' if row.target_position else 'cash'
    target = float(row.target_position) * float(ctx.parameters['allocation'])
    decision = AccountDecision.from_facts(target, reason,
        facts={'signal_day': history.index[-1].date().isoformat(), 'center': float(row.m), 'log_price': float(row.p),
            'center_gain': float(row.center_gain), 'repair_space': float(row.repair_space), 'permission': bool(row.permission),
            'entry_signal': bool(row.entry_signal), 'exit_signal': bool(row.exit_signal),
            'repair_target': float(row.repair_target), 'invalidation_origin': float(row.invalidation_origin),
            'allocation': float(ctx.parameters['allocation'])}, next_watch='下一交易日修复目标或中心失效条件变化')
    return AccountStepResult(decision, cycle_values=StateRecord())
