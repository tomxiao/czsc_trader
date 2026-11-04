"""Both computation models obey the same preparation and ownership contract."""
from dataclasses import replace

import pytest

from czsc_trader.research_tools import ResearchExecutionSession, PreparedAccountEvaluation
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


@pytest.mark.parametrize('market', ['CN', 'US'])
@pytest.mark.parametrize('computation', ['BATCH_HISTORY', 'STATEFUL_STEP'])
def test_account_preparation_ownership_and_input_isolation(tmp_path, market, computation):
    from account_parity_support import setup_account
    from strategy_runtime import StrategyComputation, ExecutionResources
    from dataflows import MarketId, BarFrequency
    context, proposal = setup_account(tmp_path, MarketId(market), BarFrequency.DAILY, StrategyComputation(computation))
    context.evaluation.resources = ExecutionResources(1)
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
