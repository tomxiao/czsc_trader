"""Authentication and identity checks only: no market data or execution."""

from hashlib import sha256

from strategy_runtime import DecisionFeedback, StrategyCandidate, StrategyRuntime

from build_candidate import SOURCE_ROOT, build, build_declared_candidate


def test_original_c9522_identity_and_source_remain_exact():
    candidate, description = build()
    assert candidate.candidate_id == "C9522"
    assert "decision_feedback" not in candidate.payload
    assert candidate.runtime_identity_sha256 == "1b74ef0bb88c1590944a3bb4c7462cc1f99dd1eb040ce511e93d44b51b163d2b"
    assert description.runtime_sha256 == "ffe91481ebfa64a9b454aae754e7cc0e1c89aa0793d2436deac84bbd4355e805"
    assert candidate.payload["runtime"]["source_sha256"] == "47ab4d98cc0e6448f73e18c8f6b10d100b9fac16bb9ccba0fccae2912a8ab954"


def test_c9523_declares_simulated_feedback_without_changing_implementation():
    original, _ = build()
    successor, description = build_declared_candidate()
    assert successor.candidate_id == "C9523"
    assert successor.payload["decision_feedback"] == "SIMULATED_FILL_FEEDBACK"
    assert successor.payload["runtime"] == original.payload["runtime"]
    assert successor.payload["parameters"] == original.payload["parameters"]
    assert description.decision_feedback is DecisionFeedback.SIMULATED_FILL_FEEDBACK
    assert successor.source_root == original.source_root
    actual_source = SOURCE_ROOT / "strategies/trend_permission.py"
    assert sha256(actual_source.read_bytes()).hexdigest() == "74aed227f79b992d2b403d8286fabb7eefe83d88abbab02a76316eadf1231e23"


def test_feedback_declaration_is_identity_bound_independently_of_candidate_number():
    declared, description = build_declared_candidate()
    undeclared_payload = {k: v for k, v in declared.payload.items() if k != "decision_feedback"}
    same_number_undeclared = StrategyCandidate("S014", "C9523", undeclared_payload, SOURCE_ROOT)
    assert declared.runtime_identity_sha256 != same_number_undeclared.runtime_identity_sha256
    assert description.runtime_sha256 != StrategyRuntime().describe(same_number_undeclared).runtime_sha256
