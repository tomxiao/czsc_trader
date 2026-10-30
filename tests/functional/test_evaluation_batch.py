"""Parallel account evaluation exposes results and errors without process persistence."""
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass, replace
from pathlib import Path
import os
import time

import pytest
from dataflows import Dataflows, DataSpace, ProviderConfig
from czsc_trader.research_tools.evaluation import _evaluate_strategy
from strategy_runtime import ExecutionResources
from czsc_trader.research_tools.evaluation_access import (
    EvaluationAccess, EvaluationOutcome, EvaluationStatus,
)
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
from czsc_trader.research_tools import ResearchExecutionSession, ExperimentRef


def session(context, request, access):
    return ResearchExecutionSession(replace(context, evaluation=access),
        experiment=ExperimentRef("S900", request.experiment_id))


@dataclass(frozen=True)
class SyntheticEvaluator:
    base_dir: Path
    space: DataSpace

    def __call__(self, request):
        (self.base_dir / ".tmp").mkdir(exist_ok=True)
        (self.base_dir / ".tmp" / f"worker-{os.getpid()}").touch()
        time.sleep(.1)
        if request.initial_cash == 13:
            raise RuntimeError("synthetic computation failure")
        if request.initial_cash == 14:
            raise CancelledError("caller cancelled")
        return _evaluate_strategy(request, dataflows=Dataflows(
            base_dir=self.base_dir, space=self.space, providers=ProviderConfig(bindings={})))


def terminated_worker(request):
    os._exit(7)


def test_parallel_results_preserve_order_and_failure_is_not_retried(managed_evaluation):
    context, request = managed_evaluation
    access = EvaluationAccess(dataflows=context.data, resources=ExecutionResources(2, 1), strategy_id="S900")
    access._batch_evaluator = SyntheticEvaluator(context.repository.root, DataSpace(Path("research/S900/assets/data")))
    with session(context, request, access) as execution:
        prepared = tuple(access.prepare(item, execution=execution) for item in
            (request, replace(request, initial_cash=13), replace(request, initial_cash=200_000), request))
        outcomes = access.evaluate_many(prepared, execution=execution)
    assert [x.status for x in outcomes] == [EvaluationStatus.SUCCEEDED, EvaluationStatus.FAILED,
                                           EvaluationStatus.SUCCEEDED, EvaluationStatus.SUCCEEDED]
    assert outcomes[1].error.code == "RuntimeError"
    assert outcomes[1].result is None
    assert outcomes[0].result.result_hash == outcomes[3].result.result_hash
    assert len(list((context.repository.root / ".tmp").glob("worker-*"))) == 2
    assert not list(context.repository.root.rglob("record.json"))
    assert not (context.repository.root / ".tmp/evaluation-workers").exists()
    assert not (context.repository.root / "data/backtest").exists()


def test_cancellation_and_worker_loss_return_truthful_status(managed_evaluation):
    context, request = managed_evaluation
    access = context.evaluation
    access._batch_evaluator = SyntheticEvaluator(context.repository.root, DataSpace(Path("research/S900/assets/data")))
    with session(context, request, access) as execution:
        prepared = access.prepare(replace(request, initial_cash=14), execution=execution)
        cancelled = access.evaluate_many((prepared,), execution=execution)[0]
    assert cancelled.status is EvaluationStatus.CANCELLED and cancelled.result is None
    broken = EvaluationAccess(dataflows=context.data, resources=ExecutionResources(2), strategy_id="S900")
    broken._batch_evaluator = terminated_worker
    with session(context, request, broken) as execution:
        prepared = broken.prepare(request, execution=execution)
        outcomes = broken.evaluate_many((prepared, prepared), execution=execution)
    assert all(x.status is EvaluationStatus.UNKNOWN and x.result is None for x in outcomes)


def test_invalid_outcome_and_request_resource_configuration_are_rejected(managed_evaluation):
    context, request = managed_evaluation
    result = context.evaluation.evaluate(request)
    with pytest.raises(ValueError, match="successful outcome"):
        EvaluationOutcome(EvaluationStatus.SUCCEEDED, result.request_hash)
    with pytest.raises(TypeError, match="workers"):
        replace(request, workers=2)
    with pytest.raises(ValueError, match="request identities differ"):
        EvaluationOutcome(EvaluationStatus.SUCCEEDED, "f" * 64, result)


@pytest.mark.parametrize("kwargs", [{"max_workers": 0}, {"native_threads_per_worker": True}, {"random_seed": -1}])
def test_invalid_resources_reject_before_computation(kwargs):
    with pytest.raises(ValueError):
        ExecutionResources(**kwargs)


def test_failed_explicit_preparation_does_not_prevent_prepared_account_evaluation(managed_evaluation):
    context, request = managed_evaluation
    access = context.evaluation
    with session(context, request, access) as execution:
        bound = access.prepare(request, execution=execution)
        read_only = Dataflows(base_dir=context.repository.root, space=context.data.binding.space,
                             providers=ProviderConfig(bindings={}))
        missing = replace(request, symbol="518850.SH", execution_data=None, input_bindings={})
        access.data = read_only
        with pytest.raises(ValueError):
            access.prepare(missing, execution=execution)
        outcome, = access.evaluate_many((bound,), execution=execution)
        assert outcome.status is EvaluationStatus.SUCCEEDED


def test_batch_evaluates_only_explicit_prepared_accounts_without_repreparation(managed_evaluation, monkeypatch):
    from czsc_trader.research_tools import _execution_session as module

    context, request = managed_evaluation
    result = context.evaluation.evaluate(request)
    access = EvaluationAccess(dataflows=context.data, resources=ExecutionResources(2), strategy_id="S900")
    events = []

    def forbidden(*args, **kwargs):
        pytest.fail("evaluate_many must not prepare inputs implicitly")

    class InlinePool:
        def __init__(self, **kwargs):
            assert kwargs["max_workers"] == 2

        def shutdown(self, **kwargs):
            pass

        def submit(self, operation, worker, args, native_threads):
            from czsc_trader.research_tools._evaluation_workers import pack

            events.append("submit")
            future = Future()
            future.set_result((pack(result), 0.0))
            return future

    monkeypatch.setattr(module, "ProcessPoolExecutor", InlinePool)
    with session(context, request, access) as execution:
        bound = access.prepare(request, execution=execution)
        monkeypatch.setattr(access, "prepare", forbidden)
        outcomes = access.evaluate_many((bound, bound), execution=execution)
    assert events == ["submit", "submit"]
    assert all(x.status is EvaluationStatus.SUCCEEDED for x in outcomes)
