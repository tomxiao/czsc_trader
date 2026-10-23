"""Fixed trend continuation with entry-locked funding exposure, SRT V2."""
from datetime import date
import numpy as np
import pandas as pd
from dataflows import DataRequest,Dataset,DataCoverageRequirement
from strategy_runtime import (StrategyImplementationV2,StrategyDefinition,InputContract,InputRequirement,CutoffRule,
    DecisionContract,ExecutionPolicy,MonitoringPolicy,RequiredCapabilities,ObservationDefinition,ObservationSeries,HistoryPolicy,CalculationScope)

def causal_features(market,shares):
    m=market.copy();m.attrs={};m.index=pd.DatetimeIndex(pd.to_datetime(m.Date))
    s=shares.copy();s.attrs={};s.index=pd.DatetimeIndex(pd.to_datetime(s.Date))
    if not m.index.is_unique or not s.index.is_unique or not m.index.is_monotonic_increasing or not s.index.is_monotonic_increasing:
        raise ValueError('ordered unique dates required')
    # The known listing-day gap is outside every required signal lookback.
    required=m.index[1:-1]
    if not required.isin(s.index).all():raise ValueError('missing share observations in required market history')
    if not s.TotalShare.gt(0).all():raise ValueError('positive shares required')
    v=s.TotalShare.reindex(m.index)
    f=pd.DataFrame({'close':m.Close,'average20':m.Close.rolling(20).mean(),'return5':m.Close/m.Close.shift(5)-1,'funding20':v.shift(1)/v.shift(21)-1})
    f=f.loc['2024-12-31':]
    if not np.isfinite(f.to_numpy(float)).all():raise ValueError('finite causal features required')
    f['trend_ok']=(f.close>f.average20)&(f.return5>0)
    return f

def intentions(f,use_funding):
    age=0;weight=0.;rows=[]
    for v in f.itertuples():
        if age:
            if not v.trend_ok or age>=3:age=0;weight=0.
            else:age+=1
        elif v.trend_ok:
            age=1;weight=1. if not use_funding or v.funding20>0 else .5
        rows.append((weight,age))
    out=f.copy();out['target_position']=[x[0] for x in rows];out['intent_age']=[x[1] for x in rows]
    return out

class FundingTrend(StrategyImplementationV2):
    def __init__(self,parameters):
        p=parameters.values
        if set(p)!={'use_funding'} or type(p['use_funding']) is not bool:raise ValueError('use_funding bool required; fixed design has no tunable parameters')
        inputs=InputContract((
            InputRequirement('market',Dataset.ETF_OHLCV.value,'159326.SZ','daily',61,CutoffRule.SIGNAL_SESSION),
            InputRequirement('execution',Dataset.ETF_UNADJUSTED_DAILY.value,'159326.SZ','daily',1,CutoffRule.SIGNAL_SESSION),
            InputRequirement('shares',Dataset.ETF_SHARE_SIZE.value,'159326.SZ','daily',22,CutoffRule.PREVIOUS_SESSION),
            InputRequirement('calendar',Dataset.TRADING_CALENDAR.value,'SZSE','daily',0,CutoffRule.LATEST_AVAILABLE)))
        self._definition=StrategyDefinition(parameters=parameters,inputs=inputs,
            decision=DecisionContract('TARGET_POSITION',0.,1.,'NEXT_SESSION'),
            execution=ExecutionPolicy('FROZEN_RULE',{'capital':{'fee_rate':.001,'mode':'target_equity_fraction','target_scope':'decision','allocation_fraction':1.},'entry':{'limit_parameter':.01,'order_type':'LIMIT'},'exit':{'limit_ratio':.1,'order_type':'MARKET'},'instrument':{'lot_size':100,'maximum_order_quantity':1000000,'price_limit_ratio':.1,'price_tick':.001}}),
            monitoring=MonitoringPolicy('OBSERVE',{}),capabilities=RequiredCapabilities(tuple(r.dataset for r in inputs.requirements),('LIMIT','MARKET')),
            tradable_symbol='159326.SZ',observation=ObservationDefinition((ObservationSeries('funding20','上一交易日已知20日份额增长','funding20'),ObservationSeries('return5','近5日价格变化','return5'),ObservationSeries('intent_age','市场意图周期年龄','intent_age')),()),history=HistoryPolicy('CANONICAL_REPLAY','2024-12-31','2024-09-09'))
    @classmethod
    def from_parameters(cls,parameters):return cls(parameters)
    @property
    def definition(self):return self._definition
    def calendar_request(self,tradable_window):
        return DataRequest(Dataset.TRADING_CALENDAR,'SZSE','2024-09-09',tradable_window.end.isoformat(),tradable_window.end.isoformat())
    def derive_calculation_scope(self,tradable_window,calendar_dates):
        days=tuple(d for d in calendar_dates if tradable_window.contains(d));signals={d:max(x for x in calendar_dates if x<d) for d in days};end=max(signals.values())
        calc=tuple(d for d in calendar_dates if date(2024,12,31)<=d<=end);requests={}
        for r in self.definition.inputs.requirements:
            if r.name=='calendar':continue
            last=max(d for d in calendar_dates if d<end) if r.name=='shares' else end
            first=min(signals.values());through=max(d for d in calendar_dates if d<first) if r.name=='shares' else first
            requests[r.name]=DataRequest(r.dataset,r.subject,'2024-09-10' if r.name=='shares' else '2024-09-09',last.isoformat(),last.isoformat(),r.frequency,
                coverage=DataCoverageRequirement(maximum_start_lag_days=None,minimum_sessions=r.lookback_sessions,observations_through=through.isoformat()))
        return CalculationScope(tradable_window,days,signals,calc,requests)
    def calculate_context_history(self,inputs,context):
        f=causal_features(inputs['market'],inputs['shares']);out=intentions(f,self.definition.parameters.values['use_funding']).reindex(context.sessions)
        if out.isna().any().any():raise ValueError('missing calculation sessions')
        return out
