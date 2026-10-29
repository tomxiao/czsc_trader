"""Synthetic public SRT/TXE replay, causality and spawn preflight; no real-data account."""
# Numerical thread limits must precede numerical-library imports in spawned workers.
# ruff: noqa: E402
from datetime import date, datetime, time, timedelta
from dataclasses import replace
from zoneinfo import ZoneInfo
from hashlib import sha256
import json
import math
import multiprocessing
import os
import pickle
import subprocess
import sys

for thread_variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[thread_variable] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

import pandas as pd
from dataflows import BarFrequency, TradingSession, TimeInterval, EquityDataRequest, EquityQuery, EquityProduct
from strategy_runtime import (StrategyRuntime, EquityPortfolio, DecisionPoint,
                              build_equity_decision_context)
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
            if day_index == 27:
                start = 60. + bar_index * .05
                close = start + .01
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


def auxiliary(bars,frequency, mode='weak'):
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
    if frequency is not BarFrequency.DAILY:
        raise ValueError('EX016 precheck requires the declared daily auxiliary')
    closes = [200.-i*.8 if mode=='weak' else 100.+i*10. if mode=='positive'
              else 200.-i*.05 for i in range(len(frame))]
    frame['Close'] = closes
    frame['Open'] = frame.Close-.1
    frame['High'] = frame.Close+.2
    frame['Low'] = frame.Close-.3
    frame['Amount'] = frame.Volume*frame.Close
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
        for name in ('decisions','orders','fills','corporate_action_entries','account_points','account_daily','trades')}
    return identities,len(result.decisions),len(result.fills)


def input_boundaries(candidate, data):
    bars, _, _, calendars = data
    interval = calendars[25].bars(BarFrequency.M30)[0]
    point = DecisionPoint(interval.start, interval.start, interval)
    history = bars.loc[bars.Date <= point.decision_at].copy(deep=True)
    market = auxiliary(bars, BarFrequency.DAILY)
    portfolio = EquityPortfolio(100000., 0, 0., 0)

    def build(values):
        return build_equity_decision_context(candidate.definition, history, portfolio, point,
                                             auxiliary_histories=values)

    context = build({'market': market})
    visible = context.auxiliary_histories['market']
    assert (visible.Date <= point.observed_through).all()
    assert (visible.AvailableDate <= point.decision_at).all()
    assert visible.Date.max() < market.Date.max()
    assert candidate.decide(context).target in (0, 1)
    rejected = []

    def reject(name, action, expected):
        try:
            action()
        except ValueError as error:
            if expected not in str(error):
                raise
            rejected.append(name)
        else:
            raise AssertionError('invalid auxiliary input accepted: ' + name)

    reject('missing', lambda: build({}), 'UNAVAILABLE')
    zero = market.copy(deep=True)
    last_visible = zero.index[zero.Date <= point.decision_at][-1]
    zero.loc[last_visible, 'Volume'] = 0.
    reject('latest_zero_volume', lambda: build({'market': zero}), 'zero-volume')
    aged = market.loc[market.Date <= point.decision_at].copy(deep=True)
    aged.loc[:, ['Date', 'AvailableDate', 'BarStart']] -= timedelta(days=6)
    reject('stale', lambda: build({'market': aged}), 'STALE')
    delayed = market.copy(deep=True)
    delayed['AvailableDate'] += timedelta(days=60)
    reject('all_future_available', lambda: build({'market': delayed}), 'UNAVAILABLE')
    reject('direct_future_context', lambda: candidate.decide(replace(context,
        auxiliary_histories={'market': market})), 'future auxiliary')
    missing = market.copy(deep=True)
    missing['BarStatus'] = 'OBSERVED'
    missing.loc[last_visible, 'BarStatus'] = 'MISSING'
    reject('latest_missing', lambda: build({'market': missing}), 'UNAVAILABLE')
    return {'causal_daily_slice': True, 'explicit_rejections': rejected}


def facts(decision):
    return {item.key: item.text for item in decision.explanation.basis}


