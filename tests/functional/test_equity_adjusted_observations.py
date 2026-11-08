"""CN/US HFQ research and independently prepared RAW simulation quotations."""
from dataclasses import replace
from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from dataflows import (AssetClass, BarFrequency, EquityProduct, InstrumentId, MarketId,
    PriceAdjustment, ProviderBinding, ProviderConfig, ProviderKey, SourceRef, TimeInterval,
    TradingSession)
from dataflows.equity_data import equity_metadata, session_record
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, CnEquitySpec, UsEquitySpec,
    EquityAuxiliaryInput, EquityInputBinding, EquityStrategyCandidate, EquityStrategyDefinition,
    ExecutionResources, ResearchExecutionSpec, StrategyComputation, equity_source_hash)
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.models import ExecutionPolicy
from strategy_runtime.equity_replay import StrategyStateSchema
from czsc_trader.application import publish_evidence_many
from czsc_trader.application.context import RepositoryContext
from czsc_trader.application.equity_evidence_io import materialize_equity_document
from czsc_trader.application.research_governance_service import (create_research_batch,
    create_research_context, create_experiment, ResearchBatchRequest, ExperimentRequest)
from czsc_trader.research_tools import (EquityEvaluationRequest, EquitySources, EquityBuyHold,
    EvaluationBenchmark, EvaluationEvidenceWrite, ResearchExecutionSession)
from czsc_trader.research_tools.equity_replay import materialize_equity


