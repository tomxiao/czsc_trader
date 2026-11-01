"""Completed observed-session first RTH low; public prefix/calendar only."""
from datetime import timedelta,time
from zoneinfo import ZoneInfo

ZONE=ZoneInfo('America/New_York')


def opening_reference(history,point,session,cycle_entry):
    if session is None:raise ValueError('Public session_context required')
    frame=history.to_frame(tail=27)
    if len(frame)!=27 or not frame.Date.is_monotonic_increasing or frame.Date.duplicated().any():
        raise ValueError('27 unique chronological complete bars required')
    last=frame.iloc[-1]
    if last.Date!=point.observed_through or any(frame.Date>point.decision_at):
        raise ValueError('Opening reference must use visible completed observations')
    day=last.BarStart.astimezone(ZONE).date()
    rows=frame[frame.BarStart.map(lambda x:x.astimezone(ZONE).date()==day)]
    first=rows.iloc[0]
    if first.BarStart.astimezone(ZONE).time()!=time(9,30):raise ValueError('Observed day first RTH bar missing')
    previous=None
    for row in rows.itertuples():
        if row.Date-row.BarStart!=timedelta(minutes=30) or (previous is not None and previous!=row.BarStart):
            raise ValueError('Observed RTH prefix must be contiguous M30')
        previous=row.Date
    if day==session.session_date:
        first_start=session.segments[0].start
        first_end=first_start+timedelta(minutes=30)
        if first_end>session.segments[0].end or first.BarStart!=first_start or first.Date!=first_end:
            raise ValueError('First complete observation differs from public planned RTH')
    elif day>=session.session_date:
        raise ValueError('Observed day cannot follow execution session')
    # For cross-day execution the already-complete observed day remains the reference.
    # Its full grid was authenticated before this experiment; no price-derived holiday fallback.
    if not 0<float(first.Low)<=float(first.Close):raise ValueError('Positive valid first low required')
    carry=cycle_entry<first.BarStart
    completed=first.Date.to_pydatetime() if hasattr(first.Date,'to_pydatetime') else first.Date
    return {'day':day.isoformat(),'low':float(first.Low) if carry else 0.,
            'at':completed,'carryin':bool(carry)}
