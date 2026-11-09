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
    RegistryError,
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


@pytest.mark.risk_cases('SM-02-C02')
def test_registration_requires_current_schema_field(registration):
    field = "schema_version"
    raw = registration.to_dict()
    assert CandidateRegistration.from_dict(raw) == registration
    del raw[field]
    with pytest.raises(ValidationError, match="unsupported candidate"):
        CandidateRegistration.from_dict(raw)


@pytest.mark.risk_cases('SM-02-C03')
def test_registration_rejects_retired_schema(registration):
    field = "schema_version"
    retired = 2
    raw = registration.to_dict()
    raw[field] = retired
    with pytest.raises(ValidationError, match="unsupported candidate"):
        CandidateRegistration.from_dict(raw)


@pytest.mark.risk_cases('SM-02-C01')
def test_SM_02_C01_registration_roundtrip(registration):
    current = replace(
        registration, origin=replace(registration.origin, experiment_id="EX001_20261003")
    )
    assert CandidateRegistration.from_dict(current.to_dict()) == current
    assert current.key.strategy_id == "S900"
    assert (current.schema_version, current.identity_schema_version) == (3, 2)


@pytest.mark.risk_cases('SM-01-C03')
def test_SM_01_C03_foreign_family_archive_rejected(registration):
    with pytest.raises(ValidationError, match="different families"):
        replace(
            registration, origin=replace(registration.origin, experiment_id="20261001_S901_EX01")
        )


@pytest.mark.risk_cases('SM-06-C04')
def test_candidate_origin_requires_unique_supporting_evidence():
    evidence = (CandidateEvidence("same.json", "a" * 64),) * 2
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
    source_root = f"assets/candidates/C0001/source/{source_hash}/strategy_runtime"
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


@pytest.mark.risk_cases('SM-03-C01')
def test_SM_03_C01_evidence_location_is_not_content_identity(persisted_candidate):
    registry, root, record = persisted_candidate
    assert registry.register_candidate(record, evidence_root=root) == record
    moved = root.with_name("relocated-evidence")
    root.rename(moved)
    assert registry.get_candidate(record.key, evidence_root=moved) == record


@pytest.mark.risk_cases('SM-03-C02')
def test_SM_03_C02_same_candidate_registration_is_idempotent(persisted_candidate):
    registry, root, record = persisted_candidate
    registry.register_candidate(record, evidence_root=root)
    path = registry.root / "S900/candidates/C0001.json"
    before = path.read_bytes()
    assert registry.register_candidate(record, evidence_root=root) == record
    assert path.read_bytes() == before


@pytest.mark.risk_cases('SM-03-C03')
def test_SM_03_C03_conflicting_registration_preserves_original(persisted_candidate):
    registry, root, record = persisted_candidate
    registry.register_candidate(record, evidence_root=root)
    path = registry.root / "S900/candidates/C0001.json"
    before = path.read_bytes()
    with pytest.raises(CandidateIdentityConflict):
        registry.register_candidate(replace(record, content_sha256="f" * 64), evidence_root=root)
    assert path.read_bytes() == before
    assert registry.get_candidate(record.key, evidence_root=root) == record






@pytest.mark.parametrize('artifact', [
    pytest.param("payload", id='SM-04-C02'),
    pytest.param("source", id='SM-04-C03'),
])
@pytest.mark.risk_cases('SM-04-C02', 'SM-04-C03')
def test_registry_rejects_tampered_candidate_artifacts(persisted_candidate, artifact):
    registry, root, record = persisted_candidate
    registry.register_candidate(record, evidence_root=root)
    reference = {"payload": record.payload, "source": record.source_files[0],
                 "evidence": record.origin.evidence[0]}[artifact]
    (root / reference.path).write_bytes(b"tampered")
    with pytest.raises(ValidationError, match="hash differs"):
        registry.get_candidate(record.key, evidence_root=root)


