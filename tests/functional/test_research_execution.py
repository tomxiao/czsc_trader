"""Public execution sessions retain accounts, share workers and fail explicitly."""

from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace

import pytest
from strategy_runtime import ExecutionResources

from czsc_trader.application.evidence_service import publish_evidence_many
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evaluation_access import EvaluationStatus
from czsc_trader.research_tools.evidence import EvaluationEvidenceWrite, PublicationStatus
from czsc_trader.research_tools.execution import (
    ResearchExecutionSession, ExecutionCheckpointRequest, CheckpointMode, ExecutionPhase,
)
from czsc_trader.research_tools._execution_checkpoint import CheckpointIntegrityError
from test_evaluation_batch import terminated_worker
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


def _session(context, request, **kwargs):
    return ResearchExecutionSession(context, experiment=ExperimentRef("S900", request.experiment_id), **kwargs)


def test_shared_execution_pool_runs_calculate_publish_calculate(managed_evaluation):
    context, request = managed_evaluation
    context.evaluation.resources = ExecutionResources(2)
    requests = (context.evaluation.prepare(request),
                context.evaluation.prepare(replace(request, initial_cash=200_000)))
    progress = []
    with _session(context, request, on_progress=progress.append) as execution:
        outcomes = context.evaluation.evaluate_many(requests, execution=execution)
        assert all(item.status is EvaluationStatus.SUCCEEDED for item in outcomes)
        writes = tuple(EvaluationEvidenceWrite(execution.experiment, f"account-{i}", item, outcome.result)
                       for i, (item, outcome) in enumerate(zip(requests, outcomes, strict=True)))
        publications = publish_evidence_many(context, writes, execution=execution)
        assert all(item.status is PublicationStatus.PUBLISHED for item in publications)
        final = context.evaluation.evaluate_many((requests[0],), execution=execution)
        assert final[0].result.result_hash == outcomes[0].result.result_hash
        assert execution.stats.pool_starts == 1
        assert execution.stats.submitted == 5
        assert execution.stats.completed == 5
        assert execution.stats.failed == execution.stats.unknown == 0
        assert {item.phase for item in progress} == {
            ExecutionPhase.COMPUTE, ExecutionPhase.SERIALIZE, ExecutionPhase.PUBLISH}
        assert all(item.completed <= item.total for item in progress)
        process_handles = tuple(execution.executor.pool._processes.values())
    assert not any(process.is_alive() for process in process_handles)
    with pytest.raises(RuntimeError, match="context manager"):
        context.evaluation.evaluate_many(requests, execution=execution)


def test_resume_reuses_calculation_and_publication_then_rejects_corruption(managed_evaluation, monkeypatch):
    context, request = managed_evaluation
    context.evaluation.resources = ExecutionResources(2)
    prepared = context.evaluation.prepare(request)
    checkpoint = ExecutionCheckpointRequest("recovery")
    with _session(context, request, checkpoint=checkpoint) as execution:
        outcome = context.evaluation.evaluate_many((prepared,), execution=execution)[0]
        write = EvaluationEvidenceWrite(execution.experiment, "account", prepared, outcome.result)
        reference = publish_evidence_many(context, (write,), execution=execution)[0].reference
        cache = execution.checkpoint.root

    def unexpected(*args, **kwargs):
        raise AssertionError("restored successful work must not execute again")

    from czsc_trader.research_tools import evaluation_access
    from czsc_trader.application import evidence_service
    monkeypatch.setattr(evaluation_access, "compute", unexpected)
    monkeypatch.setattr(evidence_service, "_serialize_worker", unexpected)
    resume = ExecutionCheckpointRequest("recovery", CheckpointMode.RESUME)
    with _session(context, request, checkpoint=resume) as execution:
        outcomes = context.evaluation.evaluate_many((prepared, prepared), execution=execution)
        assert all(item.status is EvaluationStatus.SUCCEEDED for item in outcomes)
        restored_write = replace(write, result=outcomes[0].result)
        publication = publish_evidence_many(context, (restored_write,), execution=execution)[0]
        assert publication.reference == reference
        assert execution.stats.submitted == 0
        assert execution.stats.pool_starts == 0
        assert execution.stats.reused_results == 2
        assert execution.stats.reused_publications == 1

    record = cache / "results" / f"{outcome.request_hash}.json"
    record.write_text("interrupted or corrupted", encoding="utf-8")
    with _session(context, request, checkpoint=resume) as execution:
        with pytest.raises(CheckpointIntegrityError, match="authenticate"):
            context.evaluation.evaluate_many((prepared,), execution=execution)
        assert execution.stats.submitted == 0
    source = prepared.strategy.source_root / prepared.runtime_binding["source_files"][0]
    source.write_bytes(source.read_bytes() + b"\n# changed after checkpoint\n")
    with _session(context, request, checkpoint=resume) as execution:
        with pytest.raises(ValueError, match="source closure"):
            context.evaluation.evaluate_many((prepared,), execution=execution)
        assert execution.stats.submitted == 0


