"""Typed account requests for constructor/identity tests, without research I/O."""
from datetime import date, datetime, timezone

from dataflows import AssetClass, BarFrequency, InstrumentId, MarketId, SourceRef, TimeInterval
from strategy_runtime import (
    AccountPolicy, CashAvailabilityPolicy, CnEquitySpec, EquityStrategyCandidate, EquityStrategyDefinition,
    ExecutionPolicy, ResearchExecutionSpec, StrategyComputation, UsEquitySpec, equity_source_hash,
)
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import StrategyStateSchema
from czsc_trader.research_tools import (
    EquityBuyHold, EquityEvaluationRequest, EquitySources, EvaluationBenchmark, ExperimentRef,
)


def account_contract_request(source_root, market=MarketId.US):
    # Candidate authentication still verifies actual source bytes. No research
    # registration, data space, preparation or execution result is fabricated.
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / 'strategy.py').write_text(
        'from strategy_runtime import AccountDecision, AccountStepResult\n'
        'def step(ctx, state):\n'
        '    return AccountStepResult(AccountDecision.from_facts(0., "flat", facts={}, next_watch="next"))\n',
        encoding='utf-8')
    instrument = InstrumentId(market, AssetClass.STOCK, '600000.SH' if market is MarketId.CN else 'TEST')
    spec = ResearchExecutionSpec(CnEquitySpec() if market is MarketId.CN else UsEquitySpec(), BarFrequency.M30,
        AccountPolicy(instrument.currency, CashAvailabilityPolicy.IMMEDIATE_RESEARCH),
        100 if market is MarketId.CN else 1, .01, .01, 0.)
    definition = EquityStrategyDefinition(instrument,
        spec, 1, 'strategy:step', ('strategy.py',), equity_source_hash(source_root, ('strategy.py',)),
        contract_version=4, computation=StrategyComputation.STATEFUL_STEP,
        feature_graph=FeatureGraph((), ()), state_schema=StrategyStateSchema(),
        execution_policy=ExecutionPolicy('TARGET_POSITION', {}))
    candidate = EquityStrategyCandidate('S999', 'C0001', definition, source_root)
    source = SourceRef('contract-fixture', 'v1')
    return EquityEvaluationRequest(ExperimentRef('S999', 'EX001_20261030'), candidate,
        TimeInterval(datetime(2026, 10, 30, 14, tzinfo=timezone.utc),
                     datetime(2026, 10, 30, 15, tzinfo=timezone.utc)),
        date(2026, 10, 29), EquitySources(source, source, source), 10000., .001,
        benchmark=EvaluationBenchmark(EquityBuyHold(spec)), drawdown_basis='BAR_CLOSE',
        concentration_basis='MAX_SINGLE')
