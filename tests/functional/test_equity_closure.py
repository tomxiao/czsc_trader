"""Formal US research lifecycle uses existing public preparation/publication APIs."""
from dataclasses import replace
import json

import pytest
from strategy_runtime import ExecutionResources
from strategy_runtime.equity_definition import EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash
from czsc_trader.application import (publish_evidence, publish_evidence_many, register_candidate, load_candidate,
                                    CandidateRegistrationRequest, assemble_delivery, validate_delivery)
from czsc_trader.research_tools import (EquityBuyHold, EvaluationBenchmark, EvaluationEvidenceWrite,
                                      ResearchExecutionSession, ExecutionCheckpointRequest, CheckpointMode)
from czsc_trader.research_tools.assessment import build_assessment_evidence
from czsc_trader.research_tools import delivery as d
from test_equity_research import setup_equity


def terminate_equity_worker(*args):
    import os
    os._exit(7)


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


def test_formal_equity_prepare_assess_register_and_prototype_delivery(tmp_path):
    from czsc_trader.research_tools import MaterialEvidenceWrite
    context, request, _, _ = setup_formal_equity(tmp_path)
    request = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(request)
    assert result.payload["schema"] == "equity-research/v2"
    assert request.input_binding is not None
    facts = build_assessment_evidence(request, result)
    assert facts[0].candidate.content_sha256 == request.candidate.content_identity.content_sha256
    ref = publish_evidence(context, EvaluationEvidenceWrite(request.experiment, "formal", request, result))
    assert (ref.schema, ref.schema_version) == ("equity_research", 2)
    record = register_candidate(context.repository, CandidateRegistrationRequest(request.candidate, request.experiment, (ref,), ()))
    loaded = load_candidate(context.repository, request.candidate.key)
    assert loaded.content_identity.content_sha256 == record.content_sha256
    assert context.evaluation.evaluate(replace(request, candidate=loaded)).content == result.content
    material = publish_evidence(context, MaterialEvidenceWrite(request.experiment, "definition",
        json.dumps(request.candidate.payload).encode(), "application/json", "json"))
    entry = d.PrototypeEntry("P1", d.CandidateIdentityRef(request.candidate.key, record.content_sha256),
        d.ExperimentDefinitionRef(material, "strategy:decide"), "Synthetic timing hypothesis", (),
        (d.EvaluationEvidenceRef(ref, (facts[0].evaluation_id,)),), d.PrototypeDisposition.INVESTIGATE,
        "Contract exercise only", ("Synthetic data",), "Review", (material,))
    panel = d.PrototypePanel((entry,), (), (), "Synthetic complete evidence")
    content = d.DeliveryContent(panel, d.DeliveryStatus.COMPLETE, (), (), report="# Synthetic prototype\n")
    output = assemble_delivery(context.repository, d.DeliveryDefinition(context.batch, d.DeliveryStage.PROTOTYPES, 1, ()), content)
    assert validate_delivery(context.repository, output.receipt.reference).status == "PASS"
    from czsc_trader.application import get_research_overview
    overview = get_research_overview(context.repository, context.batch)
    assert len(overview.candidates) == 1
    assert len(overview.prototype_panels) == 1


def test_formal_equity_parallel_checkpoint_and_publication_reuse(tmp_path):
    context, request, _, _ = setup_formal_equity(tmp_path)
    context.evaluation.resources = ExecutionResources(max_workers=2, native_threads_per_worker=1)
    requests = (request, replace(request, scenario_id="PRESSURE", measurement_tier="STRESS", fee_rate=.002))
    prepared = tuple(context.evaluation.prepare(r) for r in requests)
    serial = tuple(context.evaluation.evaluate(r) for r in prepared)
    with ResearchExecutionSession(context, experiment=request.experiment,
                                  checkpoint=ExecutionCheckpointRequest("equity-run")) as execution:
        outcomes = context.evaluation.evaluate_many(prepared, execution=execution)
        assert [o.status.value for o in outcomes] == ["SUCCEEDED", "SUCCEEDED"]
        assert [o.result.content for o in outcomes] == [r.content for r in serial]
        writes = tuple(EvaluationEvidenceWrite(r.experiment, r.scenario_id, r, o.result) for r, o in zip(prepared, outcomes))
        published = publish_evidence_many(context, writes, execution=execution)
        assert all(x.status.value == "PUBLISHED" for x in published)
    with ResearchExecutionSession(context, experiment=request.experiment,
                                  checkpoint=ExecutionCheckpointRequest("equity-run", CheckpointMode.RESUME)) as execution:
        restored = context.evaluation.evaluate_many(prepared, execution=execution)
        assert [o.result.content for o in restored] == [r.content for r in serial]
        assert execution.stats.reused_results == 2
        again = publish_evidence_many(context, writes, execution=execution)
        assert [x.reference for x in again] == [x.reference for x in published]
        assert execution.stats.reused_publications == 2


