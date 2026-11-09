"""Account replay ownership, state transactions and exact economic transitions."""


from dataclasses import replace








import pandas as pd




from strategy_runtime.models import ExecutionPolicy


from dataflows import AssetClass, BarFrequency, InstrumentId, MarketId, SourceRef, TradingSession, TimeInterval


from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, EquityStrategyCandidate, EquityAuxiliaryInput,
    EquityStrategyDefinition, ResearchExecutionSpec, UsEquitySpec, StrategyComputation, equity_source_hash)


from strategy_runtime.equity_features import BarField, FeatureGraph, RawField


from strategy_runtime.equity_replay import (PreparedObservations, StateField, StateValueType, StrategyStateSchema)


from execution_channels.historical import PortfolioHistoricalExecutor




from czsc_trader.application.ec_boundary import execution_spec


SOURCE = '''from strategy_runtime import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord
def step(ctx, state):
    close = ctx.features.get("close").value
    if state.cycle is None:
        held, latched = 0, False
        target = int(close >= 10.)
    else:
        held = state.cycle.values.get("held") + 1
        latched = state.cycle.values.get("latched") or close < 9.
        target = int(not latched)
    return AccountStepResult(AccountDecision.from_facts(target, "numbered test", facts={"held":held,"latched":latched},
        next_watch="next complete bar"), StateRecord(), StateRecord((("held",held),("latched",latched))))
'''


def candidate(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'strategy.py').write_text(SOURCE, encoding='utf-8')
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
    graph = FeatureGraph((RawField('close', BarField.CLOSE),), ('close',))
    schema = StrategyStateSchema(cycle_fields=(StateField('held', StateValueType.INT),
                                             StateField('latched', StateValueType.BOOL)))
    definition = EquityStrategyDefinition(InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE'),
        spec, 1, 'strategy:step', ('strategy.py',), equity_source_hash(root, ('strategy.py',)), '{}',
        contract_version=4,execution_policy=ExecutionPolicy("TARGET_POSITION", {"capital_mode":"full_available_cash"}), computation=StrategyComputation.STATEFUL_STEP, feature_graph=graph, state_schema=schema)
    return EquityStrategyCandidate('S999', 'C0001', definition, root)


def inputs(value, count=7):
    starts = pd.date_range('2024-03-01 14:30', periods=count, freq='30min', tz='UTC')
    bars = pd.DataFrame({'BarStart': starts, 'Date': starts + pd.Timedelta(minutes=30),
        'AvailableDate': starts + pd.Timedelta(minutes=30), 'Open': 10., 'High': 11.,
        'Low': 9., 'Close': 10., 'Volume': 100000., 'Amount': 1000000.,
        'BarStatus': 'OBSERVED', 'ExecutionBlocked': False})
    constraints = pd.DataFrame({'Date': starts, 'AvailableDate': starts,
                                'QuantityStep': 1, 'PriceTick': .01, 'Tradable': True,
        'SellRemainderPolicy':'STRICT_STEP','PriceLimitPolicy':'EXPLICIT_UNBOUNDED',
        'PriceLimitLower':None,'PriceLimitUpper':None,'BuySellableAt':starts})
    executor = PortfolioHistoricalExecutor(specification=execution_spec(value.definition.execution_spec),
        initial_cash=1000., fee_rate=.001,  price_basis='HFQ')
    return bars, constraints, executor


def prepare(value, bars, constraints, **kwargs):
    session = TradingSession(bars.BarStart.iloc[0].date(), value.instrument.timezone,
        (TimeInterval(bars.BarStart.iloc[0].to_pydatetime(), bars.Date.iloc[-1].to_pydatetime()),))
    session_frame = pd.DataFrame({'Date':[bars.BarStart.iloc[0]],'AvailableDate':[bars.BarStart.iloc[0]],
        'SessionDate':[session.session_date.isoformat()]})
    parameters = dict(frequency=value.definition.execution_spec.decision_clock, timezone=value.instrument.timezone,
        sessions=session_frame,trading_sessions=(session,))
    parameters.update(kwargs)
    return PreparedObservations.from_frames(bars,value.definition.feature_graph,**parameters)


def with_context(value, bars, *, max_age=1800.):
    declaration = EquityAuxiliaryInput('market', InstrumentId(MarketId.US, AssetClass.ETF, 'SPY'),
        SourceRef('synthetic', 'v3'), BarFrequency.M30, 1, max_age)
    value = replace(value, definition=replace(value.definition, auxiliary_inputs=(declaration,), session_context=True))
    session = TradingSession(bars.BarStart.iloc[0].date(), 'America/New_York',
        (TimeInterval(bars.BarStart.iloc[0].to_pydatetime(), bars.Date.iloc[-1].to_pydatetime()),))
    sessions = pd.DataFrame({'Date': [bars.BarStart.iloc[0]], 'AvailableDate': [bars.BarStart.iloc[0]],
                             'SessionDate': [session.session_date.isoformat()]})
    return value, sessions, (session,)
