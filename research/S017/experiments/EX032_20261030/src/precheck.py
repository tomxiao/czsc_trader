"""Bounded synthetic V4 checks for the exact EX032 strategy; no return evidence."""
from datetime import date, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import json

import pandas as pd
from dataflows import BarFrequency, TradingSession, TimeInterval
from strategy_runtime import AccountStrategyState, CycleState, ReadyValue, StateRecord
from strategy_runtime import PreparedReplay, run_replay
from trading_execution_engine import PortfolioHistoricalExecutor

from common import WORK, SPEC, PARAMETERS, candidate, digest, explicit_rules, save
from strategy import OUTPUTS, step


def facts(decision):
    return {row['key']: row['text'] for row in decision['explanation']['basis']}


def direct_checks():
    stamp = datetime(2019, 3, 4, 15, tzinfo=ZoneInfo('UTC'))
    values = dict(zip(OUTPUTS, (101., 99., 100., 100., 150., 1., 1., 100.), strict=True))

    def call(mechanism='S017-M005', change=None, cycle=None, current=stamp):
        data = {**values, **({} if change is None else change)}
        portfolio = SimpleNamespace(quantity=0 if cycle is None else 1, reference_price_scale=1.,
            cycle_entry=None if cycle is None else cycle.entry_at, cycle_cost=0. if cycle is None else 100.)
        context = SimpleNamespace(parameters={'entry_mechanism': mechanism, 'max_holding_bars': 65},
            portfolio=portfolio, events=(), features={k: ReadyValue(v) for k, v in data.items()},
            history=SimpleNamespace(last=lambda: {'Date': current}))
        return step(context, AccountStrategyState(cycle=cycle))

    results = {}
    for mechanism in ('S017-M005', 'S017-M008'):
        assert call(mechanism).decision.target == 1
        assert call(mechanism, {'close': 100.}).decision.target == 0
        assert call(mechanism, {'previous_close': 100.}).decision.target == 0
        assert call(mechanism, {'previous_volume': 149.999}).decision.target == 0
        results[mechanism + '_strict_reclaim_bearish_and_volume_equality'] = 'PASS'
    assert call('S017-M005', {'previous_tr': 1.00001}).decision.target == 0
    assert call('S017-M008', {'previous_tr': 1.00001}).decision.target == 1
    results['narrow_equality_and_only_declared_entry_difference'] = 'PASS'
    held = CycleState('synthetic-confirmed-cycle', stamp - timedelta(days=5), StateRecord((
        ('holding_bars', 63), ('last_completed_at', stamp - timedelta(minutes=30)), ('exit_due', False))))
    first = call(cycle=held)
    assert first.decision.target == 1 and dict(first.cycle_values.values)['holding_bars'] == 64
    held = CycleState(held.cycle_id, held.entry_at, first.cycle_values)
    due = call(cycle=held, current=stamp + timedelta(minutes=30))
    assert due.decision.target == 0 and dict(due.cycle_values.values)['holding_bars'] == 65
    assert dict(due.cycle_values.values)['exit_due'] is True
    held = CycleState(held.cycle_id, held.entry_at, due.cycle_values)
    blocked = call(cycle=held, current=stamp + timedelta(minutes=60))
    assert blocked.decision.target == 0 and dict(blocked.cycle_values.values)['exit_due'] is True
    results['confirmed_cycle_64_65_and_exit_due_latch'] = 'PASS'
    try:
        call(cycle=held, current=stamp + timedelta(minutes=30))
    except ValueError as exc:
        assert 'advance monotonically' in str(exc)
    else:
        raise AssertionError('Repeated completed observation accepted')
    results['repeated_observation_rejected'] = 'PASS'
    return results


