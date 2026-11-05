"""Native V4 S007 causal scores with independent intent and frozen cycle sizing."""
import pandas as pd
from strategy_runtime import AccountStepResult, StateRecord
from .signals import resolve_s007_feature_panel, calculate_s007_history
from .cycle_planner import plan_cycle


def signal_history(inputs, parameters, signal_date):
    rule = parameters['rule']
    selected = {'feature_seed':inputs['feature_seed']}
    if signal_date > pd.Timestamp('2026-09-02'):
        selected.update(inputs)
    panel = resolve_s007_feature_panel(selected, rule['score']).loc[:signal_date]
    return calculate_s007_history(panel, rule['normalization'], rule['score'])


def step(ctx, state):
    day = pd.Timestamp(ctx.history.last()['Date']).tz_convert('Asia/Shanghai').tz_localize(None).normalize()
    inputs = {name:view.to_frame() for name,view in ctx.observations.items()}
    market = ctx.auxiliary_histories['adjusted_daily'].to_frame()
    market['Date'] = pd.to_datetime(market.Date).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None).dt.normalize()
    inputs['adjusted_daily'] = market
    history = signal_history(inputs, ctx.parameters, day)
    if day not in history.index:
        raise ValueError('S007 signal session is missing')
    current = history.loc[day]
    target = float(current.target_position)
    decision, locked = plan_cycle(ctx, signal_target=target,
        execution=ctx.parameters['rule']['execution'],
        locked_quantity=state.account.get('locked_quantity'), had_position=state.account.get('had_position'), reason=str(current.action),
        facts={'base_score':str(current.base_score),'confirmation_score':str(current.confirmation_score),
               'signal_date':day.date().isoformat()})
    return AccountStepResult(decision, StateRecord((('locked_quantity',locked),('had_position',bool(ctx.account.quantity)))),
        StateRecord() if ctx.account.quantity or target else None)
