import numpy as np
import pandas as pd

def annual(account):
    dates=pd.DatetimeIndex(pd.to_datetime(account.date)).normalize()
    equity=account.equity.to_numpy(dtype=float)
    assert len(equity)==1636 and dates[0]==pd.Timestamp('2020-01-02') and dates[-1]==pd.Timestamp('2026-09-30')
    rows={}
    anchor=1_000_000.
    for year in sorted(set(dates.year)):
        segment=equity[dates.year==year]
        wealth=np.r_[anchor,segment]
        rows[str(year)]={'return':float(segment[-1]/anchor-1),
            'drawdown':float(np.max(1-wealth/np.maximum.accumulate(wealth))),
            'opening_equity':anchor,'closing_equity':float(segment[-1])}
        anchor=float(segment[-1])
    return rows

def summarize(bound,result,config,ledger):
    run=result.runs[0]
    own,bh=run.execution.account_daily,run.buyhold.account_daily
    pd.testing.assert_series_equal(pd.to_datetime(own.date),pd.to_datetime(bh.date))
    years,benchmark_years=annual(own),annual(bh)
    cagr=float((own.equity.iloc[-1]/1_000_000)**(252/1636)-1)
    bcagr=float((bh.equity.iloc[-1]/1_000_000)**(252/1636)-1)
    assert abs(cagr-run.observation.net_cagr)<1e-12
    closed=int(run.execution.trades.status.eq('CLOSED').sum())
    negative=[y for y in years if benchmark_years[y]['return']<0]
    gates={'return':cagr>=1.5*bcagr if bcagr>0 else cagr>0,
           'annual_drawdown':all(years[y]['drawdown']<benchmark_years[y]['drawdown'] for y in years),
           'frequency':closed*60/1636>=4,
           'negative_buyhold_year_profit':all(years[y]['return']>0 for y in negative)}
    paths=ledger.inspect_run(run)
    audit=ledger.verify_account(bound,result)
    benchmark_paths=ledger.annual_account(run.buyhold.execution)[0]
    assert len(paths['cycles'])==len(run.execution.trades)
    for row in paths['annual_account']:
        assert abs(row['account_return']-years[str(row['year'])]['return'])<1e-12
    for row in benchmark_paths:
        assert abs(row['account_return']-benchmark_years[str(row['year'])]['return'])<1e-12
    frame=run.execution.decisions.copy()
    if config['mode']=='M0':
        masks=None
    else:
        opportunity=frame.confirmation_opportunity.astype(bool)
        if config['mode']=='M1':
            expected=frame.confirmation_score.ge(-.2)
        else:
            direction=1 if config['mode']=='M2' else -1
            expected=(direction*frame.confirmation_delta).ge(0)
        assert np.array_equal(expected,frame.confirmation_pass)
        assert np.array_equal(opportunity & expected,frame.signal_reason.eq('entry'))
        assert np.array_equal(opportunity & ~expected,frame.signal_reason.eq('confirmation_rejected'))
        masks={'base_opportunities':int(opportunity.sum()),
            'rejected_opportunities':int((opportunity & ~expected).sum()),
            'zero_delta_opportunities':int((opportunity & frame.confirmation_delta.eq(0)).sum())
                 if config['mode'] in ('M2','M3') else None,
            'groups':frame.assign(year=pd.to_datetime(frame.signal_date).dt.year,
                                 opportunity=opportunity.astype(int),rejected=(opportunity & ~expected).astype(int))
                .groupby(['year','regime'])[['opportunity','rejected']].sum().reset_index().to_dict('records')}
    actual_buys=run.execution.fills.side.eq('BUY')
    full_wealth=np.r_[1_000_000.,own.equity.to_numpy()]
    drawdown=float(np.max(1-full_wealth/np.maximum.accumulate(full_wealth)))
    row={key:config[key] for key in ('index','background','mode','candidate_id','content_sha256','existing_identity')}
    row.update(net_cagr=cagr,drawdown=drawdown,closed_trades=closed,frequency60=closed*60/1636,
        annual=years,benchmark_cagr=bcagr,benchmark_annual=benchmark_years,
        negative_benchmark_years=negative,gates=gates,qualified=all(gates.values()),
        total_fees=float(run.execution.fills.fees.sum()),
        signal_entries=int(frame.signal_reason.eq('entry').sum()),buy_fills=int(actual_buys.sum()),
        final_quantity=int(own.quantity.iloc[-1]),gate_counts=masks,paths=paths,account_audit=audit,
        request_hash=result.request_hash,result_hash=result.result_hash,
        raw_input_bindings={key:value.to_dict() for key,value in bound.input_bindings.items()},
        order_statuses={str(k):int(v) for k,v in run.execution.orders.status.value_counts().items()})
    return row,frame

def paired(first,second,label):
    # Difference is full policy outcome, not a sum of rejected predecessor trades.
    result={'comparison':label,'first':first['background']+'/'+first['mode'],
        'second':second['background']+'/'+second['mode'],
        'cagr_difference':second['net_cagr']-first['net_cagr'],
        'drawdown_difference':second['drawdown']-first['drawdown'],
        'closed_trade_difference':second['closed_trades']-first['closed_trades'],
        'annual_differences':{}}
    a={str(x['year']):x for x in first['paths']['annual_account']}
    b={str(x['year']):x for x in second['paths']['annual_account']}
    for year in a:
        result['annual_differences'][year]={'net_return':b[year]['account_return']-a[year]['account_return'],
            'price_contribution':b[year]['price_contribution']-a[year]['price_contribution'],
            'fee_contribution':b[year]['fee_contribution']-a[year]['fee_contribution']}
    def key(cycle):
        return (cycle['entry_fill_time'],cycle.get('exit_fill_time'),cycle['entry_route'])
    old={key(c):c for c in first['paths']['cycles']}
    new={key(c):c for c in second['paths']['cycles']}
    removed=[c for k,c in old.items() if k not in new]
    added=[c for k,c in new.items() if k not in old]
    result['cycle_changes']={'same_entry_exit_route':len(set(old)&set(new)),
        'removed_or_retimed':removed,'added_or_retimed':added,
        'warning':'different paths inherit different cash; old-cycle pnl is descriptive, not additive policy contribution'}
    return result
