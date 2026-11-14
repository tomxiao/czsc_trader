"""CN/US HFQ research and independently prepared RAW simulation quotations."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from dataflows import (AssetClass, BarFrequency, EquityProduct, InstrumentId, MarketId,
    PriceAdjustment, ProviderBinding, ProviderConfig, ProviderKey, SourceRef, TimeInterval,
    TradingSession)
from dataflows.equity_data import equity_metadata, session_record
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, CnEquitySpec, UsEquitySpec,
    EquityStrategyCandidate, EquityStrategyDefinition,
    ExecutionResources, ResearchExecutionSpec, StrategyComputation, equity_source_hash)
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.models import ExecutionPolicy
from strategy_runtime.equity_replay import StrategyStateSchema
from czsc_trader.application.context import RepositoryContext
from czsc_trader.application.research_governance_service import (
    create_research_context, ResearchBatchRequest, ExperimentRequest)
from czsc_trader.research_tools import (EquityEvaluationRequest, EquitySources, EquityBuyHold,
    EvaluationBenchmark)
from czsc_trader.research_tools.equity_replay import materialize_equity
from research_scaffold_support import seeded_research_context


def setup_adjusted(tmp_path, market, computation=StrategyComputation.STATEFUL_STEP, *, etf=False,
                   existing_experiment=None):
    """Use real market clocks/rules, with synthetic prices and independent sessions."""
    cn = market is MarketId.CN
    instrument = (InstrumentId(market, AssetClass.ETF, "510500.SH" if cn else "QQQ") if etf
                  else InstrumentId(market, AssetClass.STOCK, "600722.SH" if cn else "MU"))
    source = SourceRef("adjusted-fixture", "v1")
    zone = ZoneInfo(instrument.timezone)
    sessions = []
    for day in (12, 13, 14, 15):
        opening = datetime(2026, 10, day, 9, 30, tzinfo=zone)
        closing = opening.replace(hour=15 if cn else 16, minute=0)
        segments = ((TimeInterval(opening, opening.replace(hour=11, minute=30)),
                     TimeInterval(opening.replace(hour=13, minute=0), closing)) if cn
                    else (TimeInterval(opening, closing),))
        sessions.append(TradingSession(opening.date(), str(zone), segments))
    sessions = tuple(sessions)
    grid = tuple(b for s in sessions for b in s.bars(BarFrequency.DAILY))
    quantity_step = 100 if cn else 1
    spec = ResearchExecutionSpec(CnEquitySpec() if cn else UsEquitySpec(), BarFrequency.DAILY,
        AccountPolicy("CNY" if cn else "USD", CashAvailabilityPolicy.IMMEDIATE_RESEARCH),
        quantity_step, .001 if cn and etf else .01, .01, 0.)
    bars = pd.DataFrame({"Date": [b.end for b in grid], "BarStart": [b.start for b in grid],
        "AvailableDate": [b.end for b in grid], "Open": 10., "High": 10.2, "Low": 9.8,
        "Close": 10., "Volume": 10000., "Amount": 100000.})
    adjusted = bars.copy(deep=True)
    adjusted.loc[:, ["Open", "High", "Low", "Close"]] *= 2
    sector_bars = bars.copy(deep=True)
    sector_bars.loc[:, ["Open", "High", "Low", "Close"]] *= 20
    products = {EquityProduct.BARS: bars,
        EquityProduct.SESSIONS: pd.DataFrame({"Date": [b.start for b in grid],
            "AvailableDate": [b.start for b in grid],
            "SessionDate": [s.session_date.isoformat() for s in sessions]}),
        EquityProduct.TRADING_FACTS: pd.DataFrame({"Date": [b.start for b in grid],
            "AvailableDate": [b.start for b in grid], "Tradable": True,
            "PriceLimitLower": 9. if cn else None, "PriceLimitUpper": 11. if cn else None})}
    calls = []

    def fetch(request):
        p = request.parameters
        calls.append(p)
        data = products[p.query.product]
        if p.query.product is EquityProduct.BARS and p.query.adjustment is PriceAdjustment.BACKWARD:
            data = adjusted if p.instrument == instrument else sector_bars
        metadata = equity_metadata(request, sessions, availability_basis="SYNTHETIC_BAR_CLOSE")
        if cn and p.query.product in (EquityProduct.TRADING_FACTS, EquityProduct.SESSIONS):
            delta = timedelta(days=1)
            following = TradingSession(sessions[-1].session_date + delta, str(zone),
                tuple(TimeInterval(part.start + delta, part.end + delta) for part in sessions[-1].segments))
            metadata["following_session"] = session_record(following)
        if p.query.product is EquityProduct.BARS:
            metadata['acquisition_method'] = 'PROVIDER_ADJUSTED' if p.query.adjustment is PriceAdjustment.BACKWARD else 'PROVIDER_RAW'
        if p.query.product is EquityProduct.TRADING_FACTS and p.query.adjustment is PriceAdjustment.BACKWARD:
            data = data.copy(deep=True)
            for column in ('PriceLimitLower', 'PriceLimitUpper'):
                data[column] = data[column].map(lambda value: None if value is None else value * 2)
        return data.copy(deep=True), metadata

    repository = RepositoryContext(tmp_path, tmp_path / "research", tmp_path / "research/registrations",
                                   tmp_path / "strategies")
    from czsc_trader.research_tools import ResearchBatchRef
    bindings = {ProviderKey(product, market, source): ProviderBinding(source.provider, source.revision, fetch)
                for product in EquityProduct}
    providers = ProviderConfig(bindings={}, equity_bindings=bindings)
    if existing_experiment is not None:
        # native_fixture already cloned a prepared data space; never replace it
        # with the empty scaffold or discard its authenticated publications.
        context = create_research_context(repository, ResearchBatchRef('S999'),
            providers=providers, execution_spec=spec)
        experiment = existing_experiment
    else:
        context, experiment = seeded_research_context(repository,
            ResearchBatchRequest("S999", "Adjusted fixture", str(instrument),
                                 {"goal": "adjusted observations with raw execution"}),
            ExperimentRequest("Adjusted fixture", "Do research prices remain independent of execution prices?",
                              date(2026, 10, 16)),
            actor="DEV", reason="isolated dual-market contract test", providers=providers, execution_spec=spec)
    context.evaluation.resources = ExecutionResources(max_workers=1, native_threads_per_worker=1)
    root = tmp_path / "fixture-source"
    root.mkdir(exist_ok=existing_experiment is not None)
    (root / "strategy.py").write_text(
        "from strategy_runtime import AccountDecision, AccountStepResult, StateRecord\n"
        "def step(ctx, state):\n"
        "    decision = AccountDecision.from_facts(1, 'hold', facts={'target': 1}, next_watch='next session')\n"
        "    return AccountStepResult(decision, cycle_values=StateRecord())\n", encoding="utf-8")
    entrypoint = "strategy:batch" if computation is StrategyComputation.BATCH_HISTORY else "strategy:step"
    definition = EquityStrategyDefinition(instrument, spec, 1, entrypoint, ("strategy.py",),
        equity_source_hash(root, ("strategy.py",)), contract_version=5,
        computation=computation, feature_graph=FeatureGraph((), ()),
        state_schema=StrategyStateSchema(),
        execution_policy=ExecutionPolicy("TARGET_POSITION", {"capital_mode": "target_equity_fraction"}))
    candidate = EquityStrategyCandidate("S999", "C0001", definition, root)
    request = EquityEvaluationRequest(experiment, candidate, TimeInterval(grid[1].start, grid[-1].end),
        date(2026, 10, 12), EquitySources(source, source, source), 10000., .001,
        benchmark=EvaluationBenchmark(EquityBuyHold(spec)), drawdown_basis="BAR_CLOSE",
        concentration_basis="TOP_DECILE")
    return context, request, products, adjusted, calls


def evaluate(context, request, execution):
    prepared = context.evaluation.prepare(request, execution=execution)
    outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
    assert outcome.status.value == "SUCCEEDED", outcome.error
    return prepared, outcome.result, materialize_equity(outcome.result).payload


def economic_rows(rows):
    # IDs intentionally include candidate/input identity; compare every economic
    # and timing field while preserving that lineage distinction.
    return [{key: value for key, value in row.items() if not key.endswith("_id")}
            for row in rows]
