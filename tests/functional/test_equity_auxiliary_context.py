"""Synthetic formal auxiliary data and session context integration contracts."""
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from dataflows import (AssetClass, EquityProduct, InstrumentId, MarketId, ProviderBinding,
                       ProviderConfig, ProviderKey, SourceRef, TimeInterval, TradingSession)
from dataflows.equity_data import equity_metadata
from strategy_runtime.equity_definition import (EquityAuxiliaryInput, EquityStrategyCandidate,
                                                 equity_source_hash)
from czsc_trader.application.research_governance_service import create_research_context
from test_equity_closure import setup_formal_equity


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


def test_auxiliary_preparation_evaluation_and_publication(tmp_path):
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import EvaluationEvidenceWrite
    from czsc_trader.research_tools.equity_assessment import build_equity_assessment_payload
    context, request, _, calls = setup_auxiliary(tmp_path)
    assert len(request.request_items(context.execution_spec)) == 6
    prepared = context.evaluation.prepare(request)
    assert len(prepared.input_binding.expected_identities) == 6
    result = context.evaluation.evaluate(prepared)
    assert len(calls) == 6
    assert "strategy_runtime.equity_context" in result.payload["request"]["engine_sources"]
    assert set(result.payload["audit_inputs"]["decision_inputs"]) == {"auxiliary", "sessions"}
    assert build_equity_assessment_payload(result.payload)
    ref = publish_evidence(context, EvaluationEvidenceWrite(request.experiment, "auxiliary", prepared, result))
    assert ref.schema_version == 2


@pytest.mark.parametrize("field", ["instrument", "source_revision", "sessions"])
def test_auxiliary_archived_metadata_is_authenticated(tmp_path, field):
    from czsc_trader.research_tools.equity_assessment import build_equity_assessment_payload
    context, request, _, _ = setup_auxiliary(tmp_path)
    payload = context.evaluation.evaluate(request).payload
    key = request.candidate.definition.auxiliary_inputs[0].data_key(EquityProduct.BARS)
    metadata = payload["data"][key]["metadata"]
    if field == "instrument":
        metadata[field]["symbol"] = "QQQ"
    elif field == "source_revision":
        metadata[field] = "v2"
    else:
        metadata[field][0]["segments"][0]["end"] = metadata[field][0]["segments"][0]["start"]
    with pytest.raises((ValueError, TypeError)):
        build_equity_assessment_payload(payload)


def test_auxiliary_inputs_do_not_change_buy_hold(tmp_path):
    context, request, _, _ = setup_auxiliary(tmp_path)
    result = context.evaluation.evaluate(request)
    definition = replace(request.candidate.definition, auxiliary_inputs=(), session_context=False)
    candidate = replace(request.candidate, definition=definition)
    # Candidate source needs context; compare against an ordinary formal candidate.
    source = candidate.source_root / "strategy.py"
    source.write_text('from strategy_runtime.equity_definition import EquityDecision\n'
        'def decide(ctx):\n'
        '    return EquityDecision.from_facts(ctx.parameters["enter"], "hold", facts={"enter":ctx.parameters["enter"]}, next_watch="next bar")\n', encoding="utf-8")
    candidate = replace(candidate, definition=replace(definition, source_sha256=equity_source_hash(source.parent, ("strategy.py",))))
    baseline = context.evaluation.evaluate(replace(request, candidate=candidate))
    assert result.payload["runs"]["buy_hold"] == baseline.payload["runs"]["buy_hold"]


def test_auxiliary_stale_input_stops_formal_evaluation(tmp_path):
    context, request, products, _ = setup_auxiliary(tmp_path)
    import pandas as pd
    bars = products["auxiliary"][EquityProduct.BARS]
    bars.loc[1:, "AvailableDate"] = bars.loc[1:, "AvailableDate"] + pd.Timedelta(days=10)
    declaration = replace(request.candidate.definition.auxiliary_inputs[0], max_age_seconds=60)
    candidate = replace(request.candidate, definition=replace(request.candidate.definition, auxiliary_inputs=(declaration,)))
    with pytest.raises(ValueError, match="AUXILIARY_INPUT_STALE"):
        context.evaluation.evaluate(replace(request, candidate=candidate))


def test_auxiliary_independent_calendar_is_allowed(tmp_path):
    context, request, products, _ = setup_auxiliary(tmp_path, auxiliary_days=(1,))
    bars = products[EquityProduct.BARS]
    start = bars.loc[bars.Date.dt.day.eq(2), "BarStart"].iloc[0].to_pydatetime()
    request = replace(request, window=TimeInterval(start, request.window.end))
    result = context.evaluation.evaluate(request)
    from czsc_trader.research_tools.equity_assessment import build_equity_assessment_payload
    assert build_equity_assessment_payload(result.payload)


@pytest.mark.parametrize("mutation,match", [("future", "AUXILIARY_INPUT_UNAVAILABLE"),
    ("stale", "AUXILIARY_INPUT_STALE"), ("missing", "independent session grid"),
    ("session", "session is not yet available")])
