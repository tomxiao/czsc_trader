"""Visible tail-only previous-session range and market-first intraday events."""
from datetime import timedelta,time
from zoneinfo import ZoneInfo

ZONE=ZoneInfo('America/New_York')


def market_context(history,point,session):
    if session is None:raise ValueError('Declared public execution session required')
    frame=history.to_frame(tail=27)
    if len(frame)<27 or not frame.Date.is_monotonic_increasing or frame.Date.duplicated().any():
        raise ValueError('27 unique chronological completed bars required')
    rows=frame.to_dict('records');last=rows[-1]
    if last['Date']!=point.observed_through or any(x['Date']>point.decision_at for x in rows):
        raise ValueError('Only completed visible observation prefix permitted')
    def day(row):return row['BarStart'].astimezone(ZONE).date()
    observed=day(last);today=[x for x in rows if day(x)==observed]
    dates=sorted({day(x) for x in rows if day(x)<observed})
    if not dates:raise ValueError('Completed prior session group required')
    prior_day=dates[-1];prior=[x for x in rows if day(x)==prior_day]
    # Completeness versus the planned543 grid is a separately authenticated batch premise.
    # These structural checks do not infer the historical schedule from prices.
    def grid(group,complete):
        if group[0]['BarStart'].astimezone(ZONE).time()!=time(9,30):raise ValueError('Missing observed session prefix')
        for j,x in enumerate(group):
            if x['Date']-x['BarStart']!=timedelta(minutes=30):raise ValueError('M30 intervals required')
            if j and group[j-1]['Date']!=x['BarStart']:raise ValueError('Missing intermediate session bar')
        if complete and (len(group) not in (7,13) or group[-1]['Date'].astimezone(ZONE).time() not in (time(13),time(16))):
            raise ValueError('Incomplete prior approved RTH group')
    grid(prior,True);grid(today,False)
    upper=max(float(x['High']) for x in prior);lower=min(float(x['Low']) for x in prior)
    if not 0<lower<upper:raise ValueError('Positive nondegenerate prior range required')
    same_day=session.session_date==observed
    executable=same_day and point.execution_interval.start==last['Date'] and any(
        seg.start<=point.execution_interval.start<point.execution_interval.end<=seg.end for seg in session.segments)
    first_cross=None;first_accept=None
    # Every earlier prefix slot necessarily had a later completed same-day interval.
    # Current terminal/cross-day slot is ineligible even if its predicate is true.
    for j in range(1,len(today)):
        if j==len(today)-1 and not executable:continue
        prev,x=today[j-1],today[j]
        if first_cross is None and float(prev['Close'])<=upper<float(x['Close']):first_cross=x['Date']
        if first_accept is None and float(x['Low'])>upper and any(float(y['Close'])<=upper for y in today[:j]):first_accept=x['Date']
    return {'observed_day':observed.isoformat(),'reference_prior_day':prior_day.isoformat(),
        'setup_reference_high':upper,'setup_reference_low':lower,'same_day_next_execution':bool(executable),
        'up_cross':bool(executable and first_cross==last['Date']),
        'up_accept':bool(executable and first_accept==last['Date']),
        'first_cross_at':first_cross,'first_accept_at':first_accept,'observed_bar_ordinal':len(today)}
