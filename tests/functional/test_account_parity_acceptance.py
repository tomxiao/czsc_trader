# Risk ownership: E2E-01
"""Three-stage acceptance through the public research APIs, not private engines."""
from datetime import date

import pytest
from dataflows import MarketId, BarFrequency
from strategy_runtime import StrategyComputation
from czsc_trader.research_tools import (ResearchExecutionSession, EvaluationEvidenceWrite,
    build_assessment_evidence, AccountRunRef, AccountDiagnosisRequest, EvaluationWindow)
from czsc_trader.application import (publish_evidence, diagnose_accounts, register_candidate,
    CandidateRegistrationRequest, load_candidate)
from account_parity_support import setup_account


def _retained_ledger(result, *, benchmark=False):
    """Read the retained full journal when a test explicitly inspects execution."""
    from czsc_trader.research_tools.equity_replay import materialize_equity
    payload = materialize_equity(result).payload
    run = payload['runs']['buy_hold' if benchmark else 'candidate']
    ledger = {**{name: payload['audit_inputs'][name] for name in (
        'bars', 'constraints', 'specification', 'initial_cash', 'fee_rate')},
        **{name: run[name] for name in ('decisions', 'orders', 'fills', 'account_entries', 'account_points', 'trades')},
        'account_contract': 4, 'price_basis':'HFQ','quantity_basis':'SIMULATED_INTEGER_UNITS'}
    if not benchmark and payload['request']['candidate_definition'].get('execution_input') is not None:
        ledger['execution_bars'] = payload['audit_inputs']['decision_inputs']['execution']['bars']
    return ledger


@pytest.mark.parametrize('market,frequency,computation', [
    pytest.param(MarketId.CN, BarFrequency.DAILY, StrategyComputation.STATEFUL_STEP, id='E2E-01-C01'),
    pytest.param(MarketId.CN, BarFrequency.M30, StrategyComputation.BATCH_HISTORY, id='E2E-01-C02'),
    pytest.param(MarketId.US, BarFrequency.DAILY, StrategyComputation.STATEFUL_STEP, id='E2E-01-C03'),
    pytest.param(MarketId.US, BarFrequency.M30, StrategyComputation.BATCH_HISTORY, id='E2E-01-C04'),
])
def test_stage_one_two_public_computation_clock_and_scale_in_out(tmp_path, market, frequency, computation):
    context, request = setup_account(tmp_path, market, frequency, computation)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.result is not None, outcome.error
        assert outcome.result.payload['schema'] == 'equity-research/v4'
        facts, = build_assessment_evidence(prepared, outcome.result, execution=execution)
        assert facts.equity.market == market.value
        assert facts.equity.currency == request.candidate.instrument.currency
        reference = publish_evidence(context, EvaluationEvidenceWrite(request.experiment,
            'parity', prepared, outcome.result), execution=execution)
        assert reference.schema_version == 4
        from czsc_trader.research_tools.evaluation import EvaluationIdentity
        from strategy_manager import CandidateKey
        raw_identity = dict(outcome.result.payload['evaluation_identity'])
        raw_identity['candidate'] = CandidateKey(**raw_identity['candidate'])
        identity = EvaluationIdentity(**raw_identity)
        diagnosis = diagnose_accounts(context.repository, AccountDiagnosisRequest(
            AccountRunRef(reference, identity), None,
            EvaluationWindow('all', date(2026,10,26) if frequency is BarFrequency.M30 else date(2026,10,27), date(2026,10,30))),
            execution=execution)
        assert diagnosis.status.value == 'COMPUTED', diagnosis.issues
        assert all(abs(day.residual) < 1e-7 for pnl in diagnosis.pnl_breakdown for day in pnl.daily)
        if computation is StrategyComputation.STATEFUL_STEP:
            # The same four market/frequency runs also own independent ledger auditing.
            from strategy_evaluator.equity import audit_equity_account
            for benchmark in (False, True):
                ledger = _retained_ledger(outcome.result, benchmark=benchmark)
                assert ledger['account_contract'] == 4
                assert ledger['price_basis']=='HFQ' and ledger['quantity_basis']=='SIMULATED_INTEGER_UNITS'
                assert {row['kind'] for row in ledger['account_entries']} <= {'SALE_SETTLEMENT'}
                audit_equity_account(**ledger, decision_contract='FORMAL_V4')
            # Independent fact audit must reject an altered, otherwise well-formed ledger.
            damaged = dict(ledger, account_points=[dict(row) for row in ledger['account_points']])
            damaged['account_points'][-1]['cash'] += 1
            with pytest.raises(ValueError):
                audit_equity_account(**damaged, decision_contract='FORMAL_V4')
    record = register_candidate(context.repository, CandidateRegistrationRequest(request.candidate,
        request.experiment, (reference,), ()))
    assert load_candidate(context.repository, request.candidate.key).content_identity.content_sha256 == record.content_sha256
