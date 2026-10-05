import pytest

from strategy_manager import CandidateKey, FreezeRequestId, FrozenVersionReference, ValidationError

@pytest.mark.parametrize("candidate_id", ["C0000", "C9999"])
def test_candidate_key_valid_boundaries(candidate_id):
    assert CandidateKey("S011", candidate_id).candidate_id == candidate_id

@pytest.mark.parametrize("candidate_id", ['', 'C001', 'C10000', 'c0621', 'CFG000621', 'S011-C0621', 'v1', 'C０６２１', ' C0621', 'C0621 ', 'C0621\n'])
def test_candidate_key_rejects_noncanonical_values(candidate_id):
    with pytest.raises(ValidationError):
        CandidateKey("S011", candidate_id)

@pytest.mark.parametrize("family", ['S01', 'S0011', 'S０１１', ' S011', 'S011 '])
def test_registry_identity_family_is_canonical(family):
    with pytest.raises(ValidationError):
        CandidateKey(family, "C0621")
    with pytest.raises(ValidationError):
        FreezeRequestId(family, "request-1")

def test_family_freeze_request_needs_no_dummy_candidate():
    assert FreezeRequestId("S011", "request-1").strategy_id == "S011"
    assert FrozenVersionReference("S011", "v1", "a" * 64, "b" * 64).version == "v1"
