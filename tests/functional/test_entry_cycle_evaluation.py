"""Dynamic cycle facts survive real preparation, workers and authenticated retention."""
from copy import deepcopy
from dataclasses import replace
import json
from hashlib import sha256

import pandas as pd
import pytest
from strategy_runtime import StrategyCandidate, implementation_identity
from strategy_evaluator import (
    AuditStatus, ReplayEvidence, audit_replay, compare_ledgers, LedgerComparisonRequest,
    LedgerComparisonMode, LedgerComparisonStatus,
)

from czsc_trader.application import describe_inspection_environment, publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite, ExecutionResources, ExperimentRef
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from czsc_trader.research_tools.evaluation_access import EvaluationStatus
from czsc_trader.application.inspection_replay import technical_ledger_differences
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


def test_cycle_allocations_survive_parallel_evaluation_and_formal_authentication(managed_evaluation):
    context, request = managed_evaluation
    source = request.strategy.source_root / "strategies/candidate_fixture.py"
    text = source.read_text(encoding="utf-8")
    text = text.replace('DecisionContract("TARGET_POSITION"', 'DecisionContract("CYCLE_TARGET"')
    text = text.replace('"mode": "full_available_cash"', '"mode": "signal_cash_fraction"')
    text = text.replace('return pd.DataFrame({"target_position": target, "fixture_signal": target}, index=sessions)',
                        'target = pd.Series([1., 1., 0., 1., 0.], index=sessions)\n'
                        '        return pd.DataFrame({"target_position": target, "fixture_signal": target, '
                        '"entry_allocation_fraction": [.5, 1., None, 1., None]}, index=sessions)')
    source.write_text(text, encoding="utf-8")
    payload = json.loads(json.dumps(dict(request.strategy.payload), default=dict))
    payload["runtime"]["source_sha256"] = implementation_identity.implementation_sha256(
        ("strategies/candidate_fixture.py",), source_root=request.strategy.source_root)
    candidate = StrategyCandidate("S900", "C0002", payload, request.strategy.source_root)
    request = replace(request, strategy=candidate, runtime_binding={
        "candidate_id": candidate.reference_id, "source_files": ["strategies/candidate_fixture.py"],
        "implementation_sha256": payload["runtime"]["source_sha256"],
    })
    bound = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(bound)
    context.evaluation.resources = ExecutionResources(2, 1)
    outcomes = context.evaluation.evaluate_many((bound, bound))
    assert all(outcome.status is EvaluationStatus.SUCCEEDED for outcome in outcomes), outcomes
    for outcome in outcomes:
        assert outcome.result.result_hash == result.result_hash
        for name in ("decisions", "orders", "fills", "account_daily", "trades"):
            pd.testing.assert_frame_equal(getattr(outcome.result.runs[0].execution, name),
                                          getattr(result.runs[0].execution, name))
    ledger = result.runs[0].execution
    states = [json.loads(value) for value in ledger.decisions.entry_cycle_after]
    assert states[0]["allocation_fraction"] == "0.5"
    assert states[1]["allocation_fraction"] == "0.5"
    assert states[3]["allocation_fraction"] == "1.0"
    assert states[0]["cycle_id"] != states[3]["cycle_id"]
    reference = publish_evidence(context, EvaluationEvidenceWrite(
        ExperimentRef("S900", request.experiment_id), "dynamic-cycle-account", bound, result))
    encoded = json.loads(reference.resolve(context.repository.root).read_bytes())
    validate_evaluation_evidence(encoded)
    environment = describe_inspection_environment(context.repository)
    assert "strategy_runtime/entry_cycle.py" in {item.path for item in environment.platform_files}
    replay = ReplayEvidence.from_dict(encoded["runs"][0]["replay_evidence"])
    audited = audit_replay(replay)
    assert audited.status is AuditStatus.PASS, audited.reason_codes
    assert "ENTRY_CYCLE_ALLOCATION" in audited.checks
    # A frozen runtime receives distinct signal/plan/cycle identities. Only
    # references are renamed; budget and quantity facts remain exact.
    encoded_replay = json.dumps(replay.to_dict())
    identities = {row[field] for name in ("decisions", "orders", "fills", "account_daily", "trades")
                  for row in getattr(replay, name)
                  for field in ("decision_id", "order_id", "fill_id", "cycle_id", "signal_identity", "plan_identity")
                  if row.get(field) is not None}
    for identity in identities:
        encoded_replay = encoded_replay.replace(identity, sha256(("release:" + identity).encode()).hexdigest())
    renamed = ReplayEvidence.from_dict(json.loads(encoded_replay))
    renamed = replace(renamed, strategy_hash="f" * 64, content_hash="")
    assert audit_replay(renamed).status is AuditStatus.PASS
    assert compare_ledgers(LedgerComparisonRequest(replay, renamed, LedgerComparisonMode.ECONOMIC)).status is LedgerComparisonStatus.EQUIVALENT
    assert not technical_ledger_differences(replay.to_dict(), renamed.to_dict(), 0)
    # Alter a cycle fact without altering cash/holdings: the independent audit,
    # rather than an outer stale checksum, must reject this plausible ledger.
    changed = deepcopy(replay.to_dict())
    first = json.loads(changed["decisions"][0]["entry_cycle_after"])
    first["cash_budget"] = "90000.0"
    changed["decisions"][0]["entry_cycle_after"] = json.dumps(first)
    changed["content_hash"] = ""
    assert "ENTRY_CYCLE_ALLOCATION_MISMATCH" in audit_replay(ReplayEvidence.from_dict(changed)).reason_codes
    assert technical_ledger_differences(replay.to_dict(), changed, 100000)
    retained = deepcopy(encoded)
    retained["runs"][0]["ledgers"]["decisions"]["data"][0]["cycle_cash_budget"] = "90000.0"
    with pytest.raises(ValueError, match="differs"):
        validate_evaluation_evidence(retained)
