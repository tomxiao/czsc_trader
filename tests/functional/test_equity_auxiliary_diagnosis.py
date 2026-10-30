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
from equity_test_support import setup_auxiliary, v3_account


@pytest.mark.parametrize("different_cost", [False, True])
def test_diagnosis_compares_optional_signal_inputs_but_keeps_execution_contract(tmp_path, different_cost):
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
    if different_cost:
        baseline = replace(baseline, fee_rate=.002)
    accounts = []
    for name, request in (("auxiliary", auxiliary), ("baseline", baseline)):
        with v3_account(context, request) as (prepared, result, payload, execution):
            evidence = publish_evidence(context, EvaluationEvidenceWrite(request.experiment, name, prepared, result), execution=execution)
            identity = dict(payload["evaluation_identity"])
            identity["candidate"] = CandidateKey(**identity["candidate"])
            accounts.append(AccountRunRef(evidence, EvaluationIdentity(**identity)))
    result = diagnose_accounts(context.repository, AccountDiagnosisRequest(*accounts,
        EvaluationWindow("full", date(2026, 10, 1), date(2026, 10, 2))))
    assert result.status == ("INCOMPARABLE" if different_cost else "COMPUTED"), result.issues
