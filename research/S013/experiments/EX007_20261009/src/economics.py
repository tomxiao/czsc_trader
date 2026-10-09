"""Researcher-owned literal mandate gates on continuous public TXE ledgers."""
import numpy as np
import pandas as pd

def annual_stats(account,initial_cash=1_000_000):
    dates=pd.DatetimeIndex(pd.to_datetime(account.date)).normalize()
    values=account.equity.to_numpy(dtype=float)
    assert len(values)==1636 and dates.is_unique and dates.is_monotonic_increasing
    assert dates[0]==pd.Timestamp('2020-01-02') and dates[-1]==pd.Timestamp('2026-09-30')
    assert np.isfinite(values).all() and (values>0).all()
    years={}
    anchor=float(initial_cash)
    for year in sorted(set(dates.year)):
        segment=values[dates.year==year]
        anchored=np.r_[anchor,segment]
        magnitude=float(np.max(1-anchored/np.maximum.accumulate(anchored)))
        years[str(year)]={'max_drawdown_magnitude':magnitude,'return':float(segment[-1]/anchor-1),
                          'sessions':len(segment),'opening_equity':anchor,'closing_equity':float(segment[-1])}
        anchor=float(segment[-1])
    return years

def summarize(result):
    run=result.runs[0]
    own,bh=run.execution.account_daily,run.buyhold.account_daily
    assert np.array_equal(pd.to_datetime(own.date),pd.to_datetime(bh.date))
    years,by=annual_stats(own),annual_stats(bh)
    cagr=float((float(own.equity.iloc[-1])/1_000_000)**(252/len(own))-1)
    bcagr=float((float(bh.equity.iloc[-1])/1_000_000)**(252/len(bh))-1)
    closed=int(run.execution.trades.status.eq('CLOSED').sum())
    assert closed==run.observation.closed_trades
    assert np.isclose(cagr,run.observation.net_cagr,rtol=0,atol=1e-12)
    freq=closed*60/len(own)
    margins={y:by[y]['max_drawdown_magnitude']-years[y]['max_drawdown_magnitude'] for y in years}
    gates={'return':cagr>=1.5*bcagr,'annual_drawdown':all(v>0 for v in margins.values()),'frequency':freq>=4}
    # Search heuristic only; qualification is the exact simultaneous Boolean above.
    return_deficit=max(0.,(1.5*bcagr-cagr)/max(abs(1.5*bcagr),.01))
    dd_deficit=sum(max(0.,-margins[y])/max(by[y]['max_drawdown_magnitude'],.01) for y in margins)
    freq_deficit=max(0.,(4-freq)/4)
    fills=run.execution.fills
    return {'candidate_id':run.candidate_id,'net_cagr':cagr,'buyhold_cagr':bcagr,'return_threshold':1.5*bcagr,
        'annual':years,'buyhold_annual':by,'annual_dd_margins':margins,'min_dd_margin':min(margins.values()),
        'closed_trades':closed,'frequency60':freq,'gates':gates,'qualified':all(gates.values()),
        'deficit':return_deficit+dd_deficit+freq_deficit,'full_max_drawdown':run.observation.max_drawdown,
        'final_quantity':int(own.quantity.iloc[-1]),'total_fees':float(fills.fees.sum()),
        'order_statuses':{str(k):int(v) for k,v in run.execution.orders.status.value_counts().items()},
        'result_hash':result.result_hash,'request_hash':result.request_hash,
        'content_sha256':run.identity.content_sha256,'input_sha256':run.identity.input_sha256,
        'protocol_sha256':run.identity.protocol_sha256,'environment_sha256':run.identity.environment_sha256}

def search_value(row):
    return -row['deficit']+0.001*row['net_cagr']
