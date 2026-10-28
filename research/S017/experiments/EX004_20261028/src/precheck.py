"""Independent causal checks for EX004; no account replay or holdout access."""
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import importlib.util
from math import isclose
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo
import os
import sys

import pandas as pd
from dataflows import PreparedDataRef, EquityDataRequest, EquityQuery, EquityProduct

from run import ROOT, WORK, SOURCE, INSTRUMENT, context, read, save, configurations, candidate
from strategy import cycle_levels, decide

ZONE = ZoneInfo('America/New_York')
PARAMETERS = dict(entry_bars=65, exit_bars=26, atr_days=14, atr_multiple=3.,
                  stop_fraction=.10, exit_mode='PERCENT_TRAIL')


def require(value, message):
    if not value:
        raise AssertionError(message)


def close(actual, expected, label):
    require(isclose(float(actual), float(expected), rel_tol=1e-11, abs_tol=1e-9), label)


def portfolio(entry, basis=100., quantity=10, scale=1.):
    return SimpleNamespace(quantity=quantity, cycle_entry=entry, cycle_cost=basis*quantity,
                           reference_price_scale=scale)


def decision(frame, account, params):
    return decide(SimpleNamespace(history=frame, portfolio=account, parameters=params))


def synthetic(days=45):
    """Synthetic weekdays only; includes two half-days and a DST transition."""
    rows = []
    for day_index, stamp in enumerate(pd.bdate_range('2020-02-03', periods=days)):
        session = stamp.date()
        length = 7 if day_index in (10, 24) else 13
        opening = datetime.combine(session, time(9,30), ZONE)
        base = 100. + .4*day_index + (8. if day_index >= 17 else 0.)
        for bar_index in range(length):
            start = pd.Timestamp(opening+timedelta(minutes=30*bar_index)).tz_convert('UTC')
            end = start+pd.Timedelta(minutes=30)
            mark = base+.07*bar_index
            width = 1.+(day_index % 5)*.35
            rows.append(dict(Date=end, BarStart=start, AvailableDate=end, Open=mark,
                             High=mark+width, Low=mark-width, Close=mark,
                             Volume=10000., Amount=mark*10000.))
    return pd.DataFrame(rows)


def oracle_atr(frame, days):
    """Independent chronological fold; do not use the strategy's rolling/shift implementation."""
    sessions = {}
    for row in frame.itertuples():
        day = row.Date.tz_convert('America/New_York').date()
        if day not in sessions:
            sessions[day] = [float(row.High), float(row.Low), float(row.Close)]
        else:
            values = sessions[day]
            values[0], values[1], values[2] = max(values[0], row.High), min(values[1], row.Low), float(row.Close)
    result, ranges, prior_close = {}, [], None
    for day,(high, low, last) in sorted(sessions.items()):
        # Use only earlier completed days at each close, including half-days as one day.
        if len(ranges) >= days:
            result[day] = sum(ranges[-days:])/days
        if prior_close is not None:
            ranges.append(max(high-low, abs(high-prior_close), abs(low-prior_close)))
        prior_close = last
    return result


def oracle_cycle(frame, account, params):
    rows = [row for row in frame.itertuples() if row.Date > account.cycle_entry]
    require(bool(rows), 'oracle requires a completed post-entry close')
    basis = account.cycle_cost/account.quantity
    mode = params['exit_mode']
    atrs = oracle_atr(frame, params['atr_days']) if mode != 'PERCENT_TRAIL' else {}
    initial_atr = None if mode == 'PERCENT_TRAIL' else atrs[account.cycle_entry.astimezone(ZONE).date()]
    level = basis*(1.-params['stop_fraction']) if mode == 'PERCENT_TRAIL' else basis-params['atr_multiple']*initial_atr
    initial_stop, peak, hit, levels = level, basis, False, []
    for row in rows:
        mark = float(row.Close)
        peak = max(peak, mark)
        if mode == 'PERCENT_TRAIL':
            level = max(level, peak*(1.-params['stop_fraction']))
        elif mode == 'ATR_TRAIL':
            level = max(level, peak-params['atr_multiple']*atrs[row.Date.tz_convert('America/New_York').date()])
        hit = hit or mark <= level
        levels.append(level)
    return dict(stop=level, initial_stop=initial_stop, peak_close=peak, stop_hit=hit,
                entry_cost_per_share=basis, entry_atr=initial_atr, levels=levels,
                cycle_observations=len(rows))


