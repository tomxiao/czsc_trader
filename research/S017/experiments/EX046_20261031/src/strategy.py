"""M005 actual26 U promotion with one marked-net-profit eligibility comparison."""
from strategy_runtime import (AccountDecision, AccountStepResult, BarField, FeatureGraph,
    Lag, Mean, RawField, ReadyValue, SameLocalSlotMedian, StateField, StateRecord,
    StateValueType, StrategyStateSchema, TrueRange)

OUTPUTS = ('close', 'previous_close', 'previous_open', 'previous_high',
    'previous_volume', 'previous_tr', 'atr_before_prior', 'same_slot_median20','ma65','ma260')


def feature_graph():
    nodes = (RawField('close', BarField.CLOSE), RawField('opening', BarField.OPEN),
        RawField('high', BarField.HIGH), RawField('low', BarField.LOW), RawField('volume', BarField.VOLUME),
        Lag('previous_close', 'close', 1), Lag('previous_open', 'opening', 1),
        Lag('previous_high', 'high', 1), Lag('previous_volume', 'volume', 1),
        TrueRange('tr', 'high', 'low', 'close'), Mean('atr13', 'tr', 13),
        Lag('previous_tr', 'tr', 1), Lag('atr_before_prior', 'atr13', 2),
        SameLocalSlotMedian('same_slot_median20', 'volume', 20, 1),Mean('ma65','close',65),Mean('ma260','close',260))
    return FeatureGraph(nodes, OUTPUTS)


def state_schema():
    return StrategyStateSchema(cycle_fields=(StateField('holding_bars',StateValueType.INT),StateField('last_completed_at',StateValueType.DATETIME),StateField('exit_due',StateValueType.BOOL),StateField('origin',StateValueType.STR),StateField('trend_active',StateValueType.BOOL),StateField('promoted',StateValueType.BOOL),StateField('exit_reason',StateValueType.STR)))

def step(ctx,state):
    if set(ctx.parameters)!={'policy'} or ctx.parameters['policy'] not in ('CONTROL_SLOW','PROFIT_AT26'):raise ValueError('Only declared two promotion policies')
    policy=ctx.parameters['policy'];portfolio=ctx.portfolio
    if portfolio.reference_price_scale!=1. or ctx.events:raise ValueError('Retained RAW NONE-event contract only')
    values={}
    for key in OUTPUTS:
        item=ctx.features.get(key)
        if type(item) is not ReadyValue:raise ValueError('Full warmup required')
        values[key]=float(item.value)
    m005=(values['previous_close']<values['previous_open'] and values['previous_volume']>=1.5*values['same_slot_median20'] and values['previous_tr']<=values['atr_before_prior'] and values['close']>values['previous_high'])
    upward=values['close']>values['ma65']>values['ma260']
    failed=values['close']<values['ma260'] or values['ma65']<values['ma260']
    signal=m005;origin='M005'
    current=ctx.history.last()['Date'];held=portfolio.quantity>0;proposal=None
    facts={**values,'entry_signal':bool(signal),'m005_signal':bool(m005),'trend_ready':bool(upward),'trend_failed':bool(failed),'policy':policy,'held':held,'portfolio_quantity':portfolio.quantity,'portfolio_cash':portfolio.cash,'cycle_present':state.cycle is not None,'holding_bars':0,'exit_due':False,'exit_trigger':'NONE','signal_origin':origin if signal else 'NONE'}
    if held:
        if state.cycle is None or state.cycle.entry_at!=portfolio.cycle_entry or portfolio.cycle_cost<=0:raise ValueError('Actual activated cycle required')
        profitable=portfolio.quantity*values['close']*.999>portfolio.cycle_cost
        facts.update(profitable_at_close=profitable,actual_cycle_cost=portfolio.cycle_cost,marked_net_sale=portfolio.quantity*values['close']*.999)
        saved=dict(state.cycle.values.values)
        if current<=saved['last_completed_at']:raise ValueError('Observation must advance')
        saved['holding_bars']+=1;saved['last_completed_at']=current
        if not saved['exit_due']:
            if saved['holding_bars']==26 and upward and (policy=='CONTROL_SLOW' or profitable):
                saved['trend_active']=True;saved['promoted']=True
            if saved['trend_active'] and failed:saved['exit_due']=True;saved['exit_reason']='TREND_FAILURE'
            elif not saved['trend_active'] and saved['holding_bars']>=26:saved['exit_due']=True;saved['exit_reason']='FIXED_26'
        target=int(not saved['exit_due']);proposal=StateRecord(tuple(saved.items()))
        facts.update(holding_bars=saved['holding_bars'],exit_due=saved['exit_due'],exit_trigger=saved['exit_reason'],cycle_origin=saved['origin'],trend_active=saved['trend_active'],promoted=saved['promoted'])
    else:
        target=int(signal)
        if target:proposal=StateRecord((('holding_bars',0),('last_completed_at',current),('exit_due',False),('origin',origin),('trend_active',origin=='TREND'),('promoted',False),('exit_reason','NONE')))
    return AccountStepResult(AccountDecision.from_facts(target,'Sustained participation policy',facts=facts,next_watch='Completed bar; confirmed fills activate the cycle; latched exit continues',capital_mode='full_available_cash'),StateRecord(),proposal)
