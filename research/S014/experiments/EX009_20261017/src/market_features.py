"""Completed-session market context and strictly lagged beta residuals."""
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeRegressor

STOCK = ['ret1','ret5','ret20','range','volume_ratio','upper_close','upper_failure',
    'lower_recovery','lower_close','previous_upper_close','gap','gap5','gap_session_product','gap_down_repair','gap_up_fade']
MARKET = ['market_gap','market_intraday','market_ret1','market_ret5','market_ret20','market_range','market_repair']
RELATIVE = ['relative_gap','relative_intraday','relative_repair','repair_market_interaction']
MODELS = {'ridge-stock':STOCK,'ridge-market':MARKET,'ridge-context':STOCK+MARKET,
    'ridge-relative':STOCK+MARKET+RELATIVE,'ridge-lagged':STOCK+[f'lag_{x}' for x in MARKET],
    'tree-stock':STOCK,'tree-relative':STOCK+MARKET+RELATIVE}


def features(bars, index, stock):
    out = stock.copy()
    c, o = index.Close.astype(float), index.Open.astype(float)
    r = np.log(c/c.shift())
    sr = np.log(bars.Close/bars.Close.shift())
    beta = sr.rolling(60).cov(r).shift() / r.rolling(60).var().shift()
    out['beta'] = beta
    out['market_gap'] = np.log(o/c.shift())
    out['market_intraday'] = np.log(c/o)
    for n in (1,5,20):
        out[f'market_ret{n}'] = np.log(c/c.shift(n))
    out['market_range'] = (index.High-index.Low)/c
    out['market_repair'] = (out.market_gap.lt(0)&out.market_intraday.gt(0)).astype(float)
    out['relative_gap'] = out.gap-beta*out.market_gap
    out['relative_intraday'] = out.intraday-beta*out.market_intraday
    out['relative_repair'] = (out.relative_gap.lt(0)&out.relative_intraday.gt(0)).astype(float)
    out['repair_market_interaction'] = out.gap_down_repair*out.market_intraday
    for name in MARKET:
        out[f'lag_{name}'] = out[name].shift()
    return out


def predict(task):
    name, left, right, y = task
    left,right,y = (np.asarray(x,dtype=float) for x in (left,right,y))
    assert all(np.isfinite(x).all() for x in (left,right,y))
    if name.startswith('tree'):
        model = DecisionTreeRegressor(max_depth=3,min_samples_leaf=40,random_state=13).fit(left,y)
        return model.predict(left),model.predict(right)
    mean,scale = left.mean(axis=0),left.std(axis=0)
    scale[scale<1e-12]=1.
    left,right=(left-mean)/scale,(right-mean)/scale
    center=float(y.mean())
    coef=np.linalg.solve(left.T@left+10*np.eye(left.shape[1]),left.T@(y-center))
    return left@coef+center,right@coef+center


def masks(frame):
    a=frame.gap.lt(0)&frame.intraday.gt(0)
    b=frame.gap.lt(0)&frame.intraday.le(0)
    c=frame.gap.ge(0)&frame.intraday.gt(0)
    ra=frame.relative_gap.lt(0)&frame.relative_intraday.gt(0)
    rb=frame.relative_gap.lt(0)&frame.relative_intraday.le(0)
    return {'stock-repair':(a,b),'market-intraday':(a&frame.market_intraday.gt(0),a&frame.market_intraday.le(0)),
        'market-gap':(a&frame.market_gap.lt(0),a&frame.market_gap.ge(0)),
        'market-trend':(a&frame.market_ret20.gt(0),a&frame.market_ret20.le(0)),
        'relative-repair':(ra,rb),'ordinary-up-candle':(a,c)}
