"""Synthetic V4 benchmark; no research artifacts, suppliers or publication."""
# ruff: noqa: E402
import argparse
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True

import pandas as pd
from dataflows import AssetClass, BarFrequency, InstrumentId, MarketId, TimeInterval, TradingSession
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, CnEquitySpec, UsEquitySpec,
    EquityStrategyCandidate, EquityStrategyDefinition, FeatureGraph, PreparedReplay,
    ResearchExecutionSpec, StrategyComputation, StrategyStateSchema, equity_source_hash, run_replay)
from trading_execution_engine import PortfolioHistoricalExecutor

SOURCE='''from strategy_runtime import AccountDecision, AccountStepResult, StateRecord
def step(ctx,state):
    target=0. if ctx.account.quantity else 1.
    return AccountStepResult(AccountDecision.from_facts(target,'timing',facts={'target':target},
        next_watch='next bar',capital_mode='full_available_cash'),cycle_values=StateRecord())
'''


def run_benchmark(*,rows,repeats,market,output):
    if type(rows) is not int or rows<2 or type(repeats) is not int or repeats<1:
        raise ValueError('rows >= 2 and repeats >= 1 required')
    market=MarketId(market)
    output=Path(output).resolve()
    if not output.is_relative_to((ROOT/'.tmp').resolve()):
        raise ValueError('output must stay inside repository .tmp')
    source=output/'source'
    source.mkdir(parents=True,exist_ok=True)
    (source/'strategy.py').write_text(SOURCE,encoding='utf-8')
    instrument=InstrumentId(market,AssetClass.STOCK,'600000.SH' if market is MarketId.CN else 'TEST')
    zone=ZoneInfo(instrument.timezone)
    sessions,grid,day=[],[],date(2020,1,2)
    while len(grid)<rows+1:
        if day.weekday()<5:
            segments=((time(9,30),time(11,30)),(time(13),time(15))) if market is MarketId.CN else ((time(9,30),time(16)),)
            session=TradingSession(day,instrument.timezone,tuple(TimeInterval(
                datetime.combine(day,a,zone),datetime.combine(day,b,zone)) for a,b in segments))
            sessions.append(session)
            grid.extend(session.bars(BarFrequency.M30))
        day+=timedelta(days=1)
    bars=pd.DataFrame({'Date':[p.end for p in grid],'BarStart':[p.start for p in grid],
        'AvailableDate':[p.end for p in grid],'Open':10.,'High':11.,'Low':9.,'Close':10.,
        'Volume':1000000.,'Amount':10000000.})
    step=100 if market is MarketId.CN else 1
    rules=pd.DataFrame({'Date':bars.BarStart,'AvailableDate':bars.BarStart,'QuantityStep':step,
        'PriceTick':.01,'Tradable':True,'SellRemainderPolicy':'FULL_LIQUIDATION',
        'PriceLimitPolicy':'DATED_LIMITS' if market is MarketId.CN else 'EXPLICIT_UNBOUNDED',
        'PriceLimitLower':1. if market is MarketId.CN else None,'PriceLimitUpper':20. if market is MarketId.CN else None,
        'BuySellableAt':bars.BarStart+pd.Timedelta(days=1) if market is MarketId.CN else bars.BarStart})
    calendar=pd.DataFrame({'Date':[s.segments[0].start for s in sessions],
        'AvailableDate':[s.segments[0].start for s in sessions],'SessionDate':[s.session_date.isoformat() for s in sessions]})
    actions=pd.DataFrame([dict(Date=grid[0].start,AvailableDate=grid[0].start,EventId='verified-none',
        Kind='NONE',Ratio=1.,CashPerShare=0.,PayAt=None)])
    spec=ResearchExecutionSpec(CnEquitySpec() if market is MarketId.CN else UsEquitySpec(),BarFrequency.M30,
        AccountPolicy(instrument.currency,CashAvailabilityPolicy.IMMEDIATE_RESEARCH),step,.01,.01,0.)
    definition=EquityStrategyDefinition(instrument,spec,1,'strategy:step',('strategy.py',),
        equity_source_hash(source,('strategy.py',)),contract_version=4,computation=StrategyComputation.STATEFUL_STEP,
        feature_graph=FeatureGraph((),()),state_schema=StrategyStateSchema())
    candidate=EquityStrategyCandidate('S999','C0001',definition,source)
    started=perf_counter()
    prepared=PreparedReplay.from_frames(bars,rules,definition.feature_graph,frequency=BarFrequency.M30,
        timezone=instrument.timezone,sessions=calendar,trading_sessions=tuple(sessions))
    prepare_seconds=perf_counter()-started
    runs,expected=[],None
    for repeat in range(repeats):
        started=perf_counter()
        executor=PortfolioHistoricalExecutor(specification=spec,initial_cash=100000.,fee_rate=.001,actions=actions,price_basis='RAW')
        outcome=run_replay(prepared,candidate,executor,start=grid[1].start,end=grid[rows].end,fee_rate=.001)
        elapsed=perf_counter()-started
        hashes={name:sha256(getattr(outcome.execution_result,name).to_json(orient='records',date_format='iso',date_unit='us').encode()).hexdigest()
            for name in ('decisions','orders','fills','corporate_action_entries','account_points','account_daily','trades')}
        if expected is not None and hashes!=expected:
            raise ValueError('repeated account facts differ')
        expected=hashes
        stats=asdict(outcome.statistics)
        if stats['source_checks']!=0 or stats['module_loads']!=1:
            raise ValueError('account loading contract differs')
        runs.append({'repeat':repeat+1,'seconds':elapsed,'runtime':stats,'table_hashes':hashes})
    result={'status':'PASS','market':market.value,'rows':rows,'repeats':repeats,'prepare_seconds':prepare_seconds,
        'calendar':'synthetic weekdays, not exchange-history evidence',
        'timing':'executor + strategy/module + replay + result tables; excludes data fetch, SE audit, publication',
        'median_seconds':median(r['seconds'] for r in runs),'runs':runs}
    (output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows',type=int,default=25000)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--market',choices=['CN','US'],default='US')
    parser.add_argument('--output',type=Path,default=ROOT/'.tmp/equity-replay-benchmark')
    result=run_benchmark(**vars(parser.parse_args()))
    print(json.dumps({k:result[k] for k in ('status','market','rows','median_seconds','prepare_seconds')}))


if __name__=='__main__':
    main()
