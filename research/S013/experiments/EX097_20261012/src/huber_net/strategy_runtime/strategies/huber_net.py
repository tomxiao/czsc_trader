"""Source-only original14 Huber strategy; original EX080 data/execution contract.

Positive Huber location is an opportunity score, not a conditional expected
net-profit claim.  Future test labels and final-year outcomes never gate forecasts.
"""
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from strategy_runtime.pricing import ExecutionPricing, ExecutionPriceBasis
from datetime import date
from .confirm_net import ConfirmNet
from .confirm_kernel import parameters as original_parameters, rebuild, episode_history, dates
from .huber_kernel import hyperparameters, forecasts


def parameters(confirmation_lookback=120, holding_sessions=4, ridge_alpha=10.0, huber_multiple=1.345):
    original_parameters(confirmation_lookback, holding_sessions, ridge_alpha)
    hyperparameters(ridge_alpha, huber_multiple)


def net_labels(prices, sessions, holding_sessions):
    parameters(holding_sessions=holding_sessions)
    axis, price_axis = dates(sessions), dates(prices.index)
    if not axis.isin(price_axis).all() or not {'Open', 'Close'}.issubset(prices.columns):
        raise ValueError('Complete native OPEN/CLOSE signal axis required')
    values = prices[['Open', 'Close']].to_numpy(float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('Finite positive native prices required')
    net = (prices.Open.shift(-holding_sessions - 1) / prices.Open.shift(-1) * (.999 / 1.001) - 1).reindex(axis)
    ends = pd.Series(price_axis, index=price_axis).shift(-holding_sessions - 1).reindex(axis)
    return pd.DataFrame({'return_4': net, 'label_end_return_4': ends}, index=axis)


def prepare_history(p, inputs, sessions):
    parameters(**p)
    inputs = {name: pd.DataFrame(value, copy=False) for name, value in inputs.items()}
    rename = {'Date': 'dt', 'Open': 'open', 'High': 'high', 'Low': 'low',
              'Close': 'close', 'Volume': 'vol', 'Amount': 'amount'}

    def numerical(frame):
        out = frame.loc[:, list(rename)].rename(columns=rename).copy()
        out.dt = pd.to_datetime(out.dt).dt.as_unit('ns')
        return out

    adjusted, raw, intra = numerical(inputs['daily']), numerical(inputs['execution']), numerical(inputs['intraday'])
    last = pd.Timestamp(sessions[-1])
    raw = raw.loc[raw.dt <= last].copy()
    intra = intra.loc[intra.dt.dt.normalize() <= last].copy()
    pricing = ExecutionPricing(ExecutionPriceBasis.HFQ_RESEARCH, date(2019, 12, 31), .2803)
    native = pricing.apply(raw, raw_daily=raw, adjusted_daily=adjusted).rename(columns={v: k for k, v in rename.items()})
    bars = pricing.apply(intra, raw_daily=raw, adjusted_daily=adjusted).rename(columns={v: k for k, v in rename.items()})
    features = rebuild(inputs['daily'], native, bars, sessions, p['confirmation_lookback'])
    prices = native.set_index('Date')
    prices.index = pd.DatetimeIndex(prices.index).as_unit('ns')
    labels = net_labels(prices, sessions, p['holding_sessions'])
    nets, fit_trace = forecasts(features, labels, p['ridge_alpha'], p['huber_multiple'])
    scores = nets.huber_net.rename('net_forecast')
    history = episode_history(scores, sessions, p['holding_sessions'])
    years = {str(row['year']): row for row in fit_trace}
    history['common14_available'] = features.notna().all(axis=1)
    history['confirmation_score'] = features.confirmation_score
    history['train_n'] = [years.get(str(t.year), {}).get('train_n', 0) for t in history.index]
    history['train_max_maturity'] = [years.get(str(t.year), {}).get('max_maturity') for t in history.index]
    history['training_mean_forecast'] = nets.training_mean
    history['huber_available'] = [years.get(str(t.year), {}).get('available', False) for t in history.index]
    history['huber_reason'] = pd.Series([years.get(str(t.year), {}).get('reason', 'PRE2021_UNAVAILABLE') for t in history.index], index=history.index, dtype=object)
    for field in ('training_mad', 'delta', 'iterations', 'max_abs_gradient', 'max_coefficient_change'):
        history['huber_' + field] = np.asarray([(years.get(str(t.year), {}).get('fit') or {}).get(field) for t in history.index], float)
    history['close'] = inputs['daily'].set_index(pd.DatetimeIndex(pd.to_datetime(inputs['daily'].Date)).as_unit('ns')).Close.reindex(history.index)
    return {'features': features, 'prices': prices, 'intraday': bars, 'labels': labels,
            'scores': nets, 'fit_trace': fit_trace, 'history': history}


class HuberNet(ConfirmNet):
    def __init__(self, parameter_values):
        p = parameter_values.values
        if set(p) != {'confirmation_lookback', 'holding_sessions', 'ridge_alpha', 'huber_multiple'}:
            raise ValueError('Exact four effective Huber parameter fields required')
        parameters(**p)
        super().__init__(ParameterSet({key: value for key, value in p.items() if key != 'huber_multiple'}))
        self._parameters = parameter_values

    def calculate_history(self, inputs, sessions):
        return prepare_history(self._parameters.values, inputs, sessions)['history']