def branch_coverage(candidate, data):
    bars, _, _, calendars = data
    interval = calendars[25].bars(BarFrequency.M30)[1]
    point = DecisionPoint(interval.start, interval.start, interval)
    history = bars.loc[bars.Date <= interval.start].copy(deep=True)
    portfolio = EquityPortfolio(100000., 0, 0., 0)

    def decide(stock, mode, held=False):
        account = replace(portfolio, quantity=10, cycle_cost=1000.) if held else portfolio
        context = build_equity_decision_context(candidate.definition, stock, account, point,
            auxiliary_histories={'market': auxiliary(bars, BarFrequency.DAILY, mode)})
        return candidate.decide(context), context

    weak, weak_context = decide(history, 'weak')
    weak_facts = facts(weak)
    assert weak.target == 1 and weak_facts['market_allowed'] == 'False'
    assert weak_facts['relative_allowed'] == 'True' and weak_facts['weak_market_exception'] == 'True'
    positive, _ = decide(history, 'positive')
    positive_facts = facts(positive)
    assert positive.target == 1 and positive_facts['market_allowed'] == 'True'
    assert positive_facts['relative_allowed'] == 'False'
    # A declining stock's prior daily endpoints are weaker than a gently falling
    # SPY, but the latest intraday jump separately makes the C13 entry true.
    denied = history.copy(deep=True)
    closes = [140.-i*.015 for i in range(len(denied))]
    denied['Open'] = closes
    denied['Close'] = closes
    denied['High'] = denied.Close+.2
    denied['Low'] = denied.Close-.2
    denied.loc[denied.index[-1], ['Open','Close','High','Low']] = [150., 150., 150.2, 149.8]
    neither, denied_context = decide(denied, 'weak_gentle')
    neither_facts = facts(neither)
    assert neither.target == 0 and neither_facts['base_target'] == 'True'
    assert neither_facts['market_allowed'] == neither_facts['relative_allowed'] == 'False'
    held, _ = decide(denied, 'weak_gentle', held=True)
    assert held.target == 1 and facts(held)['entry_context_allowed'] == 'False'
    below = denied.copy(deep=True)
    below.loc[below.index[-1], ['Open','Close','High','Low']] = [50., 50., 50.2, 49.8]
    exit_decision, _ = decide(below, 'positive', held=True)
    assert exit_decision.target == 0 and facts(exit_decision)['base_target'] == 'False'
    assert weak_facts['relative_matched_closes'] == '20'
    assert weak_facts['relative_close_intervals'] == '19'
    # Half-day completion is matched exactly, not inferred from a normal close.
    halfday = calendars[[s.session_date for s in calendars].index(date(2018,11,23))]
    assert halfday.segments[-1].end in tuple(weak_context.auxiliary_histories['market'].Date.iloc[-20:])
    assert int((history.Date == halfday.segments[-1].end).sum()) == 1
    assert calendars[0].segments[0].start.hour == 13
    assert calendars[2].segments[0].start.hour == 14
    rejected = []

    def reject(label, altered, expected):
        try:
            candidate.decide(replace(weak_context, history=altered))
        except ValueError as exc:
            assert expected in str(exc), str(exc)
            rejected.append(label)
        else:
            raise AssertionError('invalid relative alignment accepted: '+label)

    endpoint = weak_context.auxiliary_histories['market'].Date.iloc[-3]
    reject('missing_daily_endpoint', history.loc[history.Date != endpoint].copy(), 'unique exact close')
    duplicate = pd.concat([history, history.loc[history.Date == endpoint]]).sort_values('Date').reset_index(drop=True)
    reject('duplicate_daily_endpoint', duplicate, 'duplicate completion')
    malformed = history.copy(deep=True)
    malformed.loc[malformed.Date == endpoint, 'BarStart'] -= timedelta(seconds=1)
    reject('malformed_m30_endpoint', malformed, 'completed M30')
    return {'weak_market_exception': weak_facts, 'positive_market_only': positive_facts,
        'both_context_conditions_false_with_base_true': neither_facts,
        'held_ignores_entry_gate': held.target == 1, 'held_c13_exit': exit_decision.target == 0,
        'halfday_exact_endpoint': halfday.segments[-1].end.isoformat(), 'dst_utc_open_shift_verified': True,
        'alignment_rejections': rejected}


