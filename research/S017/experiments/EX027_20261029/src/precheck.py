"""Public synthetic account preflight and historical entry identity only."""
# ruff: noqa: E402
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo
import gzip
import json
import multiprocessing as mp
import os
import pickle
from time import perf_counter

ROOT = Path(__file__).resolve().parents[5]
SCRATCH = ROOT/'.tmp/s017-research/EX027_20261029/precheck'
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(SCRATCH)
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'

import pandas as pd
from dataflows import (BarFrequency, TradingSession, TimeInterval, PreparedDataRef,
                       EquityDataRequest, EquityProduct, EquityQuery, SourceRef)
from strategy_runtime import StrategyRuntime
from trading_execution_engine.equity import EquityHistoricalExecutor
from czsc_trader.research_tools import EvidenceRef
import run
from strategy import entry_facts

SOURCE = Path(__file__).resolve().parent
REFERENCE = ROOT/'research/S017/experiments/EX024_20261029'
PREP = ROOT/'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json'
RESULT_TABLES = ('decisions', 'orders', 'fills', 'corporate_action_entries',
                 'account_points', 'account_daily', 'trades')


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def authenticate(value):
    ref = EvidenceRef.from_dict(value)
    path = ref.resolve(ROOT)
    if digest(path) != ref.sha256:
        raise ValueError('Published reference identity changed')
    return path


def fixture():
    """Three entry cycles and distinct early/65-bar exits across real session edges."""
    zone = ZoneInfo('America/New_York')
    days, current = [], date(2018, 10, 1)
    while current <= date(2018, 12, 21):
        if current.weekday() < 5 and current != date(2018, 11, 22):
            days.append(current)
        current += timedelta(days=1)
    calendars = tuple(TradingSession(day, str(zone), (TimeInterval(
        datetime.combine(day, time(9, 30), zone),
        datetime.combine(day, time(13 if day == date(2018, 11, 23) else 16), zone)),)) for day in days)
    rows = []
    for session in calendars:
        for bar in session.bars(BarFrequency.M30):
            rows.append(dict(BarStart=bar.start, Date=bar.end, AvailableDate=bar.end,
                             Open=100., High=101., Low=99., Close=100., Volume=100000., Amount=10000000.))
    for i in (320, 410, 500):
        rows[i-1].update(Open=100.3, High=100.4, Low=100., Close=100.1, Volume=200000.)
        rows[i].update(Open=100.1, High=100.8, Low=100., Close=100.6)
        prior = 100.6
        for j in range(1, 66):
            close = 100.6+j*1.2 if j <= 8 else 110.2 if j < 10 else 104. if j < 20 else 99.
            rows[i+j].update(Open=prior, High=max(prior, close)+.1, Low=min(prior, close)-.1, Close=close)
            prior = close
    for row in rows:
        row['Amount'] = row['Volume']*row['Close']
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


def explanation(row):
    values = row['explanation']
    if not isinstance(values, dict):
        raise ValueError('Public decision lacks structured facts')
    return {item['key']: item['text'] for item in values['basis']}


def lifecycle(result, bars, calendars, mechanism):
    known = {bar for session in calendars for bar in session.bars(BarFrequency.M30)}
    for row in result.decisions.itertuples():
        if TimeInterval(row.execution_start, row.execution_end) not in known:
            raise ValueError('Decision escaped the synthetic session grid')
    buys = result.fills.loc[result.fills.side.eq('BUY')]
    if len(buys) != 3 or len(result.trades) != 3:
        raise ValueError('Synthetic replay must fill and close all three designed cycles')
    for fill in buys.itertuples():
        history = bars.loc[(bars.Date <= fill.interval_start) & (bars.AvailableDate <= fill.interval_start)]
        if not entry_facts(history)['entry_signal']:
            raise ValueError('Actual synthetic BUY is not anchored to M005')
    exits = []
    for _, row in result.decisions.iterrows():
        facts = explanation(row)
        if facts.get('held') == 'True' and float(row.target) == 0:
            exits.append({'holding_bars': int(facts['holding_bars']), 'trigger': facts['exit_trigger']})
    if len(exits) != 3 or any(x['trigger'] != mechanism for x in exits):
        raise ValueError('Designed exit condition was not exercised on all cycles')
    if mechanism == 'S017-M009' and any(x['holding_bars'] != 65 for x in exits):
        raise ValueError('Fixed hold must exit after exactly 65 completed holding bars')
    if mechanism != 'S017-M009' and any(not 0 < x['holding_bars'] < 65 for x in exits):
        raise ValueError('Early exit fixture failed to exercise its own condition')
    return {'actual_entries': len(buys), 'closed_cycles': len(result.trades),
            'all_actual_buys_M005': True, 'all_decisions_on_session_grid': True, 'exits': exits}


