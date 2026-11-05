"""Native V4 S011: causal pressure signal and unchanged intent-clock expiry."""
import pandas as pd
from strategy_runtime import AccountStepResult
from strategy_runtime.equity_replay import StateRecord
from .signal_math import features, policy
from .cycle_planner import plan_cycle


def local_frame(view, *, timezone='Asia/Shanghai', daily=False):
    frame=view.to_frame()
    stamp=pd.to_datetime(frame.Date)
    if stamp.dt.tz is not None:
        stamp=stamp.dt.tz_convert(timezone).dt.tz_localize(None)
    frame['Date']=stamp.dt.normalize() if daily else stamp
    return frame


def signal_history(inputs, parameters):
    for name in ('daily','market','bars'):
        first=pd.Timestamp(inputs[name].Date.iloc[0]).normalize()
        if first!=pd.Timestamp('2024-12-26'):
            raise ValueError('S011 canonical history is missing: '+name)
    panel=features(inputs)
    sessions=panel.index[panel.index >= pd.Timestamp('2025-02-05')]
    if len(sessions)==0 or sessions[0]!=pd.Timestamp('2025-02-05'):
        raise ValueError('S011 canonical signal start is missing')
    return policy(panel,parameters,sessions)


def step(ctx,state):
    inputs={'daily':local_frame(ctx.auxiliary_histories['hfq'],daily=True),
        'bars':local_frame(ctx.auxiliary_histories['intraday']),
        'market':local_frame(ctx.observations['market'],daily=True),
        'spx':local_frame(ctx.observations['spx'],timezone='America/New_York',daily=True)}
    history=signal_history(inputs,ctx.parameters)
    row=history.iloc[-1]
    execution={'capital':{'mode':'full_available_cash','target_scope':'entry_cycle','fee_rate':.001},
        'entry':{'order_type':'LIMIT','limit_parameter':ctx.parameters['premium']},
        'exit':{'order_type':'MARKET','limit_ratio':.1},
        'instrument':{'lot_size':100,'maximum_order_quantity':1000000,'price_limit_ratio':.1,'price_tick':.001}}
    decision,locked=plan_cycle(ctx,signal_target=float(row.target_position),execution=execution,
        locked_quantity=state.account.get('locked_quantity'),had_position=state.account.get('had_position'),reason=str(row.reason),
        facts={'signal_day':history.index[-1].date().isoformat(),'score':float(row.score),
            'intent_age':int(row.intent_age),'entry_threshold':ctx.parameters['entry'],
            'exit_threshold':ctx.parameters['exit'],'max_signal_days':ctx.parameters['max_days'],
            'tail':float(row['tail']),'market':float(row.market),'spx':float(row.spx),
            'spx_source_date':str(row.spx_source_time),'spx_staleness_days':int(row.spx_staleness_days)})
    return AccountStepResult(decision,StateRecord((('locked_quantity',locked),('had_position',bool(ctx.account.quantity)))),StateRecord())