def prepared_warmup(candidate):
    """Read exact EX009 products; inspect warmup plus timestamp-only completeness."""
    request = run.request(candidate)
    research = run.context()
    queries = (
        EquityDataRequest(candidate.instrument, request.sources.bars,
            EquityQuery(EquityProduct.BARS, date(2018,11,1), date(2025,12,31), BarFrequency.M30)),
        candidate.definition.auxiliary_inputs[0].requests(date(2018,11,1), date(2025,12,31))[0],
    )
    frames, identities, timestamp_only = [], [], []
    for query in queries:
        result = research.data.fetch(query, prepared=request.prepared)
        if not result.ready:
            raise ValueError('prepared warmup subset unavailable: '+str(result.error))
        frame = result.dataframe
        local = frame.Date.dt.tz_convert('America/New_York').dt.date
        assert local.min() == date(2018,11,1) and local.max() == date(2025,12,31)
        frames.append(frame.loc[local <= date(2018,12,31)].copy(deep=True))
        timestamp_only.append(frame[['Date','BarStart','AvailableDate','BarStatus']].copy(deep=True))
        identities.append(result.identity.content_sha256)
    lite, spy = frames
    observed = lite.loc[lite.BarStatus.eq('OBSERVED')].copy(deep=True)
    assert len(observed) == 508 and len(observed) >= candidate.warmup_bars == 273
    last_twenty = spy.iloc[-20:]
    assert len(last_twenty) == 20 and last_twenty.Date.is_unique
    endpoints = observed.loc[observed.Date.isin(last_twenty.Date)]
    assert len(endpoints) == 20 and tuple(endpoints.Date) == tuple(last_twenty.Date)
    assert ((endpoints.Date-endpoints.BarStart).dt.total_seconds() == 1800).all()
    assert (last_twenty.AvailableDate <= request.window.start).all()
    assert (endpoints.AvailableDate <= request.window.start).all()
    all_lite, all_spy = timestamp_only
    assert all_lite.Date.is_unique and all_spy.Date.is_unique
    observed_times = all_lite.loc[all_lite.BarStatus.eq('OBSERVED')]
    matched_times = observed_times.loc[observed_times.Date.isin(all_spy.Date)]
    assert len(matched_times) == len(all_spy) and tuple(matched_times.Date) == tuple(all_spy.Date)
    assert ((matched_times.Date-matched_times.BarStart).dt.total_seconds() == 1800).all()
    assert (all_spy.AvailableDate >= all_spy.Date).all()
    return {'status':'PASS', 'authorized_read_range':['2018-11-01','2025-12-31'],
        'warmup_inspection_range':['2018-11-01','2018-12-31'],
        'public_fetch_calls':2, 'actual_pre_evaluation_bars':508, 'declared_warmup':273,
        'warmup_observations':508, 'twenty_daily_endpoints_aligned':True,
        'relative_close_intervals':19, 'first_daily_endpoint':last_twenty.Date.iloc[0].isoformat(),
        'last_daily_endpoint':last_twenty.Date.iloc[-1].isoformat(),
        'prepared_product_content_sha256':dict(zip(('LITE_M30','SPY_DAILY'),identities)),
        'full_development_timestamp_only_scan':{'scope':['2018-11-01','2025-12-31'],
            'spy_daily_endpoints':len(all_spy),'matched_lite_m30_endpoints':len(matched_times),
            'unmatched_endpoints':0,'duplicate_timestamps':0,'computed_price_features_or_returns':False},
        'actual_input_history_unchanged':True, 'real_account_evaluations':0,
        'reserved_2026_data_read':False}


def main():
    values=run.configurations()
    candidates=[run.candidate(key,value) for key,value in values.items()]
    data=fixture()
    boundaries={key:input_boundaries(candidate,data) for key,candidate in zip(values,candidates)}
    branches={key:branch_coverage(candidate,data) for key,candidate in zip(values,candidates)}
    jobs=[(candidate,*data,False) for candidate in candidates]
    serial=[replay(job) for job in jobs]
    altered=[replay((*job[:-1],True)) for job in jobs]
    if altered!=serial:
        raise ValueError('future price perturbation changed prior public economic replay')
    if any(pickle.loads(pickle.dumps(candidate))!=candidate for candidate in candidates):
        raise ValueError('candidate serialization differs')
    if any(value[2] < 2 for value in serial):
        raise ValueError('synthetic economic replay must include actual entry and exit fills')
    with multiprocessing.get_context('spawn').Pool(1) as pool:
        parallel=pool.map(replay,jobs)
    if parallel!=serial:
        raise ValueError('spawn and serial public economic replay differ')
    mechanism=run.WORK/'src/check_mechanism.py'
    subprocess.run([sys.executable,str(mechanism)],check=True)
    prepared=prepared_warmup(candidates[0])
    payload={'status':'PASS','scope':'synthetic public SRT/TXE; public EX009 2018-2025 read restricted to 2018 Nov/Dec warmup and full-range timestamp-only completeness; zero real research account evaluations',
        'strategy_source_sha256':sha256((run.WORK/'src/strategy.py').read_bytes()).hexdigest(),
        'mechanism_source_sha256':sha256(mechanism.read_bytes()).hexdigest(),
        'public_serial_equals_spawn':True,'future_price_invariance':True,'candidate_pickle':True,
        'public_input_boundaries':boundaries,
        'branch_coverage':branches,'prepared_data':prepared,
        'candidates':{key:{'decisions':value[1],'fills':value[2],'economic_hashes':value[0]} for key,value in zip(values,serial)}}
    run.save(run.WORK/'others/precheck.json',payload)
    print(json.dumps(payload,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
