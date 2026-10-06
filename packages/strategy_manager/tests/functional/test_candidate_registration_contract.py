"""Current candidate registration serialization boundaries owned by SM."""

from dataclasses import replace
from hashlib import sha256
import json
import pytest
from strategy_manager import (
    CandidateRegistration,
    CandidateKey,
    CandidateEvidence,
    CandidateRegistrationOrigin,
    ValidationError,
    canonical_sha256,
    CandidateIdentityConflict,
    StrategyRegistry,
    StrategyFamily,
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
        "declared-source-root",
        (),
        CandidateRegistrationOrigin(
            "EX001_20261003", (CandidateEvidence("evidence/evaluation.json", "a" * 64),)
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


@pytest.mark.parametrize("evidence", [(), (CandidateEvidence("same.json", "a" * 64),) * 2])
def test_candidate_origin_requires_unique_supporting_evidence(evidence):
    with pytest.raises(ValidationError, match="unique supporting evidence"):
        CandidateRegistrationOrigin("EX001_20261003", evidence)


@pytest.fixture
def persisted_candidate(tmp_path, registration):
    """A caller-selected evidence root, independent of a repository directory scheme."""
    registry = StrategyRegistry(tmp_path / "registry")
    registry.create_family(StrategyFamily.from_dict({
        "schema_version": 2, "strategy_id": "S900", "name": "Candidate contract",
        "scope": ["588080.SH"], "research_intent": {"objective": "synthetic test"},
        "research_state": "RESEARCHING", "created_at": "2026-10-01T10:00:00+08:00",
        "created_by": "tester", "updated_at": "2026-10-01T10:00:00+08:00",
    }), actor="tester", reason="synthetic input")
    root = tmp_path / "caller-selected-evidence"
    root.mkdir()
    source = b"# synthetic runtime source\n"
    source_hash = sha256(b"strategy.py\0" + source + b"\0").hexdigest()
    source_root = f"experiments/EX001_20261003/evidence/source/{source_hash}/strategy_runtime"
    source_path = f"{source_root}/strategy.py"
    (root / source_path).parent.mkdir(parents=True)
    (root / source_path).write_bytes(source)
    payload = json.dumps({"runtime": {
        "source_files": ["strategy.py"], "source_sha256": source_hash,
    }}).encode("utf-8")
    (root / "payload.json").write_bytes(payload)
    (root / "evaluation.json").write_bytes(b'{"result":"synthetic"}')
    record = replace(registration, source_sha256=source_hash,
        payload=CandidateEvidence("payload.json", sha256(payload).hexdigest()),
        source_files=(CandidateEvidence(source_path, sha256(source).hexdigest()),),
        source_root=source_root,
        origin=CandidateRegistrationOrigin("EX001_20261003", (
            CandidateEvidence("evaluation.json", sha256((root / "evaluation.json").read_bytes()).hexdigest()),
        )))
    return registry, root, record


def test_registry_uses_explicit_evidence_root_and_preserves_content_identity(persisted_candidate):
    registry, root, record = persisted_candidate
    assert record.schema_version == 3
    assert record.identity_schema_version == 2
    assert registry.register_candidate(record, evidence_root=root) == record
    assert registry.register_candidate(record, evidence_root=root) == record
    assert registry.get_candidate(record.key, evidence_root=root) == record
    with pytest.raises(CandidateIdentityConflict):
        registry.register_candidate(replace(record, content_sha256="f" * 64), evidence_root=root)
    with pytest.raises(ValidationError, match="root is missing"):
        registry.get_candidate(record.key, evidence_root=root / "missing")


def test_registry_requires_declared_source_closure(persisted_candidate):
    registry, root, record = persisted_candidate
    with pytest.raises(ValidationError, match="safe relative path"):
        replace(record, source_root="../outside")
    with pytest.raises(ValidationError, match="source manifest differs"):
        registry.register_candidate(replace(record, source_root="another-source"), evidence_root=root)
    assert not (registry.root / "S900/candidates/C0001.json").exists()


@pytest.mark.parametrize("artifact", ["payload", "source", "evidence"])
def test_registry_rejects_tampered_candidate_artifacts(persisted_candidate, artifact):
    registry, root, record = persisted_candidate
    registry.register_candidate(record, evidence_root=root)
    reference = {"payload": record.payload, "source": record.source_files[0],
                 "evidence": record.origin.evidence[0]}[artifact]
    (root / reference.path).write_bytes(b"tampered")
    with pytest.raises(ValidationError, match="hash differs"):
        registry.get_candidate(record.key, evidence_root=root)
