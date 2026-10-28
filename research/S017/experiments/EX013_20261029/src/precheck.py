"""Synthetic public SRT/TXE replay, causality and spawn preflight; no real-data account."""
from datetime import date, datetime, time, timedelta
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
from strategy_runtime import StrategyRuntime
from trading_execution_engine.equity import EquityHistoricalExecutor
import run


def fixture():
    zone = ZoneInfo('America/New_York')
    days=[]
    current=date(2018,11,1)
    while len(days)<30:
        if current.weekday()<5 and current!=date(2018,11,22):
            days.append(current)
        current+=timedelta(days=1)
    calendars=tuple(TradingSession(day,str(zone),(TimeInterval(datetime.combine(day,time(9,30),zone),
        datetime.combine(day,time(13 if day==date(2018,11,23) else 16),zone)),)) for day in days)
    rows=[]
    for day_index,session in enumerate(calendars):
        for bar_index,bar in enumerate(session.bars(BarFrequency.M30)):
            start=90+day_index*.6+bar_index*.12
            close=start+.15+math.sin(bar_index)*.22
            rows.append(dict(BarStart=bar.start,Date=bar.end,AvailableDate=bar.end,Open=start,
                High=max(start,close)+.12,Low=min(start,close)-.12,Close=close,
                Volume=100000.+day_index*1000,Amount=(100000.+day_index*1000)*close))
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


def auxiliary(bars,frequency):
    frame=bars.copy(deep=True)
    if frequency is BarFrequency.DAILY:
        frame['_day']=frame.Date.dt.tz_convert('America/New_York').dt.date
        frame=frame.groupby('_day').agg(BarStart=('BarStart','first'),Date=('Date','last'),
            AvailableDate=('AvailableDate','last'),Open=('Open','first'),High=('High','max'),
            Low=('Low','min'),Close=('Close','last'),Volume=('Volume','sum'),Amount=('Amount','sum')).reset_index(drop=True)
    else:
        offset=[-.08 if i%3==0 else .08 for i in range(len(frame))]
        frame['Close']=frame.Open+offset
        frame['High']=frame[['Open','Close']].max(axis=1)+.1
        frame['Low']=frame[['Open','Close']].min(axis=1)-.1
    frame[['Open','High','Low','Close']]*=5
    frame['Amount']*=5
    return frame


def replay(arguments):
    candidate,bars,constraints,sessions,calendars,changed=arguments
    start=calendars[25].segments[0].start
    end=calendars[27].segments[-1].end
    kwargs={}
    if candidate.definition.auxiliary_inputs:
        histories={item.name:auxiliary(bars,item.frequency) for item in candidate.definition.auxiliary_inputs}
        if changed:
            for frame in histories.values():
                frame.loc[frame.Date>end,['Open','High','Low','Close','Amount']]*=50
        kwargs['auxiliary_histories']=histories
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
    return identities,len(result.decisions),len(result.fills)


def main():
    values=run.configurations()
    candidates=[run.candidate(key,value) for key,value in values.items()]
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
    payload={'status':'PASS','scope':'synthetic public SRT/TXE only; zero real research account evaluations',
        'strategy_source_sha256':sha256((run.WORK/'src/strategy.py').read_bytes()).hexdigest(),
        'public_serial_equals_spawn':True,'future_price_invariance':True,'candidate_pickle':True,
        'candidates':{key:{'decisions':value[1],'fills':value[2],'economic_hashes':value[0]} for key,value in zip(values,serial)}}
    run.save(run.WORK/'others/precheck.json',payload)
    print(json.dumps(payload,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
