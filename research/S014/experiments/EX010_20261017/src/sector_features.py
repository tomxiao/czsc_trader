"""Industry information with strictly prior full-rank market/sector exposures."""
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeRegressor

STOCK=['ret1','ret5','ret20','range','volume_ratio','upper_close','upper_failure','lower_recovery','lower_close',
    'previous_upper_close','gap','gap5','gap_session_product','gap_down_repair','gap_up_fade',
    'intraday','intraday5','stock_ret60','stock_range20']
MARKET=['market_gap','market_intraday','market_ret1','market_ret5','market_ret20','market_range','market_repair']
OLD_RELATIVE=['relative_gap','relative_intraday','relative_repair','repair_market_interaction']
SECTOR=['sector_gap','sector_intraday','sector_ret1','sector_ret5','sector_ret20','sector_range','sector_repair']
SECTOR_RELATIVE=['sector_relative_gap','sector_relative_intraday','sector_relative_repair','repair_sector_interaction']
BOTH=['twofactor_gap','twofactor_intraday','twofactor_repair','innovation_gap','innovation_intraday','innovation5','innovation20']
BASE=STOCK+MARKET+OLD_RELATIVE
MODELS={'stock':STOCK,'market':BASE,'sector':STOCK+SECTOR+SECTOR_RELATIVE,'plain':BASE+SECTOR,
    'both':BASE+SECTOR+BOTH,'lagged':BASE+[f'lag_{x}' for x in SECTOR],
    'oldsector':BASE+[f'old_{x}' for x in SECTOR]}


def exposures(bars,market,sector):
    stock=np.log(bars.Close/bars.Close.shift()).to_numpy()
    m=np.log(market.Close/market.Close.shift()).to_numpy()
    s=np.log(sector.Close/sector.Close.shift()).to_numpy()
    out=pd.DataFrame(np.nan,index=np.arange(len(stock)),columns=['alpha2','beta_market2','beta_sector2','beta_stock_sector','beta_sector_market','condition'])
    out['exposure_status']='WARMUP'
    for t in range(61,len(stock)):
        a,b,y=m[t-60:t],s[t-60:t],stock[t-60:t]
        x=np.column_stack((np.ones(60),a,b))
        coef,_,rank,_=np.linalg.lstsq(x,y,rcond=None)
        if rank!=3 or np.var(a)==0 or np.var(b)==0:
            out.loc[t,'exposure_status']='RANK_DEFICIENT'
            continue
        out.loc[t,['alpha2','beta_market2','beta_sector2']]=coef
        out.loc[t,'beta_stock_sector']=np.cov(y,b)[0,1]/np.var(b,ddof=1)
        out.loc[t,'beta_sector_market']=np.cov(b,a)[0,1]/np.var(a,ddof=1)
        out.loc[t,'condition']=np.linalg.cond(x[:,1:]-x[:,1:].mean(axis=0))
        out.loc[t,'exposure_status']='READY'
    return out


def features(bars,market,sector,inherited):
    out=inherited.copy()
    ex=exposures(bars,market,sector)
    for name in ex:
        out[name]=ex[name]
    c,o=sector.Close.astype(float),sector.Open.astype(float)
    out['sector_gap']=np.log(o/c.shift())
    out['sector_intraday']=np.log(c/o)
    for n in (1,5,20):
        out[f'sector_ret{n}']=np.log(c/c.shift(n))
    out['sector_range']=(sector.High-sector.Low)/c
    out['sector_repair']=(out.sector_gap.lt(0)&out.sector_intraday.gt(0)).astype(float)
    out['sector_relative_gap']=out.gap-out.beta_stock_sector*out.sector_gap
    out['sector_relative_intraday']=out.intraday-out.beta_stock_sector*out.sector_intraday
    out['sector_relative_repair']=(out.sector_relative_gap.lt(0)&out.sector_relative_intraday.gt(0)).astype(float)
    out['repair_sector_interaction']=out.gap_down_repair*out.sector_intraday
    out['twofactor_gap']=out.gap-out.beta_market2*out.market_gap-out.beta_sector2*out.sector_gap
    out['twofactor_intraday']=out.intraday-out.beta_market2*out.market_intraday-out.beta_sector2*out.sector_intraday
    out['twofactor_repair']=(out.twofactor_gap.lt(0)&out.twofactor_intraday.gt(0)).astype(float)
    out['innovation_gap']=out.sector_gap-out.beta_sector_market*out.market_gap
    out['innovation_intraday']=out.sector_intraday-out.beta_sector_market*out.market_intraday
    out['innovation1']=out.sector_ret1-out.beta_sector_market*out.market_ret1
    for n in (5,20):
        out[f'innovation{n}']=out[f'sector_ret{n}']-out.beta_sector_market*out[f'market_ret{n}']
    out['prior_innovation5']=out.innovation5.shift()
    out['twofactor_close5']=np.log1p(out.ret5)-out.beta_market2*out.market_ret5-out.beta_sector2*out.sector_ret5
    for name in SECTOR:
        out[f'lag_{name}']=out[name].shift()
        out[f'old_{name}']=out[name].shift(20)
    return out


def predict(task):
    name,left,right,y=task
    left,right,y=(np.asarray(v,dtype=float) for v in (left,right,y))
    assert all(np.isfinite(x).all() for x in (left,right,y))
    if name.startswith('tree'):
        model=DecisionTreeRegressor(max_depth=3,min_samples_leaf=40,random_state=13).fit(left,y)
        return model.predict(left),model.predict(right)
    mean,scale=left.mean(axis=0),left.std(axis=0)
    scale[scale<1e-12]=1.
    left,right=(left-mean)/scale,(right-mean)/scale
    center=float(y.mean())
    coef=np.linalg.solve(left.T@left+10*np.eye(left.shape[1]),left.T@(y-center))
    return left@coef+center,right@coef+center


def masks(g,stockq,sectorq):
    recovery=g.prior_innovation5.lt(0)
    laggard=g.sector_ret5.gt(0)&g.twofactor_close5.lt(0)
    a=g.gap_down_repair.eq(1)
    pressure=g.innovation_intraday.le(0)
    selloff=g.ret1.le(stockq)
    return {'sector-rebound':(recovery&g.innovation_intraday.gt(0),recovery&g.innovation_intraday.le(0)),
        'sector-laggard-repair':(laggard&g.intraday.gt(0),laggard&g.intraday.le(0)),
        'sector-confirms-stock-repair':(a&g.innovation_intraday.gt(0),a&g.innovation_intraday.le(0)),
        'sector-trend-with-stock-repair':(a&g.innovation5.gt(0),a&g.innovation5.le(0)),
        'relative-leader-in-sector-pressure':(pressure&g.twofactor_intraday.gt(0),pressure&g.twofactor_intraday.le(0)),
        'common-sector-selloff':(selloff&g.innovation1.le(sectorq),selloff&g.innovation1.gt(sectorq))}
