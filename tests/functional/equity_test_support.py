"""Synthetic US fixtures: independent repositories; explicit small execution budgets.

Archived seeds expose immutable bytes only. Consumers decode a fresh mutable
payload for each corruption case; no live session or certified handle is shared.
"""
from dataclasses import replace
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import (AssetClass, BarFrequency, EquityProduct, InstrumentId, MarketId,
    ProviderBinding, ProviderConfig, ProviderKey, SourceRef, TimeInterval, TradingSession)
from dataflows.equity_data import equity_metadata
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, EquityCandidate,
    ExecutionResources, ResearchExecutionSpec, UsEquitySpec, equity_implementation_hash)
from strategy_runtime.equity_definition import (EquityAuxiliaryInput, EquityStrategyCandidate,
    EquityStrategyDefinition, equity_source_hash)
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import StrategyStateSchema
from czsc_trader.application.context import RepositoryContext
from czsc_trader.application.research_governance_service import (
    create_research_batch, create_research_context, create_experiment, ResearchBatchRequest, ExperimentRequest)
from czsc_trader.research_tools import EquityEvaluationRequest, EquitySources, EvaluationBenchmark, EquityBuyHold


def alternate(history, portfolio):
    return 1 if portfolio.quantity == 0 else 0


def hold(history, portfolio):
    return 1


def setup_equity(tmp_path, decide=alternate, *, cash_policy=CashAvailabilityPolicy.IMMEDIATE_RESEARCH):
    repository = RepositoryContext(tmp_path, tmp_path / "research", tmp_path / "research/registrations", tmp_path / "strategies")
    batch = create_research_batch(repository, ResearchBatchRequest("S999", "Equity fixture", "US:LITE",
                                  {"goal": "fixture"}), actor="DEV", reason="isolated contract test")
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30, AccountPolicy("USD", cash_policy),
                                 1, .01, .01, 0.)
    instrument, source = InstrumentId(MarketId.US, AssetClass.STOCK, "LITE"), SourceRef("fixture", "v1")
    zone = ZoneInfo(instrument.timezone)
    sessions = tuple(TradingSession(date(2026, 10, day), str(zone), (TimeInterval(
        datetime(2026, 10, day, 9, 30, tzinfo=zone), datetime(2026, 10, day, 16, tzinfo=zone)),)) for day in (1, 2))
    grid = [bar for session in sessions for bar in session.bars(BarFrequency.M30)]
    bars = pd.DataFrame({"Date": [b.end for b in grid], "BarStart": [b.start for b in grid],
                         "AvailableDate": [b.end for b in grid], "Open": 10., "High": 10.2,
                         "Low": 9.8, "Close": 10., "Volume": 100., "Amount": 1000.})
    constraints = pd.DataFrame({"Date": [b.start for b in grid], "AvailableDate": [b.start for b in grid],
                                "QuantityStep": 1, "PriceTick": .01, "Tradable": True,
                                "SettlementAt": [grid[-1].end for _ in grid]})
    actions = pd.DataFrame([{"Date": grid[0].start, "AvailableDate": grid[0].start, "EventId": "none",
                             "Kind": "NONE", "Ratio": 1., "CashPerShare": 0., "PayAt": None}])
    products = {EquityProduct.BARS: bars, EquityProduct.CONSTRAINTS: constraints, EquityProduct.ACTIONS: actions,
                EquityProduct.SESSIONS: pd.DataFrame({"Date": [s.segments[0].start for s in sessions],
                "AvailableDate": [s.segments[0].start for s in sessions],
                "SessionDate": [s.session_date.isoformat() for s in sessions]})}
    calls = []

    def fetch(request):
        calls.append(request)
        metadata = equity_metadata(request, sessions, availability_basis="FIXTURE_BAR_CLOSE")
        metadata["no_actions_verified"] = True
        return products[request.parameters.query.product].copy(deep=True), metadata

    config = ProviderConfig(bindings={}, equity_bindings={ProviderKey(product, MarketId.US, source):
                            ProviderBinding("fixture", "v1", fetch) for product in EquityProduct})
    context = create_research_context(repository, batch, providers=config, execution_spec=spec)
    context.evaluation.resources = ExecutionResources(max_workers=1, native_threads_per_worker=1)
    experiment = create_experiment(context, ExperimentRequest("Fixture", "Does isolated US execution work?", date(2026, 10, 28)))
    candidate = EquityCandidate("S999", "C001", instrument, spec.fingerprint, equity_implementation_hash(decide), 1, decide)
    request = EquityEvaluationRequest(experiment, candidate, TimeInterval(grid[1].start, grid[-1].end),
                                      date(2026, 10, 1), EquitySources(source, source, source, source), 1000., .001)
    return context, request, products, calls