def same_state(actual, expected):
    for field in ('stop', 'initial_stop', 'peak_close', 'entry_cost_per_share'):
        close(actual[field], expected[field], field)
    require(actual['stop_hit'] == expected['stop_hit'], 'stop latch differs')
    require(actual['cycle_observations'] == expected['cycle_observations'], 'cycle row count differs')
    if expected['entry_atr'] is None:
        require(actual['entry_atr'] is None, 'percent mode unexpectedly uses ATR')
    else:
        close(actual['entry_atr'], expected['entry_atr'], 'entry ATR')
    require(len(actual['levels']) == len(expected['levels']), 'ratchet length differs')
    for left,right in zip(actual['levels'], expected['levels']):
        close(left, right, 'historical ratchet')
    require(all(b >= a for a,b in zip(actual['levels'], actual['levels'][1:])), 'stop moved down')


def rejected(function):
    try:
        function()
    except (ValueError, KeyError):
        return
    raise AssertionError('invalid input was accepted')


def check_entry_and_channel(old):
    frame = synthetic().iloc[:300].copy()
    frame[['Open','Close']] = 100.
    frame['High'], frame['Low'] = 101., 99.
    flat = portfolio(None, quantity=0)
    params = {**PARAMETERS, 'exit_mode':'CHANNEL'}
    old_params = dict(mode='breakout', trend_bars=260, entry_bars=65, exit_bars=26,
                      mean_bars=13, dip_atr=1., trend_filter=False, trend_exit=False)
    count = 0
    for mark in (98.,99.,100.,101.,102.):
        frame.loc[frame.index[-1], 'Close'] = mark
        for held in (False, True):
            account = portfolio(frame.BarStart.iloc[-2]) if held else flat
            current = decision(frame, account, params)
            retained = old.decide(SimpleNamespace(history=frame, portfolio=account, parameters=old_params))
            require(current.target == retained.target, 'old channel semantics differ')
            require(current.explanation.case_key == ('long' if current.target else 'flat'), 'explanation branch differs')
            count += 1
    frame.loc[frame.index[-1], 'Close'] = 102.
    frame.loc[frame.index[-1], 'High'] = 100000.
    require(decision(frame, flat, params).target == 1, 'current high leaked into breakout threshold')
    frame.loc[frame.index[-1], 'Close'] = 101.
    require(decision(frame, flat, params).target == 0, 'breakout equality must not enter')
    frame.loc[frame.index[-1], 'Close'] = 99.
    require(decision(frame, portfolio(frame.BarStart.iloc[-2]), params).target == 1,
            'channel exit equality must keep position')
    return {'branch_comparisons': count, 'explicit_boundaries': 3}


def check_percent_cycle():
    frame = synthetic().iloc[:305].copy()
    entry_index = 300
    account = portfolio(frame.BarStart.iloc[entry_index], basis=100.1)
    frame.loc[frame.index[entry_index-1], 'Close'] = 10000.
    frame.loc[frame.index[entry_index:], 'Close'] = [101.,110.,99.,120.,119.]
    frame.loc[frame.index[entry_index], 'High'] = 100000.
    original = cycle_levels(frame, account, PARAMETERS)
    same_state(original, oracle_cycle(frame, account, PARAMETERS))
    close(original['initial_stop'], 90.09, 'fee-inclusive cost basis')
    close(original['peak_close'], 120., 'pre-entry close or intrabar high leaked into peak')
    require(original['stop_hit'], 'equal stop must trigger and stay latched after recovery')
    require(decision(frame, account, PARAMETERS).target == 0, 'failed exit must remain requested while still held')
    changed = frame.copy()
    changed.loc[changed.index[entry_index:], 'High'] = 999999.
    same_state(cycle_levels(changed, account, PARAMETERS), original)
    new_account = portfolio(frame.BarStart.iloc[-1], basis=119.)
    reset = cycle_levels(frame, new_account, PARAMETERS)
    require(not reset['stop_hit'] and reset['cycle_observations'] == 1, 'new fill cycle did not reset')
    # Flat accounts ignore stale cycle state. This also covers unfilled entry attempts.
    frame.loc[frame.index[-1], 'Close'] = 100001.
    stale = portfolio(account.cycle_entry, basis=100., quantity=0)
    empty = portfolio(None, quantity=0)
    require(decision(frame, stale, PARAMETERS).target == decision(frame, empty, PARAMETERS).target,
            'flat account reused stale cycle state')
    require(original['cycle_observations'] == 5, 'preceding close equal to entry boundary was included')
    return {'checks': 9}


def check_rejections():
    frame = synthetic().iloc[:305]
    entry = frame.BarStart.iloc[300]
    invalid = [portfolio(entry, quantity=0), portfolio(None), portfolio(entry, basis=0.),
               portfolio(entry, scale=.5), portfolio(frame.Date.iloc[-1])]
    for account in invalid:
        rejected(lambda a=account: cycle_levels(frame,a,PARAMETERS))
    atr_params = {**PARAMETERS, 'exit_mode':'ATR_TRAIL'}
    short = synthetic(days=14)
    rejected(lambda: cycle_levels(short,portfolio(short.BarStart.iloc[-1]),atr_params))
    flat = synthetic(days=18)
    flat[['Open','High','Low','Close']] = 100.
    rejected(lambda: cycle_levels(flat,portfolio(flat.BarStart.iloc[-1]),atr_params))
    return {'invalid_inputs_rejected': len(invalid)+2}


