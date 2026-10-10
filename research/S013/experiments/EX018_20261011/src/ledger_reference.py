import numpy as np
import pandas as pd

def plain(value):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def annual_account(execution):
    account = execution.account_daily.copy()
    fills = execution.fills.copy()
    account['date'] = pd.to_datetime(account.date).dt.normalize()
    fills['date'] = pd.to_datetime(fills.fill_time).dt.normalize()
    signed = np.where(fills.side.eq('BUY'), 1, -1)
    quantity = fills.assign(change=signed * fills.quantity).groupby('date').change.sum()
    cash = fills.assign(change=-signed * fills.quantity * fills.price - fills.fees).groupby('date').change.sum()
    assert np.array_equal(account.date.map(quantity).fillna(0).cumsum(), account.quantity)
    cash_error = float(np.max(np.abs(1_000_000 + account.date.map(cash).fillna(0).cumsum() - account.cash)))
    assert cash_error < 1e-6
    daily = []
    previous_equity, previous_close, previous_quantity = 1_000_000., 0., 0
    by_date = {key: frame for key, frame in fills.groupby('date')}
    for row in account.itertuples():
        gross = previous_quantity * (row.close - previous_close)
        fees = 0.
        if row.date in by_date:
            for fill in by_date[row.date].itertuples():
                gross += (1 if fill.side == 'BUY' else -1) * fill.quantity * (row.close - fill.price)
                fees += fill.fees
        net = row.equity - previous_equity
        assert abs(gross - fees - net) < 1e-6
        daily.append({'date': row.date, 'price_pnl': gross, 'fees': fees, 'net_pnl': net})
        previous_equity, previous_close, previous_quantity = row.equity, row.close, row.quantity
    daily = pd.DataFrame(daily)
    result, opening = [], 1_000_000.
    for year, segment in account.groupby(account.date.dt.year):
        values = daily[daily.date.dt.year.eq(year)]
        closing = float(segment.equity.iloc[-1])
        result.append({'year': int(year), 'opening_equity': opening, 'closing_equity': closing,
                       'price_pnl': float(values.price_pnl.sum()), 'fees': float(values.fees.sum()),
                       'net_pnl': float(values.net_pnl.sum()), 'account_return': closing / opening - 1,
                       'price_contribution': float(values.price_pnl.sum() / opening),
                       'fee_contribution': float(values.fees.sum() / opening)})
        assert abs(result[-1]['net_pnl'] / opening - result[-1]['account_return']) < 1e-12
        opening = closing
    return result, cash_error


def concentration(cycles):
    closed = [row for row in cycles if row['status'] == 'CLOSED']
    positives = sorted([row['net_pnl'] for row in closed if row['net_pnl'] > 0], reverse=True)
    denominator = sum(positives)
    net = sum(row['net_pnl'] for row in closed)
    return {'closed_cycle_total_net_pnl': net, 'positive_cycle_pnl_sum': denominator,
            'largest_winning_cycle_fraction_of_positive_pnl': positives[0] / denominator if positives else None,
            'top_five_winning_cycles_fraction_of_positive_pnl': sum(positives[:5]) / denominator if positives else None,
            'largest_winning_cycle_fraction_of_closed_cycle_net_pnl': positives[0] / net if positives and net > 0 else None,
            'largest_winner': max(closed, key=lambda row: row['net_pnl']) if positives else None,
            'diagnostic_only': True}


def describe(cycles, keys):
    frame = pd.DataFrame([row for row in cycles if row['status'] == 'CLOSED'])
    rows = []
    for group, values in frame.groupby(keys, dropna=False):
        group = group if isinstance(group, tuple) else (group,)
        row = dict(zip(keys, group, strict=True))
        row.update({'closed_cycles': len(values), 'gross_return_mean': float(values.gross_return.mean()),
                    'gross_return_median': float(values.gross_return.median()),
                    'net_return_mean': float(values.net_return.mean()),
                    'holding_sessions_mean': float(values.holding_sessions.mean()),
                    'gross_price_pnl_sum': float(values.gross_price_pnl.sum()),
                    'fees_sum': float(values.fees.sum()), 'net_pnl_sum': float(values.net_pnl.sum()),
                    'nonpositive_gross_cycles': int(values.gross_return.le(0).sum()),
                    'gross_le_20bp_cycles': int(values.gross_return.le(.002).sum()),
                    'gross_le_40bp_cycles': int(values.gross_return.le(.004).sum()),
                    'gross_le_60bp_cycles': int(values.gross_return.le(.006).sum())})
        rows.append(plain(row))
    return rows


