"""Correct chronological recovery and first touch; retain prior implementation."""
import numpy as np
from features import compute as original_compute,GROUPS


def compute(data,legacy,previous):
    out,baseline=original_compute(data,legacy,previous)
    # The original pair was range location / rise from the window low. Control for it explicitly.
    out['range_location60']=out.recovery_fraction
    out['rise_from_low_speed60']=out.recovery_speed
    baseline=baseline+['range_location60','rise_from_low_speed60']
    c=data['stock.ohlcv'].Close.to_numpy(dtype=float)
    high=data['stock.ohlcv'].High;low=data['stock.ohlcv'].Low
    trough_age=np.full(len(c),np.nan);fraction=np.full(len(c),np.nan);speed=np.full(len(c),np.nan)
    for t in range(59,len(c)):
        window=c[t-59:t+1];peak_index=len(window)-1-int(np.argmax(window[::-1]))
        after=window[peak_index:];trough_index=peak_index+len(after)-1-int(np.argmin(after[::-1]))
        top,bottom=window[peak_index],window[trough_index]
        trough_age[t]=59-trough_index
        fraction[t]=0. if top==bottom else (c[t]-bottom)/(top-bottom)
        speed[t]=np.log(c[t]/bottom)/(trough_age[t]+1)
    out['trough_age']=trough_age;out['recovery_fraction']=fraction;out['recovery_speed']=speed
    boundary=high.shift().rolling(20).max();event=None;level=None;touched=False;first=np.zeros(len(c))
    for t in range(len(c)):
        if event is not None and t-event<=20:
            contact=low.iloc[t]<=level
            first[t]=float(contact and c[t]>=level and not touched)
            touched=touched or bool(contact)
        if c[t]>boundary.iloc[t]:event=t;level=float(boundary.iloc[t]);touched=False
    out['first_retest']=first
    return out,baseline
