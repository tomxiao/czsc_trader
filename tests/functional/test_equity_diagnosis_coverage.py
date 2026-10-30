"""Decision populations use explicit order references and retain unknown membership."""
from datetime import date
import json

from strategy_manager import CandidateKey
from czsc_trader.application import diagnose_accounts, publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite, MaterialEvidenceWrite
from czsc_trader.research_tools.account_diagnosis import AccountRunRef, AccountDiagnosisRequest, DecisionPopulationRef
from czsc_trader.research_tools.evaluation import EvaluationIdentity, EvaluationWindow
from equity_test_support import setup_account_research, account_research


def test_equity_population_joins_order_to_decision_and_preserves_unknown(tmp_path):
    context, request, _, _ = setup_account_research(tmp_path)
    with account_research(context,request) as (prepared,result,value,execution):
        account_ref=publish_evidence(context,EvaluationEvidenceWrite(request.experiment,'current-account',
            prepared,result),execution=execution)
    run=value['runs']['candidate']
    assert all(order['order_id']!=order['decision_id'] for order in run['orders'])
    identity = dict(value["evaluation_identity"])
    identity["candidate"] = CandidateKey(**identity["candidate"])
    account = AccountRunRef(account_ref, EvaluationIdentity(**identity))
    population = publish_evidence(context, MaterialEvidenceWrite(request.experiment, "unknown-population",
        json.dumps({"schema_version": 1, "population_id": "unknown", "evaluation_id": account.identity.evaluation_id,
                    "memberships": []}).encode(), "application/json", "json"))
    output = diagnose_accounts(context.repository, AccountDiagnosisRequest(account, None,
        EvaluationWindow("full", date(2026, 10, 1), date(2026, 10, 2)), (DecisionPopulationRef(population, "unknown"),)))
    assert output.status == "COMPUTED", output.issues
    buys = sum(row["side"] == "BUY" for row in run["orders"])
    assert buys > 0
    assert sum(row.buy_intent for row in output.decision_coverage) == buys
    assert sum(row.buy_fill for row in output.decision_coverage) == sum(row["side"] == "BUY" for row in run["fills"])
    assert all(row.member is None for row in output.decision_coverage)
    assert all(row.members == row.nonmembers == 0 and row.unknown == row.total for row in output.coverage_summary)
