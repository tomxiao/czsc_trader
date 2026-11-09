# Risk ownership: TDR-17
"""Account comparisons authenticate optional signals without treating them as traded assets."""
from dataclasses import replace
from datetime import date

import pytest

from strategy_manager import CandidateKey
from strategy_runtime import equity_source_hash
from czsc_trader.application import diagnose_accounts, publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite
from czsc_trader.research_tools.account_diagnosis import AccountDiagnosisRequest, AccountRunRef
from czsc_trader.research_tools.evaluation import EvaluationIdentity, EvaluationWindow
from equity_test_support import setup_auxiliary, account_research


@pytest.mark.parametrize('different_execution', [pytest.param(False, id='TDR-17-C08'), pytest.param(True, id='TDR-17-C07')])
def test_diagnosis_compares_optional_signal_inputs_but_keeps_execution_contract(tmp_path, different_execution):
    context, auxiliary, _, _ = setup_auxiliary(tmp_path)
    root = auxiliary.candidate.source_root / "price_only"
    root.mkdir()
    (root / "strategy.py").write_text(
        'from strategy_runtime.equity_definition import EquityDecision\n'
        'def decide(ctx):\n'
        '    return EquityDecision.from_facts(0 if ctx.portfolio.quantity else ctx.parameters["enter"], '
        '"position timing", facts={"quantity":ctx.portfolio.quantity}, next_watch="next bar")\n',
        encoding="utf-8")
    definition = replace(auxiliary.candidate.definition, auxiliary_inputs=(), session_context=False,
                         source_sha256=equity_source_hash(root, ("strategy.py",)))
    baseline = replace(auxiliary, candidate=replace(auxiliary.candidate, candidate_id="C0002",
                       definition=definition, source_root=root))
    if different_execution:
        changed_spec = replace(baseline.candidate.definition.execution_spec, buy_premium=.02)
        baseline = replace(baseline, candidate=replace(baseline.candidate,
            definition=replace(baseline.candidate.definition, execution_spec=changed_spec)))
    accounts = []
    baseline_context = context
    if different_execution:
        from strategy_runtime import StrategyRuntime
        from czsc_trader.research_tools.evaluation_access import EvaluationAccess
        baseline_context = replace(context, execution_spec=changed_spec,
            runtime=StrategyRuntime(dataflows=context.data, execution_spec=changed_spec),
            evaluation=EvaluationAccess(dataflows=context.data, strategy_id=context.strategy_id, execution_spec=changed_spec))
        baseline_context.evaluation.resources = context.evaluation.resources
    for name, request in (("auxiliary", auxiliary), ("baseline", baseline)):
        selected_context = baseline_context if name == 'baseline' else context
        with account_research(selected_context, request) as (prepared, result, payload, execution):
            evidence = publish_evidence(selected_context, EvaluationEvidenceWrite(request.experiment, name, prepared, result), execution=execution)
            identity = dict(payload["evaluation_identity"])
            identity["candidate"] = CandidateKey(**identity["candidate"])
            accounts.append(AccountRunRef(evidence, EvaluationIdentity(**identity)))
    result = diagnose_accounts(context.repository, AccountDiagnosisRequest(*accounts,
        EvaluationWindow("full", date(2026, 10, 1), date(2026, 10, 2))))
    assert result.status == ("INCOMPARABLE" if different_execution else "COMPUTED"), result.issues
