"""Both computation models obey the same preparation and ownership contract."""
from dataclasses import replace

import pytest

from czsc_trader.research_tools import ExperimentRef, ResearchExecutionSession, PreparedAccountEvaluation
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


@pytest.mark.parametrize('computation', ['batch_history', 'stateful_step'])
def test_account_preparation_ownership_and_input_isolation(request, tmp_path, computation):
    if computation == 'batch_history':
        context, proposal = request.getfixturevalue('managed_evaluation')
        experiment = ExperimentRef(context.strategy_id, proposal.experiment_id)
    else:
        from equity_test_support import setup_account_research
        context, proposal, _, _ = setup_account_research(tmp_path)
        experiment = proposal.experiment
    access = context.evaluation
    with pytest.raises(TypeError, match='explicit ResearchExecutionSession'):
        access.prepare(proposal)
    with ResearchExecutionSession(context, experiment=experiment) as execution:
        bound = access.prepare(proposal, execution=execution)
        assert type(bound) is PreparedAccountEvaluation
        changed = access.prepare(replace(proposal, initial_cash=200_000), execution=execution)
        assert changed.snapshot is bound.snapshot
        assert changed.benchmark_identity != bound.benchmark_identity
        with pytest.raises(ValueError, match='not issued'):
            access.evaluate_many((replace(bound),), execution=execution)
        outcomes = access.evaluate_many((bound, changed), execution=execution)
        assert all(item.status.value == 'SUCCEEDED' for item in outcomes), [item.error for item in outcomes]
        assert outcomes[0].request_hash != outcomes[1].request_hash
        from czsc_trader.research_tools import EvaluationEvidenceWrite
        from czsc_trader.application import publish_evidence_many
        writes = tuple(EvaluationEvidenceWrite(experiment, f'account-{i}', item, outcome.result)
                       for i, (item, outcome) in enumerate(zip((bound, changed), outcomes, strict=True)))
        published = publish_evidence_many(context, writes, execution=execution)
        assert all(item.status.value == 'PUBLISHED' for item in published), published
    with ResearchExecutionSession(context, experiment=experiment) as other:
        with pytest.raises(ValueError, match='not issued'):
            access.evaluate_many((bound,), execution=other)


def test_session_prepares_no_accounts_and_shares_exact_baseline(managed_evaluation, monkeypatch):
    from czsc_trader.backtesting import benchmarks
    context, proposal = managed_evaluation
    context.evaluation.resources = replace(context.evaluation.resources, max_workers=1)
    calls = []
    calculate = benchmarks.replay_buyhold
    def observed(*args, **kwargs):
        calls.append(1)
        return calculate(*args, **kwargs)
    monkeypatch.setattr(benchmarks, 'replay_buyhold', observed)
    experiment = ExperimentRef(context.strategy_id, proposal.experiment_id)
    with ResearchExecutionSession(context, experiment=experiment) as execution:
        left = context.evaluation.prepare(proposal, execution=execution)
        right = context.evaluation.prepare(proposal, execution=execution)
        assert calls == []
        outcomes = context.evaluation.evaluate_many((left, right), execution=execution)
        assert all(item.status.value == 'SUCCEEDED' for item in outcomes), [item.error for item in outcomes]
        assert len(calls) == len({(w.start, w.end, c.one_way_cost) for w in proposal.windows for c in proposal.costs})
        assert outcomes[0].result.result_hash == outcomes[1].result.result_hash
        a, b = outcomes[0].result.runs[0].buyhold, outcomes[1].result.runs[0].buyhold
        assert a.account_daily is not b.account_daily
        original = b.account_daily.copy()
        a.account_daily.iloc[0, a.account_daily.columns.get_loc('equity')] = -1
        import pandas as pd
        pd.testing.assert_frame_equal(b.account_daily, original)


