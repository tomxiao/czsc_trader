"""Causal OHLCV mechanism prototypes with explicit confirmed-fill holding duties."""
from strategy_runtime import (AccountDecision, AccountStepResult, BarField, RawField, Mean, Lag,
    TrueRange, FeatureGraph, ReadyValue, StateField, StateValueType, StrategyStateSchema, StateRecord)

OUTPUTS=('close','open','high','low','ma13','ma65','ma130','ma260','ma13_old','ma65_old','ma65_prior','ma130_old','atr','atr_old','previous_close',*(f'high{i}' for i in range(1,14)),*(f'low{i}' for i in range(1,14)))
def feature_graph():
    return FeatureGraph((RawField('close',BarField.CLOSE),RawField('open',BarField.OPEN),RawField('high',BarField.HIGH),
        RawField('low',BarField.LOW),Mean('ma13','close',13),Mean('ma65','close',65),Mean('ma130','close',130),Mean('ma260','close',260),
        Lag('ma13_old','ma13',1),Lag('ma65_old','ma65',13),Lag('ma65_prior','ma65',1),Lag('ma130_old','ma130',13),TrueRange('tr','high','low','close'),Mean('atr','tr',13),Lag('atr_old','atr',1),Lag('previous_close','close',1),*(Lag(f'high{i}','high',i) for i in range(1,14)),*(Lag(f'low{i}','low',i) for i in range(1,14))),OUTPUTS)
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
    h=ctx.history
    prior=[{'High':v[f'high{i}'],'Low':v[f'low{i}'],'Close':v['previous_close']} for i in range(1,14)]
    hi13=max(float(r['High']) for r in prior[:13]); lo3=min(float(r['Low']) for r in prior[:3])
    lo6=min([v['low'],*[float(r['Low']) for r in prior[:5]]])
    lo13=min(float(r['Low']) for r in prior[:13]); hi26=max(float(r['High']) for r in prior[:26])
    hi65=max(float(r['High']) for r in prior)
    up=v['ma130']>v['ma130_old'] and v['close']>v['ma130']
    reclaim=v['close']>float(prior[0]['High'])
    mode=p['mechanism']
    if mode=='UP_PULLBACK': signal=up and lo6<=v['ma13_old'] and reclaim and v['close']<hi13
    elif mode=='DEEP_REPAIR': signal=v['previous_close']<=v['ma65_prior']-2*v['atr_old'] and reclaim and v['close']<min(v['ma65'],hi13)
    elif mode=='RANGE_EXPANSION': signal=v['close']>hi26 and (hi13-lo13)<6*v['atr_old'] and v['close']>v['ma130']
    elif mode=='FAILED_BREAK': signal=v['low']<lo13 and v['close']>lo13 and v['close']>v['open'] and v['close']>v['ma260']
    elif mode=='CHANNEL_TREND': signal=v['close']>hi65 and v['ma65']>v['ma65_old']
    elif mode=='TREND_REPAIR': signal=v['close']>v['ma260'] and v['close']<v['ma65'] and reclaim
    elif mode=='MOMENTUM_RESTART': signal=v['ma13']>v['ma65']>v['ma130'] and float(prior[0]['Close'])<v['ma13_old'] and reclaim
    elif mode=='DISPLACEMENT': signal=v['close']>v['open']+v['atr'] and v['close']>hi13 and v['close']>v['ma65']
    else: raise ValueError('Unknown predeclared mechanism')
    current=h.last()['Date']; held=ctx.portfolio.quantity>0
    facts={'close':v['close'],'ma13':v['ma13'],'atr':v['atr'],'up':up,'reclaim':reclaim,'entry_context':f"ma130={v['ma130']};ma130old={v['ma130_old']};ma13prev={v['ma13_old']};lo6={lo6};hi13={hi13}",'entry_signal':bool(signal),'held':held,'mechanism':mode,'exit_policy':p['exit'],'holding_bars':0,'exit_due':False}
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
            proposal=StateRecord((('bars',0),('last',current),('floor',lo6-.25*v['atr']),('goal',hi13),('peak',v['close']),('atr',v['atr']),('due',False)))
    return AccountStepResult(AccountDecision.from_facts(target,'机制状态决策',facts=facts,next_watch='完成柱复核，下一段执行',capital_mode='full_available_cash'),StateRecord(),proposal)
