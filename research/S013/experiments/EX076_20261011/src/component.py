"""Fixed causal four-day curvature. Pure mathematics, no I/O or account model."""
import numpy as np
import pandas as pd

COMPONENT='curvature4'

def build_features(daily):
    if not isinstance(daily,pd.DataFrame) or not isinstance(daily.index,pd.DatetimeIndex):
        raise ValueError('Explicit daily DataFrame/DatetimeIndex required')
    index=daily.index
    if (daily.empty or index.tz is not None or index.hasnans or index.has_duplicates
            or not index.is_monotonic_increasing or not index.equals(index.normalize())):
        raise ValueError('Nonempty unique ordered naive complete-session index required')
    if daily.columns.has_duplicates or 'Close' not in daily:
        raise ValueError('Unique Close column required')
    close=daily.Close.astype(float)
    values=close.to_numpy()
    if np.isinf(values).any() or (values[np.isfinite(values)]<=0).any():
        raise ValueError('Observed Close must be positive finite; missing remains unavailable')
    vol=close.pct_change(fill_method=None).rolling(20,min_periods=20).std(ddof=1)
    logclose=np.log(close)
    denom=2*vol.where(vol>0)
    curvature=(logclose-2*logclose.shift(2)+logclose.shift(4))/denom
    stretch=(logclose-logclose.shift(4))/denom
    reason=pd.Series(None,index=index,dtype=object)
    reason.loc[vol.isna()|logclose.shift(4).isna()]='INSUFFICIENT_OR_MISSING_20_RETURN_HISTORY'
    reason.loc[vol.eq(0)]='ZERO_VOLATILITY'
    result=pd.DataFrame({'curvature4':curvature,'short_stretch4':stretch,
        'volatility20':vol,'curvature_unavailable_reason':reason},index=index)
    if np.isinf(result[['curvature4','short_stretch4','volatility20']].to_numpy()).any():
        raise ValueError('Infinite arithmetic cannot become a signal')
    return result

def causal_flat_eligible(entry_eligible,target_position,*,initial_target_position):
    """Original N0 policy-flat eligibility, never future fill/label selection.

    Initial target=0 must be separately authenticated original policy initial
    condition. It is not a fill for missing target history or a strategy parameter.
    """
    if (not isinstance(entry_eligible,pd.Series) or not isinstance(target_position,pd.Series)
            or not entry_eligible.index.equals(target_position.index)
            or entry_eligible.dtype!=np.dtype(bool) or entry_eligible.empty
            or initial_target_position!=0 or type(initial_target_position) not in (int,float)):
        raise ValueError('Exact aligned Boolean eligibility and authenticated original initial0 required')
    index=entry_eligible.index
    if (not isinstance(index,pd.DatetimeIndex) or index.tz is not None or index.hasnans
            or index.has_duplicates or not index.is_monotonic_increasing or not index.equals(index.normalize())):
        raise ValueError('Original full ordered session axis required')
    target=target_position.to_numpy(float)
    if not np.isfinite(target).all() or not np.isin(target,(0.,1.)).all():
        raise ValueError('Complete original binary target history required; no fill')
    previous=np.concatenate(([float(initial_target_position)],target[:-1]))
    return pd.Series(entry_eligible.to_numpy() & (previous==0),index=index,name='causal_original_policy_flat_eligible')
