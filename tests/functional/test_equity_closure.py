"""Distinct equity semantics alongside the common account lifecycle."""
from equity_test_support import setup_formal_equity, current_account_request, account_research, replay_payload
from dataclasses import replace
import json

import pytest
from strategy_runtime import ExecutionResources
from strategy_runtime.equity_definition import equity_source_hash
from czsc_trader.application import publish_evidence_many
from czsc_trader.research_tools import (EvaluationBenchmark, EvaluationEvidenceWrite,
                                      ResearchExecutionSession, ExecutionCheckpointRequest, CheckpointMode)


def publish_account(context, prepared, result, execution, name):
    outcome, = publish_evidence_many(context, (EvaluationEvidenceWrite(prepared.experiment, name, prepared, result),), execution=execution)
    assert outcome.status.value == "PUBLISHED", outcome.error
    return outcome.reference


def terminate_equity_worker(*args):
    import os
    os._exit(7)


def test_equity_formal_requires_explicit_semantics_and_rejects_tampered_results(tmp_path):
    context, request, _, _ = setup_formal_equity(tmp_path)
    request = current_account_request(context,request)
    with pytest.raises(ValueError, match="explicit drawdown"):
        replace(request, drawdown_basis=None)
    with account_research(context, request) as (_, result, _, _):
        pass
    from czsc_trader.research_tools.equity_evaluation import EquityArtifact, EquityEvaluationResult
    from czsc_trader.research_tools.equity_replay import build_equity_assessment
    envelope=result.payload
    artifacts=list(result.artifacts)
    index=next(i for i,item in enumerate(artifacts) if item.sha256==envelope['candidate_ref']['sha256'])
    value=json.loads(artifacts[index].content)
    value['run']['account_points'][2]['receivable']+=1
    artifacts[index]=EquityArtifact(artifacts[index].kind,json.dumps(value,sort_keys=True,separators=(',',':')).encode())
    envelope['candidate_ref']['sha256']=artifacts[index].sha256
    altered=EquityEvaluationResult(result.request_hash,json.dumps(envelope,sort_keys=True,separators=(',',':')).encode(),tuple(artifacts))
    with pytest.raises(ValueError,match='receivable'):
        build_equity_assessment(altered)
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
    with account_research(context, request) as (prepared, result, payload, execution):
        reference = publish_account(context, prepared, result, execution, "diagnosis")
        raw = dict(payload["evaluation_identity"])
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
    with account_research(context, request) as (prepared, result, payload, execution):
        ref = publish_account(context, prepared, result, execution, "events")
        identity = dict(payload["evaluation_identity"])
        identity["candidate"] = CandidateKey(**identity["candidate"])
        diagnosis = diagnose_accounts(context.repository, AccountDiagnosisRequest(
            AccountRunRef(ref, EvaluationIdentity(**identity)), None,
            EvaluationWindow("events", date(2026,10,1), date(2026,10,2))))
        assert diagnosis.status == "COMPUTED", diagnosis.issues
        assert all(abs(row.residual) < 1e-7 for row in diagnosis.pnl_breakdown[0].daily)
        assert payload["runs"]["candidate"]["account_points"][-1]["equity"] == pytest.approx(1018.62)


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
    payload = replay_payload(context, request)
    # Floor is applied after converting the visible reference to post-split units.
    # Rounding a pre-split order and then multiplying would incorrectly buy 196.
    for run in payload["runs"].values():
        assert run["fills"][0]["quantity"] == 197
        assert run["decisions"][0]["reference_price"] == 5.
        assert run["decisions"][0]["limit_price"] == 5.05


def test_equity_checkpoint_corruption_and_source_drift_fail_explicitly(tmp_path):
    from czsc_trader.research_tools._execution_checkpoint import CheckpointIntegrityError
    context, request, _, _ = setup_formal_equity(tmp_path)
    request = current_account_request(context, request)
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest("integrity")) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome = context.evaluation.evaluate_many((prepared,), execution=execution)[0]
        assert outcome.status.value == "SUCCEEDED"
        record = execution.checkpoint.root / "results" / f"{outcome.request_hash}.json"
    record.write_text("corrupted checkpoint", encoding="utf-8")
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest("integrity", CheckpointMode.RESUME)) as execution:
        with pytest.raises(CheckpointIntegrityError):
            prepared = context.evaluation.prepare(request, execution=execution)
            context.evaluation.evaluate_many((prepared,), execution=execution)
        assert execution.stats.submitted == 0
    source = request.candidate.source_root / "strategy.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# changed source\n", encoding="utf-8")
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        with pytest.raises(ValueError, match="hash|source"):
            context.evaluation.prepare(request, execution=execution)


def test_equity_worker_death_is_unknown_and_does_not_restart_pool(tmp_path, monkeypatch):
    from concurrent.futures.process import BrokenProcessPool
    from czsc_trader.research_tools import equity_replay
    context, request, _, _ = setup_formal_equity(tmp_path)
    request = current_account_request(context, request)
    context.evaluation.resources = ExecutionResources(2)
    monkeypatch.setattr(equity_replay, "_compute_account", terminate_equity_worker)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcomes = context.evaluation.evaluate_many((prepared, prepared), execution=execution)
        # First candidate and shared benchmark were submitted; the second
        # candidate is explicitly cancelled before submission after pool death.
        assert [x.status.value for x in outcomes] == ["UNKNOWN", "CANCELLED"]
        assert execution.stats.pool_starts == 1
        with pytest.raises(BrokenProcessPool):
            prepared = context.evaluation.prepare(request, execution=execution)
            context.evaluation.evaluate_many((prepared,), execution=execution)
        assert execution.stats.submitted == 2


def test_equity_cancelled_progress_terminates_workers_and_requires_new_session(tmp_path):
    from concurrent.futures.process import BrokenProcessPool
    context, request, _, _ = setup_formal_equity(tmp_path)
    request = current_account_request(context, request)
    context.evaluation.resources = ExecutionResources(2)
    def cancel(_):
        raise KeyboardInterrupt("explicit cancellation")
    with ResearchExecutionSession(context, experiment=request.experiment, on_progress=cancel) as execution:
        with pytest.raises(KeyboardInterrupt, match="explicit cancellation"):
            prepared = context.evaluation.prepare(request, execution=execution)
            context.evaluation.evaluate_many((prepared, prepared), execution=execution)
        assert execution.executor.broken
        assert all(not process.is_alive() for process in execution.executor.pool._processes.values())
        with pytest.raises(BrokenProcessPool):
            prepared = context.evaluation.prepare(request, execution=execution)
            context.evaluation.evaluate_many((prepared,), execution=execution)
