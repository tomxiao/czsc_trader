"""S015 causal price-pressure episodes, with optional entry-size range control."""
from datetime import date
import math

import numpy as np
import pandas as pd
from dataflows import DataRequest, Dataset, DataCoverageRequirement
from strategy_runtime import (
    StrategyImplementationV2, StrategyDefinition, ParameterSet, InputContract,
    InputRequirement, CutoffRule, DecisionContract, ExecutionPolicy,
    MonitoringPolicy, RequiredCapabilities, ObservationDefinition, ObservationSeries,
    CalculationScope, HistoryPolicy,
)


class PressureReversal(StrategyImplementationV2):
    def __init__(self, parameters: ParameterSet):
        p = parameters.values
        if set(p) != {'entry', 'exit', 'max_days', 'range_budget'}:
            raise ValueError('exact four strategy parameters required')
        if type(p['max_days']) is not int or not 1 <= p['max_days'] <= 20:
            raise ValueError('max_days must be an integer in [1,20]')
        for key in ('entry','exit','range_budget'):
            if isinstance(p[key], bool) or not math.isfinite(p[key]) or not 0 <= p[key] <= .1:
                raise ValueError(f'invalid {key}')
        inputs = InputContract((
            InputRequirement('market',Dataset.ETF_OHLCV.value,'159326.SZ','daily',20,CutoffRule.SIGNAL_SESSION),
            InputRequirement('execution',Dataset.ETF_UNADJUSTED_DAILY.value,'159326.SZ','daily',1,CutoffRule.SIGNAL_SESSION),
            InputRequirement('calendar',Dataset.TRADING_CALENDAR.value,'SZSE','daily',0,CutoffRule.LATEST_AVAILABLE),
        ))
        self._definition = StrategyDefinition(
            parameters=parameters, inputs=inputs,
            decision=DecisionContract('TARGET_POSITION',0.,1.,'NEXT_SESSION'),
            execution=ExecutionPolicy('FROZEN_RULE',{
                'capital':{'fee_rate':.001,'mode':'full_available_cash','target_scope':'entry_cycle'},
                'entry':{'limit_parameter':.01,'order_type':'LIMIT'},
                'exit':{'limit_ratio':.1,'order_type':'MARKET'},
                'instrument':{'lot_size':100,'maximum_order_quantity':1000000,
                              'price_limit_ratio':.1,'price_tick':.001}}),
            monitoring=MonitoringPolicy('OBSERVE',{}),
            capabilities=RequiredCapabilities(tuple(x.dataset for x in inputs.requirements),('LIMIT','MARKET')),
            tradable_symbol='159326.SZ',
            observation=ObservationDefinition((
                ObservationSeries('pressure','收盘相对成交均价偏离','pressure'),
                ObservationSeries('range5','近期五日振幅','range5'),
                ObservationSeries('intent_age','信号周期年龄','intent_age'),
            ),()),
            history=HistoryPolicy('CANONICAL_REPLAY','2024-12-31','2024-09-09'),
        )

    @classmethod
    def from_parameters(cls, parameters):
        return cls(parameters)

    @property
    def definition(self):
        return self._definition

    def calendar_request(self, tradable_window):
        return DataRequest(Dataset.TRADING_CALENDAR,'SZSE','2024-09-09',
                           tradable_window.end.isoformat(),tradable_window.end.isoformat())

    def derive_calculation_scope(self, tradable_window, calendar_dates):
        days = tuple(d for d in calendar_dates if tradable_window.contains(d))
        signals = {d:max(x for x in calendar_dates if x<d) for d in days}
        end = max(signals.values())
        calculations = tuple(d for d in calendar_dates if date(2024,12,31)<=d<=end)
        requests = {r.name:DataRequest(r.dataset,r.subject,'2024-09-09',end.isoformat(),
                    end.isoformat(),r.frequency,coverage=DataCoverageRequirement(
                        maximum_start_lag_days=None,minimum_sessions=r.lookback_sessions,
                        observations_through=min(signals.values()).isoformat()))
                    for r in self.definition.inputs.requirements if r.name!='calendar'}
        return CalculationScope(tradable_window,days,signals,calculations,requests)

    def calculate_context_history(self, inputs, context):
        market = inputs['market'].copy()
        market.index = pd.DatetimeIndex(pd.to_datetime(market['Date']))
        if not market.index.is_unique or not market.index.is_monotonic_increasing:
            raise ValueError('market dates must be ordered and unique')
        pressure = market['Close']/(market['Amount']/market['Volume'])-1
        amplitude = ((market['High']-market['Low'])/market['Close']).rolling(5).mean()
        frame = pd.DataFrame({'pressure':pressure,'range5':amplitude}).loc['2024-12-31':]
        if not np.isfinite(frame.to_numpy()).all() or (frame['range5']<=0).any():
            raise ValueError('finite features and positive range required')
        p = self.definition.parameters.values
        age, target = 0, 0.
        targets, ages = [], []
        for pressure_value, range_value in frame.itertuples(index=False,name=None):
            if age:
                if age >= p['max_days'] or pressure_value >= p['exit']:
                    age, target = 0, 0.
                else:
                    age += 1
            elif pressure_value <= -p['entry']:
                age = 1
                target = min(1.,p['range_budget']/range_value) if p['range_budget'] else 1.
            targets.append(target)
            ages.append(age)
        frame['target_position'], frame['intent_age'] = targets, ages
        output = frame.reindex(context.sessions)
        if output.isna().any().any():
            raise ValueError('missing signal sessions')
        return output