def test_archived_context_validation_survives_rehashed_envelope(tmp_path, mutation, match):
    from strategy_runtime.equity import equity_hash
    from czsc_trader.research_tools.equity_assessment import build_equity_assessment_payload
    context, request, _, _ = setup_auxiliary(tmp_path, max_age_seconds=70000)
    payload = context.evaluation.evaluate(request).payload
    records = payload["audit_inputs"]["decision_inputs"]
    bars = records["auxiliary"]["market"]["bars"]
    if mutation in {"future", "stale"}:
        for row in bars[0 if mutation == "future" else 1:]:
            row["AvailableDate"] = "2026-10-20T20:00:00.000000Z"
    elif mutation == "missing":
        bars.pop(0)
    else:
        records["sessions"][0]["AvailableDate"] = "2026-10-20T20:00:00.000000Z"
    payload["request"]["audit_inputs_sha256"] = equity_hash(payload["audit_inputs"])
    payload["request_hash"] = equity_hash(payload["request"])
    payload["evaluation_identity"]["protocol_sha256"] = payload["request_hash"]
    from strategy_runtime import canonical_sha256
    payload["evaluation_id"] = canonical_sha256(payload["evaluation_identity"])
    with pytest.raises(ValueError, match=match):
        build_equity_assessment_payload(payload)


def test_auxiliary_workers_and_checkpoint_use_all_pinned_inputs(tmp_path):
    from strategy_runtime import ExecutionResources
    from czsc_trader.research_tools import (ResearchExecutionSession, ExecutionCheckpointRequest, CheckpointMode)
    context, request, _, calls = setup_auxiliary(tmp_path)
    context.evaluation.resources = ExecutionResources(max_workers=2, native_threads_per_worker=1)
    requests = (request, replace(request, scenario_id="PRESSURE", measurement_tier="STRESS", fee_rate=.002))
    prepared = tuple(context.evaluation.prepare(item) for item in requests)
    serial = tuple(context.evaluation.evaluate(item) for item in prepared)
    with ResearchExecutionSession(context, experiment=request.experiment,
                                  checkpoint=ExecutionCheckpointRequest("auxiliary-run")) as execution:
        outcomes = context.evaluation.evaluate_many(prepared, execution=execution)
        assert [item.status.value for item in outcomes] == ["SUCCEEDED", "SUCCEEDED"]
        assert [item.result.content for item in outcomes] == [item.content for item in serial]
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest("auxiliary-run", CheckpointMode.RESUME)) as execution:
        restored = context.evaluation.evaluate_many(prepared, execution=execution)
        assert [item.result.content for item in restored] == [item.content for item in serial]
        assert execution.stats.reused_results == 2
    assert len(calls) == 6


def test_archived_primary_history_applies_declared_latency(tmp_path):
    import pandas as pd
    from czsc_trader.research_tools.equity_assessment import build_equity_assessment_payload
    context, request, products, _ = setup_auxiliary(tmp_path, latency_seconds=2)
    bars = products[EquityProduct.BARS]
    start = bars.BarStart.iloc[3].to_pydatetime()
    bars.loc[0, "AvailableDate"] = pd.Timestamp(start) - pd.Timedelta(seconds=1)
    request = replace(request, window=TimeInterval(start, request.window.end))
    result = context.evaluation.evaluate(request)
    first = result.payload["runs"]["candidate"]["decisions"][0]
    assert pd.Timestamp(first["observed_through"]) == bars.Date.iloc[1]
    assert build_equity_assessment_payload(result.payload)


@pytest.mark.parametrize("half_day,exit_hour", [(False, 15), (True, 12)])
def test_session_only_exit_executes_at_last_interval_open(tmp_path, half_day, exit_hour):
    import pandas as pd
    from czsc_trader.research_tools.equity_assessment import build_equity_assessment_payload
    context, request, products, _ = setup_auxiliary(tmp_path, half_day=half_day)
    source = request.candidate.source_root / "strategy.py"
    source.write_text('from strategy_runtime.equity_definition import EquityDecision\n'
        'def decide(ctx):\n'
        '    target = int(ctx.point.execution_interval.end != ctx.session.segments[-1].end)\n'
        '    return EquityDecision.from_facts(target, "session exit", facts={"session_end":ctx.session.segments[-1].end.isoformat()}, next_watch="next session")\n', encoding="utf-8")
    definition = replace(request.candidate.definition, auxiliary_inputs=(),
        source_sha256=equity_source_hash(source.parent, ("strategy.py",)))
    request = replace(request, candidate=replace(request.candidate, definition=definition))
    bars = products[EquityProduct.BARS]
    bars.loc[bars.index[-1], "Close"] = 10.1
    result = context.evaluation.evaluate(request)
    assert set(result.payload["audit_inputs"]["decision_inputs"]) == {"sessions"}
    run = result.payload["runs"]["candidate"]
    sells = [row for row in run["fills"] if row["side"] == "SELL"]
    assert len(sells) == 2
    last = pd.Timestamp(sells[-1]["interval_start"]).tz_convert("America/New_York")
    assert (last.hour, last.minute) == (exit_hour, 30)
    assert sells[-1]["price"] == 10.0
    assert run["account_points"][-1]["quantity"] == 0
    assert build_equity_assessment_payload(result.payload)