def test_equity_formal_requires_explicit_semantics_and_rejects_tampered_results(tmp_path):
    context, request, _, _ = setup_formal_equity(tmp_path)
    with pytest.raises(ValueError, match="explicit drawdown"):
        replace(request, drawdown_basis=None)
    prepared = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(prepared)
    value = result.payload
    value["runs"]["candidate"]["account_points"][2]["receivable"] += 1
    from czsc_trader.research_tools.equity_assessment import build_equity_assessment_payload
    with pytest.raises(ValueError):
        build_equity_assessment_payload(value)
    assert EvaluationBenchmark.from_dict(json.loads(json.dumps(request.benchmark.to_dict()))) == request.benchmark
    from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
    for content in (b'{"x":1,"x":2}', b'{"x":NaN}'):
        with pytest.raises(ValueError, match="duplicate|nonfinite"):
            EquityEvaluationResult(result.request_hash, content)


def test_formal_equity_diagnosis_retains_intraday_cycles_and_continuous_slice(tmp_path):
    from datetime import date
    from czsc_trader.application import diagnose_accounts
    from czsc_trader.research_tools.account_diagnosis import AccountRunRef, AccountDiagnosisRequest
    from czsc_trader.research_tools.evaluation import EvaluationIdentity, EvaluationWindow
    from strategy_manager import CandidateKey
    context, request, _, _ = setup_formal_equity(tmp_path)
    request = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(request)
    reference = publish_evidence(context, EvaluationEvidenceWrite(request.experiment, "diagnosis", request, result))
    raw = dict(result.payload["evaluation_identity"])
    raw["candidate"] = CandidateKey(**raw["candidate"])
    account = AccountRunRef(reference, EvaluationIdentity(**raw))
    full = diagnose_accounts(context.repository, AccountDiagnosisRequest(account, account,
        EvaluationWindow("full", date(2026, 10, 1), date(2026, 10, 2))))
    assert full.status == "COMPUTED", full.issues
    assert len(full.path_comparison) > 2
    assert all(abs(row.residual) < 1e-7 for row in full.pnl_breakdown[0].daily)
    sliced = diagnose_accounts(context.repository, AccountDiagnosisRequest(account, None,
        EvaluationWindow("slice", date(2026, 10, 2), date(2026, 10, 2))))
    assert sliced.status == "COMPUTED", sliced.issues
    assert sliced.pnl_breakdown[0].daily[0].opening_equity == full.pnl_breakdown[0].daily[0].closing_equity


def test_equity_diagnosis_reconciles_split_dividend_and_payment(tmp_path):
    import pandas as pd
    from dataflows import EquityProduct
    from datetime import date
    from czsc_trader.application import diagnose_accounts
    from czsc_trader.research_tools.account_diagnosis import AccountRunRef, AccountDiagnosisRequest
    from czsc_trader.research_tools.evaluation import EvaluationIdentity, EvaluationWindow
    from strategy_manager import CandidateKey
    context, request, products, _ = setup_formal_equity(tmp_path)
    source = request.candidate.source_root / "strategy.py"
    source.write_text(source.read_text(encoding="utf-8").replace(
        '0 if ctx.portfolio.quantity else ctx.parameters["enter"]', 'ctx.parameters["enter"]'), encoding="utf-8")
    definition = replace(request.candidate.definition, source_sha256=equity_source_hash(source.parent, ("strategy.py",)))
    request = replace(request, candidate=replace(request.candidate, definition=definition))
    bars = products[EquityProduct.BARS]
    stamp, pay = bars.BarStart.iloc[13], bars.Date.iloc[-1]
    bars.loc[13:, ["Open", "High", "Low", "Close"]] /= 2
    products[EquityProduct.ACTIONS] = pd.DataFrame([
        {"Date":stamp,"AvailableDate":stamp,"EventId":"split","Kind":"SPLIT","Ratio":2.,"CashPerShare":0.,"PayAt":None},
        {"Date":stamp,"AvailableDate":stamp,"EventId":"dividend","Kind":"CASH_DIVIDEND","Ratio":1.,"CashPerShare":.1,"PayAt":pay},
    ])
    request = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(request)
    ref = publish_evidence(context, EvaluationEvidenceWrite(request.experiment, "events", request, result))
    identity = dict(result.payload["evaluation_identity"])
    identity["candidate"] = CandidateKey(**identity["candidate"])
    diagnosis = diagnose_accounts(context.repository, AccountDiagnosisRequest(
        AccountRunRef(ref, EvaluationIdentity(**identity)), None,
        EvaluationWindow("events", date(2026,10,1), date(2026,10,2))))
    assert diagnosis.status == "COMPUTED", diagnosis.issues
    assert all(abs(row.residual) < 1e-7 for row in diagnosis.pnl_breakdown[0].daily)
    assert result.payload["runs"]["candidate"]["account_points"][-1]["equity"] == pytest.approx(1018.62)