def setup_formal_equity(tmp_path):
    context, old, products, calls = setup_equity(tmp_path)
    root = old.experiment.resolve(context.repository.root) / "src"
    root.mkdir(exist_ok=True)
    (root / "strategy.py").write_text(
        'from strategy_runtime.equity_definition import EquityDecision\n'
        'def decide(ctx):\n'
        '    target = 0 if ctx.portfolio.quantity else ctx.parameters["enter"]\n'
        '    return EquityDecision.from_facts(target, "position timing", facts={"quantity":ctx.portfolio.quantity,"enter":ctx.parameters["enter"]}, next_watch="next completed bar")\n',
        encoding="utf-8")
    files = ("strategy.py",)
    definition = EquityStrategyDefinition(old.candidate.instrument, context.execution_spec, 1,
                                          "strategy:decide", files, equity_source_hash(root, files), '{"enter":1}')
    candidate = EquityStrategyCandidate(context.strategy_id, "C0001", definition, root)
    request = replace(old, candidate=candidate, benchmark=EvaluationBenchmark(EquityBuyHold(context.execution_spec)),
                      drawdown_basis="BAR_CLOSE", concentration_basis="MAX_SINGLE")
    return context, request, products, calls


def setup_auxiliary(tmp_path, *, auxiliary_days=(1, 2), max_age_seconds=86400, same_source=False,
                    latency_seconds=0, half_day=False):
    """Return context/request/products/calls; products['auxiliary'] is mutable test data."""
    old_context, old, products, calls = setup_formal_equity(tmp_path)
    zone = ZoneInfo("America/New_York")
    sessions = tuple(TradingSession(date(2026, 10, day), str(zone), (TimeInterval(
        datetime(2026, 10, day, 9, 30, tzinfo=zone), datetime(2026, 10, day, 13 if half_day and day == 2 else 16, tzinfo=zone)),))
        for day in (1, 2))
    grid = tuple(bar for session in sessions for bar in session.bars(old_context.execution_spec.decision_clock))
    products[EquityProduct.BARS] = products[EquityProduct.BARS].loc[lambda rows: rows.Date.isin([bar.end for bar in grid])].copy()
    products[EquityProduct.CONSTRAINTS] = products[EquityProduct.CONSTRAINTS].loc[lambda rows: rows.Date.isin([bar.start for bar in grid])].copy()
    old = replace(old, window=TimeInterval(old.window.start, grid[-1].end))
    source = old.sources.bars if same_source else SourceRef("auxiliary-fixture", "v1")
    auxiliary = EquityAuxiliaryInput("market", InstrumentId(MarketId.US, AssetClass.ETF, "SPY"),
        source, old_context.execution_spec.decision_clock, 1, max_age_seconds)
    products["auxiliary"] = {product: products[product].copy(deep=True)
                              for product in (EquityProduct.BARS, EquityProduct.SESSIONS)}
    products["auxiliary"][EquityProduct.BARS].loc[:, ["Open", "High", "Low", "Close"]] *= 10
    for product, data in products["auxiliary"].items():
        products["auxiliary"][product] = data.loc[data.Date.dt.day.isin(auxiliary_days)].copy()

    def fetch(request):
        calls.append(request)
        is_auxiliary = request.parameters.instrument == auxiliary.instrument
        data = products["auxiliary"] if is_auxiliary else products
        calendar = tuple(s for s in sessions if s.session_date.day in auxiliary_days) if is_auxiliary else sessions
        metadata = equity_metadata(request, calendar, availability_basis="FIXTURE_BAR_CLOSE")
        metadata["no_actions_verified"] = True
        return data[request.parameters.query.product].copy(deep=True), metadata

    bindings = {ProviderKey(product, MarketId.US, old.sources.bars): ProviderBinding("fixture", "v1", fetch)
                for product in EquityProduct}
    bindings.update({ProviderKey(product, MarketId.US, source): ProviderBinding(source.provider, source.revision, fetch)
                     for product in (EquityProduct.BARS, EquityProduct.SESSIONS)})
    specification = replace(old_context.execution_spec, data_latency_seconds=latency_seconds)
    context = create_research_context(old_context.repository, old_context.batch,
        providers=ProviderConfig(bindings={}, equity_bindings=bindings), execution_spec=specification)
    context.evaluation.resources = ExecutionResources(max_workers=1, native_threads_per_worker=1)
    root = old.candidate.source_root
    (root / "strategy.py").write_text(
        'from strategy_runtime.equity_definition import EquityDecision\n'
        'def decide(ctx):\n'
        '    target = 0 if ctx.portfolio.quantity else ctx.parameters["enter"]\n'
        '    return EquityDecision.from_facts(target, "auxiliary timing", facts={"market_close":float(ctx.auxiliary_histories["market"].iloc[-1]["Close"]),"session_end":ctx.session.segments[-1].end.isoformat()}, next_watch="next completed bar")\n',
        encoding="utf-8")
    definition = replace(old.candidate.definition, source_sha256=equity_source_hash(root, ("strategy.py",)),
                         auxiliary_inputs=(auxiliary,), session_context=True, execution_spec=specification)
    candidate = EquityStrategyCandidate(context.strategy_id, "C0001", definition, root)
    from czsc_trader.research_tools import EquityBuyHold, EvaluationBenchmark
    return context, replace(old, candidate=candidate, benchmark=EvaluationBenchmark(EquityBuyHold(specification))), products, calls


