"""Synthetic public SRT/TXE replay, causality and spawn preflight; no real-data account."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from hashlib import sha256
from pathlib import Path
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


def fixture():
    zone = ZoneInfo('America/New_York')
    days=[]
    current=date(2018,10,1)
    while current <= date(2018,12,7):
        if current.weekday()<5 and current!=date(2018,11,22):
            days.append(current)
        current+=timedelta(days=1)
    calendars=tuple(TradingSession(day,str(zone),(TimeInterval(datetime.combine(day,time(9,30),zone),
        datetime.combine(day,time(13 if day==date(2018,11,23) else 16),zone)),)) for day in days)
    rows=[]
    for session in calendars:
        closes = [100.5, 101.5, 102., 102.5] + [103.] * 9
        if session.session_date == date(2018,11,26):
            closes[4] = 98.  # After morning re-entry, force a closed same-day cycle.
        for bar_index,bar in enumerate(session.bars(BarFrequency.M30)):
            start=100. if bar_index == 0 else closes[bar_index-1]
            close=closes[bar_index]
            rows.append(dict(BarStart=bar.start,Date=bar.end,AvailableDate=bar.end,Open=start,
                High=101. if bar_index == 0 else max(start,close)+.12,
                Low=99. if bar_index == 0 else min(start,close)-.12,Close=close,
                Volume=100000.,Amount=100000.*close))
    bars=pd.DataFrame(rows)
    for column in ('BarStart','Date','AvailableDate'):
        bars[column]=pd.to_datetime(bars[column],utc=True)
    constraints=pd.DataFrame(dict(Date=bars.BarStart,AvailableDate=bars.BarStart,
        QuantityStep=1,PriceTick=.01,Tradable=True))
    sessions=pd.DataFrame(dict(Date=[s.segments[0].start for s in calendars],
        AvailableDate=[s.segments[0].start for s in calendars],SessionDate=[s.session_date.isoformat() for s in calendars]))
    for column in ('Date','AvailableDate'):
        sessions[column]=pd.to_datetime(sessions[column],utc=True)
    return bars,constraints,sessions,calendars


def verify_lifecycle(result, calendars):
    """Check public feedback effects and authentic regular/half-session boundaries."""
    known = {bar for session in calendars for bar in session.bars(BarFrequency.M30)}
    decisions = result.decisions
    for row in decisions.itertuples():
        if TimeInterval(row.execution_start, row.execution_end) not in known:
            raise ValueError('public decision is outside the independent session grid')
    buys = result.fills.loc[result.fills.side.eq('BUY')].copy()
    buys['_day'] = pd.to_datetime(buys.interval_start, utc=True).dt.tz_convert('America/New_York').dt.date
    if buys.empty or buys.groupby('_day').size().gt(1).any():
        raise ValueError('actual entry-cycle day limit failed')
    if len(result.trades) < 2:
        raise ValueError('synthetic lifecycle failed to exercise completed cycle feedback')
    entries = pd.to_datetime(result.trades.entry_at, utc=True).dt.tz_convert('America/New_York').dt.date
    exits = pd.to_datetime(result.trades.exit_at, utc=True).dt.tz_convert('America/New_York').dt.date
    if not ((entries == date(2018,11,23)) & (exits == date(2018,11,26))).any():
        raise ValueError('synthetic lifecycle did not hold across the halfday/weekend')
    if int(buys['_day'].eq(date(2018,11,26)).sum()) != 1:
        raise ValueError('previous entry-day closure improperly blocked current-day entry')
    same_day_stop = (entries == date(2018,11,26)) & (exits == date(2018,11,26))
    if not same_day_stop.any():
        raise ValueError('same-day closed-cycle prevention was not exercised')
    half_end = next(s.segments[-1].end for s in calendars if s.session_date == date(2018,11,23))
    half_decision = decisions.loc[decisions.execution_start.eq(half_end-timedelta(minutes=30))]
    if len(half_decision) != 1 or float(half_decision.target.iloc[0]) != 1:
        raise ValueError('an untriggered held cycle failed to survive the halfday last interval')
    first = decisions.loc[decisions.execution_start.eq(
        datetime(2018,11,26,9,30,tzinfo=ZoneInfo('America/New_York')))]
    if len(first) != 1 or float(first.target.iloc[0]) != 1:
        raise ValueError('crossday holding was lost before the new opening bar completed')
    for _, row in decisions.iterrows():
        explanation = row['explanation']
        if not isinstance(explanation, dict):
            raise ValueError('public session strategy decision lacks financial explanation')
        facts = {item['key']: item['text'] for item in explanation['basis']}
        if facts['allow_overnight'] != 'True':
            raise ValueError('public synthetic replay unexpectedly selected the verification-only branch')
    return {'closed_cycles': len(result.trades), 'actual_entries': len(buys),
            'unique_actual_entry_per_day': True, 'previous_day_exit_allows_current_entry': True,
            'same_day_actual_closed_cycle_blocks_reentry': True,
            'halfday_weekend_hold': True, 'next_session_first_point': True,
            'all_decisions_on_session_grid': True}


def replay(arguments):
    candidate,bars,constraints,sessions,calendars,changed=arguments
    start=next(s.segments[0].start for s in calendars if s.session_date==date(2018,11,21))
    end=next(s.segments[-1].end for s in calendars if s.session_date==date(2018,12,4))
    kwargs={}
    if candidate.definition.session_context:
        kwargs.update(sessions=sessions,trading_sessions=calendars)
    bars=bars.copy(deep=True)
    if changed:
        bars.loc[bars.Date>end,['Open','High','Low','Close','Amount']]*=50
    stamp=bars.BarStart.iloc[0]
    actions=pd.DataFrame([dict(Date=stamp,AvailableDate=stamp,EventId='synthetic-none',
        Kind='NONE',Ratio=1.,CashPerShare=0.,PayAt=None)])
    executor=EquityHistoricalExecutor(specification=run.SPEC,initial_cash=100000.,fee_rate=.001,actions=actions)
    result=StrategyRuntime(execution_spec=run.SPEC).create(candidate).run_window(bars,constraints,executor,
        start=start,end=end,fee_rate=.001,**kwargs)
    identities={name:sha256(getattr(result,name).to_json(date_format='iso',double_precision=15).encode()).hexdigest()
        for name in ('decisions','orders','fills','account_points','trades')}
    return identities,len(result.decisions),len(result.fills),verify_lifecycle(result,calendars)


def main():
    values=run.configurations()
    candidates=[run.candidate(key,value) for key,value in values.items()]
    if values != {'C0044': {'allow_overnight': True}}:
        raise ValueError('only the fixed C0044 True configuration may be prechecked')
    for candidate in candidates:
        definition = candidate.definition
        if (definition.warmup_bars != 261 or not definition.session_context
                or definition.feedback_mode != 'CONFIRMED_CLOSED_CYCLE_V1' or definition.auxiliary_inputs):
            raise ValueError('candidate feedback, session, warmup or no-aux contract changed')
    data=fixture()
    jobs=[(candidate,*data,False) for candidate in candidates]
    serial=[replay(job) for job in jobs]
    altered=[replay((*job[:-1],True)) for job in jobs]
    if altered!=serial:
        raise ValueError('future price perturbation changed prior public economic replay')
    if any(pickle.loads(pickle.dumps(candidate))!=candidate for candidate in candidates):
        raise ValueError('candidate serialization differs')
    with multiprocessing.get_context('spawn').Pool(2) as pool:
        parallel=pool.map(replay,jobs)
    if parallel!=serial:
        raise ValueError('spawn and serial public economic replay differ')
    mechanism=run.WORK/'src/check_mechanism.py'
    subprocess.run([sys.executable,str(mechanism)],check=True)
    mechanism_evidence = run.read(run.WORK/'others/precheck_mechanism.json')
    if (mechanism_evidence['status'] != 'PASS' or mechanism_evidence['tests_run'] != 13
            or mechanism_evidence['false_policy_equivalence_cases'] != 152):
        raise ValueError('required mechanism and False-policy comparison coverage changed')
    payload={'status':'PASS','scope':'synthetic public SRT/TXE only; zero real research account evaluations',
        'strategy_source_sha256':sha256((run.WORK/'src/strategy.py').read_bytes()).hexdigest(),
        'public_serial_equals_spawn':True,'future_price_invariance':True,'candidate_pickle':True,
        'max_spawn_workers':2,'precheck_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'mechanism_evidence_sha256':sha256((run.WORK/'others/precheck_mechanism.json').read_bytes()).hexdigest(),
        'mechanism_tests':13,'false_policy_equivalence_cases':152,
        'candidates':{key:{'decisions':value[1],'fills':value[2],'economic_hashes':value[0],
            'lifecycle_and_session':value[3]} for key,value in zip(values,serial)}}
    run.save(run.WORK/'others/precheck.json',payload)
    print(json.dumps(payload,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
