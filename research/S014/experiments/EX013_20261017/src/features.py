"""Seven fixed numerical mechanism families; all states use completed bars."""
import numpy as np
import pandas as pd

GROUPS={
 'compression':['prior_compression','expansion','compression_expansion','compressed_breakout','compressed_repair'],
 'breakout_path':['event_age','event_distance','retest_hold','failed_breakout','reclaim','first_retest'],
 'concentration':['positive_concentration','negative_concentration','largest_share','return_center','jump_trend'],
 'participation':['up_down_volume','down_impact','impact_change','absorption','volume_price_persistence'],
 'coupling':['corr_market','corr_sector','residual_fraction','residual_corr_interaction','residual_fraction_interaction','correlation_shift'],
 'drawdown_age':['peak_age','trough_age','recovery_fraction','recovery_speed','depth_age'],
 'session_memory':['gap_autocorr','intraday_autocorr','cross_session_corr','repair_persistence','opposite_session_fraction']}


def compute(data,legacy,previous):
    bars=data['stock.ohlcv'];c,h,l,o,v=(bars[x].astype(float) for x in ('Close','High','Low','Open','Volume'))
    r=np.log(c/c.shift());span=h-l
    # Strong predecessor values, omit diagnostic condition/rank fields, old20-day placebo and redundant copies.
    exclusions={'signal','exposure_status','condition','alpha2'}
    prior_cols=[x for x in previous if x not in exclusions and not x.startswith(('old_','unit_','lag_market_'))]
    out=previous[prior_cols].copy()
    for name in legacy:
        if name not in ('signal','signal_date','ret_1','ret_5','ret_20','range_1','volume_ratio_5_20'):
            out['legacy_'+name]=legacy[name]
    location=((2*c-h-l)/span.replace(0,np.nan)).fillna(0.)
    denom=v.rolling(5).sum()
    out['volume_location']=(location*v).rolling(5).sum()/denom
    out['signed_volume']=(np.sign(c.pct_change())*v).rolling(5).sum()/denom
    out['volume_momentum']=out.volume_ratio*c.pct_change(5)
    out['distance_ma20']=c/c.rolling(20).mean()-1
    out['ma_alignment']=c.rolling(5).mean()/c.rolling(20).mean()-1
    out['ma_slope']=c.rolling(20).mean()/c.rolling(20).mean().shift(5)-1
    tr=pd.concat([span,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    out['support_distance']=(c-c.shift().rolling(5).min())/tr.rolling(20).mean()
    vol20=r.rolling(20).std();vol60=r.rolling(60).std()
    out['vol20']=vol20;out['vol60']=vol60
    peak=c.rolling(60).max();trough=c.rolling(60).min()
    out['drawdown60']=c/peak-1
    # This includes control levels; group effects must exceed them.
    baseline=list(out.columns)
    out['prior_compression']=vol20.shift()/vol60.shift()
    out['expansion']=(span/c)/((span/c).shift().rolling(20).mean())
    out['compression_expansion']=out.expansion/out.prior_compression
    boundary=h.shift().rolling(20).max();br=c.gt(boundary)
    out['compressed_breakout']=br.astype(float)/out.prior_compression
    out['compressed_repair']=out.gap_down_repair/out.prior_compression
    ages=np.full(len(c),21.);distance=np.zeros(len(c));hold=np.zeros(len(c));failure=np.zeros(len(c));reclaim=np.zeros(len(c));first=np.zeros(len(c))
    event=None;level=None;touched=False
    for t in range(len(c)):
        if event is not None and t-event<=20:
            ages[t]=t-event;distance[t]=c.iloc[t]/level-1
            hold[t]=float(l.iloc[t]<=level and c.iloc[t]>=level)
            failure[t]=float(c.iloc[t]<level)
            reclaim[t]=float(t>0 and c.iloc[t-1]<level and c.iloc[t]>=level)
            first[t]=hold[t] and not touched
            touched=touched or bool(hold[t])
        # Today's breakout becomes a past event on the next bar; no future boundary recomputation.
        if br.iloc[t]:event=t;level=float(boundary.iloc[t]);touched=False
    for name,values in zip(GROUPS['breakout_path'],[ages,distance,hold,failure,reclaim,first],strict=True):out[name]=values
    pos=r.clip(lower=0);neg=(-r.clip(upper=0))
    def safe_ratio(a,b):return a/b.replace(0,np.nan)
    out['positive_concentration']=safe_ratio(pos.pow(2).rolling(20).sum(),pos.rolling(20).sum().pow(2)).fillna(0.)
    out['negative_concentration']=safe_ratio(neg.pow(2).rolling(20).sum(),neg.rolling(20).sum().pow(2)).fillna(0.)
    out['largest_share']=safe_ratio(r.abs().rolling(20).max(),r.abs().rolling(20).sum()).fillna(0.)
    out['return_center']=safe_ratio(r.rolling(20).apply(lambda x:np.dot(x,np.linspace(-1,1,20)),raw=True),r.abs().rolling(20).sum()).fillna(0.)
    out['jump_trend']=out.largest_share*r.rolling(20).sum()
    up=v.where(r>0,0.).rolling(20).sum();down=v.where(r<0,0.).rolling(20).sum()
    out['up_down_volume']=(up-down)/v.rolling(20).sum()
    volume_scale=v/v.shift().rolling(20).mean()
    impact=(-r.clip(upper=0))/volume_scale
    out['down_impact']=impact.rolling(5).mean()
    out['impact_change']=impact.rolling(5).mean()-impact.shift(5).rolling(5).mean()
    out['absorption']=-out.impact_change*out.volume_ratio
    out['volume_price_persistence']=(np.sign(r)*np.sign(v.diff())).rolling(20).mean()
    m=np.log(data['market'].Close/data['market'].Close.shift());s=np.log(data['sector'].Close/data['sector'].Close.shift())
    out['corr_market']=r.rolling(60).corr(m).shift()
    out['corr_sector']=r.rolling(60).corr(s).shift()
    residual=r-out.beta_market2*m-out.beta_sector2*s
    out['residual_fraction']=residual.rolling(60).std().shift()/vol60.shift()
    out['residual_corr_interaction']=residual*out.corr_market
    out['residual_fraction_interaction']=residual*out.residual_fraction
    out['correlation_shift']=r.rolling(20).corr(m).shift()-out.corr_market
    out['peak_age']=c.rolling(60).apply(lambda x:np.argmax(x[::-1]),raw=True)
    out['trough_age']=c.rolling(60).apply(lambda x:np.argmin(x[::-1]),raw=True)
    # Range location is not a claim that the trough follows the peak.
    out['recovery_fraction']=((c-trough)/(peak-trough).replace(0,np.nan)).fillna(0.)
    out['recovery_speed']=np.log(c/trough)/(out.trough_age+1)
    out['depth_age']=out.drawdown60*out.peak_age/60
    gap=np.log(o/c.shift());session=np.log(c/o)
    out['gap_autocorr']=gap.rolling(20).corr(gap.shift())
    out['intraday_autocorr']=session.rolling(20).corr(session.shift())
    out['cross_session_corr']=gap.rolling(20).corr(session.shift())
    out['repair_persistence']=(gap.lt(0)&session.gt(0)).astype(float).rolling(20).mean()*session
    out['opposite_session_fraction']=(gap*session<0).astype(float).rolling(20).mean()
    return out.replace([np.inf,-np.inf],np.nan),baseline