def setup_v3(tmp_path):
    context, legacy, products, calls = setup_equity(tmp_path)
    root = tmp_path / "fixture-source"
    root.mkdir()
    (root / "strategy.py").write_text(
        "from strategy_runtime.equity_definition import EquityDecision\n"
        "from strategy_runtime.equity_replay import StepResult, StateRecord\n"
        "def step(ctx, state):\n"
        "    target = 0 if ctx.portfolio.quantity else 1\n"
        "    return StepResult(EquityDecision.from_facts(target, 'alternate', "
        "facts={'quantity': ctx.portfolio.quantity}, next_watch='next bar'), cycle_values=StateRecord())\n", encoding="utf-8")
    definition = EquityStrategyDefinition(legacy.candidate.instrument, context.execution_spec, 1,
        "strategy:step", ("strategy.py",), equity_source_hash(root, ("strategy.py",)),
        contract_version=3, feature_graph=FeatureGraph((), ()), state_schema=StrategyStateSchema())
    candidate = EquityStrategyCandidate("S999", "C0001", definition, root)
    request = replace(legacy, candidate=candidate,
        benchmark=EvaluationBenchmark(EquityBuyHold(context.execution_spec)),
        drawdown_basis="BAR_CLOSE", concentration_basis="TOP_DECILE")
    return context, request, products, calls


@pytest.fixture(scope="module")
def archived_formal_account_bytes(frozen_seed_root):
    from czsc_trader.research_tools.equity_assessment import build_equity_assessment_payload
    seed = frozen_seed_root / f"formal-archive-{uuid4().hex}"
    seed.mkdir()
    context, request, _, _ = setup_formal_equity(seed)
    prepared = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(prepared)
    assert build_equity_assessment_payload(result.payload)
    return result.content


@pytest.fixture(scope="module")
def archived_auxiliary_account_bytes(frozen_seed_root):
    from czsc_trader.research_tools.equity_assessment import build_equity_assessment_payload
    seed = frozen_seed_root / f"auxiliary-archive-{uuid4().hex}"
    seed.mkdir()
    context, request, _, _ = setup_auxiliary(seed, max_age_seconds=70000)
    prepared = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(prepared)
    assert build_equity_assessment_payload(result.payload)
    key = request.candidate.definition.auxiliary_inputs[0].data_key(EquityProduct.BARS)
    return result.content, key
