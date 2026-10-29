"""Five frozen causal entry expressions on completed LITE M30 bars."""
import numpy as np
import pandas as pd

NAMES = ('A','B','C','AC','AV')
PRIMARY = {'A':65,'B':65,'C':13,'AC':65,'AV':65,'PAT':13}


def predicates(close, previous_close, previous_high, mean, previous_mean, lag_mean,
               previous_atr, previous_high65, previous_atr13, previous_atr65,
               volume, volume_median):
    """Scalar/array-compatible exact inequalities; previous_* exclude the current bar."""
    a = close > previous_high65
    return {'A':a, 'B':(mean > lag_mean) & (previous_close <= previous_mean) & (close > mean),
        'C':(previous_close <= previous_mean-2*previous_atr) & (close > previous_high),
        'AC':a & (previous_atr13 <= .7*previous_atr65),
        'AV':a & (volume >= 1.5*volume_median)}


def compute(bars):
    if not bars.Date.is_monotonic_increasing or bars.Date.duplicated().any():
        raise ValueError('Require unique chronological completed bars')
    local = bars.BarStart.dt.tz_convert('America/New_York')
    days, slots = local.dt.strftime('%Y-%m-%d'),local.dt.strftime('%H:%M')
    if pd.DataFrame({'day':days,'slot':slots}).duplicated().any():
        raise ValueError('Duplicate session and RTH slot')
    previous = bars.Close.shift(1)
    tr = pd.concat([bars.High-bars.Low,(bars.High-previous).abs(),
                    (bars.Low-previous).abs()],axis=1).max(axis=1)
    # No preceding close exists for the first row; do not invent a true range there.
    tr.iloc[0] = np.nan
    mean = bars.Close.rolling(65,min_periods=65).mean()
    median = bars.Volume.groupby(slots,sort=False).transform(
        lambda x:x.shift(1).rolling(20,min_periods=20).median())
    features = pd.DataFrame({'close':bars.Close, 'previous_close':previous,
        'previous_high':bars.High.shift(1), 'mean':mean,'previous_mean':mean.shift(1),
        'lag_mean':mean.shift(13),'previous_atr':tr.rolling(13,min_periods=13).mean().shift(1),
        'previous_high65':bars.High.shift(1).rolling(65,min_periods=65).max(),
        'previous_atr13':tr.shift(1).rolling(13,min_periods=13).mean(),
        'previous_atr65':tr.shift(1).rolling(65,min_periods=65).mean(),
        'volume':bars.Volume,'volume_median':median})
    ready = features.notna().all(axis=1) & (features.volume_median>0)
    flags = pd.DataFrame(predicates(**{k:features[k] for k in features}),index=bars.index)
    return flags,ready,features


def scalar_at(bars,i):
    """Independent bounded-loop reference for focused tests and event auditing."""
    if i<77:
        return None
    def avgclose(end):
        return sum(float(bars.Close.iloc[j]) for j in range(end-64,end+1))/65
    def atr(end,n):
        values=[]
        for j in range(end-n+1,end+1):
            if j<1:
                return None
            high,low,previous=map(float,(bars.High.iloc[j],bars.Low.iloc[j],bars.Close.iloc[j-1]))
            values.append(max(high-low,abs(high-previous),abs(low-previous)))
        return sum(values)/n
    now=bars.BarStart.iloc[i].tz_convert('America/New_York')
    historical=[]
    for j in range(i-1,-1,-1):
        at=bars.BarStart.iloc[j].tz_convert('America/New_York')
        if at.date()<now.date() and (at.hour,at.minute)==(now.hour,now.minute):
            historical.append(float(bars.Volume.iloc[j]))
            if len(historical)==20:
                break
    if len(historical)!=20 or np.median(historical)<=0:
        return None
    c,pc,ph=map(float,(bars.Close.iloc[i],bars.Close.iloc[i-1],bars.High.iloc[i-1]))
    m,pm,lm=avgclose(i),avgclose(i-1),avgclose(i-13)
    a=c>max(float(x) for x in bars.High.iloc[i-65:i])
    return {'A':a,'B':m>lm and pc<=pm and c>m,
        'C':pc<=pm-2*atr(i-1,13) and c>ph,
        'AC':a and atr(i-1,13)<=.7*atr(i-1,65),
        'AV':a and float(bars.Volume.iloc[i])>=1.5*float(np.median(historical))}
