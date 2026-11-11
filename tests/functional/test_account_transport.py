"""TDR-16: bounded shared transport keeps accounts independent and reclaimable."""
from dataclasses import replace
from multiprocessing.shared_memory import SharedMemory

import pytest

from czsc_trader.research_tools._account_transport import AccountInputStore, read_account_input
from czsc_trader.research_tools._cpu_affinity import _select_slots, replay_resources
from czsc_trader.research_tools import ResearchExecutionSession
from strategy_runtime import ExecutionResources
from equity_test_support import setup_account_research


def test_TDR_16_transport_reuses_binary_inputs_and_releases_blocks():
    store = AccountInputStore()
    try:
        reference = store.put(('same-input',), ((1., 2.), {'time': '2026-01-01'}))
        assert store.put(('same-input',), None) == reference
        assert read_account_input(reference) == ((1., 2.), {'time': '2026-01-01'})
        assert read_account_input(reference) is read_account_input(reference)
        store.retain(())
        with pytest.raises(FileNotFoundError):
            SharedMemory(name=reference.name)
    finally:
        store.close()
    with pytest.raises(RuntimeError, match='closed'):
        store.put(('later',), ())


def test_TDR_16_transport_rejects_corrupt_input_before_decode():
    store = AccountInputStore()
    try:
        reference = store.put(('corrupt-input',), (1, 2, 3))
        block = SharedMemory(name=reference.name)
        try:
            block.buf[0] ^= 1
        finally:
            block.close()
        with pytest.raises(ValueError, match='digest differs'):
            read_account_input(reference)
    finally:
        store.close()


def test_TDR_16_transport_is_bounded():
    store = AccountInputStore()
    try:
        for index in range(8):
            store.put(index, (index,))
        with pytest.raises(ValueError, match='capacity'):
            store.put(8, (8,))
        with pytest.raises(ValueError, match='eight'):
            store.retain(tuple(range(9)))
        store.retain((7,))
        assert len(store.blocks) == 1
    finally:
        store.close()


def test_TDR_16_shared_workers_match_serial_and_reuse_across_batches(tmp_path):
    context, request, _, _ = setup_account_research(tmp_path)
    requests = tuple(replace(request, candidate=replace(request.candidate, candidate_id=f'C{i:04}'))
                     for i in range(1, 5))
    context.evaluation.resources = ExecutionResources(1, 1, 19)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        handles = tuple(context.evaluation.prepare(x, execution=execution) for x in requests)
        expected = context.evaluation.evaluate_many(handles, execution=execution)
    context.evaluation.resources = None
    budget, slots = replay_resources(None)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        handles = tuple(context.evaluation.prepare(x, execution=execution) for x in requests)
        first = context.evaluation.evaluate_many(handles[:2], execution=execution)
        store = execution.executor.account_inputs
        first_refs = {value[1] for value in store.blocks.values()}
        second = context.evaluation.evaluate_many(handles[2:], execution=execution)
        assert {value[1] for value in store.blocks.values()} == first_refs
        assert execution.equity_statistics.benchmark_runs == 1
        stats = execution.stats
        assert stats.pool_starts == 1
        assert stats.worker_limit == budget.max_workers == len(slots)
        assert stats.native_threads_per_worker == 1
        assert stats.peak_in_flight == min(3, len(slots))
        assert 1 <= len(stats.worker_bindings) <= min(len(slots), stats.submitted)
        assert len({pid for pid, _ in stats.worker_bindings}) == len(stats.worker_bindings)
        assert len({cpu for _, cpu in stats.worker_bindings}.intersection(slots)) == len(stats.worker_bindings)
        for before, after in zip(expected, first + second, strict=True):
            assert before.result is not None, before.error
            assert after.result is not None, after.error
            assert after.result.content == before.result.content
            assert after.result.artifacts == before.result.artifacts
    for reference in first_refs:
        with pytest.raises(FileNotFoundError):
            SharedMemory(name=reference.name)


def test_TDR_16_core_selection_respects_process_mask_and_rejects_incomplete_topology():
    allowed = {1, 2, 3, 7}
    groups = ((0, 1), (2, 3), (4, 5), (6, 7))
    assert _select_slots(allowed, groups) == (1, 2, 7)
    with pytest.raises(RuntimeError, match='does not cover'):
        _select_slots(allowed, groups[:-1])
    with pytest.raises(RuntimeError, match='overlapping'):
        _select_slots(allowed, groups + ((1, 8),))
    with pytest.raises(ValueError, match='one native thread'):
        replay_resources(ExecutionResources(1, 2))


def test_TDR_16_binding_failure_prevents_account_computation(monkeypatch):
    from czsc_trader.research_tools import _execution_session as executor
    from threading import Lock

    def fail_binding(_):
        raise OSError('synthetic affinity failure')

    monkeypatch.setattr(executor, 'bind_worker', fail_binding)
    monkeypatch.setattr(executor, '_worker_binding_error', None)
    pids = [0]
    executor._initialize_replay_worker((7,), pids, Lock())
    assert pids == [-1]
    with pytest.raises(RuntimeError, match='logical CPU 7: synthetic affinity failure'):
        executor._timed_task(pytest.fail, ('unbound task executed',), 1)


def test_TDR_16_cancelled_shared_workers_release_blocks(tmp_path):
    context, request, _, _ = setup_account_research(tmp_path)
    context.evaluation.resources = ExecutionResources(2, 1, 19)
    references = []

    def cancel(_):
        references.extend(item[1] for item in execution.executor.account_inputs.blocks.values())
        raise KeyboardInterrupt('cancel shared accounts')

    with pytest.raises(KeyboardInterrupt, match='cancel shared accounts'):
        with ResearchExecutionSession(context, experiment=request.experiment, on_progress=cancel) as execution:
            handles = tuple(context.evaluation.prepare(replace(request,
                candidate=replace(request.candidate, candidate_id=f'C{i:04}')), execution=execution)
                for i in (1, 2))
            context.evaluation.evaluate_many(handles, execution=execution)
    assert references
    assert execution.executor.account_inputs.closed and execution.executor.closed
    for reference in references:
        with pytest.raises(FileNotFoundError):
            SharedMemory(name=reference.name)
