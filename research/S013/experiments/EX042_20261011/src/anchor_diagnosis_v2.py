"""Pure native-path bear TIME anchor classification and complete cash attribution."""
from collections.abc import Mapping
import math

import numpy as np
import pandas as pd


CATEGORIES = ('BELOW', 'EQUAL', 'ABOVE', 'NONE')
EXITS = frozenset(('loss', 'trailing', 'range', 'time', 'regime'))
INITIAL_EQUITY = 1_000_000.
LIMITS = (
    'Descriptions of original certified native signal and actual cash paths only. '
    'Entry anchors are causal HFQ signal Close, distinct from actual fill profitability. '
    'All signal years and execution-date cash years are retained separately. '
    'No changed policy, deleted-trade profit, counterfactual cash, probability forecast or new economic gate. '
    'Cycle marked PnL can cross years and is not annual account return. '
    'The33 original same-market parameter neighbors are dependent observations, not independent samples.'
)


def standard(value):
    """Validate standard JSON; preserve explicit None, reject every nonfinite."""
    if isinstance(value, Mapping):
        return {str(key): standard(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [standard(nested) for nested in value]
    if isinstance(value, np.generic):
        return standard(value.item())
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            raise ValueError('Missing date must be explicit None')
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Nonfinite financial/diagnostic value')
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError('Unsupported native diagnostic value: ' + type(value).__name__)


def finite(value, positive=False):
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError('Finite positive value required' if positive else 'Finite value required')
    return result


def price_category(close, anchor):
    close, anchor = finite(close, True), finite(anchor, True)
    return 'BELOW' if close < anchor else 'ABOVE' if close > anchor else 'EQUAL'


def signal_path(values, execution):
    assert isinstance(values.index, pd.DatetimeIndex)
    dates = values.index.normalize()
    assert len(dates) and dates.is_unique and dates.is_monotonic_increasing
    assert dates.equals(values.index)
    decisions = execution.decisions.reset_index(drop=True)
    assert len(decisions) == len(values) and decisions.decision_id.is_unique
    pd.testing.assert_index_equal(pd.DatetimeIndex(pd.to_datetime(decisions.signal_date)).normalize(), dates, check_names=False)
    valid = pd.DatetimeIndex(pd.to_datetime(values.valid_session)).normalize()
    pd.testing.assert_index_equal(pd.DatetimeIndex(pd.to_datetime(decisions.valid_session)).normalize(), valid, check_names=False)
    assert valid.is_unique and valid.is_monotonic_increasing
    for name in ('signal_reason',):
        np.testing.assert_array_equal(decisions[name], values[name])
    np.testing.assert_array_equal(decisions.target_position, values.target)
    records, events = [], []
    holding, route, age, anchor = False, None, 0, None
    last_context, last_event = 'NONE', None
    holding_source, holding_event = 'NONE', None
    for i, (date, row) in enumerate(zip(dates, values.itertuples(), strict=True)):
        for name in ('holding_before', 'eligible', 'opportunity', 'score_pass', 'entry', 'close_up', 'body_up'):
            assert isinstance(getattr(row, name), (bool, np.bool_)), 'Certified predicate must be boolean: ' + name
        assert not isinstance(row.age_before, (bool, np.bool_))
        assert finite(row.age_before) >= 0 and int(row.age_before) == row.age_before
        close = finite(row.signal_close, True)
        opening, previous = finite(row.signal_open, True), finite(row.previous_signal_close, True)
        assert row.raw_route in ('bull', 'bear')
        assert bool(row.holding_before) == holding
        assert row.route_before == route and row.age_before == (age if holding else 0)
        assert row.active_route == (route if holding else row.raw_route)
        assert bool(row.opportunity) == bool(not holding and row.eligible)
        assert bool(row.entry) == (row.signal_reason == 'entry')
        assert bool(row.close_up) == (close > previous) and bool(row.body_up) == (close > opening)
        before_context, before_event = last_context, last_event
        source_before, source_event_before = (holding_source, holding_event) if holding else ('NONE', None)
        anchor_before, route_before = anchor, route
        if holding:
            assert row.signal_reason in EXITS | {'hold'} and not row.entry
            age += 1
            if row.signal_reason != 'hold':
                category = price_category(close, anchor) if route == 'bear' and row.signal_reason == 'time' else 'NONE'
                event = {'event_id': len(events), 'signal_index': i, 'signal_date': date,
                         'valid_session': valid[i], 'exit_reason': row.signal_reason, 'exit_route': route,
                         'holding_age_at_exit': age, 'entry_anchor_signal_close': anchor,
                         'exit_signal_close': close, 'exit_minus_anchor_hfq': close - anchor,
                         'category': category, 'is_bear_time': route == 'bear' and row.signal_reason == 'time',
                         'holding_source_context': holding_source, 'holding_source_event_id': holding_event}
                events.append(event)
                last_context, last_event = category, event['event_id']
                holding, route = False, None
        else:
            assert row.signal_reason in ('flat', 'entry', 'confirmation_rejected', 'entry_direction_rejected')
            if row.entry:
                assert row.opportunity and row.score_pass
                holding_source, holding_event = before_context, before_event
                holding, route, age, anchor = True, row.raw_route, 0, close
                last_context, last_event = 'NONE', None
            elif row.signal_reason.endswith('rejected'):
                assert row.opportunity
            else:
                assert not row.opportunity
        assert finite(row.target) == float(holding)
        records.append({'signal_index': i, 'signal_date': date, 'valid_session': valid[i],
            'decision_id': decisions.decision_id.iloc[i], 'raw_route': row.raw_route,
            'active_route': row.active_route, 'holding_before': bool(row.holding_before),
            'route_before': route_before, 'age_before': int(row.age_before),
            'eligible': bool(row.eligible), 'opportunity': bool(row.opportunity),
            'score_pass': bool(row.score_pass), 'entry': bool(row.entry), 'target': finite(row.target),
            'signal_reason': row.signal_reason, 'signal_close': close, 'signal_open': opening,
            'previous_signal_close': previous, 'close_up': bool(row.close_up), 'body_up': bool(row.body_up),
            'entry_anchor_signal_close_before': anchor_before, 'entry_anchor_signal_close_after': anchor,
            'pre_context': before_context, 'pre_context_event_id': before_event,
            'post_context': last_context, 'post_context_event_id': last_event,
            'holding_source_context_before': source_before, 'holding_source_event_id_before': source_event_before,
            'holding_source_context_after': holding_source if holding else 'NONE',
            'holding_source_event_id_after': holding_event if holding else None})
    entries = [i for i, record in enumerate(records) if record['entry']]
    for event in events:
        i = event['signal_index']
        next_entries = [j for j in entries if j > i]
        following = next_entries[0] if next_entries else None
        end = following + 1 if following is not None else len(records)
        opportunity = [j for j in range(i + 1, end) if records[j]['opportunity'] and records[j]['raw_route'] == 'bear']
        refused = [j for j in range(i + 1, end) if records[j]['signal_reason'] == 'entry_direction_rejected']

        def next_record(j):
            return None if j is None else {'signal_index': j, 'signal_date': records[j]['signal_date'],
                'raw_route': records[j]['raw_route'], 'signal_reason': records[j]['signal_reason'],
                'waiting_signal_sessions': j - i, 'pre_context': records[j]['pre_context'],
                'close_up': records[j]['close_up'], 'body_up': records[j]['body_up']}

        event.update(next_any_entry=next_record(following),
                     next_bear_opportunity=next_record(opportunity[0] if opportunity else None),
                     next_direction_rejection=next_record(refused[0] if refused else None),
                     bear_opportunity_indices=opportunity, direction_rejection_indices=refused,
                     no_subsequent_entry=following is None,
                     context_end_exclusive=end)
    tail = {'holding': holding, 'route': route, 'age': age if holding else 0,
            'entry_anchor_signal_close': anchor if holding else None,
            'holding_source_context': holding_source if holding else 'NONE',
            'holding_source_event_id': holding_event if holding else None,
            'unconsumed_exit_context': last_context, 'unconsumed_exit_event_id': last_event}
    return records, events, tail


def signal_statistics(records, events):
    years = sorted({record['signal_date'].year for record in records})
    output = []
    for year in ['ALL', *years]:
        days = [record for record in records if year == 'ALL' or record['signal_date'].year == year]
        exits = [event for event in events if year == 'ALL' or event['signal_date'].year == year]
        for category in CATEGORIES:
            selected = [record for record in days if record['pre_context'] == category]
            time = [event for event in exits if event['exit_reason'] == 'time' and event['category'] == category]
            output.append({'year': str(year), 'category': category, 'signal_days': len(selected),
                'flat_signal_days': sum(not record['holding_before'] for record in selected),
                'bear_opportunities': sum(record['opportunity'] and record['raw_route'] == 'bear' for record in selected),
                'signal_entries': sum(record['entry'] for record in selected),
                'direction_rejections': sum(record['signal_reason'] == 'entry_direction_rejected' for record in selected),
                'all_time_exits': len(time), 'bear_time_exits': sum(event['is_bear_time'] for event in time),
                'time_exits_without_subsequent_entry': sum(event['no_subsequent_entry'] for event in time)})
    assert sum(row['signal_days'] for row in output if row['year'] == 'ALL') == len(records)
    assert sum(row['signal_days'] for row in output if row['year'] != 'ALL') == len(records)
    assert sum(row['all_time_exits'] for row in output if row['year'] == 'ALL') == sum(event['exit_reason'] == 'time' for event in events)
    return output


def actual_cash(records, execution):
    account = execution.account_daily.copy().reset_index(drop=True)
    account['date'] = pd.to_datetime(account.date).dt.normalize()
    pd.testing.assert_index_equal(pd.DatetimeIndex(account.date).as_unit('ns'), pd.DatetimeIndex([record['valid_session'] for record in records]).as_unit('ns'), check_names=False)
    assert account.date.is_unique and account.date.is_monotonic_increasing
    lookup = {record['decision_id']: record for record in records}
    assert len(lookup) == len(records)
    fills = execution.fills.copy()
    assert fills.fill_id.is_unique and set(fills.side) <= {'BUY', 'SELL'}
    fills['date'] = pd.to_datetime(fills.fill_time).dt.normalize()
    assert set(fills.date) <= set(account.date)
    days = {day: group.sort_values(['fill_time', 'fill_id']) for day, group in fills.groupby('date')}
    inventory, cycles, daily = {}, {}, []
    cash, previous_equity, previous_close = INITIAL_EQUITY, INITIAL_EQUITY, 0.
    for mark, record in zip(account.itertuples(), records, strict=True):
        close, equity = finite(mark.close, True), finite(mark.equity, True)
        native_cash = finite(mark.cash)
        assert int(mark.quantity) == mark.quantity and mark.quantity >= 0
        parts = {category: {'gross_price_change': 0., 'fees': 0.} for category in CATEGORIES}
        for cycle_id, quantity in inventory.items():
            parts[cycles[cycle_id]['source_category']]['gross_price_change'] += quantity * (close - previous_close)
        fill_rows = []
        for fill in days.get(mark.date, pd.DataFrame()).itertuples():
            assert fill.decision_id in lookup
            signal = lookup[fill.decision_id]
            assert signal['valid_session'] == mark.date
            assert pd.Timestamp(fill.signal_date).normalize() == signal['signal_date']
            price, fees = finite(fill.price, True), finite(fill.fees)
            quantity = int(fill.quantity)
            assert quantity == fill.quantity and quantity > 0 and fees >= 0
            if fill.side == 'BUY':
                assert signal['target'] == 1.
                if fill.cycle_id not in cycles:
                    cycles[fill.cycle_id] = {'cycle_id': fill.cycle_id,
                        'source_category': signal['holding_source_context_after'],
                        'source_event_id': signal['holding_source_event_id_after'],
                        'entry_decision_id': fill.decision_id, 'entry_signal_date': signal['signal_date'],
                        'entry_fill_time': pd.Timestamp(fill.fill_time), 'purchased_quantity': 0,
                        'sold_quantity': 0, 'buy_notional': 0., 'sell_notional': 0., 'fees': 0.,
                        'buy_fill_source_disagreements': 0, 'fill_decision_ids': []}
                cycle = cycles[fill.cycle_id]
                cycle['buy_fill_source_disagreements'] += int(signal['holding_source_context_after'] != cycle['source_category'])
                inventory[fill.cycle_id] = inventory.get(fill.cycle_id, 0) + quantity
                cycle['purchased_quantity'] += quantity
                cycle['buy_notional'] += quantity * price
                sign = 1
            else:
                assert fill.cycle_id in cycles and inventory.get(fill.cycle_id, 0) >= quantity
                cycle = cycles[fill.cycle_id]
                inventory[fill.cycle_id] -= quantity
                cycle['sold_quantity'] += quantity
                cycle['sell_notional'] += quantity * price
                cycle['last_sell_fill_time'] = pd.Timestamp(fill.fill_time)
                sign = -1
            cycle['fees'] += fees
            cycle['fill_decision_ids'].append(fill.decision_id)
            category = cycle['source_category']
            parts[category]['gross_price_change'] += sign * quantity * (close - price)
            parts[category]['fees'] += fees
            cash -= sign * quantity * price + fees
            fill_rows.append({'fill_id': fill.fill_id, 'cycle_id': fill.cycle_id,
                'decision_id': fill.decision_id, 'side': fill.side, 'quantity': quantity,
                'price': price, 'fees': fees, 'source_category': category,
                'decision_holding_source_context': signal['holding_source_context_after'] if fill.side == 'BUY' else signal['holding_source_context_before']})
        assert sum(inventory.values()) == mark.quantity
        assert abs(cash - native_cash) < 1e-6 and abs(native_cash + mark.quantity * close - equity) < 1e-6
        net = equity - previous_equity
        for component in parts.values():
            component['net_equity_change'] = component['gross_price_change'] - component['fees']
        assert abs(sum(component['net_equity_change'] for component in parts.values()) - net) < 1e-6
        fees = sum(component['fees'] for component in parts.values())
        daily.append({'date': mark.date, 'signal_date': record['signal_date'], 'decision_id': record['decision_id'],
            'pre_context': record['pre_context'], 'pre_context_event_id': record['pre_context_event_id'],
            'opening_equity': previous_equity, 'closing_equity': equity, 'cash': native_cash,
            'quantity': int(mark.quantity), 'close': close, 'net_equity_change': net, 'fees': fees,
            'holding_source_components': [{'category': category, **parts[category]} for category in CATEGORIES],
            'fills': fill_rows})
        previous_equity, previous_close = equity, close
    trades = execution.trades
    assert trades.cycle_id.is_unique and set(trades.cycle_id) == set(cycles)
    native_cycles = trades.set_index('cycle_id')
    cycle_rows = []
    for cycle_id, cycle in cycles.items():
        remaining = inventory[cycle_id]
        status = 'OPEN' if remaining else 'CLOSED'
        assert native_cycles.loc[cycle_id, 'status'] == status
        marked_pnl = cycle['sell_notional'] + remaining * previous_close - cycle['buy_notional'] - cycle['fees']
        cycle_rows.append({**cycle, 'status': status, 'remaining_quantity': remaining,
            'marked_net_pnl_including_tail': marked_pnl,
            'warning': 'Whole-cycle actual marked PnL, potentially跨year; never annual return or deletion gain.'})
    assert abs(sum(row['marked_net_pnl_including_tail'] for row in cycle_rows) - (previous_equity - INITIAL_EQUITY)) < 1e-6
    years = sorted({row['date'].year for row in daily})
    annual = []
    for year in ['ALL', *years]:
        selected = [row for row in daily if year == 'ALL' or row['date'].year == year]
        opening, closing = selected[0]['opening_equity'], selected[-1]['closing_equity']
        groups = []
        for category in CATEGORIES:
            prior = [row for row in selected if row['pre_context'] == category]
            source = [part for row in selected for part in row['holding_source_components'] if part['category'] == category]
            groups.append({'category': category, 'pre_context_days': len(prior),
                'pre_context_net_equity_change': sum(row['net_equity_change'] for row in prior),
                'pre_context_fees': sum(row['fees'] for row in prior),
                'holding_source_net_equity_change': sum(part['net_equity_change'] for part in source),
                'holding_source_fees': sum(part['fees'] for part in source)})
        net, fees = sum(row['net_equity_change'] for row in selected), sum(row['fees'] for row in selected)
        assert abs(net - (closing - opening)) < 1e-6
        for key in ('pre_context_net_equity_change', 'holding_source_net_equity_change'):
            assert abs(sum(group[key] for group in groups) - net) < 1e-6
        for key in ('pre_context_fees', 'holding_source_fees'):
            assert abs(sum(group[key] for group in groups) - fees) < 1e-6
        annual.append({'year': str(year), 'opening_equity': opening, 'closing_equity': closing,
            'net_equity_change': net, 'fees': fees, 'account_return': closing / opening - 1, 'groups': groups})
    return daily, annual, cycle_rows


def diagnose_account(values, execution):
    """All dates/native cash included; input state is already independently certified."""
    records, events, tail = signal_path(values, execution)
    daily, annual, cycles = actual_cash(records, execution)
    assert len(records) == len(values) == len(daily)
    result = {'all_native_days': records, 'exit_events': events,
        'statistics': signal_statistics(records, events), 'annual_cash': annual,
        'all_execution_days': daily, 'cycles': cycles,
        'summary': {'native_signal_days': len(records), 'actual_execution_days': len(daily),
            'all_signal_exits': len(events), 'all_time_exits': sum(event['exit_reason'] == 'time' for event in events),
            'bear_time_exits': sum(event['is_bear_time'] for event in events),
            'bear_time_categories': {category: sum(event['is_bear_time'] and event['category'] == category for event in events) for category in CATEGORIES},
            'signal_tail': tail, 'closed_actual_cycles': sum(cycle['status'] == 'CLOSED' for cycle in cycles),
            'open_actual_cycles': sum(cycle['status'] == 'OPEN' for cycle in cycles),
            'actual_buy_fill_source_disagreements': sum(cycle['buy_fill_source_disagreements'] for cycle in cycles),
            'new_account_evaluations': 0, 'cash_partitions': 'BOTH_EXACT_COMPLETE'},
        'definitions': {'contexts': 'BELOW/EQUAL/ABOVE only bear TIME exit current HFQClose vs same-holding signal-entry anchor; other exits NONE. Strict comparisons, no epsilon.',
            'pre_context': 'Last exit category before T; any new signal entry clears, flat/refusal/rawroute change preserves.',
            'holding_source': 'Entry snapshots its pre-context; signal holding preserves source. Actual cycle source takes first BUY fill decision_id verified signal source; all fills retain their own decision provenance and any mismatch is explicit.',
            'next_events': 'Next bear opportunity/refusal restricted to the exit context until the next any-route entry inclusive; None if absent, including open tails.',
            'cash': 'Separate complete partitions by signal T pre-context and actual-cycle entry-source category. Actual inventory/fill-price/fees reconstruct each native daily equity change; initial equity1M and year opening carry exact. Groups are additive cash accounting, not additive intervention profit.'},
        'limits': LIMITS}
    return standard(result)
