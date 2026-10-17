"""Fixed S014 daily strategies; causal fill-state reconstruction, no account sizing."""
from datetime import date,datetime,time
from decimal import Decimal,ROUND_FLOOR,ROUND_HALF_UP
from pathlib import Path
import numpy as np
import pandas as pd
from dataflows import DataRequest,Dataset
from strategy_runtime import (StrategyImplementation,ParameterSet,StrategyDefinition,ObservationDefinition,ObservationSeries,
    InputContract,InputRequirement,CutoffRule,DecisionContract,ExecutionPolicy,MonitoringPolicy,RequiredCapabilities,CalculationScope)
from trading_execution_engine import OrderSpec,DailyQuote,SessionPriceLimits,resolve_fill

VARIANTS=('parent_H1','parent_H3','high_H3','high_H3_low_H1')

def tick(value,mode=ROUND_FLOOR):
    return float((Decimal(str(value))/Decimal('.01')).to_integral_value(rounding=mode)*Decimal('.01'))

def buy_limit(previous_raw_close,previous_scale):
    return min(tick(previous_raw_close*1.01),tick(tick(previous_raw_close*1.1)-.01,ROUND_HALF_UP))*previous_scale

def history(market,raw,limits,status,samples,variant):
    if variant not in VARIANTS:raise ValueError('Unknown fixed variant')
    market=market.set_index(pd.to_datetime(market.Date)).sort_index();raw=raw.set_index(pd.to_datetime(raw.Date)).reindex(market.index)
    bounds=limits.set_index(pd.to_datetime(limits.Date));states=status.set_index(pd.to_datetime(status.Date))
    if market.index.has_duplicates or raw.Close.isna().any():raise ValueError('Unique aligned prices required')
    # Scale anchor cancels out in fill-price comparisons; account sizing remains in SRT.
    scale=market.Close/raw.Close;gap=np.log(market.Open/market.Close.shift());corr=gap.rolling(20).corr(gap.shift())
    parent=(gap<0)&(market.Close>market.Open)
    samples=samples.copy();samples['maturity_date']=pd.to_datetime(samples.maturity_date)
    threshold=None;year=None;held=False;entry=None;horizon=None;intent=None;rows=[]
    for i,day in enumerate(market.index):
        bought=False;sold=False;failed_buy=intent is not None and intent['side']=='BUY'
        if intent is not None:
            if day not in states.index:raise ValueError('Missing stock trading status')
            state=states.loc[day,'Status']
            if state not in ('TRADING','SUSPENDED'):raise ValueError('Unknown trading status')
            if state=='TRADING':
                if day not in bounds.index:raise ValueError('Missing price limits')
                b=bounds.loc[day];bar=market.iloc[i]
                rule=SessionPriceLimits(day.date(),float(b.DownLimit*scale.iloc[i]),float(b.UpLimit*scale.iloc[i]),float(.01*scale.iloc[i]))
                order=OrderSpec('BUY','LIMIT',100,intent['limit']) if intent['side']=='BUY' else OrderSpec('SELL','MARKET',100)
                fill=resolve_fill(order,session_open=float(bar.Open),session_time=datetime.combine(day.date(),time(9,30)),intraday_touches=(),daily_quote=DailyQuote(float(bar.Low),float(bar.High)),session_limits=rule)
                if fill.filled:
                    if intent['side']=='BUY':held=True;entry=i;horizon=intent['horizon'];bought=True;failed_buy=False
                    else:held=False;entry=None;horizon=None;sold=True
        if threshold is None or day.year!=year:
            matured=samples.loc[samples.maturity_date.lt(day)]
            if len(matured)>=60:threshold=float(matured.gap_autocorr.median())
        year=day.year;ready=threshold is not None and np.isfinite(corr.iloc[i]);high=bool(ready and corr.iloc[i]>=threshold)
        intent=None;target=0.;accepted=False
        if held:
            if i>=entry+horizon-1:intent={'side':'SELL'}
            else:target=1.
        elif not failed_buy and ready and parent.iloc[i] and (variant!='high_H3' or high):
            h=1 if variant=='parent_H1' or (variant=='high_H3_low_H1' and not high) else 3
            intent={'side':'BUY','limit':buy_limit(float(raw.Close.iloc[i]),float(scale.iloc[i])),'horizon':h};target=1.;accepted=True
        rows.append({'target_position':target,'parent':bool(parent.iloc[i]),'ready':ready,'high':high,'threshold':threshold,'gap_autocorr':corr.iloc[i],
                     'held_at_close':held,'buy_filled_today':bought,'sell_filled_today':sold,'failed_buy_reset':failed_buy,'entry_signal':accepted,'holding_horizon':horizon or (intent.get('horizon',0) if intent else 0)})
    return pd.DataFrame(rows,index=market.index)

