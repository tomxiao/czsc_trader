"""Synthetic US fixtures: independent repositories; explicit small execution budgets.

Archived seeds expose immutable bytes only. Consumers decode a fresh mutable
payload for each corruption case; no live session or certified handle is shared.
"""
from dataclasses import dataclass, replace
from datetime import date, datetime
from contextlib import contextmanager
from zoneinfo import ZoneInfo

import pandas as pd
from dataflows import (AssetClass, BarFrequency, EquityProduct, EquityDataRequest, EquityQuery, InstrumentId, MarketId,
    ProviderBinding, ProviderConfig, ProviderKey, SourceRef, TimeInterval, TradingSession)
from dataflows.equity_data import equity_metadata
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy,
    ExecutionResources, ResearchExecutionSpec, UsEquitySpec, StrategyComputation)
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


@dataclass
class _FixtureCandidate:
    strategy_id: str
    candidate_id: str
    instrument: InstrumentId
    execution_spec_hash: str
    warmup_bars: int
    decide: object


@dataclass
class _FixtureRequest:
    """Input values for isolated frozen-V2 tests, never a TDR research request."""
    experiment: object
    candidate: object
    window: object
    history_start: object
    sources: object
    initial_cash: float
    fee_rate: float
    prepared: object = None
    input_binding: object = None
    audit_inputs_sha256: str | None = None
    benchmark: object = None
    window_id: str = 'FULL'
    scenario_id: str = 'STANDARD'
    measurement_tier: str = 'FORMAL'
    drawdown_basis: str | None = None
    concentration_basis: str | None = None
    frequency_window_days: int = 60
    lineage: object = None

    @property
    def formal(self):
        return isinstance(self.candidate, EquityStrategyCandidate)

    def request_items(self, specification):
        end = self.window.end.astimezone(ZoneInfo(self.candidate.instrument.timezone)).date()
        values = tuple((product.name.lower(),EquityDataRequest(self.candidate.instrument,
            getattr(self.sources,product.name.lower()),EquityQuery(product,self.history_start,end,specification.decision_clock)))
            for product in EquityProduct)
        if self.formal:
            values += tuple((item.data_key(product), query) for item in self.candidate.definition.auxiliary_inputs
                for product,query in zip((EquityProduct.BARS,EquityProduct.SESSIONS),item.requests(self.history_start,end),strict=True))
        return values

    def requests(self, specification):
        return tuple(query for _,query in self.request_items(specification))


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
                                "PriceLimitPolicy": 'EXPLICIT_UNBOUNDED',
                                "PriceLimitLower": None, "PriceLimitUpper": None,
                                "BuySellableAt": [b.start for b in grid],
                                "SellRemainderPolicy": 'FULL_LIQUIDATION',
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
    candidate = _FixtureCandidate(strategy_id='S999', candidate_id='C0001', instrument=instrument,
        execution_spec_hash=spec.fingerprint, warmup_bars=1, decide=decide)
    request = _FixtureRequest(experiment, candidate, TimeInterval(grid[1].start, grid[-1].end),
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


def setup_account_research(tmp_path):
    context, legacy, products, calls = setup_equity(tmp_path)
    root = tmp_path / "fixture-source"
    root.mkdir()
    (root / "strategy.py").write_text(
        "from strategy_runtime import AccountDecision, AccountStepResult, StateRecord\n"
        "def step(ctx, state):\n"
        "    target = 0 if ctx.portfolio.quantity else 1\n"
        "    return AccountStepResult(AccountDecision.from_facts(target, 'alternate', "
        "facts={'quantity': ctx.portfolio.quantity}, next_watch='next bar'), cycle_values=StateRecord())\n", encoding="utf-8")
    definition = EquityStrategyDefinition(legacy.candidate.instrument, context.execution_spec, 1,
        "strategy:step", ("strategy.py",), equity_source_hash(root, ("strategy.py",)),
        contract_version=4, computation=StrategyComputation.STATEFUL_STEP,
        feature_graph=FeatureGraph((), ()), state_schema=StrategyStateSchema())
    candidate = EquityStrategyCandidate("S999", "C0001", definition, root)
    request = EquityEvaluationRequest(legacy.experiment,candidate,legacy.window,legacy.history_start,
        legacy.sources,legacy.initial_cash,legacy.fee_rate,
        benchmark=EvaluationBenchmark(EquityBuyHold(context.execution_spec)),
        drawdown_basis="BAR_CLOSE", concentration_basis="TOP_DECILE")
    return context, request, products, calls


def current_account_request(context, request):
    """Express a frozen fixture decision in the current account contract."""
    from hashlib import sha256
    if isinstance(request, EquityEvaluationRequest):
        return request
    if request.formal:
        definition = request.candidate.definition
        content = (request.candidate.source_root / "strategy.py").read_text(encoding="utf-8")
        content = content.replace('.iloc[-1]["Close"]', '.last()["Close"]')
    else:
        target = "1" if request.candidate.decide is hold else "0 if ctx.portfolio.quantity else 1"
        content = ('from strategy_runtime.equity_definition import EquityDecision\n'
                   'def decide(ctx):\n'
                   f'    return EquityDecision.from_facts({target}, "fixture", facts={{"quantity":ctx.portfolio.quantity}}, next_watch="next bar")\n')
        definition = EquityStrategyDefinition(request.candidate.instrument, context.execution_spec,
            request.candidate.warmup_bars, "strategy:decide", ("strategy.py",), "0" * 64)
    content += ('\nfrom strategy_runtime import AccountDecision, AccountStepResult, StateRecord\n'
                'def step(ctx, state):\n'
                '    result=decide(ctx)\n'
                '    return AccountStepResult(AccountDecision(result.target,result.explanation,capital_mode="full_available_cash"), cycle_values=StateRecord())\n')
    root = request.experiment.resolve(context.repository.root) / ".tmp" / sha256(content.encode()).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    (root / "strategy.py").write_text(content, encoding="utf-8")
    definition = replace(definition, entrypoint="strategy:step", source_sha256=equity_source_hash(root, ("strategy.py",)),
        contract_version=4, computation=StrategyComputation.STATEFUL_STEP,feedback_mode='CONFIRMED_EXECUTION',
        feature_graph=FeatureGraph((), ()), state_schema=StrategyStateSchema())
    candidate_id = request.candidate.candidate_id if request.formal else "C0001"
    candidate = EquityStrategyCandidate(request.candidate.strategy_id, candidate_id, definition, root)
    return EquityEvaluationRequest(request.experiment,candidate,request.window,request.history_start,
        request.sources,request.initial_cash,request.fee_rate,
        benchmark=EvaluationBenchmark(EquityBuyHold(context.execution_spec)),
        drawdown_basis=request.drawdown_basis or "BAR_CLOSE", concentration_basis=request.concentration_basis or "MAX_SINGLE",
        window_id=request.window_id,scenario_id=request.scenario_id,measurement_tier=request.measurement_tier,
        frequency_window_days=request.frequency_window_days,lineage=request.lineage)


@contextmanager
def account_research(context, request):
    from czsc_trader.research_tools import ResearchExecutionSession
    from czsc_trader.research_tools.equity_replay import materialize_equity
    request = current_account_request(context, request)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        if outcome.result is None:
            raise ValueError(outcome.error.message)
        yield prepared, outcome.result, materialize_equity(outcome.result).payload, execution


def replay_payload(context, request):
    with account_research(context, request) as (_, _, payload, _):
        return payload