@pytest.mark.risk_cases('SM-05-C01')
def test_SM_05_C01_metadata_read_does_not_require_retained_source(persisted_candidate):
    registry, root, record = persisted_candidate
    registry.register_candidate(record, evidence_root=root)
    record.source_files[0].resolve(root).unlink()
    assert registry.get_candidate_registration(record.key) == record
    with pytest.raises(ValidationError, match="missing"):
        registry.get_candidate(record.key, evidence_root=root)
    with pytest.raises(TypeError, match="CandidateKey"):
        registry.get_candidate_registration(record.key.to_dict())


@pytest.mark.risk_cases('SM-05-C02')
def test_SM_05_C02_metadata_read_authenticates_envelope(persisted_candidate):
    registry, root, record = persisted_candidate
    registry.register_candidate(record, evidence_root=root)
    path = registry.root / "S900/candidates/C0001.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["record_sha256"] = "f" * 64
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RegistryError, match="identity differs"):
        registry.get_candidate_registration(record.key)


@pytest.mark.risk_cases('SM-05-C03')
def test_SM_05_C03_registration_does_not_authenticate_historical_attachments(persisted_candidate):
    registry, root, record = persisted_candidate
    (root / record.origin.evidence[0].path).unlink()
    assert registry.register_candidate(record, evidence_root=root) == record
    assert registry.register_candidate(record, evidence_root=root) == record
    # The explicitly deep retained-file getter keeps its inspection/freeze contract.
    with pytest.raises(ValidationError, match="missing"):
        registry.get_candidate(record.key, evidence_root=root)


@pytest.mark.risk_cases('SM-05-C04')
def test_SM_05_C04_registration_reads_each_snapshot_file_once(persisted_candidate, monkeypatch):
    from pathlib import Path

    registry, root, record = persisted_candidate
    observed = []
    read = Path.read_bytes
    def counted(path):
        observed.append(path)
        return read(path)
    monkeypatch.setattr(Path, "read_bytes", counted)
    registry.register_candidate(record, evidence_root=root)
    assert observed.count(root / record.payload.path) == 1
    assert observed.count(root / record.source_files[0].path) == 1
    assert root / record.origin.evidence[0].path not in observed


@pytest.mark.risk_cases('SM-04-C01')
def test_SM_04_C01_missing_declared_source_prevents_registration(persisted_candidate):
    registry, root, record = persisted_candidate
    (root / record.source_files[0].path).unlink()
    with pytest.raises(ValidationError, match="missing"):
        registry.register_candidate(record, evidence_root=root)
    assert not (registry.root / "S900/candidates/C0001.json").exists()


@pytest.mark.parametrize('condition', [
    pytest.param("missing", id='SM-04-C04'),
    pytest.param("tampered", id='SM-04-C05'),
])
@pytest.mark.risk_cases('SM-04-C04', 'SM-04-C05')
def test_frozen_data_resource_is_authenticated_separately(persisted_candidate, condition):
    registry, root, record = persisted_candidate
    resource = b"date,value\n2026-10-01,1\n"
    fingerprint = sha256(resource).hexdigest()
    name = "data/observations.csv"
    payload = json.loads((root / record.payload.path).read_bytes())
    payload["runtime"]["kind"] = "ACCOUNT_REPLAY"
    payload["equity_definition"] = {"observation_inputs": [
        {"asset": {"relative_path": name, "sha256": fingerprint}},
    ]}
    payload_bytes = json.dumps(payload).encode("utf-8")
    (root / record.payload.path).write_bytes(payload_bytes)
    asset = CandidateEvidence(f"{record.source_root}/{name}", fingerprint)
    record = replace(record,
        payload=CandidateEvidence(record.payload.path, sha256(payload_bytes).hexdigest()),
        source_files=(*record.source_files, asset))
    if condition == "tampered":
        (root / asset.path).parent.mkdir(parents=True)
        (root / asset.path).write_bytes(b"altered resource")
    with pytest.raises(ValidationError, match="missing" if condition == "missing" else "hash differs"):
        registry.register_candidate(record, evidence_root=root)
    assert not (registry.root / "S900/candidates/C0001.json").exists()
