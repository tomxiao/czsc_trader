"""Causal pressure-state mechanisms under the unchanged S015 trading contract."""
from datetime import date
import math

import numpy as np
import pandas as pd
from dataflows import DataRequest, Dataset, DataCoverageRequirement
from strategy_runtime import (
    StrategyImplementationV2, StrategyDefinition, InputContract, InputRequirement,
    CutoffRule, DecisionContract, ExecutionPolicy, MonitoringPolicy, RequiredCapabilities,
    ObservationDefinition, ObservationSeries, HistoryPolicy, CalculationScope,
)


EXTRAS = {
    'volume_high': {}, 'volume_low': {}, 'base': {}, 'cross': {}, 'recover': {}, 'deteriorate': {},
    'staged': {'probe': (0.,1.)}, 'delayed': {},
    'trend_up': {'lookback': (2,60)}, 'trend_down': {'lookback': (2,60)},
    'trend_weight': {'lookback': (2,60),'low_weight': (0.,1.)},
    'normalized': {'lookback': (2,60)}, 'cumulative': {'lookback': (2,60)},
    'failed_rebound': {}, 'extend_rebound': {'extension': (1,10)},
    'adaptive_risk': {'lookback': (2,60),'risk_budget': (.001,.1)},
    'price_confirm': {}, 'momentum': {},
}


