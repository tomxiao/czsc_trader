"""Draft public synthetic preflight for a fixed volume/overnight interaction.

DO NOT execute from this unassigned preparation directory. After an explicitly
allocated experiment integrates the colocated strategy/check_mechanism and run
modules, main() can exercise public SRT/TXE, write actual precheck evidence and
bind its actual source hashes. Drafting or linting this file is not a PASS.
No market download or real-data account evaluation belongs to this preflight.
"""
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import multiprocessing
import pickle
import subprocess
import sys

import pandas as pd
from dataflows import BarFrequency, TradingSession, TimeInterval
from strategy_runtime import StrategyRuntime
from trading_execution_engine.equity import EquityHistoricalExecutor
import run


SOURCE = Path(__file__).resolve().parent
RESULT_TABLES = ('decisions', 'orders', 'fills', 'corporate_action_entries',
                 'account_points', 'account_daily', 'trades')
EQUAL_DAY = date(2018, 11, 27)
LOW_DAY = date(2018, 11, 28)


def fixture():
    """New fixture: prior14-relative opening volume; original EX015 is untouched."""
    zone = ZoneInfo('America/New_York')
    days, current = [], date(2018, 10, 1)
    while current <= date(2018, 12, 7):
        if current.weekday() < 5 and current != date(2018, 11, 22):
            days.append(current)
        current += timedelta(days=1)
    calendars = tuple(TradingSession(day, str(zone), (TimeInterval(
        datetime.combine(day, time(9, 30), zone),
        datetime.combine(day, time(13 if day == date(2018, 11, 23) else 16), zone)),)) for day in days)
    rows, prior_openings = [], []
    special_high = {date(2018, 11, 21): 420000., date(2018, 11, 23): 560000.,
                    date(2018, 11, 26): 700000.}
    for session in calendars:
        day = session.session_date
        prior_mean = sum(prior_openings[-14:])/14 if len(prior_openings) >= 14 else 140000.
        if day in special_high:
            opening_volume = special_high[day]
        elif day == EQUAL_DAY:
            opening_volume = prior_mean
        elif day == LOW_DAY:
            opening_volume = prior_mean/2
        elif day > LOW_DAY:
            opening_volume = 3*prior_mean
        else:
            opening_volume = 140000.
        prior_openings.append(opening_volume)
        closes = [100.5, 101.5, 102., 102.5] + [103.]*9
        if day == date(2018, 11, 26):
            closes[4] = 98.  # Close the new Monday cycle, then prohibit same-day re-entry.
        for index, bar in enumerate(session.bars(BarFrequency.M30)):
            opening = 100. if index == 0 else closes[index-1]
            close = closes[index]
            volume = opening_volume if index == 0 else 140000.
            rows.append(dict(BarStart=bar.start, Date=bar.end, AvailableDate=bar.end,
                Open=opening, High=101. if index == 0 else max(opening, close)+.12,
                Low=99. if index == 0 else min(opening, close)-.12,
                Close=close, Volume=volume, Amount=volume*close))
    bars = pd.DataFrame(rows)
    for field in ('BarStart', 'Date', 'AvailableDate'):
        bars[field] = pd.to_datetime(bars[field], utc=True)
    constraints = pd.DataFrame(dict(Date=bars.BarStart, AvailableDate=bars.BarStart,
        QuantityStep=1, PriceTick=.01, Tradable=True))
    sessions = pd.DataFrame(dict(Date=[s.segments[0].start for s in calendars],
        AvailableDate=[s.segments[0].start for s in calendars],
        SessionDate=[s.session_date.isoformat() for s in calendars]))
    for field in ('Date', 'AvailableDate'):
        sessions[field] = pd.to_datetime(sessions[field], utc=True)
    return bars, constraints, sessions, calendars


def facts(row):
    explanation = row['explanation']
    if not isinstance(explanation, dict):
        raise ValueError('public decision lacks a structured financial explanation')
    values = {item['key']: item['text'] for item in explanation['basis']}
    if len(values) != len(explanation['basis']):
        raise ValueError('public decision contains duplicate fact keys')
    return values


