# Risk ownership: TDR-07 TDR-16
"""Distinct equity semantics alongside the common account lifecycle."""
from dataclasses import replace
import json

import pytest
from strategy_runtime import ExecutionResources
from czsc_trader.application import publish_evidence_many
from czsc_trader.research_tools import (EvaluationEvidenceWrite,
                                      ResearchExecutionSession)


def publish_account(context, prepared, result, execution, name):
    outcome, = publish_evidence_many(context, (EvaluationEvidenceWrite(prepared.experiment, name, prepared, result),), execution=execution)
    assert outcome.status.value == "PUBLISHED", outcome.error
    return outcome.reference




def test_TDR_16_C03_equity_projection_keeps_explicit_semantics_and_audit_detects_tampering(account_facts):
    _, result = account_facts
    from czsc_trader.research_tools.equity_evaluation import EquityArtifact, EquityEvaluationResult
    from czsc_trader.research_tools.equity_replay import build_equity_assessment, materialize_equity
    from strategy_evaluator.equity import audit_equity_account

    def audit(value):
        payload = materialize_equity(value).payload
        inputs = {name: payload['audit_inputs'][name] for name in (
            'initial_cash', 'specification', 'bars', 'price_basis', 'quantity_basis', 'constraints', 'fee_rate')}
        run = {name: payload['runs']['candidate'][name] for name in (
            'decisions', 'orders', 'fills', 'account_entries', 'account_points', 'trades')}
        return audit_equity_account(**inputs, **run, account_contract=4, decision_contract='FORMAL_V4')

    baseline, = build_equity_assessment(result)
    assert audit(result).observations > 0
    envelope=result.payload
    artifacts=list(result.artifacts)
    index=next(i for i,item in enumerate(artifacts) if item.sha256==envelope['candidate_ref']['sha256'])
    value=json.loads(artifacts[index].content)
    value['run']['account_points'][2]['receivable']+=1
    artifacts[index]=EquityArtifact(artifacts[index].kind,json.dumps(value,sort_keys=True,separators=(',',':')).encode())
    envelope['candidate_ref']['sha256']=artifacts[index].sha256
    altered=EquityEvaluationResult(result.request_hash,json.dumps(envelope,sort_keys=True,separators=(',',':')).encode(),tuple(artifacts))
    # Projection consumes saved observations, while numerical certification is
    # an explicit request. A coherent content hash does not certify accounting.
    projected, = build_equity_assessment(altered)
    assert projected.account == baseline.account and projected.equity == baseline.equity
    with pytest.raises(ValueError, match='^equity audit mismatch: v4 account receivable$'):
        audit(altered)




@pytest.fixture(scope='module')
def cancelled_execution(tmp_path_factory):
    from equity_test_support import setup_account_research
    context, request, _, _ = setup_account_research(tmp_path_factory.mktemp('cancelled-account'))
    context.evaluation.resources = ExecutionResources(2)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        original = context.evaluation.prepare(request, execution=execution)
        complete, = context.evaluation.evaluate_many((original,), execution=execution)
        assert complete.result is not None, complete.error
        retained_bytes = complete.result.content
        next_request = replace(request, candidate=replace(request.candidate, candidate_id='C0002'))
        next_account = context.evaluation.prepare(next_request, execution=execution)
        def cancel(_):
            raise KeyboardInterrupt('explicit cancellation')
        execution.executor.on_progress = cancel
        with pytest.raises(KeyboardInterrupt, match='explicit cancellation'):
            context.evaluation.evaluate_many((next_account,), execution=execution)
        yield context, execution, next_account, complete.result, retained_bytes


def test_TDR_07_C04_cancel_retains_completed_and_reclaims_workers(cancelled_execution):
    _, execution, _, completed, original_bytes = cancelled_execution
    assert completed.content == original_bytes
    assert execution.executor.broken
    assert all(not p.is_alive() for p in execution.executor.pool._processes.values())


def test_TDR_07_C05_cancelled_session_cannot_resume(cancelled_execution):
    from concurrent.futures.process import BrokenProcessPool
    context, execution, prepared, _, _ = cancelled_execution
    starts = execution.stats.pool_starts
    with pytest.raises(BrokenProcessPool):
        context.evaluation.evaluate_many((prepared,), execution=execution)
    assert execution.stats.pool_starts == starts