def test_formal_benchmark_applies_opening_split_before_integer_share_budget(tmp_path):
    import pandas as pd
    from dataflows import EquityProduct
    context, request, products, _ = setup_formal_equity(tmp_path)
    bars = products[EquityProduct.BARS]
    stamp = bars.BarStart.iloc[1]
    bars.loc[1:, ["Open", "High", "Low", "Close"]] /= 2
    bars["Volume"] = 1000.
    products[EquityProduct.ACTIONS] = pd.DataFrame([
        {"Date":stamp,"AvailableDate":stamp,"EventId":"opening-split","Kind":"SPLIT", "Ratio":2.,"CashPerShare":0.,"PayAt":None},
    ])
    result = context.evaluation.evaluate(request)
    # Floor is applied after converting the visible reference to post-split units.
    # Rounding a pre-split order and then multiplying would incorrectly buy 196.
    for run in result.payload["runs"].values():
        assert run["fills"][0]["quantity"] == 197
        assert run["decisions"][0]["reference_price"] == 5.
        assert run["decisions"][0]["limit_price"] == 5.05


def test_equity_checkpoint_corruption_and_source_drift_fail_explicitly(tmp_path):
    from czsc_trader.research_tools._execution_checkpoint import CheckpointIntegrityError
    context, request, _, _ = setup_formal_equity(tmp_path)
    request = context.evaluation.prepare(request)
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest("integrity")) as execution:
        outcome = context.evaluation.evaluate_many((request,), execution=execution)[0]
        assert outcome.status.value == "SUCCEEDED"
        record = execution.checkpoint.root / "results" / f"{outcome.request_hash}.json"
    record.write_text("corrupted checkpoint", encoding="utf-8")
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest("integrity", CheckpointMode.RESUME)) as execution:
        with pytest.raises(CheckpointIntegrityError):
            context.evaluation.evaluate_many((request,), execution=execution)
        assert execution.stats.submitted == 0
    source = request.candidate.source_root / "strategy.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# changed source\n", encoding="utf-8")
    outcome = context.evaluation.evaluate_many((request,))[0]
    assert outcome.status.value == "FAILED"
    assert "hash" in outcome.error.message.lower() or "source" in outcome.error.message.lower()


def test_equity_worker_death_is_unknown_and_does_not_restart_pool(tmp_path, monkeypatch):
    from concurrent.futures.process import BrokenProcessPool
    from czsc_trader.research_tools import _equity_batch
    context, request, _, _ = setup_formal_equity(tmp_path)
    request = context.evaluation.prepare(request)
    context.evaluation.resources = ExecutionResources(2)
    monkeypatch.setattr(_equity_batch, "compute_equity", terminate_equity_worker)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        outcomes = context.evaluation.evaluate_many((request, request), execution=execution)
        assert [x.status.value for x in outcomes] == ["UNKNOWN", "UNKNOWN"]
        assert execution.stats.pool_starts == 1
        with pytest.raises(BrokenProcessPool):
            context.evaluation.evaluate_many((request,), execution=execution)
        assert execution.stats.submitted == 2


def test_equity_cancelled_progress_terminates_workers_and_requires_new_session(tmp_path):
    from concurrent.futures.process import BrokenProcessPool
    context, request, _, _ = setup_formal_equity(tmp_path)
    request = context.evaluation.prepare(request)
    context.evaluation.resources = ExecutionResources(2)
    def cancel(_):
        raise KeyboardInterrupt("explicit cancellation")
    with ResearchExecutionSession(context, experiment=request.experiment, on_progress=cancel) as execution:
        with pytest.raises(KeyboardInterrupt, match="explicit cancellation"):
            context.evaluation.evaluate_many((request, request), execution=execution)
        assert execution.executor.broken
        assert all(not process.is_alive() for process in execution.executor.pool._processes.values())
        with pytest.raises(BrokenProcessPool):
            context.evaluation.evaluate_many((request,), execution=execution)