def verify_lifecycle(result, calendars):
    """Require actual fills, feedback effects, volume rejection and session edges."""
    known = {bar for session in calendars for bar in session.bars(BarFrequency.M30)}
    decisions = result.decisions
    for _, row in decisions.iterrows():
        if TimeInterval(row.execution_start, row.execution_end) not in known:
            raise ValueError('public decision is outside the independent session grid')
        values = facts(row)
        if values['volume_gate'] != 'True' or values['allow_overnight'] != 'True':
            raise ValueError('public synthetic replay selected an unintended policy')
    buys = result.fills.loc[result.fills.side.eq('BUY')].copy()
    buys['_day'] = pd.to_datetime(buys.interval_start, utc=True).dt.tz_convert('America/New_York').dt.date
    if buys.empty or buys.groupby('_day').size().gt(1).any():
        raise ValueError('actual entry-cycle day limit failed')
    if len(result.trades) < 2:
        raise ValueError('completed cycle feedback was not exercised')
    orders = result.orders.set_index('order_id', verify_integrity=True)
    indexed_decisions = decisions.set_index('decision_id', verify_integrity=True)
    for _, fill in buys.iterrows():
        order = orders.loc[fill.order_id]
        values = facts(indexed_decisions.loc[order.decision_id])
        if (values.get('held') != 'False' or values.get('breakout') != 'True'
                or values.get('volume_allowed') != 'True'
                or values.get('relative_volume_sessions') != '14'
                or not float(values['opening_volume']) > float(values['prior_opening_mean_volume'])):
            raise ValueError('actual synthetic BUY lacks a strict high-volume opening breakout')
    zone = ZoneInfo('America/New_York')
    rejection_checks = {}
    for day, label in ((EQUAL_DAY, 'EQUAL'), (LOW_DAY, 'LOW')):
        selected = decisions.loc[decisions.execution_start.eq(datetime.combine(day, time(10, 30), zone))]
        if len(selected) != 1:
            raise ValueError('volume rejection decision is missing')
        row = selected.iloc[0]
        values = facts(row)
        opening, prior = float(values['opening_volume']), float(values['prior_opening_mean_volume'])
        relation = opening == prior if label == 'EQUAL' else opening < prior
        if (not relation or values.get('held') != 'False' or values.get('breakout') != 'True'
                or values.get('opening_bullish') != 'True' or values.get('volume_allowed') != 'False'
                or values.get('completed_entry_cycle_today') != 'False' or float(row.target) != 0
                or buys['_day'].eq(day).any()):
            raise ValueError('equal/low volume was not explicitly responsible for rejecting a legal breakout')
        rejection_checks[label] = {'session': day.isoformat(), 'opening_volume': opening,
                                  'prior14_mean': prior, 'target': 0, 'actual_buys': 0}
    entries = pd.to_datetime(result.trades.entry_at, utc=True).dt.tz_convert(zone).dt.date
    exits = pd.to_datetime(result.trades.exit_at, utc=True).dt.tz_convert(zone).dt.date
    if not ((entries == date(2018, 11, 23)) & (exits == date(2018, 11, 26))).any():
        raise ValueError('half-day/weekend hold was not exercised')
    if int(buys['_day'].eq(date(2018, 11, 26)).sum()) != 1:
        raise ValueError('previous entry-day closure improperly blocked current-day entry')
    if not ((entries == date(2018, 11, 26)) & (exits == date(2018, 11, 26))).any():
        raise ValueError('same-day new cycle closure was not exercised')
    blocked = decisions.loc[decisions.execution_start.eq(datetime(2018, 11, 26, 12, 30, tzinfo=zone))]
    if (len(blocked) != 1 or float(blocked.target.iloc[0]) != 0
            or facts(blocked.iloc[0]).get('completed_entry_cycle_today') != 'True'):
        raise ValueError('actual same-day closed-cycle feedback failed to prevent re-entry')
    half_end = next(s.segments[-1].end for s in calendars if s.session_date == date(2018, 11, 23))
    half = decisions.loc[decisions.execution_start.eq(half_end-timedelta(minutes=30))]
    if len(half) != 1 or float(half.target.iloc[0]) != 1:
        raise ValueError('an untriggered held cycle failed to survive the half-day last interval')
    first = decisions.loc[decisions.execution_start.eq(datetime(2018, 11, 26, 9, 30, tzinfo=zone))]
    if len(first) != 1 or float(first.target.iloc[0]) != 1:
        raise ValueError('crossday holding was lost before the next opening bar completed')
    return {'closed_cycles': len(result.trades), 'actual_entries': len(buys),
        'all_actual_buys_strictly_high_volume': True, 'volume_rejection': rejection_checks,
        'unique_actual_entry_per_day': True, 'previous_day_exit_allows_current_entry': True,
        'same_day_actual_closed_cycle_blocks_reentry': True, 'halfday_weekend_hold': True,
        'next_session_first_point': True, 'all_decisions_on_session_grid': True}


