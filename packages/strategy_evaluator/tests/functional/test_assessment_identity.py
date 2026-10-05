import pytest

from strategy_evaluator import AssessmentCandidate, ValidationError

@pytest.mark.parametrize("candidate_id", ["C0000", "C9999"])
def test_assessment_candidate_valid_boundaries(candidate_id):
    assert AssessmentCandidate(f"S011-{candidate_id}", "a" * 64).candidate_id == f"S011-{candidate_id}"

@pytest.mark.parametrize("candidate_id", ['', 'C001', 'C10000', 'c0621', 'CFG000621', 'S011-C0621', 'v1', 'C０６２１', ' C0621', 'C0621 ', 'C0621\n'])
def test_assessment_rejects_noncanonical_candidate_identity(candidate_id):
    with pytest.raises(ValidationError):
        AssessmentCandidate(f"S011-{candidate_id}", "a" * 64)