class PressurePath(StrategyImplementationV2):
    def __init__(self, parameters):
        p = parameters.values
        if p.get('mode') not in EXTRAS or set(p) != {'mode','entry','exit','hold'} | set(EXTRAS[p['mode']]):
            raise ValueError('exact mechanism-specific parameter set required')
        domains = {'entry': (0.,1.),'exit': (0.,1.),'hold': (1,20),**EXTRAS[p['mode']]}
        for k,(lo,hi) in domains.items():
            if isinstance(p[k],bool) or not isinstance(p[k],(int,float)) or not math.isfinite(p[k]) or not lo <= p[k] <= hi:
                raise ValueError(f'invalid {k}')
            if k in ('hold','lookback','extension') and type(p[k]) is not int:
                raise ValueError(f'{k} must be integer')
        inputs = InputContract((
            InputRequirement('market',Dataset.ETF_OHLCV.value,'159326.SZ','daily',61,CutoffRule.SIGNAL_SESSION),
            InputRequirement('execution',Dataset.ETF_UNADJUSTED_DAILY.value,'159326.SZ','daily',1,CutoffRule.SIGNAL_SESSION),
            InputRequirement('calendar',Dataset.TRADING_CALENDAR.value,'SZSE','daily',0,CutoffRule.LATEST_AVAILABLE),
        ))
        self._definition = StrategyDefinition(parameters=parameters,inputs=inputs,
            decision=DecisionContract('TARGET_POSITION',0.,1.,'NEXT_SESSION'),
            execution=ExecutionPolicy('FROZEN_RULE',{
                'capital':{'fee_rate':.001,'mode':'target_equity_fraction','target_scope':'decision','allocation_fraction':1.},
                'entry':{'limit_parameter':.01,'order_type':'LIMIT'},
                'exit':{'limit_ratio':.1,'order_type':'MARKET'},
                'instrument':{'lot_size':100,'maximum_order_quantity':1000000,'price_limit_ratio':.1,'price_tick':.001}}),
            monitoring=MonitoringPolicy('OBSERVE',{}),
            capabilities=RequiredCapabilities(tuple(r.dataset for r in inputs.requirements),('LIMIT','MARKET')),
            tradable_symbol='159326.SZ',observation=ObservationDefinition((
                ObservationSeries('pressure','收盘相对成交均价偏离','pressure'),
                ObservationSeries('intent_age','信号周期年龄','intent_age'),
                ObservationSeries('confirmed','周期内已确认','confirmed'),
            ),()),history=HistoryPolicy('CANONICAL_REPLAY','2024-12-31','2024-09-09'))

    @classmethod
    def from_parameters(cls, parameters):
        return cls(parameters)

    @property
    def definition(self):
        return self._definition

    def calendar_request(self, tradable_window):
        return DataRequest(Dataset.TRADING_CALENDAR,'SZSE','2024-09-09',tradable_window.end.isoformat(),tradable_window.end.isoformat())

    def derive_calculation_scope(self, tradable_window, calendar_dates):
        days = tuple(d for d in calendar_dates if tradable_window.contains(d))
        signals = {d:max(x for x in calendar_dates if x<d) for d in days}
        end = max(signals.values())
        calculations = tuple(d for d in calendar_dates if date(2024,12,31)<=d<=end)
        requests = {r.name:DataRequest(r.dataset,r.subject,'2024-09-09',end.isoformat(),end.isoformat(),r.frequency,
            coverage=DataCoverageRequirement(maximum_start_lag_days=None,minimum_sessions=r.lookback_sessions,
                observations_through=min(signals.values()).isoformat())) for r in self.definition.inputs.requirements if r.name!='calendar'}
        return CalculationScope(tradable_window,days,signals,calculations,requests)

    def calculate_context_history(self, inputs, context):
        m = inputs['market'].copy()
        m.index = pd.DatetimeIndex(pd.to_datetime(m.Date))
        if not m.index.is_unique or not m.index.is_monotonic_increasing:
            raise ValueError('ordered unique market dates required')
        p = self.definition.parameters.values
        mode, lb = p['mode'],p.get('lookback',20)
        pressure = m.Close/(m.Amount/m.Volume)-1
        amount = np.log(m.Amount)
        liquidity = ((amount-amount.rolling(20).mean())/amount.rolling(20).std(ddof=0)
                     if mode in ('volume_high','volume_low') else pd.Series(0.,index=m.index))
        ranges = ((m.High-m.Low)/m.Close).rolling(lb).mean()
        f = pd.DataFrame({'pressure':pressure,'previous':pressure.shift(1),'close':m.Close,
                          'previous_close':m.Close.shift(1),'trend':m.Close/m.Close.shift(lb)-1,
                          'range':ranges,'average':pressure.rolling(lb).mean(),'liquidity':liquidity}).loc['2024-12-31':]
        if not np.isfinite(f.to_numpy()).all() or (f['range']<=0).any():
            raise ValueError('finite causal inputs and positive ranges required')
        age, confirmed, origin_close, origin_pressure = 0,False,0.,0.
        targets,ages,flags = [],[],[]
        for v in f.itertuples(index=False):
            signal = v.pressure/v.range if mode=='normalized' else v.average if mode=='cumulative' else v.pressure
            if age:
                exit_now = signal >= p['exit'] if mode!='momentum' else signal <= -p['exit']
                timed = age >= p['hold']
                if mode=='failed_rebound' and v.close<origin_close and v.pressure<origin_pressure:
                    exit_now = True
                if mode=='extend_rebound' and timed and v.close>origin_close and age < p['hold']+p['extension']:
                    timed = False
                if exit_now or timed:
                    age,confirmed = 0,False
                else:
                    age += 1
                    if v.close>=origin_close and v.pressure>origin_pressure:
                        confirmed = True
            else:
                enter = signal <= -p['entry']
                if mode=='cross':
                    enter = enter and v.previous > -p['entry']
                elif mode=='recover':
                    enter = enter and v.pressure > v.previous
                elif mode=='deteriorate':
                    enter = enter and v.pressure < v.previous
                elif mode=='trend_up':
                    enter = enter and v.trend > 0
                elif mode=='trend_down':
                    enter = enter and v.trend <= 0
                elif mode=='volume_high':
                    enter = enter and v.liquidity>=0
                elif mode=='volume_low':
                    enter = enter and v.liquidity<0
                elif mode=='price_confirm':
                    enter = enter and v.close > v.previous_close
                elif mode=='momentum':
                    enter = signal >= p['entry']
                if enter:
                    age,confirmed,origin_close,origin_pressure = 1,False,v.close,v.pressure
            target = 1. if age else 0.
            if age:
                if mode=='staged' and not confirmed:
                    target = p['probe']
                elif mode=='delayed' and not confirmed:
                    target = 0.
                elif mode=='trend_weight' and v.trend<=0:
                    target = p['low_weight']
                elif mode=='adaptive_risk':
                    target = min(1.,p['risk_budget']/v.range)
            targets.append(target)
            ages.append(age)
            flags.append(float(confirmed))
        f['target_position'],f['intent_age'],f['confirmed'] = targets,ages,flags
        out = f.reindex(context.sessions)
        if out.isna().any().any():
            raise ValueError('missing calculation sessions')
        return out
