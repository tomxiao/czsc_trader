"""Independent synthetic formulas and public V3 complete-cycle checks."""
# ruff: noqa: E402
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT/'.tmp/s017-research'/WORK.name/'entry-checks'
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(SCRATCH)
for variable in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

import pandas as pd
from dataflows import AssetClass, BarFrequency, InstrumentId, MarketId, TimeInterval, TradingSession
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, EquityStrategyCandidate,
    EquityStrategyDefinition, ResearchExecutionSpec, StrategyRuntime, UsEquitySpec, equity_source_hash)
from trading_execution_engine.equity import EquityHistoricalExecutor
from signals import NAMES, compute
from strategy_v3 import feature_graph, state_schema, step

SPEC = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
    AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)


def fixture():
    zone = ZoneInfo('America/New_York')
    days, current = [], date(2018, 10, 1)
    while len(days) < 52:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    calendars = tuple(TradingSession(day, str(zone), (TimeInterval(
        datetime.combine(day, time(9, 30), zone), datetime.combine(day, time(16), zone)),)) for day in days)
    rows, previous = [], 100.
    for session in calendars:
        for bar in session.bars(BarFrequency.M30):
            index, phase = len(rows), len(rows) % 30
            drift = (index//30)*.75
            if phase <= 11:
                close = 100.+phase*.4+drift
            elif phase == 12:
                close = 104.1+drift
            elif phase == 13:
                close = 103.8+drift
            elif phase == 14:
                close = 104.7+drift
            elif phase < 22:
                close = 104.7-(phase-14)*.3+drift
            else:
                # Repeated lows flatten before the next cycle's recovery.
                close = 100.+drift
            opening = previous
            rows.append(dict(BarStart=bar.start, Date=bar.end, AvailableDate=bar.end,
                Open=opening, High=max(opening,close)+.12, Low=min(opening,close)-.12,
                Close=close, Volume=100000., Amount=close*100000.))
            previous = close
    bars = pd.DataFrame(rows)
    for column in ('BarStart','Date','AvailableDate'):
        bars[column] = pd.to_datetime(bars[column],utc=True)
    constraints = pd.DataFrame(dict(Date=bars.BarStart,AvailableDate=bars.BarStart,
        QuantityStep=1,PriceTick=.01,Tradable=True))
    sessions = pd.DataFrame(dict(Date=[s.segments[0].start for s in calendars],
        AvailableDate=[s.segments[0].start for s in calendars],SessionDate=[s.session_date.isoformat() for s in calendars]))
    for column in ('Date','AvailableDate'):
        sessions[column] = pd.to_datetime(sessions[column],utc=True)
    actions = pd.DataFrame([dict(Date=bars.BarStart.iloc[0],AvailableDate=bars.BarStart.iloc[0],
        EventId='EX030-synthetic-none',Kind='NONE',Ratio=1.,CashPerShare=0.,PayAt=None)])
    return bars,constraints,sessions,calendars,actions,calendars[22].segments[0].start,calendars[44].segments[-1].end


def scalar(bars,i):
    c = [float(value) for value in bars.Close.iloc[:i+1]]
    h = [float(value) for value in bars.High.iloc[:i+1]]
    low = [float(value) for value in bars.Low.iloc[:i+1]]
    prior = sum(c[i-65:i])/65
    older = sum(c[i-78:i-13])/65
    background = c[i-1] < prior
    base = background and c[i] > max(h[i-6:i])
    up, held_low = prior > older, min(low[i-6:i]) >= min(low[i-12:i-6])
    return (base,base and up,base and held_low),(background,background and up,background and held_low)


def candidate(mechanism):
    source,files = WORK/'src',('strategy_v3.py',)
    definition = EquityStrategyDefinition(InstrumentId(MarketId.US,AssetClass.STOCK,'LITE'),SPEC,261,
        'strategy_v3:step',files,equity_source_hash(source,files),
        json.dumps({'entry_mechanism':mechanism,'max_holding_bars':6}),contract_version=3,
        feature_graph=feature_graph(),state_schema=state_schema())
    return EquityStrategyCandidate('S017',{'S017-M017':'C0056','S017-M019':'C0059','S017-M020':'C0060'}[mechanism],definition,source)


def replay(mechanism, future=False, block_at=None):
    bars,constraints,sessions,calendars,actions,start,end = fixture()
    if future:
        later = bars.Date > end
        bars.loc[later,['Open','High','Low','Close']] *= 100
        bars.loc[later,'Volume'] *= 10
        bars.loc[later,'Amount'] *= 1000
    if block_at is not None:
        constraints.loc[constraints.Date.eq(block_at),'Tradable'] = False
    result = StrategyRuntime(execution_spec=SPEC).create(candidate(mechanism)).run_window(
        bars,constraints,EquityHistoricalExecutor(specification=SPEC,initial_cash=100000.,fee_rate=.001,actions=actions),
        start=start,end=end,fee_rate=.001,sessions=sessions,trading_sessions=calendars)
    flags,_,_ = compute(bars)
    buy_fills = result.fills.loc[result.fills.side.eq('BUY')]
    assert not buy_fills.empty and not result.trades.empty
    indices = {stamp: index for index,stamp in enumerate(bars.Date)}
    expected_clock, actual_entries, cycle_holds = 0, {}, []
    for fill in buy_fills.itertuples():
        actual_entries[fill.cycle_id] = fill.interval_start
    for decision in result.decisions.itertuples():
        facts = {item['key']:item['text'] for item in decision.explanation['basis']}
        index = indices[decision.observed_through]
        assert (facts['entry_signal']=='True') == bool(flags.iloc[index][mechanism])
        if facts['held']=='True':
            entry = pd.Timestamp(facts['actual_entry'])
            expected_clock = int(((bars.BarStart >= entry)&(bars.Date <= decision.observed_through)).sum())
            assert int(facts['holding_bars']) == expected_clock
            assert decision.target == int(expected_clock < 6)
            cycle_holds.append(expected_clock)
        else:
            assert int(facts['holding_bars']) == 0
    tables = ('decisions','orders','fills','corporate_action_entries','account_points','account_daily','trades')
    hashes = {name:sha256(getattr(result,name).to_json(date_format='iso',double_precision=15).encode()).hexdigest() for name in tables}
    return {'hashes':hashes,'buy_fills':len(buy_fills),'closed_cycles':len(result.trades),
        'max_holding_bars':max(cycle_holds),'first_buy':buy_fills.iloc[0].interval_start,
        'first_sell':result.fills.loc[result.fills.side.eq('SELL')].iloc[0].interval_start}


def main():
    bars,*_ = fixture()
    flags,parents,regimes = compute(bars)
    compared = 0
    for i in range(78,len(bars)):
        expected,wanted_parents = scalar(bars,i)
        assert tuple(bool(flags.iloc[i][name]) for name in NAMES) == expected
        assert tuple(bool(parents.iloc[i][name]) for name in NAMES) == wanted_parents
        compared += 3
    assert all(flags[name].any() for name in NAMES)
    assert (flags[NAMES[1]] <= flags[NAMES[0]]).all() and (flags[NAMES[2]] <= flags[NAMES[0]]).all()
    changed = bars.copy()
    changed.loc[500:,['Open','High','Low','Close']] *= 100
    f,p,r = compute(changed)
    pd.testing.assert_frame_equal(flags.iloc[:500],f.iloc[:500])
    pd.testing.assert_frame_equal(parents.iloc[:500],p.iloc[:500])
    pd.testing.assert_series_equal(regimes.iloc[:500],r.iloc[:500])
    edge = bars.iloc[:80].copy()
    edge[['Open','High','Low','Close']] = [100.,102.,98.,100.]
    edge.loc[70,'Close'] = 101.
    edge.loc[78,'Close'] = 99.
    edge.loc[79,['High','Close']] = [104.,103.]
    f,_,_ = compute(edge)
    assert bool(f.iloc[-1][NAMES[0]]) and not bool(f.iloc[-1][NAMES[1]]) and bool(f.iloc[-1][NAMES[2]])
    edge.loc[70,'Close'] = 101.1
    assert bool(compute(edge)[0].iloc[-1][NAMES[1]])
    edge.loc[78,'Low'] = 97.9
    assert not bool(compute(edge)[0].iloc[-1][NAMES[2]])
    edge.loc[79,'Close'] = 102.
    assert not bool(compute(edge)[0].iloc[-1][NAMES[0]])
    try:
        step(SimpleNamespace(parameters={'entry_mechanism':NAMES[1],'max_holding_bars':13},portfolio=None),None)
    except ValueError:
        pass
    else:
        raise AssertionError('Nonfrozen horizon accepted')
    runtime = {}
    for mechanism in NAMES[1:]:
        baseline = replay(mechanism)
        assert baseline['hashes'] == replay(mechanism,future=True)['hashes']
        failed = replay(mechanism,block_at=baseline['first_buy'])
        blocked = replay(mechanism,block_at=baseline['first_sell'])
        assert blocked['max_holding_bars'] > 6
        runtime[mechanism] = {'baseline':baseline,'failed_buy':failed,'blocked_exit':blocked,'future_seven_tables_equal':True}
    result = {'status':'PASS','scope':'SYNTHETIC_VECTOR_AND_PUBLIC_V3_RUNTIME',
        'scalar_vector_comparisons':compared,'runtime':runtime,
        'checks':['independent_scalar_vector','parent_containment','strict_mean_and_breakout',
            'inclusive_equal_lows','prior_only_windows','future_suffix_seven_table_invariance',
            'actual_fill_clock','failed_buy_no_clock','blocked_exit_continues','fixed_six_only'],
        'sources':{path.name:sha256(path.read_bytes()).hexdigest() for path in
            (Path(__file__),WORK/'src/strategy_v3.py',WORK/'src/signals.py')}}
    (WORK/'others/entry_checks.json').write_text(json.dumps(result,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(result,default=str),flush=True)


if __name__ == '__main__':
    main()
