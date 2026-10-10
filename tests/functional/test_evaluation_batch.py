"""Parallel account evaluation exposes results and errors without process persistence."""
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass, replace
from pathlib import Path
import os
import time

import pytest
from dataflows import Dataflows, DataSpace, ProviderConfig
from czsc_trader.research_tools.evaluation import _evaluate_strategy
from czsc_trader.research_tools.evaluation_access import (
    EvaluationAccess, EvaluationResources, EvaluationOutcome, EvaluationStatus,
)
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


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
    access = EvaluationAccess(dataflows=context.data, resources=EvaluationResources(2, 1), strategy_id="S900")
    access._batch_evaluator = SyntheticEvaluator(context.repository.root, DataSpace(Path("research/S900/assets/data")))
    outcomes = access.evaluate_many((request, replace(request, initial_cash=13),
                                     replace(request, initial_cash=200_000), request))
    assert [x.status for x in outcomes] == [EvaluationStatus.SUCCEEDED, EvaluationStatus.FAILED,
                                           EvaluationStatus.SUCCEEDED, EvaluationStatus.SUCCEEDED]
    assert outcomes[1].error.code == "RuntimeError"
    assert outcomes[1].result is None
    assert outcomes[0].result.result_hash == outcomes[3].result.result_hash
    assert len(list((context.repository.root / ".tmp").glob("worker-*"))) == 2
    assert not list(context.repository.root.rglob("record.json"))
    assert not list((context.repository.root / ".tmp/evaluation-workers").iterdir())
    assert not (context.repository.root / "data/backtest").exists()


def test_cancellation_and_worker_loss_return_truthful_status(managed_evaluation):
    context, request = managed_evaluation
    access = context.evaluation
    access._batch_evaluator = SyntheticEvaluator(context.repository.root, DataSpace(Path("research/S900/assets/data")))
    cancelled = access.evaluate_many((replace(request, initial_cash=14),))[0]
    assert cancelled.status is EvaluationStatus.CANCELLED and cancelled.result is None
    broken = EvaluationAccess(dataflows=context.data, resources=EvaluationResources(2))
    broken._batch_evaluator = terminated_worker
    outcomes = broken.evaluate_many((request, request))
    assert all(x.status is EvaluationStatus.UNKNOWN and x.result is None for x in outcomes)


def test_invalid_outcome_and_nested_parallelism_are_rejected(managed_evaluation):
    context, request = managed_evaluation
    result = context.evaluation.evaluate(request)
    with pytest.raises(ValueError, match="successful outcome"):
        EvaluationOutcome(EvaluationStatus.SUCCEEDED, result.request_hash)
    with pytest.raises(ValueError, match="workers=1"):
        context.evaluation.evaluate_many((replace(request, workers=2),))
    with pytest.raises(ValueError, match="request identities differ"):
        EvaluationOutcome(EvaluationStatus.SUCCEEDED, "f" * 64, result)


@pytest.mark.parametrize("kwargs", [{"max_workers": 0}, {"native_threads_per_worker": True}, {"random_seed": -1}])
def test_invalid_resources_reject_before_computation(kwargs):
    with pytest.raises(ValueError):
        EvaluationResources(**kwargs)


def test_batch_data_preparation_failure_is_returned_for_only_the_failed_item(managed_evaluation):
    context, request = managed_evaluation
    bound = context.evaluation.prepare(request)
    read_only = Dataflows(base_dir=context.repository.root, space=context.data.binding.space,
                         providers=ProviderConfig(bindings={}))
    access = EvaluationAccess(dataflows=read_only, strategy_id="S900")
    missing = replace(request, symbol="518850.SH", execution_data=None, input_bindings={})
    outcomes = access.evaluate_many((bound, missing))
    assert outcomes[0].status is EvaluationStatus.SUCCEEDED
    assert outcomes[1].status is EvaluationStatus.FAILED and outcomes[1].result is None
    assert outcomes[1].error.code


def test_batch_submits_prepared_account_before_preparing_the_next(managed_evaluation, monkeypatch):
    from czsc_trader.research_tools import evaluation_access as module

    context, request = managed_evaluation
    bound = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(bound)
    access = EvaluationAccess(dataflows=context.data, resources=EvaluationResources(2), strategy_id="S900")
    events = []

    def prepare(item):
        events.append("prepare")
        if len(events) == 3:
            assert events == ["prepare", "submit", "prepare"]
        return item

    class InlinePool:
        def __init__(self, **kwargs):
            assert kwargs["max_workers"] == 2

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, operation, payload):
            from czsc_trader.research_tools._evaluation_workers import pack

            events.append("submit")
            future = Future()
            future.set_result(pack(result))
            return future

    monkeypatch.setattr(access, "prepare", prepare)
    monkeypatch.setattr(module, "ProcessPoolExecutor", InlinePool)
    outcomes = access.evaluate_many((bound, bound))
    assert events == ["prepare", "submit", "prepare", "submit"]
    assert all(x.status is EvaluationStatus.SUCCEEDED for x in outcomes)
