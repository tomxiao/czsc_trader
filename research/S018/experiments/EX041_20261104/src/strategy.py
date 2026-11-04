from decimal import Decimal, ROUND_FLOOR
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


def data(bars):
    c, o = bars.Close, bars.Open
    r = np.log(c).diff()
    sigma = r.rolling(20).std().shift(2)
    ranges = (bars.High-bars.Low)/c.shift()
    features = pd.DataFrame({
        'drift': r.rolling(20).sum().shift(2)/(sigma*np.sqrt(20)),
        'range_state': np.log(ranges.rolling(5).mean()/ranges.rolling(20).mean()),
        'shock_today': r/sigma, 'shock_yesterday': r.shift()/sigma,
        'intraday': np.log(c/o)/sigma, 'gap': np.log(o/c.shift())/sigma})
    # Price-only, fee-adjusted one-session labels; formal account adds dividends.
    limit = np.array([float((Decimal(str(float(x)))*Decimal('1.01')/Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.01')) for x in c])
    entry_open, entry_low = o.shift(-1).to_numpy(), bars.Low.shift(-1).to_numpy()
    tolerance = np.maximum.reduce([np.abs(limit), np.abs(entry_open), np.abs(entry_low), np.abs(bars.High.shift(-1).to_numpy())])*1e-12
    fill = np.where(entry_open <= limit+tolerance, entry_open, np.where(entry_low <= limit+tolerance,limit,np.nan))
    y = o.shift(-2).to_numpy()*.999/(fill*1.001)-1
    dates = pd.to_datetime(bars.Date).dt.strftime('%Y-%m-%d').to_numpy()
    valid = (dates >= '2022-12-30') & np.isfinite(y) & np.isfinite(features.to_numpy()).all(axis=1)
    return features, y, valid, fill


def forecast(bars, model):
    features, y, valid, _ = data(bars)
    n = int(valid.sum())
    if n < 126:
        return None, n
    if model == 'none':
        return 1., n
    if model == 'mean':
        return float(y[valid].mean()), n
    cols = ['drift','range_state','shock_yesterday']
    cols += ['shock_today'] if model == 'shock' else ['intraday','gap']
    fitted = make_pipeline(StandardScaler(), Ridge(alpha=10.))
    fitted.fit(features.loc[valid,cols].to_numpy(), y[valid])
    return float(fitted.predict(features.loc[features.index[-1:],cols].to_numpy())[0]), n


def step(ctx, state):
    bars = ctx.history.to_frame()
    c = bars.Close
    price = float(c.iloc[-1])
    pred, n = forecast(bars, ctx.parameters['model'])
    two_down = c.iloc[-1] < c.iloc[-2] < c.iloc[-3]
    enter = pred is not None and pred > 0 and (ctx.parameters['entry'] == 'all' or two_down)
    active = ctx.position.active
    if active is None:
        anchor, floor = price, float(bars.Low.iloc[-1])
        target, reason = float(enter), 'forecast entry' if enter else 'no opportunity'
    else:
        anchor, floor = state.cycle.values.get('anchor'), state.cycle.values.get('floor')
        held = sum(t >= active.entry_interval.start for t in bars.Date)
        done = held >= 1 if ctx.parameters['exit'] == '1' else (held >= 6 or (held >= 3 and price <= anchor))
        target, reason = float(not done), 'complete' if done else 'hold'
    return AccountStepResult(AccountDecision.from_facts(target, reason,
        facts={'anchor':anchor, 'forecast':pred if pred is not None else 'not_ready',
               'training_n':n, 'observed_signal':bool(enter)},
        next_watch='next complete daily bar', capital_mode='full_available_cash'),
        cycle_values=StateRecord((('anchor',anchor),('floor',floor))) if active is not None or target else None)
