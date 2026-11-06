"""Native V4 C9700: original intent history and locked signal cash budget."""
import pandas as pd
from strategy_runtime import AccountStepResult
from strategy_runtime.equity_replay import StateRecord
from .signal_math import causal_features, intentions
from .cycle_planner import plan_cycle


def local_frame(view, *, daily=False):
    frame=view.to_frame()
    frame['Date']=pd.to_datetime(frame.Date).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    if daily:
        frame['Date']=frame.Date.dt.normalize()
    return frame


def signal_history(raw, hfq, intraday, parameters):
    # The canonical start is validated by the original calculation itself.
    raw=raw.loc[raw.Date >= '2024-09-09'].copy()
    hfq=hfq.loc[hfq.Date >= '2024-09-09'].copy()
    intraday=intraday.loc[intraday.Date >= '2025-01-02'].copy()
    return intentions(causal_features(hfq,raw,intraday,parameters['lookback'],parameters['center_kind']),parameters)


def step(ctx,state):
    history=signal_history(local_frame(ctx.history,daily=True),
        local_frame(ctx.auxiliary_histories['hfq'],daily=True),
        local_frame(ctx.auxiliary_histories['intraday']),ctx.parameters)
    row=history.iloc[-1]
    reason='entry' if row.entry_signal else 'exit' if row.exit_signal else 'hold' if row.target_position else 'cash'
    execution={'capital':{'mode':'signal_cash_fraction','target_scope':'entry_cycle','fee_rate':.001},
        'entry':{'order_type':'LIMIT','limit_parameter':.01},'exit':{'order_type':'MARKET','limit_ratio':.1},
        'instrument':{'lot_size':100,'maximum_order_quantity':1000000,'price_limit_ratio':.1,'price_tick':.001}}
    decision,locked=plan_cycle(ctx,signal_target=float(row.target_position),execution=execution,
        locked_quantity=state.account.get('locked_quantity'),had_position=state.account.get('had_position'),reason=reason,allocation=float(ctx.parameters['allocation']),
        facts={'signal_day':history.index[-1].date().isoformat(),'center':float(row.m),'log_price':float(row.p),
            'center_gain':float(row.center_gain),'repair_space':float(row.repair_space),'permission':bool(row.permission),
            'entry_signal':bool(row.entry_signal),'exit_signal':bool(row.exit_signal),
            'repair_target':float(row.repair_target),'invalidation_origin':float(row.invalidation_origin)})
    return AccountStepResult(decision,StateRecord((('locked_quantity',locked),('had_position',bool(ctx.account.quantity)))),StateRecord())