def inspect_run(run):
    execution = run.execution
    fills, trades, decisions = execution.fills, execution.trades, execution.decisions
    assert set(fills.side) <= {'BUY', 'SELL'}
    assert decisions.decision_id.is_unique and trades.cycle_id.is_unique and fills.fill_id.is_unique
    assert set(fills.cycle_id) == set(trades.cycle_id)
    lookup = decisions.set_index('decision_id')
    calendar = list(pd.to_datetime(execution.account_daily.date).dt.normalize())
    indices = {day: index for index, day in enumerate(calendar)}
    groups = {key: values.sort_values('fill_time') for key, values in fills.groupby('cycle_id')}
    cycles, max_return_error, multiple_fill_cycles = [], 0., []
    for trade in trades.itertuples():
        group = groups[trade.cycle_id]
        buys, sells = group[group.side.eq('BUY')], group[group.side.eq('SELL')]
        assert len(buys) and trade.status in ('CLOSED', 'OPEN')
        purchased, sold = int(buys.quantity.sum()), int(sells.quantity.sum())
        buy_notional = float((buys.quantity * buys.price).sum())
        sell_notional = float((sells.quantity * sells.price).sum())
        fees, buy_fees = float(group.fees.sum()), float(buys.fees.sum())
        assert purchased == trade.quantity
        assert abs(float(trade.entry_price) - buy_notional / purchased) < 1e-12
        if len(buys) > 1 or len(sells) > 1:
            multiple_fill_cycles.append(trade.cycle_id)
        entry_fill = buys.iloc[0]
        assert pd.Timestamp(trade.entry_date) == pd.Timestamp(entry_fill.fill_time)
        entry = lookup.loc[entry_fill.decision_id]
        assert pd.Timestamp(entry.signal_date) == pd.Timestamp(entry_fill.signal_date)
        assert pd.Timestamp(entry.valid_session).normalize() == pd.Timestamp(entry_fill.fill_time).normalize()
        row = {'cycle_id': trade.cycle_id, 'status': trade.status, 'purchased_quantity': purchased,
               'sold_quantity': sold, 'buy_notional': buy_notional, 'sell_notional': sell_notional,
               'fees': fees, 'buy_fees': buy_fees, 'sell_fees': float(sells.fees.sum()),
               'buy_cash_change': -buy_notional - buy_fees,
               'sell_cash_change': sell_notional - float(sells.fees.sum()),
               'entry_signal_date': pd.Timestamp(entry_fill.signal_date),
               'entry_fill_time': pd.Timestamp(entry_fill.fill_time),
               'entry_route': entry.regime, 'entry_reason': entry.signal_reason,
               'entry_exit_context': entry.get('confirmation_exit_context', None),
               'entry_confirmation_score': entry.get('confirmation_score', None),
               'entry_acf': float(entry.acf1), 'entry_momentum20': float(entry.momentum20),
               'entry_range_position': float(entry.range_position),
               'entry_fill_year': int(pd.Timestamp(entry_fill.fill_time).year),
               'fill_count': len(group), 'fills': group.to_dict('records')}
        if trade.status == 'CLOSED':
            assert purchased == sold and len(sells)
            assert abs(float(trade.exit_price) - sell_notional / sold) < 1e-12
            exit_fill = sells.iloc[-1]
            assert pd.Timestamp(trade.exit_date) == pd.Timestamp(exit_fill.fill_time)
            exit_decision = lookup.loc[exit_fill.decision_id]
            assert pd.Timestamp(exit_decision.signal_date) == pd.Timestamp(exit_fill.signal_date)
            assert pd.Timestamp(exit_decision.valid_session).normalize() == pd.Timestamp(exit_fill.fill_time).normalize()
            gross, net = sell_notional - buy_notional, sell_notional - buy_notional - fees
            computed_return = net / (buy_notional + buy_fees)
            error = abs(computed_return - float(trade.net_return))
            max_return_error = max(max_return_error, error)
            assert error < 1e-12
            entry_day, exit_day = pd.Timestamp(entry_fill.fill_time).normalize(), pd.Timestamp(exit_fill.fill_time).normalize()
            row.update({'gross_price_pnl': gross, 'net_pnl': net,
                        'gross_return': gross / buy_notional, 'net_return': computed_return,
                        'exit_signal_date': pd.Timestamp(exit_fill.signal_date),
                        'exit_fill_time': pd.Timestamp(exit_fill.fill_time),
                        'exit_fill_year': int(pd.Timestamp(exit_fill.fill_time).year),
                        'exit_reason': exit_decision.signal_reason, 'exit_signal_route': exit_decision.regime,
                        'holding_sessions': indices[exit_day] - indices[entry_day]})
        else:
            assert purchased > sold
            marked_value = (purchased - sold) * float(execution.account_daily.close.iloc[-1])
            row.update({'remaining_quantity': purchased - sold,
                        'mark_date': pd.Timestamp(execution.account_daily.date.iloc[-1]),
                        'marked_value': marked_value,
                        'marked_gross_price_pnl': sell_notional + marked_value - buy_notional,
                        'marked_net_pnl': sell_notional + marked_value - buy_notional - fees,
                        'closed_cycle_net_return': None})
        if entry.regime=='ensemble':
            row['feature_scope']='Single center features are descriptive only; actual route and exits are ensemble voting.'
            row['entry_center_regime']=entry.center_regime
            row['entry_votes']=int(entry.ensemble_votes)
            row['entry_quorum']=int(entry.ensemble_quorum)
        cycles.append(plain(row))
    annual, cash_error = annual_account(execution)
    tails = [row for row in cycles if row['status'] != 'CLOSED']
    ending = execution.account_daily.iloc[-1]
    assert sum(row['remaining_quantity'] for row in tails) == ending.quantity
    cycle_profit = sum(row['net_pnl'] for row in cycles if row['status'] == 'CLOSED')
    marked_tail_profit = sum(row['marked_net_pnl'] for row in tails)
    assert abs(cycle_profit + marked_tail_profit - (float(ending.equity) - 1_000_000.)) < 1e-6
    closed = [row for row in cycles if row['status'] == 'CLOSED']
    concentrated = concentration(cycles)
    account_profit = float(ending.equity) - 1_000_000.
    concentrated['full_account_net_pnl_including_marked_tail'] = account_profit
    concentrated['largest_winning_cycle_fraction_of_full_account_net_pnl'] = (
        concentrated['largest_winner']['net_pnl'] / account_profit
        if concentrated['largest_winner'] is not None and account_profit > 0 else None)
    return {'scenario': run.scenario_id, 'closed_cycles': len(closed), 'open_tail_cycles': tails,
            'multiple_fill_cycles': multiple_fill_cycles, 'cycles': cycles,
            'net_return_max_error': max_return_error, 'cash_reconciliation_max_error': cash_error,
            'quantity_reconciliation': 'EXACT_EQUAL', 'gross_return_threshold_counts': {
                str(bp): sum(row['gross_return'] <= bp / 10_000 for row in closed) for bp in (0, 20, 40, 60)},
            'concentration': concentrated, 'annual_account': annual,
            'exit_year_route_reason_descriptions': describe(cycles, ['exit_fill_year', 'entry_route', 'exit_reason']),
            'entry_year_route_descriptions': describe(cycles, ['entry_fill_year', 'entry_route'])}

