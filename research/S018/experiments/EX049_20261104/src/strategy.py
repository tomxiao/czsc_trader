from decimal import Decimal, ROUND_FLOOR
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


def features(mu, so):
    m=np.log(mu.Close).diff(); s=np.log(so.Close).diff()
    sigma=m.rolling(20).std().shift(2)
    beta=m.rolling(60).cov(s).shift(2)/s.rolling(60).var().shift(2)
    ran=(mu.High-mu.Low)/mu.Close.shift()
    return pd.DataFrame({
        'mu_drift':m.rolling(20).sum().shift(2)/(sigma*np.sqrt(20)),
        'range_state':np.log(ran.rolling(5).mean()/ran.rolling(20).mean()),
        'mu_intraday':np.log(mu.Close/mu.Open)/sigma,'mu_gap':np.log(mu.Open/mu.Close.shift())/sigma,
        'mu_yesterday':m.shift()/sigma,
        'sector_drift':s.rolling(20).sum().shift(2)/(s.rolling(20).std().shift(2)*np.sqrt(20)),
        'common_today':beta*s/sigma,'common_yesterday':beta*s.shift()/sigma})


def forecast(raw,mu,so,model_name):
    f=features(mu,so)
    limit=np.array([float((Decimal(str(float(c)))*Decimal('1.01')/Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.01')) for c in raw.Close])
    nextopen=raw.Open.shift(-1).to_numpy(); nextlow=raw.Low.shift(-1).to_numpy()
    fill=np.where(nextopen<=limit,nextopen,np.where(nextlow<limit,limit,np.nan))
    # A price-only proxy, with actual strict-limit fills and both fees. Its exit
    # opening is already in visible history; live account also books dividends.
    labels=raw.Open.shift(-2).to_numpy()*.999/(fill*1.001)-1
    dates=raw.Date.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d')
    valid=np.flatnonzero((dates>='2022-12-30').to_numpy() & np.isfinite(labels) & np.isfinite(f.to_numpy()).all(axis=1))
    if len(valid)<126:return None,len(valid)
    indices=valid[-126:]
    assert indices[-1]<=len(raw)-3
    models={'mean':[], 'mu_only':['mu_drift','range_state','mu_intraday','mu_gap','mu_yesterday'],
        'sector_only':['sector_drift','common_today','common_yesterday']}
    models['joint']=models['mu_only']+models['sector_only']
    columns=models[model_name]
    if not columns:return float(labels[indices].mean()),126
    model=make_pipeline(StandardScaler(),Ridge(alpha=10.))
    model.fit(f.iloc[indices][columns].to_numpy(),labels[indices])
    return float(model.predict(f.iloc[-1:][columns].to_numpy())[0]),126


def step(ctx,state):
    raw=ctx.history.to_frame();mu=ctx.auxiliary_histories['mu_hfq'].to_frame();so=ctx.auxiliary_histories['soxx_hfq'].to_frame()
    assert raw.Date.tolist()==mu.Date.tolist()==so.Date.tolist()
    p=ctx.parameters
    prediction,n=forecast(raw,mu,so,p['model'])
    positive=prediction is not None and prediction>0
    two_down=bool(mu.Close.iloc[-1]<mu.Close.iloc[-2]<mu.Close.iloc[-3])
    enter=positive and (p['entry']=='all' or two_down)
    price=float(mu.Close.iloc[-1]);active=ctx.position.active
    if active is None:
        anchor=price; target=float(enter);reason='positive opportunity' if enter else 'no positive opportunity'
    else:
        anchor=state.cycle.values.get('anchor')
        held=sum(t>=active.entry_interval.start for t in raw.Date)
        if p['exit']=='renew':done=not positive
        elif p['exit']=='1':done=held>=1
        else:done=held>=6 or (held>=3 and price<=anchor)
        target=float(not done);reason='forecast expired' if done else 'hold with declared evidence'
    return AccountStepResult(AccountDecision.from_facts(target,reason,
        facts={'anchor':anchor,'observed_signal':enter,'forecast':prediction if prediction is not None else 'not_ready',
            'train_n':n,'model':p['model'],'label':'price-only strict limit and fees; dividends in formal account'},
        next_watch='next completed daily bar',capital_mode='full_available_cash'),
        cycle_values=StateRecord((('anchor',anchor),)) if active is not None or target else None)
