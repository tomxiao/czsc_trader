"""Existing M005/M008 entries with one confirmed-fill 65-bar holding rule."""
from strategy_runtime import (AccountDecision, AccountStepResult, BarField, FeatureGraph,
    Lag, Mean, RawField, ReadyValue, SameLocalSlotMedian, StateField, StateRecord,
    StateValueType, StrategyStateSchema, TrueRange)

OUTPUTS = ('close', 'previous_close', 'previous_open', 'previous_high',
    'previous_volume', 'previous_tr', 'atr_before_prior', 'same_slot_median20','opening','low','atr13','atr_prior',*(f'low{i}' for i in range(1,6)))


def feature_graph():
    nodes = (RawField('close', BarField.CLOSE), RawField('opening', BarField.OPEN),
        RawField('high', BarField.HIGH), RawField('low', BarField.LOW), RawField('volume', BarField.VOLUME),
        Lag('previous_close', 'close', 1), Lag('previous_open', 'opening', 1),
        Lag('previous_high', 'high', 1), Lag('previous_volume', 'volume', 1),
        TrueRange('tr', 'high', 'low', 'close'), Mean('atr13', 'tr', 13),
        Lag('previous_tr', 'tr', 1), Lag('atr_before_prior', 'atr13', 2),
        SameLocalSlotMedian('same_slot_median20', 'volume', 20, 1),Lag('atr_prior','atr13',1),*(Lag(f'low{i}','low',i) for i in range(1,6)))
    return FeatureGraph(nodes, OUTPUTS)


def state_schema():
    return StrategyStateSchema(cycle_fields=(StateField('holding_bars', StateValueType.INT),
        StateField('last_completed_at', StateValueType.DATETIME), StateField('exit_due', StateValueType.BOOL),StateField('origin',StateValueType.STR),StateField('floor',StateValueType.FLOAT),StateField('peak',StateValueType.FLOAT),StateField('atr',StateValueType.FLOAT)))


def step(ctx,state):
    p=ctx.parameters
    if set(p)!={'mechanism','exit','maximum'} or p['mechanism']!='M005_GAP_UNION' or p['exit'] not in ('SOURCE','TIME') or p['maximum']!=65:raise ValueError('Declared union policies only')
    v={}
    for key in OUTPUTS:
        value=ctx.features.get(key)
        if type(value) is not ReadyValue:raise ValueError('Full warmup required')
        v[key]=float(value.value)
    if ctx.events or ctx.portfolio.reference_price_scale!=1.:raise ValueError('Retained RAW NONE-action contract')
    from zoneinfo import ZoneInfo
    current=ctx.history.last(); previous=ctx.history.last(1); zone=ZoneInfo('America/New_York')
    local=current['BarStart'].astimezone(zone); prior=previous['Date'].astimezone(zone)
    first=local.hour==9 and local.minute==30 and prior.date()<local.date()
    m005=v['previous_close']<v['previous_open'] and v['close']>v['previous_high'] and v['previous_volume']>=1.5*v['same_slot_median20'] and v['previous_tr']<=v['atr_before_prior']
    gap=first and v['opening']<=v['previous_close']-v['atr_prior'] and v['close']>v['previous_close']
    signal=m005 or gap; origin='M005' if m005 else 'GAP'; held=ctx.portfolio.quantity>0; proposal=None
    facts={'entry_signal':bool(signal),'m005_signal':bool(m005),'gap_signal':bool(gap),'signal_origin':origin if signal else 'NONE','held':held,'holding_bars':0,'exit_due':False,'exit_policy':p['exit']}
    if held:
        if state.cycle is None or state.cycle.entry_at!=ctx.portfolio.cycle_entry:raise ValueError('Actual cycle required')
        saved=dict(state.cycle.values.values)
        if current['Date']<=saved['last_completed_at']:raise ValueError('Observation must advance')
        saved['holding_bars']+=1;saved['last_completed_at']=current['Date'];saved['peak']=max(saved['peak'],v['close'])
        risk=p['exit']=='SOURCE' and saved['origin']=='GAP' and v['close']<saved['floor']
        trailing=p['exit']=='SOURCE' and saved['origin']=='GAP' and v['close']<saved['peak']-3*saved['atr']
        saved['exit_due']=saved['exit_due'] or risk or trailing or saved['holding_bars']>=65
        target=int(not saved['exit_due']);proposal=StateRecord(tuple(saved.items()))
        facts.update(holding_bars=saved['holding_bars'],exit_due=saved['exit_due'],cycle_origin=saved['origin'],risk_failed=risk,trailing_exit=trailing)
    else:
        target=int(signal)
        if target:
            floor=min([v['low'],*(v[f'low{i}'] for i in range(1,6))])-.25*v['atr13']
            proposal=StateRecord((('holding_bars',0),('last_completed_at',current['Date']),('exit_due',False),('origin',origin),('floor',floor),('peak',v['close']),('atr',v['atr13'])))
    return AccountStepResult(AccountDecision.from_facts(target,'Union policy',facts=facts,next_watch='Confirm completed bar, execute next interval',capital_mode='full_available_cash'),StateRecord(),proposal)
