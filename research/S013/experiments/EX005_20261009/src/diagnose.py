"""Independent cash/position checks, annual price/fee attribution, known data limits."""
import numpy as np
import pandas as pd

from common import RUNS, CACHE, read, write, cache_read


def rows():
    return [row for path in sorted(RUNS.glob('state_*.json'))
            if 'rows' in read(path) for row in read(path)['rows']]


def verify_account(bound, result):
    run = result.runs[0]
    account = run.execution.account_daily.copy()
    fills = run.execution.fills.copy()
    account['date'] = pd.to_datetime(account.date).dt.normalize()
    fills['date'] = pd.to_datetime(fills.fill_time).dt.normalize()
    quantities = fills.assign(signed=np.where(fills.side.eq('BUY'), 1, -1) * fills.quantity)
    by_date = {day: group for day, group in fills.groupby('date')}
    signed = quantities.groupby('date').signed.sum()
    expected_quantity = account.date.map(signed).fillna(0).cumsum().to_numpy()
    assert np.array_equal(expected_quantity, account.quantity.to_numpy())
    cash_changes = fills.assign(change=np.where(fills.side.eq('BUY'), -1, 1)
                                * fills.quantity * fills.price - fills.fees).groupby('date').change.sum()
    expected_cash = 1_000_000 + account.date.map(cash_changes).fillna(0).cumsum().to_numpy()
    cash_error = float(np.max(np.abs(expected_cash - account.cash.to_numpy())))
    assert cash_error < 1e-6
    previous_equity, previous_quantity, previous_close = 1_000_000., 0, 0.
    contributions = []
    errors = []
    for day in account.itertuples():
        gross = previous_quantity * (day.close - previous_close)
        fees = 0.
        if day.date in by_date:
            for fill in by_date[day.date].itertuples():
                sign = 1 if fill.side == 'BUY' else -1
                gross += sign * fill.quantity * (day.close - fill.price)
                fees += fill.fees
        net = day.equity - previous_equity
        errors.append(abs(gross - fees - net))
        contributions.append({'date': day.date, 'gross': gross, 'fees': fees, 'net': net})
        previous_equity, previous_quantity, previous_close = day.equity, day.quantity, day.close
    assert max(errors) < 1e-6
    frame = pd.DataFrame(contributions)
    annual, anchor = {}, 1_000_000.
    for year in range(2020, 2027):
        sub = frame.loc[frame.date.dt.year.eq(year)]
        segment = account.loc[account.date.dt.year.eq(year)]
        wealth = np.r_[anchor, segment.equity.to_numpy()]
        annual[str(year)] = {'opening_equity': anchor, 'net_pnl': float(sub.net.sum()),
            'price_pnl': float(sub.gross.sum()), 'fees': float(sub.fees.sum()),
            'net_return': float(wealth[-1] / anchor - 1),
            'price_contribution': float(sub.gross.sum() / anchor),
            'fee_contribution': float(sub.fees.sum() / anchor),
            'drawdown_magnitude': float(np.max(1 - wealth / np.maximum.accumulate(wealth)))}
        assert abs(annual[str(year)]['net_return'] - sub.net.sum() / anchor) < 1e-12
        anchor = float(wealth[-1])
    data = bound.execution_data
    raw = data.raw_execution_daily.set_index('dt')
    normalized = data.execution_daily.set_index('dt')
    low_date = pd.Timestamp('2020-12-01')
    scale = float(normalized.loc[low_date, 'close'] / raw.loc[low_date, 'close'])
    actual_low = float(data.execution_intraday.loc[
        pd.to_datetime(data.execution_intraday.dt).dt.normalize().eq(low_date), 'low'].min())
    assert abs(float(raw.loc[low_date, 'low']) - 6.961) < 1e-12
    assert abs(actual_low / scale - 6.967) < 1e-12
    orders = run.execution.orders
    affected = orders.loc[pd.to_datetime(orders.execution_date).dt.normalize().eq(low_date)]
    potential = affected.loc[affected.side.eq('BUY') & affected.order_type.eq('LIMIT')
        & affected.status.eq('UNFILLED') & affected.limit_price.gt(6.961 * scale)
        & affected.limit_price.le(6.967 * scale)]
    return {'candidate_id': bound.strategy.candidate_id, 'annual': annual,
            'max_cash_error': cash_error, 'max_daily_attribution_error': max(errors),
            'quantity_reconciliation': 'EXACT_EQUAL', 'execution_data_identity': data.fingerprint,
            'known_low_error_potential_orders': len(potential)}


def main():
    valid = [row for row in rows() if row['status'] == 'SUCCEEDED']
    assert len({row['candidate_id'] for row in valid}) == len(valid)
    diagnostics = []
    for row in valid:
        bound, result = cache_read(CACHE / f'{row["candidate_id"]}.pkl.gz')
        assert result.result_hash == row['result_hash']
        proof = verify_account(bound, result)
        for year, value in proof['annual'].items():
            assert abs(value['net_return'] - row['annual'][year]['return']) < 1e-12
            assert abs(value['drawdown_magnitude'] - row['annual'][year]['max_drawdown_magnitude']) < 1e-12
        diagnostics.append(proof)
    write(RUNS / 'diagnostics.json', {'status': 'PASS', 'accounts': diagnostics,
        'known_low_error_potential_orders': sum(x['known_low_error_potential_orders'] for x in diagnostics),
        'scope': 'full successful standard accounts; known 2020-12-01 minute Low discrepancy; no unknown tick reconstruction',
        'high_limitations': 'four known minute High deviations do not enter trusted daily features or LIMIT BUY/MARKET SELL fills'})
    print({'status': 'PASS', 'accounts': len(diagnostics),
           'known_low_error_potential_orders': sum(x['known_low_error_potential_orders'] for x in diagnostics)})


if __name__ == '__main__':
    main()
