"""Development prototype: causal short-pressure reversal; no frozen release."""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataflows import Dataset
from strategy_runtime import (
    StrategyImplementation, RuntimeDefinition, ImplementationRef, ParameterSet,
    InputRequirement, InputContract, CutoffRule, DecisionContract, ExecutionPolicy,
    MonitoringPolicy, RequiredCapabilities, HistoryPolicy, InputAlignment,
    AlignmentRule, align_input_history, next_session_calendar_window,
    next_session_calculation_scope,
)

ALIGNMENT = InputAlignment(AlignmentRule.STRICT_PRIOR, 'Date', 'US', 'SSE', 10, False)
FIELDS = ('tail_weight', 'spx_weight', 'entry', 'exit', 'max_days', 'lookback', 'premium')


def indexed(frame):
    frame = frame.copy()
    frame['Date'] = pd.to_datetime(frame.Date)
    if frame.Date.duplicated().any() or not frame.Date.is_monotonic_increasing:
        raise ValueError('unordered or duplicate dates')
    return frame.set_index('Date')


def features(inputs):
    daily = indexed(inputs['daily'])
    market = indexed(inputs['market'])
    bars = inputs['bars'].copy()
    bars['Date'] = pd.to_datetime(bars.Date)
    bars['day'] = bars.Date.dt.normalize()
    bars['clock'] = bars.Date.dt.strftime('%H:%M')
    close = bars.pivot(index='day', columns='clock', values='Close')
    if set(close.columns) != {'10:00','10:30','11:00','11:30','13:30','14:00','14:30','15:00'} or close.isna().any().any():
        raise ValueError('incomplete intraday bars')
    aligned = align_input_history(inputs['spx'], daily.index, ALIGNMENT,
                                  value_columns=('PercentChange',)).dataframe
    aligned.index = daily.index
    output = pd.DataFrame({
        'tail': close['15:00'].div(close['13:30']).sub(1).reindex(daily.index),
        'market': market.Close.pct_change(fill_method=None).reindex(daily.index),
        'spx': aligned.PercentChange,
        'risk5': daily.High.sub(daily.Low).div(daily.Close).rolling(5).mean(),
    }, index=daily.index)
    for col in ('decision_time','source_time','staleness_days'):
        output['spx_'+col] = aligned[col]
    return output


def rank(values, lookback):
    def last(x):
        if not np.isfinite(x[-1]):
            return np.nan
        valid = x[np.isfinite(x)]
        return ((valid < x[-1]).sum()+.5*(valid == x[-1]).sum())/len(valid)-.5
    return values.rolling(lookback, min_periods=20).apply(last, raw=True)


def policy(panel, params, sessions):
    """Signal-cycle expiry is counted from intent, never from an assumed fill."""
    lb = params['lookback']
    tail, market, spx = (-rank(panel['tail'], lb), -rank(panel.market, lb), rank(panel.spx, lb))
    weight = params['tail_weight']
    score = (weight*tail+(1-weight)*market+params['spx_weight']*spx)/(1+params['spx_weight'])
    frame = panel.reindex(sessions).copy()
    frame['score'] = score.reindex(sessions)
    if frame[['tail','market','spx','risk5','score']].isna().any().any():
        raise ValueError('missing input or insufficient causal warmup')
    current, age = 0, 0
    targets, reasons, ages = [], [], []
    for value in frame.score:
        reason = 'HOLD' if current else 'CASH'
        if current:
            age += 1
            if value <= params['exit'] or age >= params['max_days']:
                current, reason = 0, 'PRESSURE_RELEASED' if value <= params['exit'] else 'SIGNAL_EXPIRED'
        elif value >= params['entry']:
            current, age, reason = 1, 0, 'PRESSURE_ENTRY'
        targets.append(current); reasons.append(reason); ages.append(age)
    frame['target_position'] = targets
    frame['reason'] = reasons
    frame['intent_age'] = ages
    return frame


class S011Reversal(StrategyImplementation):
    def __init__(self, candidate):
        self.params = dict(candidate.payload['parameters'])
        if set(self.params) != set(FIELDS):
            raise ValueError('unexpected parameters')
        p = self.params
        if not (0 <= p['tail_weight'] <= 1 and 0 <= p['spx_weight'] <= 1
                and -.5 <= p['exit'] < p['entry'] <= .5
                and type(p['max_days']) is int and 1 <= p['max_days'] <= 3
                and type(p['lookback']) is int and 20 <= p['lookback'] <= 120
                and 0 <= p['premium'] <= .01):
            raise ValueError('parameter bounds violated')
        req = (
            InputRequirement('daily', Dataset.ETF_OHLCV.value, '159326.SZ', 'daily', 30, CutoffRule.SIGNAL_SESSION),
            InputRequirement('bars', Dataset.ETF_OHLCV.value, '159326.SZ', '30m', 30, CutoffRule.SIGNAL_SESSION),
            InputRequirement('execution', Dataset.ETF_UNADJUSTED_DAILY.value, '159326.SZ', 'daily', 1, CutoffRule.SIGNAL_SESSION),
            InputRequirement('market', Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY.value, '000300.SH', 'daily', 30, CutoffRule.SIGNAL_SESSION),
            InputRequirement('spx', Dataset.GLOBAL_INDEX_DAILY.value, 'SPX', 'daily', 30, CutoffRule.LATEST_AVAILABLE, maximum_staleness_days=10, alignment=ALIGNMENT),
            InputRequirement('calendar', Dataset.TRADING_CALENDAR.value, 'SSE', 'daily', 0, CutoffRule.LATEST_AVAILABLE),
        )
        ref = candidate.payload['runtime']
        self._definition = RuntimeDefinition(
            schema_version=2, strategy_family_id='S011', version=None,
            release_id=candidate.reference_id, release_hash=candidate.runtime_identity_sha256,
            implementation=ImplementationRef(ref['module'],ref['qualname'],1,ref['source_sha256']),
            parameters=ParameterSet(p), inputs=InputContract(req),
            decision=DecisionContract('TARGET_POSITION',0.,1.,'NEXT_SESSION_OPEN'),
            execution=ExecutionPolicy('FROZEN_RULE',{
                'capital':{'fee_rate':.001,'mode':'full_available_cash','target_scope':'entry_cycle'},
                'entry':{'order_type':'LIMIT','limit_parameter':p['premium']},
                'exit':{'order_type':'MARKET','limit_ratio':.1},
                'instrument':{'lot_size':100,'maximum_order_quantity':1000000,'price_limit_ratio':.1,'price_tick':.001},
            }), monitoring=MonitoringPolicy('DEVELOPMENT_ONLY',{}),
            capabilities=RequiredCapabilities(tuple(sorted({r.dataset for r in req})),('LIMIT','MARKET')),
            tradable_symbol='159326.SZ', identity_kind='CANDIDATE',candidate_id=candidate.candidate_id,
            history=HistoryPolicy('CANONICAL_REPLAY','2025-02-05','2024-12-26'))

    @classmethod
    def from_candidate(cls, candidate):
        return cls(candidate)

    @property
    def definition(self):
        return self._definition

    def calendar_window(self, window):
        return next_session_calendar_window(self.definition, window)

    def derive_calculation_scope(self, window, dates):
        return next_session_calculation_scope(self.definition, window, dates)

    def calculate_history(self, inputs, sessions):
        panel = features(inputs)
        canonical = panel.index[panel.index >= '2025-02-05']
        return policy(panel,self.params,canonical).reindex(sessions)

    def calculate_window_history(self, inputs, sessions):
        return policy(features(inputs),self.params,sessions)
