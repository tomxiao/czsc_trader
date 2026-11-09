"""V4 computation/clock parity and actual position execution, using synthetic facts."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
from strategy_runtime.models import ExecutionPolicy
from dataflows import AssetClass, BarFrequency, InstrumentId, MarketId, TradingSession, TimeInterval
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, CnEquitySpec, UsEquitySpec,
    ResearchExecutionSpec, EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash,
    StrategyComputation)
from strategy_runtime.equity_features import FeatureGraph, RawField, BarField
from strategy_runtime.equity_replay import PreparedObservations, StrategyStateSchema
from execution_channels.historical import PortfolioHistoricalExecutor
from czsc_trader.application.ec_boundary import execution_spec


STEP = """from strategy_runtime import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord
def step(ctx,state):
    target=(.25,.5,.25,0.)[int(ctx.history.last()['Close']-10)%4]
    return AccountStepResult(AccountDecision.from_facts(target,'repair target',facts={'target':target},next_watch='next bar'), cycle_values=StateRecord())
"""
BATCH = """from strategy_runtime import AccountDecision
def calculate(ctx):
    return tuple(AccountDecision.from_facts((.25,.5,.25,0.)[int(row.history.last()['Close']-10)%4], 'repair target', facts={'close':row.history.last()['Close']},next_watch='next bar') for row in ctx.observations)
"""


def setup(root, market, frequency, computation, *, with_executor=True):
    root.mkdir(parents=True,exist_ok=True)
    (root/'strategy.py').write_text(STEP if computation is StrategyComputation.STATEFUL_STEP else BATCH,encoding='utf-8')
    instrument=InstrumentId(market,AssetClass.STOCK,'600000.SH' if market is MarketId.CN else 'TEST')
    spec=ResearchExecutionSpec(CnEquitySpec() if market is MarketId.CN else UsEquitySpec(),frequency,
        AccountPolicy('CNY' if market is MarketId.CN else 'USD',CashAvailabilityPolicy.IMMEDIATE_RESEARCH),100,.01,.01,0.)
    definition=EquityStrategyDefinition(instrument,spec,1,'strategy:step' if computation is StrategyComputation.STATEFUL_STEP else 'strategy:calculate',
        ('strategy.py',),equity_source_hash(root,('strategy.py',)),contract_version=4,execution_policy=ExecutionPolicy("TARGET_POSITION", {}),computation=computation,
        feature_graph=FeatureGraph((RawField('close',BarField.CLOSE),),('close',)),state_schema=StrategyStateSchema())
    candidate=EquityStrategyCandidate('S999','C0001',definition,root)
    zone=ZoneInfo(instrument.timezone)
    # Declared synthetic sessions, not an official exchange calendar.
    sessions=tuple(TradingSession(date(2024,3,d),str(zone),(TimeInterval(datetime(2024,3,d,9,30,tzinfo=zone),datetime(2024,3,d,11,30,tzinfo=zone)),)) for d in (4,5,6,7,8))
    periods=tuple(p for s in sessions for p in ((TimeInterval(s.segments[0].start,s.segments[-1].end),) if frequency is BarFrequency.DAILY else s.bars(frequency)))
    starts=pd.DatetimeIndex([p.start for p in periods]).tz_convert('UTC')
    ends=pd.DatetimeIndex([p.end for p in periods]).tz_convert('UTC')
    bars=pd.DataFrame({'BarStart':starts,'Date':ends,'AvailableDate':ends,'Open':10.,'High':15.,'Low':9.,'Close':[10.+i%4 for i in range(len(periods))],'Volume':1000000.,'Amount':10000000.})
    constraints=pd.DataFrame({'Date':starts,'AvailableDate':starts,'QuantityStep':100,'PriceTick':.01,'Tradable':True,
        'SellRemainderPolicy':'STRICT_STEP','PriceLimitPolicy':'EXPLICIT_UNBOUNDED','PriceLimitLower':None,'PriceLimitUpper':None,'BuySellableAt':starts})
    session_frame=pd.DataFrame({'Date':[s.segments[0].start for s in sessions], 'AvailableDate':[s.segments[0].start for s in sessions], 'SessionDate':[s.session_date.isoformat() for s in sessions]})
    prepared=PreparedObservations.from_frames(bars,definition.feature_graph,frequency=frequency,timezone=instrument.timezone,sessions=session_frame,trading_sessions=sessions)
    executor=None if not with_executor else PortfolioHistoricalExecutor(specification=execution_spec(spec),initial_cash=100000.,fee_rate=.001,price_basis='HFQ')
    return candidate,prepared,executor,bars,constraints,sessions,session_frame