def test_cost_and_cash_changes_reuse_authenticated_input_preparation(managed_evaluation, monkeypatch):
    from czsc_trader.research_tools import EvaluationCost
    context, proposal = managed_evaluation
    proposal = replace(proposal, input_bindings={})
    calls = {'prepare': 0, 'fetch': 0}
    for name in calls:
        original = getattr(context.data, name)
        def observed(*args, _name=name, _call=original, **kwargs):
            calls[_name] += 1
            return _call(*args, **kwargs)
        monkeypatch.setattr(context.data, name, observed)
    with ResearchExecutionSession(context, experiment=ExperimentRef(context.strategy_id, proposal.experiment_id)) as execution:
        first = context.evaluation.prepare(proposal, execution=execution)
        before = dict(calls)
        assert before['prepare'] > 0
        assert before['fetch'] > 0
        second = context.evaluation.prepare(replace(proposal, initial_cash=200_000,
            costs=(EvaluationCost('new-fee', .002),)), execution=execution)
        assert calls == before
        assert first.snapshot is second.snapshot
        assert first.benchmark_identity != second.benchmark_identity
        with pytest.raises(TypeError, match='EvaluationRequest'):
            context.evaluation.prepare(object(), execution=execution)


def test_prepared_worker_does_not_repeat_request_source_authentication(managed_evaluation, monkeypatch):
    from czsc_trader.research_tools import evaluation
    context, proposal = managed_evaluation
    context.evaluation.resources = replace(context.evaluation.resources, max_workers=1)
    with ResearchExecutionSession(context, experiment=ExperimentRef(context.strategy_id, proposal.experiment_id)) as execution:
        bound = context.evaluation.prepare(proposal, execution=execution)
        def forbidden(*args, **kwargs):
            pytest.fail('prepared account must not repeat request authentication or binding')
        monkeypatch.setattr(evaluation, '_request_contract', forbidden)
        monkeypatch.setattr(evaluation, '_prepare_evaluation_inputs', forbidden)
        outcome, = context.evaluation.evaluate_many((bound,), execution=execution)
        assert outcome.status.value == 'SUCCEEDED', outcome.error


def test_prepared_account_uses_private_input_values_after_caller_mutation(managed_evaluation):
    context, proposal = managed_evaluation
    context.evaluation.resources = replace(context.evaluation.resources, max_workers=1)
    with ResearchExecutionSession(context, experiment=ExperimentRef(context.strategy_id, proposal.experiment_id)) as execution:
        bound = context.evaluation.prepare(proposal, execution=execution)
        other = context.evaluation.prepare(proposal, execution=execution)
        assert other.snapshot is bound.snapshot
        first, = context.evaluation.evaluate_many((bound,), execution=execution)
        assert first.status.value == 'SUCCEEDED', first.error
        public = bound.request.execution_data
        for name in ('execution_daily', 'adjusted_daily'):
            table = getattr(public, name)
            for column in ('open', 'high', 'low', 'close'):
                if column in table:
                    table.loc[:, column] = 9999.
        second, = context.evaluation.evaluate_many((other,), execution=execution)
        assert second.status.value == 'SUCCEEDED', second.error
        assert first.result.result_hash == second.result.result_hash


def test_restored_account_does_not_recompute_baseline(managed_evaluation, monkeypatch):
    from czsc_trader.backtesting import benchmarks
    from czsc_trader.research_tools import ExecutionCheckpointRequest, CheckpointMode
    context, proposal = managed_evaluation
    experiment = ExperimentRef(context.strategy_id, proposal.experiment_id)
    with ResearchExecutionSession(context, experiment=experiment,
            checkpoint=ExecutionCheckpointRequest('unified-baseline')) as execution:
        bound = context.evaluation.prepare(proposal, execution=execution)
        outcome, = context.evaluation.evaluate_many((bound,), execution=execution)
        assert outcome.result is not None, outcome.error
        result_hash = outcome.result.result_hash
    def unexpected(*args, **kwargs):
        raise AssertionError('a restored account must not replay its baseline')
    monkeypatch.setattr(benchmarks, 'replay_buyhold', unexpected)
    with ResearchExecutionSession(context, experiment=experiment,
            checkpoint=ExecutionCheckpointRequest('unified-baseline', CheckpointMode.RESUME)) as execution:
        bound = context.evaluation.prepare(proposal, execution=execution)
        outcome, = context.evaluation.evaluate_many((bound,), execution=execution)
        assert outcome.result is not None, outcome.error
        assert outcome.result.result_hash == result_hash
        assert execution.stats.reused_results == 1 and execution.stats.submitted == 0