def check_atr_boundaries():
    frame = synthetic(days=17)
    session = frame.Date.dt.tz_convert('America/New_York').dt.date
    days = list(dict.fromkeys(session))
    entry_index = int(frame.index[session.eq(days[15])][0])
    prefix = frame.iloc[:entry_index+1].copy()
    account = portfolio(prefix.BarStart.iloc[-1], basis=float(prefix.Close.iloc[-1]))
    params = {**PARAMETERS, 'exit_mode':'ATR_TRAIL'}
    # Exactly 15 prior complete sessions, with a large overnight gap on the earliest TR day.
    prefix.loc[session.iloc[:len(prefix)].eq(days[0]), ['Open','High','Low','Close']] *= .5
    same_state(cycle_levels(prefix,account,params), oracle_cycle(prefix,account,params))
    initial = cycle_levels(prefix,account,params)
    altered = prefix.copy()
    altered.loc[altered.index[-1], 'High'] = 100000.
    altered.loc[altered.index[-1], 'Low'] = 1.
    same_state(cycle_levels(altered,account,params), initial)
    # Updating the next day's first completed close may use the previous day's final range.
    next_index = int(frame.index[session.eq(days[16])][0])
    extension = frame.iloc[:next_index+1].copy()
    same_state(cycle_levels(extension,account,params), oracle_cycle(extension,account,params))
    require(len(frame.loc[session.eq(days[10])]) == 7, 'half-day fixture changed')
    return {'checks': 4, 'atr_definition': '14 prior complete session TRs; update by completed-close local day'}


def check_full_prefix():
    frame = synthetic()
    entry_index = 390
    account = portfolio(frame.BarStart.iloc[entry_index], basis=float(frame.Close.iloc[entry_index]))
    # Force a shock and later recovery to exercise latch independently of the final close.
    frame.loc[frame.index[entry_index+15:entry_index+18], 'Close'] *= .6
    frame = frame.iloc[:entry_index+65]
    count = 0
    for mode in ('PERCENT_TRAIL','ATR_TRAIL','INITIAL_ATR_ONLY'):
        params = {**PARAMETERS, 'exit_mode':mode}
        full = cycle_levels(frame, account, params)
        same_state(full,oracle_cycle(frame,account,params))
        for stop in range(entry_index+1, len(frame)+1):
            prefix = frame.iloc[:stop]
            state = cycle_levels(prefix,account,params)
            same_state(state,oracle_cycle(prefix,account,params))
            require(len(state['levels']) == stop-entry_index, 'prefix history length differs')
            for left,right in zip(state['levels'],full['levels'][:stop-entry_index]):
                close(left,right,'future bars changed historical stop')
            require(decision(prefix,account,params).target == int(not state['stop_hit']), 'decision/latch disagreement')
            count += 1
        if mode == 'INITIAL_ATR_ONLY':
            require(all(level == full['initial_stop'] for level in full['levels']), 'initial-only stop ratcheted')
    require(len(set(row.utcoffset() for row in frame.Date.dt.tz_convert('America/New_York'))) == 2,
            'DST fixture must span the clock change')
    return {'prefix_states_compared':count, 'independent_full_sequences':3,
            'half_days':2, 'dst_transition':True}