def replay(arguments):
    candidate, mechanism, changed = arguments
    bars, constraints, sessions, calendars = fixture()
    zone = ZoneInfo('America/New_York')
    start, end = datetime(2018, 11, 1, 9, 30, tzinfo=zone), datetime(2018, 12, 14, 16, tzinfo=zone)
    if changed:
        future = bars.Date > end
        if not future.any():
            raise ValueError('Future perturbation has no suffix to change')
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
    return {'economic_hashes': identities, 'decisions': len(result.decisions), 'fills': len(result.fills),
            'lifecycle': lifecycle(result, bars, calendars, mechanism)}


def reproduce_entries():
    """Read authenticated bars only; no real-data SRT/TXE account is evaluated."""
    started = perf_counter()
    publication = run.read(REFERENCE/'others/publication.json')
    pre = run.read(REFERENCE/'others/pre_run_evidence.json')
    if publication['validation']['status'] != 'PASS':
        raise ValueError('EX024 publication is not certified')
    authenticate(publication['report'])
    analysis_path = authenticate(publication['materials']['analysis'])
    analysis = run.read(analysis_path)
    verification = run.read(authenticate(publication['materials']['verification']))
    if verification['status'] != 'PASS' or verification['analysis_sha256'] != digest(analysis_path):
        raise ValueError('EX024 independent validation is stale')
    facts_path = authenticate(publication['materials']['signal-facts'])
    reference_source = authenticate(pre['materials']['numbered_entries-source'])
    if (digest(reference_source) != digest(REFERENCE/'src/numbered_entries.py')
            or digest(reference_source) != analysis['sources']['numbered_entries.py']
            or digest(facts_path) != analysis['artifacts']['signal_facts']
            or digest(authenticate(pre['previous']['prepared-reference'])) != digest(PREP)):
        raise ValueError('Reference source, data preparation or facts identity changed')
    reference = json.loads(gzip.decompress(facts_path.read_bytes()))
    if len(reference) != 22790 or analysis['signal_counts']['S017-M005'] != 324:
        raise ValueError('Reference population changed')
    saved = run.read(PREP)
    value = saved['reference']
    prepared = PreparedDataRef(UUID(value['space_id']), UUID(value['preparation_id']), value['manifest_sha256'])
    request = EquityDataRequest(run.INSTRUMENT,
        SourceRef('futu', 's017-development-gap-known-interruptions-v1-20261028'),
        EquityQuery(EquityProduct.BARS, date(2018, 11, 1), date(2025, 12, 31), BarFrequency.M30))
    fetched = run.context().data.fetch(request, prepared=prepared)
    expected = {r['product']: r['sha256'] for r in saved['items']}[EquityProduct.BARS.value]
    if (not fetched.ready or fetched.identity.content_sha256 != expected
            or expected != analysis['inputs']['BARS']['sha256']):
        raise ValueError('Original prepared bars unavailable or changed')
    bars = fetched.dataframe.reset_index(drop=True)
    local = bars.Date.dt.tz_convert('America/New_York')
    if (not bars.BarStatus.eq('OBSERVED').all() or not bars.AvailableDate.eq(bars.Date).all()
            or not bars.Date.is_monotonic_increasing or bars.Date.duplicated().any()
            or local.min().date() < date(2018, 11, 1) or local.max().date() > date(2025, 12, 31)):
        raise ValueError('Prepared bar contract or authorized window changed')
    count = 0
    comparison_digest = sha256()
    entry_local = bars.BarStart.dt.tz_convert('America/New_York')
    for row in reference:
        i = row['i']
        if (bars.Date.iloc[i].isoformat() != row['signal_at']
                or not date(2019, 1, 2) <= entry_local.iloc[i+1].date() <= date(2025, 12, 31)):
            raise ValueError('Published decision is outside its declared point/window')
        # SRT supplies all observed history through this point, not only warmup_bars.
        current = entry_facts(bars.iloc[:i+1])
        expected_signal = 'S017-M005' in row['signals']
        if not current['entry_ready'] or current['entry_signal'] != expected_signal:
            raise ValueError(f'M005 changed at eligible decision index {i}')
        count += int(current['entry_signal'])
        comparison_digest.update(f'{i}:{int(expected_signal)}\n'.encode())
    if count != 324:
        raise ValueError('M005 trigger count changed')
    payload = {'status': 'PASS', 'scope': 'ENTRY_IDENTITY_ONLY_NO_REAL_ACCOUNT',
        'strategy_source_sha256': digest(SOURCE/'strategy.py'), 'precheck_source_sha256': digest(Path(__file__)),
        'reference_source_sha256': digest(reference_source), 'reference_facts': publication['materials']['signal-facts'],
        'reference_analysis': publication['materials']['analysis'], 'prepared_reference_sha256': digest(PREP),
        'prepared': value, 'bars_sha256': expected, 'eligible': len(reference), 'M005_signals': count,
        'pointwise_signal_sha256': comparison_digest.hexdigest(), 'signal_mismatches': 0,
        'planned_execution_window': ['2019-01-02', '2025-12-31'], 'warmup_start': '2018-11-01',
        'first_signal_at': reference[0]['signal_at'], 'last_signal_at': reference[-1]['signal_at'],
        'first_execution_at': bars.BarStart.iloc[reference[0]['i']+1].isoformat(),
        'last_execution_at': bars.BarStart.iloc[reference[-1]['i']+1].isoformat(),
        'reserved_2026_used': False, 'real_account_evaluations': 0, 'seconds': perf_counter()-started}
    run.save(run.WORK/'others/entry_reproduction.json', payload)
    print('ENTRY_REPRODUCTION_PASS', len(reference), count, flush=True)
    return payload