class RepairStrategy(StrategyImplementation):
    def __init__(self,parameters):
        if set(parameters.values)!={'variant'} or parameters.values['variant'] not in VARIANTS:raise ValueError('Exactly one fixed variant required')
        self._parameters=parameters
        self._definition=StrategyDefinition(parameters=parameters,tradable_symbol='600722.SH',
            inputs=InputContract((InputRequirement('calendar',Dataset.TRADING_CALENDAR.value,'SSE','daily',0,CutoffRule.SIGNAL_SESSION),)+tuple(InputRequirement(n,d.value,'600722.SH','daily',1 if n in ('market','raw') else 0,CutoffRule.SIGNAL_SESSION) for n,d in [('market',Dataset.STOCK_OHLCV),('raw',Dataset.STOCK_UNADJUSTED_DAILY),('limits',Dataset.SECURITY_PRICE_LIMITS),('status',Dataset.SECURITY_TRADING_STATUS)])),
            decision=DecisionContract('TARGET_POSITION',0.,1.,'NEXT_SESSION'),
            execution=ExecutionPolicy('FROZEN_RULE',{'capital':{'fee_rate':.001,'mode':'full_available_cash','target_scope':'entry_cycle'},'entry':{'order_type':'LIMIT','limit_parameter':.01},'exit':{'order_type':'MARKET','limit_ratio':.1},'instrument':{'lot_size':100,'maximum_order_quantity':1000000,'price_limit_ratio':.1,'price_tick':.01}}),
            monitoring=MonitoringPolicy('OBSERVE',{}),capabilities=RequiredCapabilities((Dataset.TRADING_CALENDAR.value,Dataset.STOCK_OHLCV.value,Dataset.STOCK_UNADJUSTED_DAILY.value,Dataset.SECURITY_PRICE_LIMITS.value,Dataset.SECURITY_TRADING_STATUS.value),('LIMIT','MARKET')),
            observation=ObservationDefinition((ObservationSeries('environment','高环境','high'),ObservationSeries('opportunity','低开收阳','parent')),()))
    @classmethod
    def from_parameters(cls,parameters:ParameterSet):return cls(parameters)
    @property
    def definition(self):return self._definition
    def calendar_request(self,tradable_window):
        return DataRequest(Dataset.TRADING_CALENDAR,'SSE','2019-12-01',tradable_window.end.isoformat(),tradable_window.end.isoformat())
    def derive_calculation_scope(self,tradable_window,calendar_dates):
        if tradable_window.start!=date(2020,1,2):raise ValueError('This comparison requires the original full-window account start')
        trading=tuple(x for x in calendar_dates if tradable_window.contains(x));signals={x:max(p for p in calendar_dates if p<x) for x in trading}
        first,last=min(signals.values()),max(signals.values());requests={}
        for requirement in self.definition.inputs.requirements:
            if requirement.name=='calendar':continue
            start=max(first,date(2020,1,1)) if requirement.name=='limits' else first
            requests[requirement.name]=DataRequest(requirement.dataset,requirement.subject,start.isoformat(),last.isoformat(),last.isoformat())
        calculation=tuple(x for x in calendar_dates if first<=x<=last)
        return CalculationScope(tradable_window,trading,signals,calculation,requests)
    def calculate_history(self,inputs,sessions):
        samples=pd.read_csv(Path(__file__).with_name('calibration_samples.csv'))
        out=history(inputs['market'],inputs['raw'],inputs['limits'],inputs['status'],samples,self._parameters.values['variant'])
        return out.loc[sessions]
