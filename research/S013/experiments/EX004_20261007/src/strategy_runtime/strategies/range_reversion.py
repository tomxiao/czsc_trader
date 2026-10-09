"""S013 causal range reversion; decisions after T17:00, execution T+1 OPEN."""
from datetime import timedelta
import math
import numpy as np
import pandas as pd
from dataflows import DataRequest, DataCoverageRequirement, Dataset
from strategy_runtime import (
    StrategyImplementation, StrategyDefinition, ParameterSet, InputContract,
    InputRequirement, CutoffRule, DecisionContract, ExecutionPolicy, MonitoringPolicy,
    RequiredCapabilities, ObservationDefinition, CalculationScope,
)


def components(frame, range_window=60):
    bars = frame.copy()
    bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
    if not bars.index.is_unique or not bars.index.is_monotonic_increasing:
        raise ValueError('daily input must be unique and ordered')
    close = bars.Close.astype(float)
    low = bars.Low.rolling(range_window).min()
    high = bars.High.rolling(range_window).max()
    position = (close-low)/(high-low)
    def acf(values):
        centered = values-values.mean()
        variance = np.mean(centered**2)
        return np.nan if np.isclose(variance,0) else float(np.dot(centered[1:], centered[:-1])/19/variance)
    persistence = close.pct_change(fill_method=None).rolling(20).apply(acf, raw=True)
    return pd.DataFrame({'range_position': position, 'acf1': persistence, 'close': close,
        'momentum20': close/close.shift(20)-1}, index=bars.index)


