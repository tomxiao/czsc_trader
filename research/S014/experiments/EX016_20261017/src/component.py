"""Causal distribution calibration; no future labels or external annual thresholds."""
import numpy as np
import pandas as pd

def causal_gap_environment(bars:pd.DataFrame,window:int=252)->pd.DataFrame:
    if type(window) is not int or window<60:raise ValueError('Integer calibration window >=60 required')
    dates=pd.DatetimeIndex(pd.to_datetime(bars.Date))
    if not dates.is_monotonic_increasing or dates.has_duplicates:raise ValueError('Unique ascending completed days required')
    if not np.isfinite(bars[['Open','Close']].to_numpy()).all() or (bars[['Open','Close']]<=0).any().any():raise ValueError('Finite positive adjusted prices required')
    gap=np.log(bars.Open/bars.Close.shift());intra=np.log(bars.Close/bars.Open)
    corr=gap.rolling(20).corr(gap.shift());threshold=corr.shift().rolling(window,min_periods=60).median()
    ready=corr.notna()&threshold.notna();high=pd.Series(pd.NA,index=bars.index,dtype='boolean');high.loc[ready]=corr.loc[ready]>=threshold.loc[ready]
    return pd.DataFrame({'Date':dates,'gap':gap,'intraday':intra,'correlation':corr,'threshold':threshold,'ready':ready,
        'parent':gap.lt(0)&intra.gt(0),'high':high})
