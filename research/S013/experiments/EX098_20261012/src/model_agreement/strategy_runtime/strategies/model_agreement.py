"""Fixed original14 current2of3 model agreement policy; inherited exact EX080 native contract, no IO."""
from datetime import date
import numpy as np
import pandas as pd
from strategy_runtime.pricing import ExecutionPricing, ExecutionPriceBasis
from .confirm_net import ConfirmNet
from .confirm_kernel import rebuild, episode_history, dates
from .agreement_kernel import forecasts, hyperparameters, MODELS

PARAMETERS = {'confirmation_lookback':120,'holding_sessions':4,'ridge_alpha':10.0,
              'huber_multiple':1.345,'tree_depth':2,'minimum_leaf':40}
DOMAINS = [('confirmation_lookback',40,120,'INTEGER'),('holding_sessions',1,60,'INTEGER'),
           ('ridge_alpha',1.,100.,'CONTINUOUS'),('huber_multiple',.5,3.,'CONTINUOUS'),
           ('tree_depth',1,4,'INTEGER'),('minimum_leaf',20,120,'INTEGER')]


def parameters(values):
    if set(values) != set(PARAMETERS):
        raise ValueError('Exact six effective agreement parameters required')
    for name, lower, upper, kind in DOMAINS:
        expected = int if kind == 'INTEGER' else float
        if type(values[name]) is not expected or not np.isfinite(values[name]) or not lower <= values[name] <= upper:
            raise ValueError('Full legal agreement domain and exact type required: '+name)
    hyperparameters(values['ridge_alpha'],values['huber_multiple'],values['tree_depth'],values['minimum_leaf'])


def net_labels(prices, sessions, holding_sessions):
    """Only observed T+1 and T+1+H OPENs; NA tail never gates prediction."""
    if type(holding_sessions) is not int or not 1 <= holding_sessions <= 60:
        raise ValueError('Holding integer full domain1..60 required')
    axis, calendar = dates(sessions), dates(prices.index)
    opens = prices.Open.to_numpy(float)
    if not axis.isin(calendar).all() or not np.isfinite(opens).all() or (opens <= 0).any():
        raise ValueError('Complete signal axis and finite positive observed native OPENs required')
    positions = calendar.get_indexer(axis)
    rows = []
    for i in positions:
        end = i + 1 + holding_sessions
        rows.append((float(opens[end] / opens[i + 1] * (0.999 / 1.001) - 1), calendar[end])
                    if end < len(calendar) else (np.nan, pd.NaT))
    return pd.DataFrame(rows, index=axis, columns=['return_4', 'label_end_return_4'])


def model_inputs(inputs, sessions, p):
    parameters(p)
    inputs = {name: pd.DataFrame(value, copy=False) for name, value in inputs.items()}
    rename = {
        "Date": "dt",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "vol",
        "Amount": "amount",
    }

    def numerical(f):
        out = f.loc[:, list(rename)].rename(columns=rename).copy()
        out.dt = pd.to_datetime(out.dt).dt.as_unit("ns")
        return out

    adjusted = numerical(inputs["daily"])
    raw = numerical(inputs["execution"])
    intra = numerical(inputs["intraday"])
    last = pd.Timestamp(sessions[-1])
    raw = raw.loc[raw.dt <= last].copy()
    intra = intra.loc[intra.dt.dt.normalize() <= last].copy()
    pricing = ExecutionPricing(ExecutionPriceBasis.HFQ_RESEARCH, date(2019, 12, 31), 0.2803)
    native = pricing.apply(raw, raw_daily=raw, adjusted_daily=adjusted).rename(
        columns={v: k for k, v in rename.items()}
    )
    bars = pricing.apply(intra, raw_daily=raw, adjusted_daily=adjusted).rename(
        columns={v: k for k, v in rename.items()}
    )
    feature = rebuild(inputs["daily"], native, bars, sessions, p["confirmation_lookback"])
    prices = native.set_index("Date")
    prices.index = pd.DatetimeIndex(prices.index).as_unit("ns")

    return feature, prices


def history_from_model(feature, prices, sessions, p):
    parameters(p)
    labels = net_labels(prices, sessions, p['holding_sessions'])
    scores, proof = forecasts(feature, labels, ridge_alpha=p['ridge_alpha'], huber_multiple=p['huber_multiple'], tree_depth=p['tree_depth'], minimum_leaf=p['minimum_leaf'])
    history = episode_history(scores.vote_score, sessions, p['holding_sessions'])
    yearly = {row['year']: row for row in proof['joint_ridge']}
    history['common14_available'] = feature.notna().all(axis=1)
    history['confirmation_score'] = feature.confirmation_score
    history['train_n'] = [yearly.get(t.year, {}).get('train_n', 0) for t in history.index]
    history['train_max_maturity'] = [yearly.get(t.year, {}).get('max_maturity') for t in history.index]
    history['all_models_available'] = scores.all_available
    history['positive_vote_count'] = scores.positive_votes
    history['agreement_entry_score'] = scores.vote_score
    for name in MODELS:
        history[name + '_score'] = scores[name]
        history[name + '_available'] = np.isfinite(scores[name])
    return history, labels, scores, proof


class AgreementNet(ConfirmNet):
    def __init__(self, parameters_value):
        parameters(parameters_value.values)
        self._parameters = parameters_value

    def calculate_history(self, inputs, sessions):
        p = self._parameters.values
        feature, prices = model_inputs(inputs, sessions, p)
        history, _, _, _ = history_from_model(feature, prices, sessions, p)
        history['close'] = (pd.DataFrame(inputs['daily'], copy=False)
            .set_index(pd.DatetimeIndex(pd.to_datetime(inputs['daily'].Date)).as_unit('ns'))
            .Close.reindex(history.index))
        return history