def synthetic_frames():
    zone = ZoneInfo('America/New_York')
    dates, current = [], date(2019, 2, 1)
    while len(dates) < 40:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    sessions = tuple(TradingSession(day, str(zone), (TimeInterval(
        datetime(day.year, day.month, day.day, 9, 30, tzinfo=zone),
        datetime(day.year, day.month, day.day, 16, tzinfo=zone)),)) for day in dates)
    periods = tuple(period for session in sessions for period in session.bars(BarFrequency.M30))
    starts = pd.DatetimeIndex([p.start for p in periods]).tz_convert('UTC')
    ends = pd.DatetimeIndex([p.end for p in periods]).tz_convert('UTC')
    bars = pd.DataFrame({'BarStart': starts, 'Date': ends, 'AvailableDate': ends,
        'Open': 100., 'High': 100.5, 'Low': 99.5, 'Close': 100.,
        'Volume': 1000000., 'Amount': 100000000.})
    for signal, wide in ((273, False), (276, False), (350, True), (420, False)):
        bars.loc[signal - 1, ['Open', 'High', 'Low', 'Close', 'Volume']] = (
            [104., 104.5, 99.5, 100., 1500000.] if wide else [100.2, 100.4, 99.6, 100., 1500000.])
        bars.loc[signal, ['Open', 'High', 'Low', 'Close']] = (
            [100.3, 104.7, 100.2, 104.6] if wide else [100.3, 100.7, 100.2, 100.6])
    constraints = explicit_rules(pd.DataFrame({'Date': starts, 'AvailableDate': starts,
        'QuantityStep': 1, 'PriceTick': .01, 'Tradable': True}))
    constraints.loc[[274, 342], 'Tradable'] = False
    actions = pd.DataFrame([{'Date': starts[0], 'AvailableDate': starts[0], 'EventId': 'synthetic-none',
        'Kind': 'NONE', 'Ratio': 1., 'CashPerShare': 0., 'PayAt': None}])
    frame = pd.DataFrame({'Date': [s.segments[0].start for s in sessions],
        'AvailableDate': [s.segments[0].start for s in sessions],
        'SessionDate': [s.session_date.isoformat() for s in sessions]})
    return bars, constraints, actions, sessions, frame


def replay(key, bars, constraints, actions, sessions, frame, *, last=None):
    value = candidate(key)
    prepared = PreparedReplay.from_frames(bars, constraints, value.definition.feature_graph,
        frequency=BarFrequency.M30, timezone=value.instrument.timezone,
        sessions=frame, trading_sessions=sessions)
    executor = PortfolioHistoricalExecutor(specification=SPEC, initial_cash=100000.,
        fee_rate=.001, actions=actions, price_basis='RAW')
    return run_replay(prepared, value, executor,
        start=bars.BarStart.iloc[274].to_pydatetime(),
        end=bars.Date.iloc[-1 if last is None else last].to_pydatetime(), fee_rate=.001)


def normalize_prefix(result, cutoff):
    fields = {'decisions': 'decision_at', 'orders': 'valid_start', 'fills': 'interval_start',
        'account_points': 'time', 'account_daily': 'time', 'trades': 'exit_at'}
    output = {}
    for table, time_column in fields.items():
        frame = getattr(result, table)
        if frame.empty:
            output[table] = []
            continue
        if table == 'trades':
            frame = frame[frame.status.eq('CLOSED')]
        stamps = pd.to_datetime(frame[time_column], utc=True)
        selected = frame[stamps <= cutoff] if table.startswith('account') or table == 'trades' else frame[stamps < cutoff]
        # Different prepared identities may legitimately change bookkeeping ids.
        selected = selected.drop(columns=[c for c in selected.columns if c.endswith('_id')], errors='raise')
        output[table] = json.loads(selected.to_json(orient='records', date_format='iso', double_precision=15))
    assert result.corporate_action_entries.empty
    output['corporate_action_entries'] = []
    return output


