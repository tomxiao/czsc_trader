"""Real Windows/spawn computation, parent-owned evidence and failure boundaries."""

from dataclasses import replace
from datetime import date
import json
import os
import time

import pandas as pd
import pytest
from dataflows import Dataset
from research_experiment import EvaluationAttemptStatus, EvaluationOutcome, ExperimentResources
from czsc_trader.research_tools import EvaluationExecutionError
from czsc_trader.research_tools.evaluation import evaluate_strategy
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


def synthetic_provider(request):
    dates = pd.bdate_range("2026-09-14", periods=6)
    dataset = str(request.dataset)
    metadata = {"vendor": "test"}
    if dataset == Dataset.TRADING_CALENDAR.value:
        dates = pd.date_range(request.start, request.end)
        return pd.DataFrame({"Date": dates, "IsOpen": (dates.weekday < 5).astype(int)}), metadata
    if dataset == "etf.share":
        frame = pd.DataFrame({"Date": dates, "Flow": [0.1, 0.8, 0.8, 0.1, 0., 0.]})
    elif dataset == Dataset.ETF_SHARE_SIZE.value:
        frame = pd.DataFrame({"Date": dates, "TotalShare": range(1, 7)})
        metadata["vendor_symbol"] = request.symbol
    else:
        frame = pd.DataFrame({"Date": dates, "Open": 1., "Close": 1., "High": 1.,
                              "Low": 1., "Volume": 1000., "Amount": 1000.})
        if dataset == Dataset.ETF_UNADJUSTED_DAILY.value:
            metadata["adjustment"] = "none"
    return frame.loc[frame.Date.between(pd.Timestamp(request.start), pd.Timestamp(request.end))].reset_index(drop=True), metadata


def synthetic_evaluator(request):
    # Expose actual process participation independently of platform result fields.
    (request.repository_root / ".tmp" / f"worker-{os.getpid()}").touch()
    time.sleep(.2)
    if request.initial_cash == 13:
        raise RuntimeError("synthetic computation failure")
    assert set(request.input_bindings) == {item.window_id for item in request.windows}
    return evaluate_strategy(request)


def terminated_worker(request):
    os._exit(7)


@pytest.fixture
def batch(managed_evaluation):
    context, request = managed_evaluation
    context.resources = context.evaluation._resources = ExperimentResources(2, 1)
    context.evaluation._batch_evaluator = synthetic_evaluator
    return context, request


def test_batch_multicore_failure_retry_and_order(batch):
    context, request = batch
    requests = (request, replace(request, initial_cash=13), replace(request, initial_cash=200_000), request)
    outcomes = context.evaluation.evaluate_many(requests)
    assert [x.record.status for x in outcomes] == [EvaluationAttemptStatus.SUCCEEDED,
        EvaluationAttemptStatus.FAILED, EvaluationAttemptStatus.SUCCEEDED, EvaluationAttemptStatus.SUCCEEDED]
    assert outcomes[1].result is None
    assert outcomes[1].record.error_code == "RuntimeError"
    assert len({x.record.attempt_id for x in outcomes}) == 4
    assert len(list((request.repository_root / ".tmp").glob("worker-*"))) == 2
    assert not (request.repository_root / "research/registrations").exists()
    for item in outcomes:
        saved = context.workspace.path(f"evaluations/{item.record.attempt_id}/record.json")
        assert json.loads(saved.read_text())["status"] == item.record.status.value
        if item.result is not None:
            context.workspace.validate_artifact(item.record.result_artifact)
            assert item.result.attempt_id == item.record.attempt_id
    again = context.evaluation.evaluate_many((request,))[0]
    assert again.record.attempt_id not in {x.record.attempt_id for x in outcomes}
    assert again.result.result_hash == outcomes[0].result.result_hash
    assert len(context.trace.evaluations) == 5
    # Successful workers release calculation scratch; the failed attempt keeps
    # one workspace for diagnosis, independently of the shared DFLS assets.
    assert len(list((request.repository_root / ".tmp/evaluation-workers").iterdir())) == 1
    with pytest.raises(ValueError, match="successful outcome"):
        EvaluationOutcome(outcomes[0].record, None)
    with pytest.raises(ValueError, match="successful outcome"):
        EvaluationOutcome(outcomes[1].record, outcomes[0].result)


@pytest.mark.parametrize("change", [{"workers": 2}, {"data_cutoff": date(2026, 9, 1)}])
def test_batch_prevalidates_all_before_execution(batch, change):
    context, request = batch
    with pytest.raises(ValueError):
        context.evaluation.evaluate_many((request, replace(request, **change)))
    assert not context.trace.evaluations
    assert not list((request.repository_root / ".tmp").glob("worker-*"))


def test_batch_transport_is_preflighted(batch):
    context, request = batch
    context.evaluation._batch_evaluator = lambda request: None
    with pytest.raises((AttributeError, TypeError)):
        context.evaluation.evaluate_many((request,))
    assert not context.trace.evaluations


def test_batch_evidence_write_failure_raises(batch, monkeypatch):
    from czsc_trader.research_tools._evaluation_records import _CallEvidence
    context, request = batch
    def fail(*args):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr(_CallEvidence, "result", fail)
    with pytest.raises(EvaluationExecutionError) as error:
        context.evaluation.evaluate_many((request, request))
    assert error.value.error_code == "EVIDENCE_WRITE_FAILED"
    assert all(x.status is not EvaluationAttemptStatus.SUCCEEDED for x in context.trace.evaluations)
    assert all(x.status is not EvaluationAttemptStatus.STARTED for x in context.trace.evaluations)


def test_batch_context_owner_and_completed_guards(batch):
    context, request = batch
    context.evaluation._owner_pid = -1
    with pytest.raises(RuntimeError, match="another process"):
        context.evaluation.evaluate_many((request,))
    context.evaluation._owner_pid = os.getpid()
    context.workspace.path("execution_receipt.json").write_text("{}")
    with pytest.raises(RuntimeError, match="complete"):
        context.evaluation.evaluate_many((request,))


def test_default_formal_evaluator_transport(batch):
    from czsc_trader.research_tools._evaluation_workers import PlatformEvaluator, pack
    context, request = batch
    assert pack((PlatformEvaluator(request.repository_root), request, 1))
    assert pack(evaluate_strategy)


def test_platform_worker_rejects_missing_parent_preparation(batch):
    from czsc_trader.research_tools._evaluation_workers import PlatformEvaluator
    _, request = batch
    evaluator = PlatformEvaluator(request.repository_root)
    with pytest.raises(ValueError, match="parent-prepared"):
        evaluator(request)


def test_dead_worker_is_unknown_and_never_success(batch):
    context, request = batch
    context.evaluation._batch_evaluator = terminated_worker
    outcomes = context.evaluation.evaluate_many((request, request))
    assert all(x.record.status is EvaluationAttemptStatus.UNKNOWN for x in outcomes)
    assert all(x.result is None and x.record.completed_count is None for x in outcomes)
