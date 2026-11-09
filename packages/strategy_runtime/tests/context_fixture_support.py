"""Declared auxiliary/session inputs: causal slicing, identity and isolation."""




from datetime import date, datetime, timedelta, timezone








import pandas as pd




from dataflows import (InstrumentId, MarketId, AssetClass, BarFrequency, TimeInterval,
                       TradingSession, SourceRef)


from strategy_runtime import (EquityAuxiliaryInput, EquityStrategyCandidate, EquityStrategyDefinition, EquityPortfolio,
    DecisionPoint, ResearchExecutionSpec, UsEquitySpec, AccountPolicy, CashAvailabilityPolicy,
    equity_source_hash, build_equity_decision_context)


def auxiliary_declaration():
    return EquityAuxiliaryInput('market', InstrumentId(MarketId.US, AssetClass.ETF, 'SPY'),
        SourceRef('synthetic', 'v1'), BarFrequency.M30, 2, 3600, analysis_price='RAW')


def make_candidate(root, *, enabled=True, latency=0):
    root.mkdir(parents=True, exist_ok=True)
    source = ('from strategy_runtime import EquityDecision\n'
        'def decide(ctx):\n'
        ' values = list(ctx.auxiliary_histories)\n'
        ' previous = ctx.auxiliary_histories[values[0]].Close.iloc[-1] if values else 0\n'
        ' if values: ctx.auxiliary_histories[values[0]].iloc[-1, 4] = 999\n'
        ' return EquityDecision.from_facts(int(bool(values)), "declared context", '
        'facts={"aliases": str(values), "close": previous, "session": str(ctx.session), '
        '"available": str(ctx.session_available_at)}, next_watch="next interval")\n')
    (root / 'strategy.py').write_text(source, encoding='utf-8')
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.,
        data_latency_seconds=latency)
    auxiliary = auxiliary_declaration()
    definition = EquityStrategyDefinition(InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE'), spec,
        1, 'strategy:decide', ('strategy.py',), equity_source_hash(root, ('strategy.py',)),
        auxiliary_inputs=(auxiliary,) if enabled else (), session_context=enabled,analysis_price="RAW")
    return EquityStrategyCandidate('S999', 'C0001', definition, root)


def fixture(day=date(2025, 11, 28), *, close_hour=18):
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).replace(hour=14, minute=30)
    session = TradingSession(day, 'America/New_York',
        (TimeInterval(start, start.replace(hour=close_hour, minute=0)),))
    decision = start + timedelta(hours=1)
    point = DecisionPoint(decision, decision, TimeInterval(decision, decision + timedelta(minutes=30)))
    ends = [decision - timedelta(minutes=30), decision, decision + timedelta(minutes=30)]
    aux = pd.DataFrame({'Date': ends, 'AvailableDate': ends, 'Open': 10., 'High': 11.,
                        'Close': [10., 11., 10.], 'Low': 9., 'Volume': 100.})
    primary = aux.iloc[:2].copy(deep=True)
    sessions = pd.DataFrame({'Date': [start], 'AvailableDate': [start], 'SessionDate': [day.isoformat()]})
    return primary, aux, point, sessions, (session,)


def build(value, data, **overrides):
    history, aux, point, sessions, calendar = data
    arguments = dict(auxiliary_histories={'market': aux}, sessions=sessions, trading_sessions=calendar)
    arguments.update(overrides)
    return build_equity_decision_context(value.definition, history, EquityPortfolio(1000., 0, 0., 0),
                                        point, **arguments)