class RangeReversion(StrategyImplementation):
    def __init__(self, parameters):
        self._parameters = parameters
        p = parameters.values
        if set(p) != {'range_window','entry','exit','max_hold','acf_min','stop_loss',
                      'trailing_stop','cooldown','momentum_min','limit_premium'}:
            raise ValueError('exact parameter contract required')
        if type(p['range_window']) is not int or not 21 <= p['range_window'] <= 180:
            raise ValueError('range_window must be 21..180 sessions')
        if not 0 <= p['entry'] < p['exit'] <= 1:
            raise ValueError('range thresholds must satisfy 0 <= entry < exit <= 1')
        if type(p['max_hold']) is not int or not 1 <= p['max_hold'] <= 60:
            raise ValueError('max_hold must be 1..60')
        if type(p['cooldown']) is not int or not 0 <= p['cooldown'] <= 20:
            raise ValueError('cooldown must be 0..20')
        for key in ('stop_loss','trailing_stop'):
            if p[key] is not None and not 0 < p[key] < .5:
                raise ValueError(key+' must be null or positive fraction below .5')
        for key in ('acf_min','momentum_min'):
            if p[key] is not None and not math.isfinite(p[key]):
                raise ValueError(key+' must be finite or null')
        if not 0 <= p['limit_premium'] < .09:
            raise ValueError('limit_premium outside instrument range')

    @classmethod
    def from_parameters(cls, parameters: ParameterSet):
        return cls(parameters)

    @property
    def definition(self):
        p = self._parameters.values
        return StrategyDefinition(
            parameters=self._parameters,
            inputs=InputContract((InputRequirement('daily','etf.ohlcv','510500.SH',
                'daily',max(21,p['range_window']),CutoffRule.SIGNAL_SESSION),
                InputRequirement('execution','etf.unadjusted_daily','510500.SH','daily',1,CutoffRule.SIGNAL_SESSION),
                InputRequirement('calendar','calendar.trading_sessions','SSE','daily',0,CutoffRule.SIGNAL_SESSION))),
            decision=DecisionContract('TARGET_POSITION',0.0,1.0,'NEXT_SESSION'),
            execution=ExecutionPolicy('FROZEN_RULE',{
                'instrument':{'lot_size':100,'price_tick':.001,'price_limit_ratio':.10,
                              'maximum_order_quantity':1_000_000},
                'capital':{'mode':'AVAILABLE_CASH','allocation_fraction':1.0,
                           'fee_rate':.001,'target_scope':'STRATEGY'},
                'entry':{'order_type':'LIMIT','limit_parameter':p['limit_premium']},
                'exit':{'order_type':'MARKET','limit_ratio':.10}}),
            monitoring=MonitoringPolicy('RESEARCH',{'frequency_window_sessions':60}),
            capabilities=RequiredCapabilities(('etf.ohlcv','etf.unadjusted_daily','calendar.trading_sessions'),('LIMIT','MARKET'),('OPEN',)),
            tradable_symbol='510500.SH', observation=ObservationDefinition((),()),
        )

    def calendar_request(self, window):
        warmup = max(item.lookback_sessions for item in self.definition.inputs.requirements)
        start = window.start - timedelta(days=max(45, warmup * 2))
        return DataRequest(Dataset.TRADING_CALENDAR, 'SSE', start.isoformat(),
                           window.end.isoformat(), window.end.isoformat())

    def derive_calculation_scope(self, window, calendar_dates):
        trading = tuple(day for day in calendar_dates if window.contains(day))
        if not trading or trading[0] != window.start or trading[-1] != window.end:
            raise ValueError('tradable window endpoints must be open sessions')
        signals = {}
        for day in trading:
            previous = tuple(item for item in calendar_dates if item < day)
            if not previous:
                raise ValueError('trading calendar lacks preceding signal session')
            signals[day] = previous[-1]
        first, last = signals[trading[0]], signals[trading[-1]]
        available = tuple(day for day in calendar_dates if day <= first)
        inputs = {}
        for item in self.definition.inputs.requirements:
            if item.dataset == Dataset.TRADING_CALENDAR.value:
                continue
            depth = max(1, item.lookback_sessions)
            if len(available) < depth:
                raise ValueError('trading calendar cannot satisfy input history: ' + item.name)
            if item.cutoff_rule is not CutoffRule.SIGNAL_SESSION:
                raise ValueError('S013 inputs require signal-session cutoff')
            start = available[-depth]
            coverage = DataCoverageRequirement(
                maximum_start_lag_days=None, minimum_observations=depth,
                minimum_sessions=depth, observations_through=first.isoformat())
            inputs[item.name] = DataRequest(
                item.dataset, item.subject, start.isoformat(), last.isoformat(),
                last.isoformat(), item.frequency, coverage=coverage)
        calculation = tuple(day for day in calendar_dates if first <= day <= last)
        return CalculationScope(window, trading, signals, calculation, inputs)

    def calculate_history(self, inputs, sessions):
        p = self._parameters.values
        feature = components(inputs['daily'],p['range_window']).reindex(sessions)
        if not np.isfinite(feature.to_numpy()).all():
            raise ValueError('required causal features missing')
        holding = False
        age = 0
        cooldown = 0
        anchor = peak = 0.0
        targets, reasons = [], []
        for row in feature.itertuples():
            reason = 'flat'
            if holding:
                age += 1
                peak = max(peak,row.close)
                loss = p['stop_loss'] is not None and row.close/anchor-1 <= -p['stop_loss']
                trail = p['trailing_stop'] is not None and row.close/peak-1 <= -p['trailing_stop']
                if loss or trail or row.range_position >= p['exit'] or age >= p['max_hold']:
                    holding = False
                    cooldown = p['cooldown']
                    reason = 'loss' if loss else 'trailing' if trail else 'range' if row.range_position >= p['exit'] else 'time'
                else:
                    reason = 'hold'
            elif cooldown:
                cooldown -= 1
                reason = 'cooldown'
            elif (row.range_position <= p['entry']
                  and (p['acf_min'] is None or row.acf1 >= p['acf_min'])
                  and (p['momentum_min'] is None or row.momentum20 >= p['momentum_min'])):
                holding = True
                age = 0
                anchor = peak = row.close
                reason = 'entry'
            targets.append(float(holding))
            reasons.append(reason)
        return feature.assign(target_position=targets,signal_reason=reasons)
