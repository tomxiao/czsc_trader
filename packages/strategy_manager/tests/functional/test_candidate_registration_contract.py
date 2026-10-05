"""Current candidate registration serialization boundaries owned by SM."""

from dataclasses import replace
import pytest
from strategy_manager import (
    CandidateRegistration,
    CandidateKey,
    CandidateEvidence,
    CandidateRegistrationOrigin,
    ValidationError,
    canonical_sha256,
)


@pytest.fixture
def registration():
    return CandidateRegistration(
        CandidateKey("S900", "C0001"),
        "a" * 64,
        "b" * 64,
        canonical_sha256([]),
        CandidateEvidence("payload.json", "c" * 64),
        (CandidateEvidence("strategy.py", "d" * 64),),
        (),
        CandidateRegistrationOrigin(
            "20261001_S900_EX01", "e" * 64, "f" * 64, CandidateEvidence("preflight.json", "a" * 64)
        ),
    )


@pytest.mark.parametrize("field", ["schema_version", "identity_schema_version"])
def test_registration_requires_current_schema_field(registration, field):
    raw = registration.to_dict()
    assert CandidateRegistration.from_dict(raw) == registration
    del raw[field]
    with pytest.raises(ValidationError, match="unsupported candidate"):
        CandidateRegistration.from_dict(raw)


@pytest.mark.parametrize("field", ["schema_version", "identity_schema_version"])
def test_registration_rejects_retired_schema(registration, field):
    raw = registration.to_dict()
    raw[field] = 1
    with pytest.raises(ValidationError, match="unsupported candidate"):
        CandidateRegistration.from_dict(raw)


def test_registration_accepts_new_archive_identity_without_embedded_family(registration):
    current = replace(
        registration, origin=replace(registration.origin, experiment_id="EX001_20261003")
    )
    assert CandidateRegistration.from_dict(current.to_dict()) == current
    assert current.key.strategy_id == "S900"


def test_registration_rejects_embedded_foreign_family_in_legacy_archive(registration):
    with pytest.raises(ValidationError, match="different families"):
        replace(
            registration, origin=replace(registration.origin, experiment_id="20261001_S901_EX01")
        )