def setup_adjusted(tmp_path, market, computation=StrategyComputation.STATEFUL_STEP, *, etf=False,
                   existing_experiment=None):
    """Use real market clocks/rules, with synthetic prices and independent sessions."""
    cn = market is MarketId.CN
    instrument = (InstrumentId(market, AssetClass.ETF, "510500.SH" if cn else "QQQ") if etf
                  else InstrumentId(market, AssetClass.STOCK, "600722.SH" if cn else "MU"))
    sector = InstrumentId(market, AssetClass.ETF, ("159326.SZ" if etf else "510500.SH") if cn else "SOXX")
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
    batch = (ResearchBatchRef('S999') if existing_experiment is not None else
        create_research_batch(repository, ResearchBatchRequest("S999", "Adjusted fixture",
            str(instrument), {"goal": "adjusted observations with raw execution"}), actor="DEV",
            reason="isolated dual-market contract test"))
    bindings = {ProviderKey(product, market, source): ProviderBinding(source.provider, source.revision, fetch)
                for product in EquityProduct}
    context = create_research_context(repository, batch,
        providers=ProviderConfig(bindings={}, equity_bindings=bindings), execution_spec=spec)
    context.evaluation.resources = ExecutionResources(max_workers=1, native_threads_per_worker=1)
    experiment = existing_experiment or create_experiment(context, ExperimentRequest("Adjusted fixture",
        "Do research prices remain independent of execution prices?", date(2026, 10, 16)))
    root = tmp_path / "fixture-source"
    root.mkdir(exist_ok=existing_experiment is not None)
    (root / "strategy.py").write_text(
        "from strategy_runtime import AccountDecision, AccountStepResult, StateRecord\n"
        "def decision(ctx):\n"
        "    raw = float(ctx.history.last()['Close'])\n"
        "    observed = [float(view.last()['Close']) for view in ctx.auxiliary_histories.values()]\n"
        "    assert raw == 20.\n"
        "    assert not observed or observed == [20., 200.]\n"
        "    return AccountDecision.from_facts(1, 'hold', "
        "facts={'raw': raw, 'observed': str(observed)}, next_watch='next session')\n"
        "def step(ctx, state):\n"
        "    return AccountStepResult(decision(ctx), cycle_values=StateRecord())\n"
        "def batch(ctx):\n"
        "    return tuple(decision(row) for row in ctx.observations)\n", encoding="utf-8")
    auxiliary = (EquityAuxiliaryInput("stock_hfq", instrument, source, BarFrequency.DAILY, 1, 86400 * 4, "HFQ"),
                 EquityAuxiliaryInput("sector_hfq", sector, source, BarFrequency.DAILY, 1, 86400 * 4, "HFQ"))
    entrypoint = "strategy:batch" if computation is StrategyComputation.BATCH_HISTORY else "strategy:step"
    definition = EquityStrategyDefinition(instrument, spec, 1, entrypoint, ("strategy.py",),
        equity_source_hash(root, ("strategy.py",)), contract_version=4,
        computation=computation, feature_graph=FeatureGraph((), ()),
        state_schema=StrategyStateSchema(), auxiliary_inputs=auxiliary,
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


@pytest.mark.parametrize("market", (MarketId.CN, MarketId.US))
@pytest.mark.parametrize("computation", (StrategyComputation.STATEFUL_STEP, StrategyComputation.BATCH_HISTORY))
def test_adjusted_observations_prepare_evaluate_publish_read_use_hfq_execution(tmp_path, market, computation):
    context, request, _, _, calls = setup_adjusted(tmp_path, market, computation)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared, result, payload = evaluate(context, request, execution)
        binding = prepared.request.input_binding
        assert len(binding.expected_identities) == 7
        items = binding.bind_requests(prepared.request.requests(context.execution_spec))
        assert set(key for key, _ in items) == set(binding.expected_identities)
        physical = dict(items)
        assert physical["sessions"] == physical["auxiliary:stock_hfq:sessions"]
        assert physical["bars"].parameters.query.adjustment is PriceAdjustment.BACKWARD
        assert physical["auxiliary:stock_hfq:bars"].parameters.query.adjustment is PriceAdjustment.BACKWARD
        assert EquityInputBinding.from_dict(json.loads(json.dumps(binding.to_dict()))) == binding
        assert payload["data"]["bars"]["metadata"]["adjustment"] == PriceAdjustment.BACKWARD.value
        assert payload["data"]["auxiliary:stock_hfq:bars"]["metadata"]["adjustment"] == PriceAdjustment.BACKWARD.value
        assert payload["data"]["bars"]["content_sha256"] == payload["data"]["auxiliary:stock_hfq:bars"]["content_sha256"]
        fills = payload["runs"]["candidate"]["fills"]
        assert fills and all(row["price"] == 20. for row in fills)
        assert all(row["quantity"] % (100 if market is MarketId.CN else 1) == 0 for row in fills)
        published, = publish_evidence_many(context,
            (EvaluationEvidenceWrite(request.experiment, "adjusted", prepared, result),), execution=execution)
        assert published.status.value == "PUBLISHED", published.error
        path = published.reference.resolve(context.repository.root)
        restored = materialize_equity_document(context.repository.root,
            path.relative_to(context.repository.root).as_posix(), path.read_bytes()).payload
        assert restored == payload
        raw_request = replace(request, candidate=replace(request.candidate, candidate_id="C0002",
            definition=replace(request.candidate.definition, auxiliary_inputs=())))
        _, _, raw_payload = evaluate(context, raw_request, execution)
        assert raw_payload["runs"]["buy_hold"] == payload["runs"]["buy_hold"]
        for name in ("fills", "account_daily"):
            assert economic_rows(raw_payload["runs"]["candidate"][name]) == economic_rows(payload["runs"]["candidate"][name])
        assert execution.equity_statistics.benchmark_runs == 1
    # Seven logical roles share the primary HFQ stream and calendar.
    # Removing auxiliary observations must reuse the same physical products.
    assert len(calls) == 5
    assert len(set(calls)) == 5


@pytest.mark.parametrize("market", (MarketId.CN, MarketId.US))
def test_alias_change_uses_distinct_snapshot_and_reuses_physical_data(tmp_path, market):
    context, request, _, _, calls = setup_adjusted(tmp_path, market)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        _, first, original = evaluate(context, request, execution)
        definition = request.candidate.definition
        renamed = replace(definition.auxiliary_inputs[0], name="renamed_hfq")
        changed = replace(request, candidate=replace(request.candidate, candidate_id="C0002",
            definition=replace(definition, auxiliary_inputs=(renamed, definition.auxiliary_inputs[1]))))
        _, second, renamed_payload = evaluate(context, changed, execution)
        assert first.payload["input_ref"] != second.payload["input_ref"]
        assert "auxiliary:renamed_hfq:bars" in renamed_payload["data"]
        assert "auxiliary:stock_hfq:bars" not in renamed_payload["data"]
        assert original["runs"]["buy_hold"] == renamed_payload["runs"]["buy_hold"]
        for name in ("fills", "account_daily"):
            assert economic_rows(original["runs"]["candidate"][name]) == economic_rows(renamed_payload["runs"]["candidate"][name])
        assert execution.equity_statistics.input_snapshots == 2
        assert execution.equity_statistics.benchmark_runs == 1
    assert len(calls) == 5


@pytest.mark.parametrize("market", (MarketId.CN, MarketId.US))
def test_adjusted_observation_availability_is_causal(tmp_path, market):
    context, request, _, adjusted, _ = setup_adjusted(tmp_path, market)
    # The second day's adjusted close is unavailable until after the whole run.
    # Its outlier would fail the strategy assertion if visibility used Date only.
    adjusted.loc[1, ["Open", "High", "Low", "Close"]] = [21., 21.5, 20.5, 21.]
    adjusted.loc[1, "AvailableDate"] += pd.Timedelta(days=10)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        _, _, payload = evaluate(context, request, execution)
        assert len(payload["runs"]["candidate"]["decisions"]) == 3
        recorded = payload["audit_inputs"]["decision_inputs"]["auxiliary"]["stock_hfq"]["bars"]
        assert recorded[1]["Close"] == 21.


@pytest.mark.parametrize('basis', [None, '', 'another-adjustment-base'])
def test_hfq_limits_cannot_mix_adjustment_bases(basis):
    from czsc_trader.application.execution_inputs import execution_constraints
    metadata = {'bars': {'adjustment': 'hfq', 'price_basis_id': 'primary'},
                'trading_facts': {'adjustment': 'hfq', 'price_basis_id': basis}}
    with pytest.raises(ValueError, match='price limits must use the primary HFQ basis'):
        execution_constraints(None, {}, metadata)


def test_research_identity_pins_shared_execution_rules(tmp_path):
    context, request, _, _, _ = setup_adjusted(tmp_path, MarketId.US)
    identity = request.identity(context.execution_spec)
    assert 'execution_channels.planning.session_rules' in identity['engine_sources']
