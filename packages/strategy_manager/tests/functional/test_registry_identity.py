import pytest

from strategy_manager import CandidateKey, FreezeRequestId, FrozenVersionReference, ValidationError

@pytest.mark.risk_cases('SM-01-C01')
def test_candidate_key_valid_boundaries():
    candidate_id = "C0001"
    assert CandidateKey("S011", candidate_id).candidate_id == candidate_id

@pytest.mark.risk_cases('SM-01-C02')
def test_candidate_key_rejects_noncanonical_values():
    candidate_id = 'C1'
    with pytest.raises(ValidationError):
        CandidateKey("S011", candidate_id)


@pytest.mark.risk_cases('SM-01-C04')
def test_SM_01_C04_family_freeze_request_needs_no_dummy_candidate():
    assert FreezeRequestId("S011", "request-1").strategy_id == "S011"
    assert FrozenVersionReference("S011", "v1", "a" * 64, "b" * 64).version == "v1"
