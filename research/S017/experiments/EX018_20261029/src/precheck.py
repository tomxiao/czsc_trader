"""Synthetic public SRT/TXE replay, causality and spawn preflight; no real-data account."""
from pathlib import Path
from datetime import date, datetime, time, timedelta
from dataclasses import replace
from zoneinfo import ZoneInfo
from hashlib import sha256
import json
import math
import multiprocessing
import pickle
import subprocess
import sys

import pandas as pd
from dataflows import BarFrequency, TradingSession, TimeInterval
from strategy_runtime import (StrategyRuntime, EquityPortfolio, DecisionPoint,
                              build_equity_decision_context)
from trading_execution_engine.equity import EquityHistoricalExecutor
import run


def fixture():
    zone = ZoneInfo('America/New_York')
    days=[]
    current=date(2018,11,1)
    while len(days)<42:
        if current.weekday()<5 and current!=date(2018,11,22):
            days.append(current)
        current+=timedelta(days=1)
    calendars=tuple(TradingSession(day,str(zone),(TimeInterval(datetime.combine(day,time(9,30),zone),
        datetime.combine(day,time(13 if day==date(2018,11,23) else 16),zone)),)) for day in days)
    rows=[]
    for day_index,session in enumerate(calendars):
        for bar_index,bar in enumerate(session.bars(BarFrequency.M30)):
            phase = len(rows) % 26
            pattern = [(100,98,99),(102,99,101),(101,97,98),(100,95,96),(102,97,101),
                       (105,100,104),(102,99,100),(101,97,98),(103,98,102)]
            if phase < len(pattern):
                high, low, close = pattern[phase]
            else:
                close = 102 - (phase-8)*2 if phase < 19 else 82 + (phase-19)*2
                high, low = close+.5, close-.5
            rows.append(dict(BarStart=bar.start,Date=bar.end,AvailableDate=bar.end,Open=close,
                High=high,Low=low,Close=close,Volume=100000.,Amount=100000.*close))
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


def replay(arguments):
    candidate,bars,constraints,sessions,calendars,changed=arguments
    start=calendars[25].segments[0].start
    end=calendars[37].segments[-1].end
    assert not candidate.definition.auxiliary_inputs and not candidate.definition.session_context
    kwargs={}
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
        for name in ('decisions','orders','fills','corporate_action_entries','account_points','account_daily','trades')}
    assert len(result.fills) >= 2 and len(result.trades) >= 1
    return identities,len(result.decisions),len(result.fills),len(result.trades)


def main():
    values=run.configurations()
    candidates=[run.candidate(key,value) for key,value in values.items()]
    data=fixture()
    original_bars = data[0].copy(deep=True)
    assert all(not c.definition.auxiliary_inputs and not c.definition.session_context for c in candidates)
    jobs=[(candidate,*data,False) for candidate in candidates]
    serial=[replay(job) for job in jobs]
    altered=[replay((*job[:-1],True)) for job in jobs]
    pd.testing.assert_frame_equal(data[0], original_bars)
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
    payload={'status':'PASS','scope':'synthetic public SRT/TXE only; zero real research account evaluations',
        'strategy_source_sha256':sha256((run.WORK/'src/strategy.py').read_bytes()).hexdigest(),
        'public_serial_equals_spawn':True,'future_price_invariance':True,'candidate_pickle':True,
        'primary_only_contract':True,
        'precheck_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'mechanism_evidence_sha256':sha256((run.WORK/'others/precheck_mechanism.json').read_bytes()).hexdigest(),
        'candidates':{key:{'decisions':value[1],'fills':value[2],'closed_cycles':value[3],'economic_hashes':value[0]} for key,value in zip(values,serial)}}
    run.save(run.WORK/'others/precheck.json',payload)
    print(json.dumps(payload,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
