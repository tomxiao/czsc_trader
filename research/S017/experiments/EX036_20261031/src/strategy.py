"""Causal OHLCV mechanism prototypes with explicit confirmed-fill holding duties."""
from strategy_runtime import (AccountDecision, AccountStepResult, BarField, RawField, Mean, Lag,
    TrueRange, FeatureGraph, ReadyValue, StateField, StateValueType, StrategyStateSchema, StateRecord)

OUTPUTS=('close', 'open', 'high', 'low', 'atr', 'ma13', 'ma130', 'atr_old', 'high1', 'high2', 'high3', 'high4', 'high5', 'high6', 'high7', 'high8', 'high9', 'high10', 'high11', 'high12', 'high13', 'high14', 'high15', 'high16', 'high17', 'high18', 'high19', 'high20', 'high21', 'high22', 'high23', 'high24', 'high25', 'high26', 'low1', 'low2', 'low3', 'low4', 'low5', 'low6', 'low7', 'low8', 'low9', 'low10', 'low11', 'low12', 'low13')

def feature_graph():
    return FeatureGraph((RawField('close',BarField.CLOSE),RawField('open',BarField.OPEN),RawField('high',BarField.HIGH),RawField('low',BarField.LOW),TrueRange('tr','high','low','close'),Mean('atr','tr',13),Mean('ma13','close',13),Mean('ma130','close',130),Lag('atr_old','atr',1),Lag('high1','high',1),Lag('high2','high',2),Lag('high3','high',3),Lag('high4','high',4),Lag('high5','high',5),Lag('high6','high',6),Lag('high7','high',7),Lag('high8','high',8),Lag('high9','high',9),Lag('high10','high',10),Lag('high11','high',11),Lag('high12','high',12),Lag('high13','high',13),Lag('high14','high',14),Lag('high15','high',15),Lag('high16','high',16),Lag('high17','high',17),Lag('high18','high',18),Lag('high19','high',19),Lag('high20','high',20),Lag('high21','high',21),Lag('high22','high',22),Lag('high23','high',23),Lag('high24','high',24),Lag('high25','high',25),Lag('high26','high',26),Lag('low1','low',1),Lag('low2','low',2),Lag('low3','low',3),Lag('low4','low',4),Lag('low5','low',5),Lag('low6','low',6),Lag('low7','low',7),Lag('low8','low',8),Lag('low9','low',9),Lag('low10','low',10),Lag('low11','low',11),Lag('low12','low',12),Lag('low13','low',13),),OUTPUTS)

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
    highs=[v[f'high{i}'] for i in range(1,27)]; lows=[v[f'low{i}'] for i in range(1,14)]
    hi13=max(highs[:13]); hi26=max(highs[:26]); hi65=max(highs); lo3=min(lows[:3]); lo13=min(lows[:13]); lo6=min([v['low'],*lows[:5]])
    reclaim=v['close']>highs[0]; mode=p['mechanism']
    signal=v['close']>hi26 and (hi13-lo13)<6*v['atr_old'] and v['close']>v['ma130']
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
        else: raise ValueError('Unknown exit')
        s['due']=s['due'] or risk or economic or s['bars']>=p['maximum']
        target=int(not s['due']); proposal=StateRecord(tuple(s.items()))
        facts.update(holding_bars=s['bars'],exit_due=s['due'],floor=s['floor'],goal=s['goal'],risk_failed=risk,economic_exit=economic)
    else:
        target=int(signal)
        if target:
            proposal=StateRecord((('bars',0),('last',current),('floor',v['close']-3*v['atr']),('goal',hi13),('peak',v['close']),('atr',v['atr']),('due',False)))
    return AccountStepResult(AccountDecision.from_facts(target,'机制状态决策',facts=facts,next_watch='完成柱复核，下一段执行',capital_mode='full_available_cash'),StateRecord(),proposal)