def replay(arguments):
    candidate, bars, constraints, sessions, calendars, changed = arguments
    start = next(s.segments[0].start for s in calendars if s.session_date == date(2018, 11, 21))
    end = next(s.segments[-1].end for s in calendars if s.session_date == date(2018, 12, 4))
    bars = bars.copy(deep=True)
    if changed:
        future = bars.Date > end
        bars.loc[future, ['Open', 'High', 'Low', 'Close']] *= 50
        bars.loc[future, 'Volume'] *= 17
        bars.loc[future, 'Amount'] *= 850
    stamp = bars.BarStart.iloc[0]
    actions = pd.DataFrame([dict(Date=stamp, AvailableDate=stamp, EventId='synthetic-none',
        Kind='NONE', Ratio=1., CashPerShare=0., PayAt=None)])
    executor = EquityHistoricalExecutor(specification=run.SPEC, initial_cash=100000., fee_rate=.001, actions=actions)
    result = StrategyRuntime(execution_spec=run.SPEC).create(candidate).run_window(
        bars, constraints, executor, start=start, end=end, fee_rate=.001,
        sessions=sessions, trading_sessions=calendars)
    identities = {name: sha256(getattr(result, name).to_json(
        date_format='iso', double_precision=15).encode()).hexdigest() for name in RESULT_TABLES}
    return identities, len(result.decisions), len(result.fills), verify_lifecycle(result, calendars)


def main():
    if SOURCE != (run.WORK/'src').resolve():
        raise ValueError('integrate this draft into the allocated experiment before public execution')
    values = run.configurations()
    if values != {'C0046': {'volume_gate': True, 'allow_overnight': True}}:
        raise ValueError('only the fixed high-volume crossday C0046 configuration may be prechecked')
    candidates = [run.candidate(key, parameters) for key, parameters in values.items()]
    for candidate in candidates:
        definition = candidate.definition
        if (definition.warmup_bars != 261 or not definition.session_context
                or definition.feedback_mode != 'CONFIRMED_CLOSED_CYCLE_V1' or definition.auxiliary_inputs):
            raise ValueError('candidate feedback, session, warmup or no-aux contract changed')
    data = fixture()
    jobs = [(candidate, *data, False) for candidate in candidates]
    serial = [replay(job) for job in jobs]
    altered = [replay((*job[:-1], True)) for job in jobs]
    if altered != serial:
        raise ValueError('future OHLCV perturbation changed one of the seven prior result tables or lifecycle facts')
    if any(pickle.loads(pickle.dumps(candidate)) != candidate for candidate in candidates):
        raise ValueError('candidate serialization differs')
    with multiprocessing.get_context('spawn').Pool(2) as pool:
        parallel = pool.map(replay, jobs)
    if parallel != serial:
        raise ValueError('spawn and serial seven-table public synthetic results differ')
    mechanism = SOURCE/'check_mechanism.py'
    completed = subprocess.run([sys.executable, str(mechanism)], capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError('mechanism checks failed:\n'+completed.stdout+'\n'+completed.stderr)
    mechanism_path = run.WORK/'others/precheck_mechanism.json'
    evidence = run.read(mechanism_path)
    expected_cases = {'c36': 144, 'c37': 144, 'c44': 144, 'combined_held': 36,
                      'combined_flat': 108, 'blocked_by_volume': 24, 'prefix_comparisons': 4}
    if (evidence != json.loads(completed.stdout)
            or evidence['status'] != 'PASS' or evidence['scope'] != 'SYNTHETIC_ONLY_NO_REAL_ACCOUNT'
            or evidence['tests_run'] != 18 or evidence['cases'] != expected_cases
            or evidence['source_sha256_before'] != evidence['source_sha256_after']
            or evidence['strategy_source_sha256'] != sha256((SOURCE/'strategy.py').read_bytes()).hexdigest()
            or evidence['check_source_sha256'] != sha256(mechanism.read_bytes()).hexdigest()):
        raise ValueError('actual mechanism coverage or source identity differs')
    # The integrated checker owns the mechanism evidence file. Bind its actual
    # bytes without rewriting it; run.checked_precheck() checks the same hashes.
    payload = {'status': 'PASS', 'scope': 'synthetic public SRT/TXE only; zero real research account evaluations',
        'strategy_source_sha256': sha256((SOURCE/'strategy.py').read_bytes()).hexdigest(),
        'precheck_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'mechanism_evidence_sha256': sha256(mechanism_path.read_bytes()).hexdigest(),
        'mechanism_source_sha256': sha256(mechanism.read_bytes()).hexdigest(),
        'public_serial_equals_spawn': True, 'future_price_and_volume_invariance': True,
        'candidate_pickle': True, 'max_spawn_workers': 2, 'compared_result_tables': list(RESULT_TABLES),
        'mechanism_tests': evidence['tests_run'], 'mechanism_cases': evidence['cases'],
        'candidates': {key: {'decisions': value[1], 'fills': value[2], 'economic_hashes': value[0],
            'lifecycle_volume_and_session': value[3]} for key, value in zip(values, serial)}}
    run.save(run.WORK/'others/precheck.json', payload)
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
