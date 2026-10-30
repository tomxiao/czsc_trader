"""Account calculation shares only exact benchmark contracts and detached facts."""
from dataclasses import replace

from czsc_trader.backtesting.benchmarks import BenchmarkReplayScope
from czsc_trader.research_tools.evaluation import _evaluate_strategy, EvaluationCost
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


def test_same_contract_benchmark_reused_without_mutable_account_aliases(managed_evaluation):
    context, request = managed_evaluation
    scope = BenchmarkReplayScope()
    first = _evaluate_strategy(request, dataflows=context.data, benchmark_scope=scope)
    second = _evaluate_strategy(request, dataflows=context.data, benchmark_scope=scope)
    assert (scope.computed, scope.reused) == (1, 1)
    assert first.result_hash == second.result_hash
    a, b = first.runs[0].buyhold, second.runs[0].buyhold
    assert a.account_daily is not b.account_daily
    original = b.account_daily.iloc[0]["equity"]
    a.account_daily.loc[a.account_daily.index[0], "equity"] = -1
    a.metrics["total_return"] = -1
    third = _evaluate_strategy(request, dataflows=context.data, benchmark_scope=scope)
    assert third.runs[0].buyhold.account_daily.iloc[0]["equity"] == original
    assert third.result_hash == second.result_hash


def test_different_fee_and_funding_do_not_reuse_benchmark(managed_evaluation):
    context, request = managed_evaluation
    scope = BenchmarkReplayScope()
    base = _evaluate_strategy(request, dataflows=context.data, benchmark_scope=scope)
    stressed = _evaluate_strategy(replace(request, costs=(EvaluationCost("stress", .002),)),
        dataflows=context.data, benchmark_scope=scope)
    funded = _evaluate_strategy(replace(request, initial_cash=request.initial_cash * 2),
        dataflows=context.data, benchmark_scope=scope)
    assert (scope.computed, scope.reused) == (3, 0)
    assert stressed.runs[0].buyhold.account_daily.iloc[-1]["equity"] != base.runs[0].buyhold.account_daily.iloc[-1]["equity"]
    assert funded.runs[0].buyhold.account_daily.iloc[-1]["equity"] > base.runs[0].buyhold.account_daily.iloc[-1]["equity"]


def test_batch_history_and_input_preparation_are_not_repeated_per_cost_account(managed_evaluation, monkeypatch):
    from strategy_runtime.strategy import StrategyInstance
    context, request = managed_evaluation
    calls = {"prepare": 0, "history": 0, "fork": 0}
    prepare = StrategyInstance.prepare_data
    history = StrategyInstance._history
    fork = StrategyInstance.fork_for_replay
    def counted_prepare(instance, *args, **kwargs):
        calls["prepare"] += 1
        assert kwargs["persist"] is False
        return prepare(instance, *args, **kwargs)
    def counted_history(instance, data, mode):
        if (data.dataset_identity, mode) not in instance._history_cache:
            calls["history"] += 1
        return history(instance, data, mode)
    def counted_fork(instance, **kwargs):
        calls["fork"] += 1
        return fork(instance, **kwargs)
    monkeypatch.setattr(StrategyInstance, "prepare_data", counted_prepare)
    monkeypatch.setattr(StrategyInstance, "_history", counted_history)
    monkeypatch.setattr(StrategyInstance, "fork_for_replay", counted_fork)
    previous = set(context.repository.root.rglob("input-bindings/*.json"))
    result = _evaluate_strategy(replace(request, costs=(EvaluationCost("standard", .001),
        EvaluationCost("pressure", .002))), dataflows=context.data)
    assert len(result.runs) == 2
    assert calls == {"prepare": 1, "history": 1, "fork": 2}
    assert set(context.repository.root.rglob("input-bindings/*.json")) == previous


def test_worker_consumes_parent_benchmark_seed_and_rejects_missing_contract(managed_evaluation, monkeypatch):
    import pandas as pd
    import pytest
    from czsc_trader.backtesting import benchmarks
    context, request = managed_evaluation
    scope = BenchmarkReplayScope()
    window = request.windows[0]
    terms = benchmarks.BenchmarkWindow(pd.Timestamp(window.start), pd.Timestamp(window.end), request.costs[0].one_way_cost)
    seed = scope.prepare(request.execution_data, terms, request.initial_cash, benchmark=request.benchmark)
    assert scope.prepare(request.execution_data, terms, request.initial_cash, benchmark=request.benchmark) is seed
    assert (scope.computed, scope.reused) == (1, 1)
    worker = BenchmarkReplayScope.from_seeds((seed,))
    def forbidden(*args, **kwargs):
        pytest.fail("worker must not recompute the parent-prepared benchmark")
    monkeypatch.setattr(benchmarks, "replay_buyhold", forbidden)
    result = _evaluate_strategy(request, dataflows=context.data, benchmark_scope=worker)
    assert result.runs[0].buyhold is not None
    assert (worker.computed, worker.reused) == (0, 1)
    with pytest.raises(ValueError, match="not prepared"):
        _evaluate_strategy(replace(request, initial_cash=request.initial_cash * 2),
            dataflows=context.data, benchmark_scope=worker)