def integration_checks():
    bars, constraints, actions, sessions, frame = synthetic_frames()
    altered = bars.copy(deep=True)
    altered.loc[400:, ['Open', 'High', 'Low', 'Close']] *= 1.4
    altered.loc[400:, 'Volume'] *= 3.
    altered.loc[400:, 'Amount'] *= 4.2
    cutoff = bars.BarStart.iloc[400]
    evidence = {}
    for key, parameters in PARAMETERS.items():
        failed = replay(key, bars, constraints, actions, sessions, frame, last=274)
        assert failed.state.cycle is None
        assert failed.execution_result.fills.empty
        assert len(failed.execution_result.orders) == 1
        assert failed.execution_result.orders.status.iloc[0] != 'FILLED'
        base = replay(key, bars, constraints, actions, sessions, frame)
        result = base.execution_result
        changed = replay(key, altered, constraints, actions, sessions, frame)
        original_prefix = normalize_prefix(result, cutoff)
        modified_prefix = normalize_prefix(changed.execution_result, cutoff)
        assert original_prefix == modified_prefix, 'Future data changed completed prefix facts'
        buys = result.fills[result.fills.side.eq('BUY')]
        sells = result.fills[result.fills.side.eq('SELL')]
        expected = 3 if parameters['entry_mechanism'] == 'S017-M008' else 2
        assert len(buys) == len(sells) == expected
        assert pd.Timestamp(buys.interval_start.iloc[0]) == bars.BarStart.iloc[277]
        assert pd.Timestamp(sells.interval_start.iloc[0]) == bars.BarStart.iloc[343]
        decision_facts = [(pd.Timestamp(row['decision_at']), facts(row)) for row in result.decisions.to_dict('records')]
        at_due = next(value for stamp, value in decision_facts if stamp == bars.BarStart.iloc[342])
        after_block = next(value for stamp, value in decision_facts if stamp == bars.BarStart.iloc[343])
        first_held = next(value for stamp, value in decision_facts if stamp == bars.BarStart.iloc[278])
        assert first_held['holding_bars'] == '1'
        assert at_due['holding_bars'] == '65' and at_due['exit_trigger'] == 'S017-M009'
        assert after_block['holding_bars'] == '66' and after_block['exit_trigger'] == 'S017-M009'
        assert base.state.cycle is None and result.account_points.quantity.iloc[-1] == 0
        assert base.statistics.module_loads == 1
        assert (result.account_points.cash >= 0).all()
        evidence[key] = {'status': 'PASS', 'mechanism': parameters['entry_mechanism'],
            'buy_fills': len(buys), 'sell_fills': len(sells),
            'failed_buy_cycle_unstarted': True, 'first_held_completed_bars': 1,
            'first_exit_due_completed_bars': 65, 'blocked_exit_completed_bars': 66,
            'first_buy_interval': str(buys.interval_start.iloc[0]),
            'first_sell_interval': str(sells.interval_start.iloc[0]),
            'prefix_cutoff': cutoff.isoformat(),
            'prefix_seven_tables_sha256': sha256(json.dumps(original_prefix, sort_keys=True).encode()).hexdigest(),
            'future_suffix_rows_modified': len(bars) - 400,
            'module_loads': base.statistics.module_loads}
    return evidence


def main():
    before = digest(WORK / 'src/strategy.py')
    output = {'status': 'RUNNING', 'strategy_source_sha256': before,
        'precheck_source_sha256': digest(WORK / 'src/precheck.py'),
        'common_source_sha256': digest(WORK / 'src/common.py'),
        'contract': 'PUBLIC_SRT_TXE_V4', 'direct_checks': direct_checks()}
    output['integration'] = integration_checks()
    assert before == digest(WORK / 'src/strategy.py'), 'Strategy changed during checks'
    output.update(status='PASS', synthetic_only=True, historical_accounts_run=0,
        formal_account_publications=0, market_data_downloads=0,
        limitations=['Synthetic weekday sessions are declared test clocks, not verified market history.',
            'Checks do not establish historical performance or full repository regression.',
            'Prefix comparison excludes bookkeeping ids and only includes trades closed by cutoff; open exposure remains in account points.',
            'Raw synthetic bars have no economic events; no nonempty corporate-action claim.'])
    save(WORK / 'others/precheck.json', output)
    print('EX032_PUBLIC_V4_PRECHECK_PASS', before, flush=True)


if __name__ == '__main__':
    main()