def test_broken_pool_is_not_replaced_or_retried_implicitly(managed_evaluation):
    context, request = managed_evaluation
    context.evaluation.resources = ExecutionResources(2)
    context.evaluation._batch_evaluator = terminated_worker
    with _session(context, request) as execution:
        outcomes = context.evaluation.evaluate_many((request, request), execution=execution)
        assert all(item.status is EvaluationStatus.UNKNOWN for item in outcomes)
        assert execution.stats.pool_starts == 1
        assert execution.stats.submitted == 2
        with pytest.raises(BrokenProcessPool, match="explicit new session"):
            context.evaluation.evaluate_many((request,), execution=execution)
        assert execution.stats.pool_starts == 1


def test_session_identity_reuse_and_nested_active_calls_are_rejected(managed_evaluation):
    context, request = managed_evaluation
    context.evaluation.resources = ExecutionResources(1)
    errors = []
    def progress(_):
        with pytest.raises(RuntimeError, match="active operation") as failure:
            context.evaluation.evaluate_many((request,), execution=execution)
        errors.append(failure.value)

    execution = _session(context, request, on_progress=progress)
    with execution:
        with pytest.raises(RuntimeError, match="reopened"):
            execution.__enter__()
        with pytest.raises(RuntimeError, match="active execution session"):
            _session(context, request).__enter__()
        outcome = context.evaluation.evaluate_many((request,), execution=execution)[0]
        assert outcome.status is EvaluationStatus.SUCCEEDED
        assert errors
        with pytest.raises(ValueError, match="another experiment"):
            context.evaluation.evaluate_many((replace(request, experiment_id="EX002_20261022"),), execution=execution)
    with pytest.raises(RuntimeError, match="reopened"):
        execution.__enter__()


def test_checkpoint_save_failure_requires_explicit_new_session(managed_evaluation, monkeypatch):
    context, request = managed_evaluation
    context.evaluation.resources = ExecutionResources(2)
    with _session(context, request, checkpoint=ExecutionCheckpointRequest("disk-failure")) as execution:
        def fail_save(*_):
            raise OSError("injected checkpoint write failure")
        monkeypatch.setattr(execution.checkpoint, "save_result", fail_save)
        with pytest.raises(OSError, match="checkpoint write failure"):
            context.evaluation.evaluate_many((request, request), execution=execution)
        with pytest.raises(BrokenProcessPool, match="explicit new session"):
            context.evaluation.evaluate_many((request,), execution=execution)
        assert execution.stats.pool_starts == 1


def test_duplicate_concurrent_results_share_one_semantic_checkpoint(managed_evaluation):
    context, request = managed_evaluation
    context.evaluation.resources = ExecutionResources(2)
    with _session(context, request, checkpoint=ExecutionCheckpointRequest("duplicates")) as execution:
        outcomes = context.evaluation.evaluate_many((request, request), execution=execution)
        assert all(item.status is EvaluationStatus.SUCCEEDED for item in outcomes)
        assert outcomes[0].result.result_hash == outcomes[1].result.result_hash
        assert len(tuple((execution.checkpoint.root / "results").glob("*.json"))) == 1
        restored = context.evaluation.evaluate_many((request,), execution=execution)[0]
        assert restored.status is EvaluationStatus.SUCCEEDED
        assert restored.result.result_hash == outcomes[0].result.result_hash


@pytest.mark.parametrize("run_id", [None, 1, "", "../escape", "a/b", "a.b", " x", "a" * 81])
def test_execution_checkpoint_run_id_requires_safe_typed_identifier(run_id):
    with pytest.raises(ValueError, match="run_id"):
        ExecutionCheckpointRequest(run_id)


def test_execution_checkpoint_mode_requires_enum():
    with pytest.raises(TypeError, match="CheckpointMode"):
        ExecutionCheckpointRequest("run", "RESUME")
