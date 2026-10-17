"""Research-only H3 conditional environment; never emits an order."""
from collections.abc import Mapping
import numpy as np
import pandas as pd


def gap_sequence_context(bars: pd.DataFrame, annual_thresholds: Mapping[int,float]) -> pd.DataFrame:
    """Thresholds must be fixed from the declared, already-matured annual H3 pool."""
    dates=pd.DatetimeIndex(pd.to_datetime(bars.Date))
    if not dates.is_monotonic_increasing or dates.has_duplicates:
        raise ValueError('Unique ascending completed sessions required')
    if (bars[['Open','Close']]<=0).any().any():
        raise ValueError('Positive HFQ prices required')
    if not annual_thresholds or not all(np.isfinite(v) for v in annual_thresholds.values()):
        raise ValueError('Explicit finite training thresholds required')
    gap=np.log(bars.Open/bars.Close.shift())
    intraday=np.log(bars.Close/bars.Open)
    correlation=gap.rolling(20).corr(gap.shift())
    threshold=pd.Series([annual_thresholds.get(int(y),np.nan) for y in dates.year],index=bars.index)
    ready=correlation.notna()&threshold.notna()
    parent=gap.lt(0)&intraday.gt(0)
    high=pd.Series(pd.NA,index=bars.index,dtype='boolean')
    high.loc[ready]=correlation.loc[ready]>=threshold.loc[ready]
    return pd.DataFrame({'Date':dates,'gap_autocorr20':correlation,'annual_threshold':threshold,
        'ready':ready,'low_open_positive_close':parent,'relatively_high_state':high})