def load_old_strategy():
    path = ROOT/'research/S017/experiments/EX002_20261028/src/strategy.py'
    spec = importlib.util.spec_from_file_location('s017_ex004_old_channel_precheck',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_prepared(old):
    saved = read(ROOT/'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json')
    identity = saved['reference']
    prepared = PreparedDataRef(UUID(identity['space_id']),UUID(identity['preparation_id']),identity['manifest_sha256'])
    research = context()
    results = {}
    for product in (EquityProduct.BARS, EquityProduct.ACTIONS):
        query = EquityDataRequest(INSTRUMENT,SOURCE,EquityQuery(product,date(2018,11,1),date(2025,12,31)))
        result = research.data.fetch(query,prepared=prepared)
        require(result.ready, str(result.error))
        results[product] = result
    frame, actions = results[EquityProduct.BARS].dataframe, results[EquityProduct.ACTIONS].dataframe
    local = frame.Date.dt.tz_convert('America/New_York')
    require(local.min().date() == date(2018,11,1) and local.max().date() == date(2025,12,31),
            'prepared bars do not exactly cover authorized bounds')
    require(frame.BarStatus.eq('OBSERVED').all(), 'missing/zero-volume data require a new explicit decision')
    require((frame.Volume > 0).all(), 'zero-volume row present')
    require(int(frame.ExecutionBlocked.sum()) == 5, 'known interruption count changed')
    require(not actions.Kind.eq('SPLIT').any(), 'RAW cycle stop cannot cross a split')
    require(actions.Kind.eq('NONE').all(), 'prepared action assumptions changed')
    for product,result in results.items():
        original = next(item for item in saved['items'] if item['product'] == product.value)
        require(result.identity.content_sha256 == original['sha256'], 'prepared content identity drift')
    count, old_checks = 0, 0
    indices = sorted({508 + int(i*(len(frame)-508-131)/7) for i in range(8)})
    old_params = dict(mode='breakout', trend_bars=260, entry_bars=65, exit_bars=26,
                      mean_bars=13, dip_atr=1., trend_filter=False, trend_exit=False)
    for first in indices:
        account = portfolio(frame.BarStart.iloc[first], basis=float(frame.Open.iloc[first])*1.001)
        for length in (1,13,65):
            prefix = frame.iloc[:first+length]
            for mode in ('PERCENT_TRAIL','ATR_TRAIL','INITIAL_ATR_ONLY'):
                params = {**PARAMETERS,'exit_mode':mode}
                actual = cycle_levels(prefix,account,params)
                same_state(actual,oracle_cycle(prefix,account,params))
                require(decision(prefix,account,params).target == int(not actual['stop_hit']), 'real-prefix decision mismatch')
                count += 1
            for quantity in (0,10):
                current_account = portfolio(account.cycle_entry, quantity=quantity)
                current = decision(prefix,current_account,{**PARAMETERS,'exit_mode':'CHANNEL'})
                prior = old.decide(SimpleNamespace(history=prefix,portfolio=current_account,parameters=old_params))
                require(current.target == prior.target,'real-prefix old channel mismatch')
                old_checks += 1
    return {'reference':identity, 'fetch_calls':2,
        'authorized_range':['2018-11-01','2025-12-31'], 'bars':len(frame),
        'status_counts':frame.BarStatus.value_counts().to_dict(),
        'known_blocked_bars':int(frame.ExecutionBlocked.sum()), 'action_kinds':actions.Kind.value_counts().to_dict(),
        'content_sha256':{product.value:result.identity.content_sha256 for product,result in results.items()},
        'sampled_entry_indices':indices, 'cycle_oracle_comparisons':count, 'old_channel_comparisons':old_checks,
        'portfolio_scope':'Synthetic held/flat snapshots at causal sampled entries; no account, fill or return claim.'}


def check():
    scratch = ROOT/'.tmp/s017-trend'
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(scratch)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    source = WORK/'src/strategy.py'
    source_hash = sha256(source.read_bytes()).hexdigest()
    old = load_old_strategy()
    cases = {}
    tasks = (
        ('entry_and_channel',lambda:check_entry_and_channel(old)),
        ('percent_cycle',check_percent_cycle), ('invalid_boundaries',check_rejections),
        ('daily_atr_boundaries',check_atr_boundaries), ('full_prefix_causality',check_full_prefix),
        ('prepared_causal_samples',lambda:check_prepared(old)),
    )
    for name,function in tasks:
        try:
            details = function()
            cases[name] = {'status':'PASS',**details}
            print('PASS',name,flush=True)
        except Exception as exc:
            cases[name] = {'status':'FAIL','error_type':type(exc).__name__,'error':str(exc)}
            print('FAIL',name,type(exc).__name__,str(exc),flush=True)
    try:
        for key,params in configurations().items():
            definition = candidate(key,params).definition
            require(definition.from_dict(definition.to_dict()) == definition,'definition roundtrip differs')
        require(sha256(source.read_bytes()).hexdigest() == source_hash,'strategy source changed during checks')
        cases['definitions_and_source'] = {'status':'PASS','definitions':len(configurations())}
    except Exception as exc:
        cases['definitions_and_source'] = {'status':'FAIL','error_type':type(exc).__name__,'error':str(exc)}
    passed = sum(value['status'] == 'PASS' for value in cases.values())
    output = {'status':'PASS' if passed == len(cases) else 'FAIL',
        'scope':'Synthetic and pinned-development causal checks only; no full account replay, returns or holdout access.',
        'strategy_source_sha256':source_hash,'precheck_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'passed_groups':passed,'total_groups':len(cases),'cases':cases,
        'atr_timing':'Prior local-session ATR at each completed close; no extra open-before-first-close ratchet update.',
        'stop_semantics':'Close-triggered, fee-inclusive initial basis, next-interval execution requested; no guaranteed stop-price fill.'}
    save(WORK/'others/precheck.json',output)
    if output['status'] != 'PASS':
        raise RuntimeError('EX004 focused precheck failed; see others/precheck.json')
    print('EX004 PRECHECK PASS',passed,'groups',flush=True)


if __name__ == '__main__':
    check()