def main():
    started = perf_counter()
    if SOURCE != (run.WORK/'src').resolve():
        raise ValueError('Incorrect allocated experiment')
    strategy_hash = digest(SOURCE/'strategy.py')
    values = run.configurations()
    if set(values) != {'C0048', 'C0049', 'C0050'}:
        raise ValueError('Only three frozen prototype configurations may be prechecked')
    candidates = [run.candidate(key, parameters) for key, parameters in values.items()]
    for candidate in candidates:
        definition = candidate.definition
        if (definition.warmup_bars != 261 or definition.session_context
                or definition.feedback_mode != 'CONFIRMED_EXECUTION' or definition.auxiliary_inputs):
            raise ValueError('Warmup, feedback, session or auxiliary contract changed')
    jobs = [(candidate, values[key]['exit_mechanism'], False) for key, candidate in zip(values, candidates)]
    serial = [replay(job) for job in jobs]
    altered = [replay((*job[:-1], True)) for job in jobs]
    if altered != serial:
        raise ValueError('Future OHLCV perturbation changed a prior table or lifecycle')
    if any(pickle.loads(pickle.dumps(candidate)) != candidate for candidate in candidates):
        raise ValueError('Candidate serialization differs')
    with mp.get_context('spawn').Pool(2) as pool:
        parallel = pool.map(replay, jobs)
    if parallel != serial:
        raise ValueError('Spawn and serial public seven-table results differ')
    reproduction = reproduce_entries()
    if digest(SOURCE/'strategy.py') != strategy_hash:
        raise ValueError('Strategy changed during precheck')
    payload = {'status': 'PASS', 'scope': 'SYNTHETIC_PUBLIC_ACCOUNTS_AND_REAL_ENTRY_IDENTITY_ONLY',
        'strategy_source_sha256': strategy_hash, 'precheck_source_sha256': digest(Path(__file__)),
        'entry_reproduction_sha256': digest(run.WORK/'others/entry_reproduction.json'),
        'public_serial_equals_spawn': True, 'future_price_and_volume_invariance': True,
        'candidate_pickle': True, 'max_spawn_workers': 2, 'native_threads': 1,
        'compared_result_tables': list(RESULT_TABLES), 'real_account_evaluations': 0,
        'eligible_entry_comparisons': reproduction['eligible'], 'M005_signals': reproduction['M005_signals'],
        'candidates': dict(zip(values, serial)), 'seconds': perf_counter()-started}
    run.save(run.WORK/'others/precheck.json', payload)
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
