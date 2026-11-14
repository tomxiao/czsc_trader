# Risk ownership: TDR-07 TDR-02
"""Current V4 batch outcomes keep order and report failures without retry."""
from concurrent.futures import CancelledError
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
from hashlib import sha256
from itertools import count
import os

import pytest
from strategy_runtime import ExecutionResources, StrategyPerformanceBudget, equity_source_hash
from equity_test_support import setup_account_research
from czsc_trader.research_tools import ResearchExecutionSession
from czsc_trader.research_tools.evaluation_access import EvaluationStatus


def terminated_worker(*args):
    os._exit(7)


def test_TDR_07_C01_v4_results_preserve_order_and_failed_accounts_are_not_retried(tmp_path, monkeypatch):
    from czsc_trader.research_tools import equity_replay
    context, request, _, _ = setup_account_research(tmp_path)
    context.evaluation.resources = ExecutionResources(1)
    original = equity_replay._compute_account
    calls = []
    def calculate(*args):
        cash = args[2].initial_cash
        calls.append(cash)
        if cash == 13:
            raise RuntimeError('synthetic account failure')
        if cash == 14:
            raise CancelledError('synthetic account cancellation')
        return original(*args)
    monkeypatch.setattr(equity_replay, '_compute_account', calculate)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        # Ordering is a host contract: force the executor boundary to deliver
        # actual computed results backwards. Process death is tested separately.
        actual_run = execution.executor.run
        completion_keys = []
        def reversed_completions(*args, **kwargs):
            completed = list(actual_run(*args, **kwargs))
            completion_keys.extend(item[0] for item in reversed(completed))
            yield from reversed(completed)
        monkeypatch.setattr(execution.executor, 'run', reversed_completions)
        prepared = tuple(context.evaluation.prepare(replace(request, initial_cash=cash), execution=execution)
            for cash in (100000, 200000))
        outcomes = context.evaluation.evaluate_many(prepared, execution=execution)
        assert completion_keys
        assert all(item.status is EvaluationStatus.SUCCEEDED for item in outcomes)
        assert [item.request_hash for item in outcomes] == [sha256(item.contract_content).hexdigest() for item in prepared]


def test_TDR_07_C03_v4_worker_loss_is_unknown_and_does_not_restart_pool(tmp_path, monkeypatch):
    from czsc_trader.research_tools import equity_replay
    context, request, _, _ = setup_account_research(tmp_path)
    context.evaluation.resources = ExecutionResources(2)
    monkeypatch.setattr(equity_replay, '_compute_transported_account', terminated_worker)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.status is EvaluationStatus.UNKNOWN and outcome.result is None
        assert execution.stats.pool_starts == 1
        with pytest.raises(BrokenProcessPool, match='explicit new session'):
            context.evaluation.evaluate_many((prepared,), execution=execution)
        assert execution.stats.pool_starts == 1


def test_TDR_07_runtime_input_rejection_preserves_spawn_pool(tmp_path):
    context, request, _, _ = setup_account_research(tmp_path)
    context.evaluation.resources = ExecutionResources(2)
    candidate = request.candidate
    path = candidate.source_root / 'strategy.py'
    path.write_text('def step(ctx, state):\n    return ctx.dfls.fetch(None)\n', encoding='utf-8')
    definition = replace(candidate.definition, source_sha256=equity_source_hash(candidate.source_root, ('strategy.py',)))
    request = replace(request, candidate=replace(candidate, definition=definition))
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.status is EvaluationStatus.FAILED
        assert 'strategy must request a declared input' in outcome.error.message
        assert execution.stats.unknown == 0
        assert not execution.executor.broken


@pytest.mark.parametrize('kwargs', [{'max_workers': 0}])
def test_TDR_02_C06_invalid_resources_reject_before_computation(kwargs):
    with pytest.raises(ValueError):
        ExecutionResources(**kwargs)


@pytest.mark.parametrize('call_limit, rate_limit, success', [(0.0001, 5, False), (0.5, 0.1, False), (0.5, 5, True)])
def test_TDR_07_strategy_budget_qualifies_first_account_before_batch(tmp_path, monkeypatch, call_limit, rate_limit, success):
    from strategy_runtime import strategy_performance

    clock = count(step=1_000_000)
    monkeypatch.setattr(strategy_performance, 'thread_time_ns', lambda: next(clock))
    context, request, _, _ = setup_account_research(tmp_path)
    context.evaluation.resources = ExecutionResources(1)
    neighbor = replace(request, candidate=replace(request.candidate, candidate_id='C0002'))
    budget = StrategyPerformanceBudget(max_call_seconds=call_limit, max_seconds_per_1000_calls=rate_limit)
    with ResearchExecutionSession(context, experiment=request.experiment, performance_budget=budget) as execution:
        handles = tuple(context.evaluation.prepare(item, execution=execution) for item in (request, neighbor))
        results = context.evaluation.evaluate_many(handles, execution=execution)
        assert 'PERFORMANCE' in dict(execution.stats.phase_wall_seconds)
        if not success:
            assert all(result.status is EvaluationStatus.FAILED for result in results)
            assert all(result.error.code == 'StrategyPerformanceExceeded' for result in results)
            assert 'pilot did not qualify' in results[1].error.message
            assert execution.stats.submitted == 1
            assert execution.equity_statistics.benchmark_runs == 0
            return
        assert all(result.status is EvaluationStatus.SUCCEEDED for result in results)
        assert execution.stats.submitted == 3
        assert execution.equity_statistics.candidate_runs == 2
        assert execution.equity_statistics.benchmark_runs == 1
        profiles = [item.strategy_performance for item in execution.equity_statistics.account_timings if item.kind == 'CANDIDATE']
        assert len(profiles) == 2
        assert all(0 < profile.prefix_calls < profile.calls for profile in profiles)






def test_TDR_07_C02_failed_account_not_retried(tmp_path, monkeypatch):
    from czsc_trader.research_tools import equity_replay
    context, request, _, _ = setup_account_research(tmp_path)
    context.evaluation.resources = ExecutionResources(1)
    original = equity_replay._compute_account
    calls = []
    def calculate(*args):
        cash = args[2].initial_cash
        calls.append(cash)
        if cash == 13:
            raise RuntimeError('synthetic account failure')
        if cash == 14:
            raise CancelledError('synthetic account cancellation')
        return original(*args)
    monkeypatch.setattr(equity_replay, '_compute_account', calculate)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(replace(request, initial_cash=13), execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.status is EvaluationStatus.FAILED and outcome.result is None
        assert calls == [13, 13]  # candidate and benchmark, each exactly once
