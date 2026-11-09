# Risk ownership: TDR-07 TDR-02
"""Current V4 batch outcomes keep order and report failures without retry."""
from concurrent.futures import CancelledError
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
from hashlib import sha256
import os

import pytest
from strategy_runtime import ExecutionResources
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
    monkeypatch.setattr(equity_replay, '_compute_account', terminated_worker)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.status is EvaluationStatus.UNKNOWN and outcome.result is None
        assert execution.stats.pool_starts == 1
        with pytest.raises(BrokenProcessPool, match='explicit new session'):
            context.evaluation.evaluate_many((prepared,), execution=execution)
        assert execution.stats.pool_starts == 1


@pytest.mark.parametrize('kwargs', [{'max_workers': 0}])
def test_TDR_02_C06_invalid_resources_reject_before_computation(kwargs):
    with pytest.raises(ValueError):
        ExecutionResources(**kwargs)






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
