import pytest

from strategy_evaluator import AssessmentCandidate, ValidationError


@pytest.mark.risk_cases('SE-02-C07')
def test_SE_02_C07_noncanonical_candidate_identity_rejected():
    with pytest.raises(ValidationError):
        AssessmentCandidate("S011-C1", "a" * 64)
