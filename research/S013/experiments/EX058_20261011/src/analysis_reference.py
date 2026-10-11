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

def _audit_recovery_eligibility(frame, config):
    """Independently derive original/extended eligibility from actual before-state.

    The exception contains no confirmation-score predicate. This is signal
    eligibility authentication, not a forecast or account-profit calculation.
    """
    p = config['payload']['parameters']
    assert config['mechanism'] == 'RAW_BEAR_TIME_BELOW_BODY_ACF_RECOVERY'
    assert p['confirmation']['scope'] == 'both' and p['confirmation']['enabled'] is True
    assert p['confirmation']['profile'] == 'all' and p['confirmation']['orientation'] == 1
    assert np.isfinite(frame.acf1.to_numpy()).all(), 'Recovery cannot waive missing raw ACF'
    np.testing.assert_array_equal(frame.entry_acf_value.to_numpy(), frame.acf1.to_numpy())
    assert frame.target_position.isin((0., 1.)).all()
    before_flat = frame.target_position.shift(1, fill_value=0.).eq(0.)
    held_route = frame.regime.where(frame.signal_reason.eq('entry')).shift(1).ffill()
    assert held_route[~before_flat].isin(('bull', 'bear')).all(), 'Held route must follow prior signal entry'
    routes = frame.regime.where(before_flat, held_route)
    assert routes.isin(('bull', 'bear')).all()
    acf_pass = np.array([p[route]['acf_min'] is None or value >= p[route]['acf_min']
                         for route, value in zip(routes, frame.acf1, strict=True)], dtype=bool)
    range_pass = frame.range_position.to_numpy() <= np.array([p[route]['entry'] for route in routes])
    momentum_pass = np.array([p[route]['momentum_min'] is None or value >= p[route]['momentum_min']
                             for route, value in zip(routes, frame.momentum20, strict=True)], dtype=bool)
    body_up = frame.entry_signal_close.gt(frame.entry_signal_open)
    np.testing.assert_array_equal(body_up.to_numpy(), frame.entry_direction_up.to_numpy())
    category = frame.last_exit_category
    assert (category.isna() | category.isin(('BELOW', 'EQUAL', 'ABOVE'))).all()
    recovery = (before_flat & frame.regime.eq('bear') & frame.last_exit_reason.eq('time')
                & frame.last_exit_route.eq('bear') & category.eq('BELOW') & body_up
                & ~acf_pass & range_pass & momentum_pass)
    eligible = range_pass & momentum_pass & (acf_pass | recovery.to_numpy())
    np.testing.assert_array_equal(acf_pass, frame.entry_acf_pass.to_numpy())
    np.testing.assert_array_equal(recovery.to_numpy(), frame.entry_acf_recovery_applies.to_numpy())
    np.testing.assert_array_equal(eligible, frame.entry_eligible.to_numpy())
    np.testing.assert_array_equal((before_flat & eligible).to_numpy(), frame.confirmation_opportunity.to_numpy())
    assert not frame.entry_direction_gate_applies.any(), 'Recovery has no direction veto'
    assert not frame.signal_reason.eq('entry_direction_rejected').any()
    return {'acf_recovery_opportunities': int(recovery.sum()),
            'original_eligible_flat_opportunities': int((before_flat & range_pass & momentum_pass & acf_pass).sum()),
            'enhanced_eligible_flat_opportunities': int((before_flat & eligible).sum()),
            'holding_eligibility_has_no_exception': True}


