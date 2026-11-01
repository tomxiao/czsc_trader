"""Visible terminated negative-body context; no session reset or fabricated boundary."""


def negative_run(history,point):
    frame=history.to_frame(tail=261)
    if len(frame)!=261 or not frame.Date.is_monotonic_increasing or frame.Date.duplicated().any():
        raise ValueError('Declared261 unique completed observations required')
    if frame.Date.iloc[-1]!=point.observed_through or any(frame.Date>point.decision_at):
        raise ValueError('Visible completed history only')
    j=len(frame)-2
    while j>=0 and float(frame.Close.iloc[j])<float(frame.Open.iloc[j]):j-=1
    if j<0:raise ValueError('NEGATIVE_RUN_LEFT_CENSORED: no actual nonnegative terminator in visible261')
    length=len(frame)-2-j
    if length<1:raise ValueError('E0 context requires a previous negative body')
    high=float(frame.High.iloc[j+1:-1].max())
    if high<=0:raise ValueError('Positive completed run high required')
    return {'length':length,'high':high,'terminator_at':frame.Date.iloc[j],
            'run_start_at':frame.Date.iloc[j+1]}
