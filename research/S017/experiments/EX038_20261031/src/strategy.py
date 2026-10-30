"""Causal OHLCV mechanism prototypes with explicit confirmed-fill holding duties."""
from strategy_runtime import (AccountDecision, AccountStepResult, BarField, RawField, Mean, Lag,
    TrueRange, FeatureGraph, ReadyValue, StateField, StateValueType, StrategyStateSchema, StateRecord)

OUTPUTS=('close', 'open', 'high', 'low', 'atr', 'ma13', 'close13', 'high1', 'low1', 'low2', 'low3', 'low4', 'low5')

def feature_graph():
    return FeatureGraph((RawField('close',BarField.CLOSE),RawField('open',BarField.OPEN),RawField('high',BarField.HIGH),RawField('low',BarField.LOW),TrueRange('tr','high','low','close'),Mean('atr','tr',13),Mean('ma13','close',13),Lag('close13','close',13),Lag('high1','high',1),Lag('low1','low',1),Lag('low2','low',2),Lag('low3','low',3),Lag('low4','low',4),Lag('low5','low',5),),OUTPUTS)

def state_schema():
    return StrategyStateSchema(cycle_fields=(StateField('bars',StateValueType.INT),StateField('last',StateValueType.DATETIME),
        StateField('floor',StateValueType.FLOAT),StateField('goal',StateValueType.FLOAT),StateField('peak',StateValueType.FLOAT),
        StateField('atr',StateValueType.FLOAT),StateField('due',StateValueType.BOOL)))
def step(ctx,state):
    p=ctx.parameters
    if set(p)!={'mechanism','exit','maximum'}: raise ValueError('Exact declared parameters required')
    v={}
    for key in OUTPUTS:
        item=ctx.features.get(key)
        if type(item) is not ReadyValue: raise ValueError('Full warmup required')
        v[key]=float(item.value)
    if ctx.events or ctx.portfolio.reference_price_scale!=1.: raise ValueError('Retained NONE-action RAW contract only')
    current=ctx.history.last()['Date']; held=ctx.portfolio.quantity>0
    highs=[v[f'high{i}'] for i in range(1,2)]; lows=[v[f'low{i}'] for i in range(1,6)]
    hi13=max(highs[:13]); hi26=max(highs[:26]); hi65=max(highs); lo3=min(lows[:3]); lo13=min(lows[:13]); lo6=min([v['low'],*lows[:5]])
    reclaim=v['close']>highs[0]; mode=p['mechanism']
    local_start=ctx.history.last()['BarStart'].astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')); prior_local=ctx.history.last(1)['Date'].astimezone(__import__('zoneinfo').ZoneInfo('America/New_York'))
    first=local_start.hour==9 and local_start.minute==30 and prior_local.date()<local_start.date()
    signal=v['atr']>0 and v['close']-v['close13']>.3*13*v['atr']
    facts={'close':v['close'],'ma13':v['ma13'],'atr':v['atr'],'entry_signal':bool(signal),'held':held,'mechanism':mode,'exit_policy':p['exit'],'holding_bars':0,'exit_due':False}
    proposal=None
    if held:
        if state.cycle is None or state.cycle.entry_at!=ctx.portfolio.cycle_entry: raise ValueError('Actual cycle required')
        s=dict(state.cycle.values.values)
        if current<=s['last']: raise ValueError('Observation must advance')
        s['bars']+=1; s['last']=current; s['peak']=max(s['peak'],v['close'])
        risk=v['close']<s['floor']
        if p['exit']=='TARGET': economic=v['close']>=s['goal']
        elif p['exit']=='STRUCTURE': economic=v['close']<v['ma13'] and v['close']<lo3
        elif p['exit']=='CHANNEL': economic=v['close']<lo13
        elif p['exit']=='TRAIL': economic=v['close']<s['peak']-3*s['atr']
        elif p['exit']=='MEAN': economic=v['close']>=v['ma65']
        elif p['exit']=='EFFICIENCY': economic=v['close']<v['close13']
        elif p['exit']=='TIME': economic=False
        else: raise ValueError('Unknown exit')
        s['due']=s['due'] or risk or economic or s['bars']>=p['maximum']
        target=int(not s['due']); proposal=StateRecord(tuple(s.items()))
        facts.update(holding_bars=s['bars'],exit_due=s['due'],floor=s['floor'],goal=s['goal'],risk_failed=risk,economic_exit=economic)
    else:
        target=int(signal)
        if target:
            proposal=StateRecord((('bars',0),('last',current),('floor',v['close']-3*v['atr']),('goal',hi13),('peak',v['close']),('atr',v['atr']),('due',False)))
    return AccountStepResult(AccountDecision.from_facts(target,'机制状态决策',facts=facts,next_watch='完成柱复核，下一段执行',capital_mode='full_available_cash'),StateRecord(),proposal)