def _audit_boundary_recovery_eligibility(frame, config):
    """Independently derive original/extended eligibility from actual before-state.

    The exception contains no confirmation-score predicate. This is signal
    eligibility authentication, not a forecast or account-profit calculation.
    """
    p = config['payload']['parameters']
    assert config['mechanism'] == 'RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY'
    assert p['mechanism'] == config['mechanism']
    for name in ('entry_direction_up', 'entry_direction_gate_applies', 'entry_acf_pass',
                 'entry_acf_recovery_applies', 'entry_eligible', 'confirmation_opportunity', 'confirmation_pass'):
        assert frame[name].dtype == np.dtype(bool), 'Required native boolean dtype: ' + name
    assert p['confirmation']['scope'] == 'both' and p['confirmation']['enabled'] is True
    assert p['confirmation']['profile'] == 'all' and p['confirmation']['orientation'] == 1
    assert np.isfinite(frame.acf1.to_numpy()).all(), 'Recovery cannot waive missing raw ACF'
    np.testing.assert_array_equal(frame.entry_acf_value.to_numpy(), frame.acf1.to_numpy())
    assert frame.target_position.isin((0., 1.)).all()
    before_flat = frame.target_position.shift(1, fill_value=0.).eq(0.)
    held_route = frame.regime.where(frame.signal_reason.eq('entry')).shift(1).ffill()
    assert held_route[~before_flat].isin(('bull', 'bear')).all(), 'Held route must follow prior signal entry'
    routes = frame.regime.where(before_flat, held_route)
    assert routes.isin(('bull', 'bear')).all()
    acf_pass = np.array([p[route]['acf_min'] is None or value >= p[route]['acf_min']
                         for route, value in zip(routes, frame.acf1, strict=True)], dtype=bool)
    range_pass = frame.range_position.to_numpy() <= np.array([p[route]['entry'] for route in routes])
    momentum_pass = np.array([p[route]['momentum_min'] is None or value >= p[route]['momentum_min']
                             for route, value in zip(routes, frame.momentum20, strict=True)], dtype=bool)
    body_up = frame.entry_signal_close.gt(frame.entry_signal_open)
    np.testing.assert_array_equal(body_up.to_numpy(), frame.entry_direction_up.to_numpy())
    category = frame.last_exit_category
    assert (category.isna() | category.isin(('BELOW', 'EQUAL', 'ABOVE'))).all()
    recovery = (before_flat & frame.regime.eq('bear') & frame.last_exit_reason.eq('time')
                & frame.last_exit_route.eq('bear') & category.eq('BELOW') & body_up
                & ~acf_pass & range_pass & momentum_pass)
    eligible = range_pass & momentum_pass & (acf_pass | recovery.to_numpy())
    np.testing.assert_array_equal(acf_pass, frame.entry_acf_pass.to_numpy())
    np.testing.assert_array_equal(recovery.to_numpy(), frame.entry_acf_recovery_applies.to_numpy())
    np.testing.assert_array_equal(eligible, frame.entry_eligible.to_numpy())
    np.testing.assert_array_equal((before_flat & eligible).to_numpy(), frame.confirmation_opportunity.to_numpy())
    previous_momentum = frame.previous_regime_momentum.to_numpy()
    momentum = frame.regime_momentum.to_numpy()
    assert np.isfinite(previous_momentum).all() and np.isfinite(momentum).all()
    previous_regime = np.where(previous_momentum >= p['regime_threshold'], 'bull', 'bear')
    raw_regime = np.where(momentum >= p['regime_threshold'], 'bull', 'bear')
    np.testing.assert_array_equal(previous_regime, frame.previous_regime.to_numpy())
    np.testing.assert_array_equal(raw_regime, frame.regime.to_numpy())
    boundary = frame.regime.eq('bull') & frame.previous_regime.eq('bear')
    np.testing.assert_array_equal(boundary.to_numpy(), frame.entry_direction_gate_applies.to_numpy())
    return {'acf_recovery_opportunities': int(recovery.sum()),
            'original_eligible_flat_opportunities': int((before_flat & range_pass & momentum_pass & acf_pass).sum()),
            'enhanced_eligible_flat_opportunities': int((before_flat & eligible).sum()),
            'holding_eligibility_has_no_exception': True,
            'direction_boundary_signal_days': int(boundary.sum()),
            'direction_gate_opportunities': int((before_flat & eligible & boundary).sum())}


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
            expected=frame.confirmation_score.ge(config['payload']['parameters']['confirmation']['threshold'])
        else:
            direction=1 if config['mode']=='M2' else -1
            expected=(direction*frame.confirmation_delta).ge(0)
        assert np.array_equal(expected,frame.confirmation_pass)
        state_confirmed=pd.Series(True,index=frame.index)
        if config.get('mechanism') == 'RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY':
            _audit_boundary_recovery_eligibility(frame, config)
            state_confirmed=~frame.entry_direction_gate_applies | frame.entry_direction_up
        if config.get('mechanism') == 'RAW_BEAR_TIME_BELOW_BODY_ACF_RECOVERY':
            _audit_recovery_eligibility(frame, config)
        if config.get('mechanism') in ('MEAN_BEAR_TIME_REENTRY_CLOSE','MEAN_BEAR_TIME_REENTRY_BODY'):
            independent=(frame.entry_signal_close.gt(frame.previous_signal_close) if config['mechanism'].endswith('CLOSE')
                         else frame.entry_signal_close.gt(frame.entry_signal_open))
            assert np.array_equal(independent,frame.entry_direction_up)
            applies=opportunity & frame.regime.eq('bear') & frame.last_exit_reason.eq('time') & frame.last_exit_route.eq('bear')
            assert np.array_equal(applies,frame.entry_direction_gate_applies)
            state_confirmed=~applies | independent
        if config.get('mechanism') in ('MEAN_BEAR_TIME_BELOW_CLOSE', 'MEAN_BEAR_TIME_BELOW_BODY',
                                     'MEAN_BEAR_TIME_ABOVE_CLOSE', 'MEAN_BEAR_TIME_ABOVE_BODY',
                                     'MEAN_FIXED120_BEAR_TIME_BELOW_CLOSE', 'MEAN_BEAR_TIME_BELOW_SEGMENT_CLOSE', 'RAW_BEAR_TIME_BELOW_CLOSE', 'RAW_BEAR_TIME_BELOW_BODY'):
            independent=(frame.entry_signal_close.gt(frame.previous_signal_close) if config['mechanism'].endswith('CLOSE')
                         else frame.entry_signal_close.gt(frame.entry_signal_open))
            assert np.array_equal(independent,frame.entry_direction_up)
            category=frame.last_exit_category
            assert (category.isna() | category.isin(('BELOW','EQUAL','ABOVE'))).all(), 'Invalid exit category'
            selected='BELOW' if '_BELOW_' in config['mechanism'] else 'ABOVE'
            applies=(opportunity & frame.regime.eq('bear') & frame.last_exit_reason.eq('time')
                     & frame.last_exit_route.eq('bear') & category.eq(selected))
            assert np.array_equal(applies,frame.entry_direction_gate_applies)
            state_confirmed=~applies | independent
        if config.get('mechanism') in ('NEW_BULL_CLOSE_UP','NEW_BULL_BODY_UP','NEW_BULL_BODY_ANCHOR_LOSS','NEW_BULL_BODY_ANCHOR_LOSS2','MEAN_ACF_NEW_BULL_CLOSE','MEAN_ACF_NEW_BULL_BODY','BEAR_MEAN_ACF_BODY_ADVERSE_TR','BEAR_MEAN_ACF_BODY_ADVERSE_TR2','BEAR_MEAN_ACF_BODY_ADVERSE_TR3'):
            independent=(frame.entry_signal_close.gt(frame.previous_signal_close) if config['mechanism'] in ('NEW_BULL_CLOSE_UP','MEAN_ACF_NEW_BULL_CLOSE')
                         else frame.entry_signal_close.gt(frame.entry_signal_open))
            assert np.array_equal(independent,frame.entry_direction_up)
            applies=frame.regime.eq('bull') & frame.previous_regime.eq('bear')
            assert np.array_equal(applies,frame.entry_direction_gate_applies)
            state_confirmed=~applies | independent
        state_rejected=opportunity & ~state_confirmed
        score_rejected=opportunity & state_confirmed & ~expected
        assert np.array_equal(opportunity & state_confirmed & expected,frame.signal_reason.eq('entry'))
        assert np.array_equal(score_rejected,frame.signal_reason.eq('confirmation_rejected'))
        assert np.array_equal(state_rejected,frame.signal_reason.eq('entry_direction_rejected'))
        masks={'base_opportunities':int(opportunity.sum()),
            'rejected_opportunities':int(score_rejected.sum()),
            'state_rejected_opportunities':int(state_rejected.sum()),
            'raw_score_below_threshold_opportunities':int((opportunity & ~expected).sum()),
            'zero_delta_opportunities':int((opportunity & frame.confirmation_delta.eq(0)).sum())
                 if config['mode'] in ('M2','M3') else None,
            'groups':frame.assign(year=pd.to_datetime(frame.signal_date).dt.year,
                                 opportunity=opportunity.astype(int),rejected=score_rejected.astype(int),
                                 state_rejected=state_rejected.astype(int))
                .groupby(['year','regime'])[['opportunity','rejected','state_rejected']].sum().reset_index().to_dict('records')}
    if config.get('mechanism') == 'RAW_BEAR_TIME_BELOW_BODY_ACF_RECOVERY':
        masks.update(_audit_recovery_eligibility(frame, config))
    if config.get('mechanism') == 'RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY':
        masks.update(_audit_boundary_recovery_eligibility(frame, config))
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
