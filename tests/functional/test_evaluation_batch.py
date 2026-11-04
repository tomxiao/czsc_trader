"""Current V4 batch outcomes keep order and report failures without retry."""
from concurrent.futures import CancelledError
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
import os

import pytest
from strategy_runtime import ExecutionResources
from equity_test_support import setup_account_research
from czsc_trader.research_tools import ResearchExecutionSession
from czsc_trader.research_tools.evaluation_access import EvaluationOutcome, EvaluationStatus


def terminated_worker(*args):
    os._exit(7)


def test_v4_results_preserve_order_and_failed_accounts_are_not_retried(tmp_path, monkeypatch):
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
        prepared = tuple(context.evaluation.prepare(replace(request, initial_cash=cash), execution=execution)
            for cash in (100000, 13, 14, 100000))
        outcomes = context.evaluation.evaluate_many(prepared, execution=execution)
        assert [x.status for x in outcomes] == [EvaluationStatus.SUCCEEDED, EvaluationStatus.FAILED,
            EvaluationStatus.CANCELLED, EvaluationStatus.SUCCEEDED]
        assert outcomes[0].result.result_hash == outcomes[3].result.result_hash
        assert calls.count(13) == calls.count(14) == 2  # one candidate and one benchmark; no retry
        assert outcomes[1].result is None and outcomes[2].result is None
        with pytest.raises(ValueError, match='successful outcome'):
            EvaluationOutcome(EvaluationStatus.SUCCEEDED, outcomes[0].request_hash)
        with pytest.raises(ValueError, match='request identities differ'):
            EvaluationOutcome(EvaluationStatus.SUCCEEDED, 'f'*64, outcomes[0].result)


def test_v4_worker_loss_is_unknown_and_does_not_restart_pool(tmp_path, monkeypatch):
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


@pytest.mark.parametrize('kwargs', [{'max_workers': 0}, {'native_threads_per_worker': True}, {'random_seed': -1}])
def test_invalid_resources_reject_before_computation(kwargs):
    with pytest.raises(ValueError):
        ExecutionResources(**kwargs)


def test_retired_ordinary_account_interfaces_are_absent_and_rejected(tmp_path):
    from czsc_trader import research_tools
    from czsc_trader.research_tools import evaluation, account_preparation, assessment
    from czsc_trader.research_tools.evidence import EvaluationEvidenceWrite
    context, request, _, _ = setup_account_research(tmp_path)
    assert not hasattr(context.evaluation, 'evaluate')
    for name in ('EvaluationRequest', 'EvaluationResult', 'EvaluationRun'):
        assert name not in research_tools.__all__
    for name in ('EvaluationRequest', 'EvaluationResult', '_evaluate_strategy', 'serialize_evaluation_evidence'):
        assert not hasattr(evaluation, name)
    assert not hasattr(account_preparation, 'prepare_account')
    assert not hasattr(assessment, '_assessment_with_replays')
    with pytest.raises(TypeError, match='EquityEvaluationRequest'):
        context.evaluation.prepare(object())
    with pytest.raises(TypeError, match='PreparedAccountEvaluation'):
        EvaluationEvidenceWrite(request.experiment, 'retired', object(), object())


@pytest.mark.parametrize('name, fee, tier', [('', .001, 'FORMAL'), ('../escape', .001, 'FORMAL'),
    ('NUL', .001, 'FORMAL'), ('trailing.', .001, 'FORMAL'), ('bad\nname', .001, 'FORMAL'),
    ('valid', float('nan'), 'FORMAL'), ('valid', -.001, 'FORMAL'), ('valid', 1., 'FORMAL'),
    ('valid', True, 'FORMAL'), ('valid', .001, 'UNKNOWN')])
def test_evaluation_cost_rejects_invalid_identity_fee_and_tier(name, fee, tier):
    from czsc_trader.research_tools import EvaluationCost
    with pytest.raises(ValueError):
        EvaluationCost(name, fee, tier)
