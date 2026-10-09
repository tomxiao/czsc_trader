"""SM publication durability through its public request, registry and query APIs."""

from dataclasses import replace
from hashlib import sha256
import json

import pytest
from strategy_manager import (
    CandidateEvidence, DecisionReference, FreezeFile, FreezeReceipt, FreezeRequestId,
    FreezeStatus, FreezeVersionRequest, RegistryError, ResearchDecision,
    ResearchEvidenceOwner, ResearchEvidenceRef, ResearchState, StrategyFamily,
    StrategyRegistry, StrategyVersion, ValidationError, canonical_sha256,
)


@pytest.fixture
def publication(tmp_path):
    """A complete SM package input; no research execution is needed to publish it."""
    raw = {
        "schema_version": 5, "strategy_id": "S900", "version": "v1",
        "release_id": "S900-v1", "parent_version": None,
        "change_summary": "synthetic SM publication", "source_experiment": "20261001_S900_EX01",
        "source_candidate": "C0001", "selection_data_cutoff": "2026-09-21",
        "forward_start": "2026-09-22", "strategy_payload": {"fixture": "SM publication"},
    }
    version = StrategyVersion.from_dict({**raw, "release_hash": canonical_sha256(raw)})
    family = StrategyFamily(2, "S900", "Publication fixture", "ETF", {"hypothesis": "synthetic"},
        ResearchState.RESEARCHING, "2026-10-01T00:00:00+00:00", "test", "2026-10-01T00:00:00+00:00")
    package = tmp_path / "staged"
    (package / "src/strategy_runtime").mkdir(parents=True)
    (package / "src/strategy_runtime/fixture.py").write_text("# SM payload fixture\n", encoding="utf-8")
    (package / "runtime_binding.json").write_text(json.dumps({
        "release_id": version.release_id, "release_hash": version.release_hash,
    }), encoding="utf-8")
    manifest = {
        "schema_version": 1, "strategy_version_id": version.release_id,
        "strategy_version_hash": version.release_hash, "source_candidate_id": "S900-C0001",
        "candidate_package_hash": "a" * 64, "runtime_root": "src/strategy_runtime",
        "runtime_binding": "runtime_binding.json",
        "files": {path.relative_to(package).as_posix(): sha256(path.read_bytes()).hexdigest()
                  for path in package.rglob("*") if path.is_file()},
    }
    digest = canonical_sha256(manifest)
    (package / "release_manifest.json").write_text(json.dumps({**manifest, "package_hash": digest}), encoding="utf-8")
    request = FreezeVersionRequest(FreezeRequestId("S900", "request1"), "b" * 64,
        version, family, package, digest, tmp_path / "journal")
    return StrategyRegistry(tmp_path / "strategies"), request


@pytest.mark.parametrize("after_commit", [False, True])
def test_publication_interruption_respects_visibility(publication, monkeypatch, after_commit):
    from strategy_manager import freeze_store

    registry, request = publication
    durable = freeze_store._durable
    class Interrupted(BaseException):
        pass
    def interrupt(path, value, **kwargs):
        if path.name == "v1.json":
            assert registry.get_freeze_result(request.request_id, journal_root=request.journal_root).status is FreezeStatus.IN_PROGRESS
            assert registry.versions("S900") == ()
            if after_commit:
                durable(path, value, **kwargs)
            raise Interrupted()
        return durable(path, value, **kwargs)
    # Inject the disk interruption; all publication and query behavior runs publicly.
    monkeypatch.setattr(freeze_store, "_durable", interrupt)
    with pytest.raises(Interrupted):
        registry.freeze_version(request)
    receipt = registry.get_freeze_result(request.request_id, journal_root=request.journal_root)
    assert receipt.status is (FreezeStatus.COMMITTED if after_commit else FreezeStatus.UNKNOWN)
    assert registry.freeze_version(request) == receipt
    assert bool(registry.versions("S900")) is after_commit
    if not after_commit:
        with pytest.raises(RegistryError, match="unresolved"):
            registry.freeze_version(replace(request, request_id=FreezeRequestId("S900", "other")))


@pytest.mark.parametrize("failure", ["commit", "version", "corrupt_request"])
def test_publication_failure_is_terminal_and_never_retried(publication, monkeypatch, failure):
    from strategy_manager import freeze_store

    registry, request = publication
    if failure != "corrupt_request":
        durable = freeze_store._durable
        def fail(path, value, **kwargs):
            if path.name == ("committed.json" if failure == "commit" else "v1.json"):
                raise OSError("synthetic disk failure")
            return durable(path, value, **kwargs)
        monkeypatch.setattr(freeze_store, "_durable", fail)
    receipt = registry.freeze_version(request)
    if failure == "corrupt_request":
        journal = request.journal_root / request.request_id.value / "request.json"
        journal.write_text("{malformed", encoding="utf-8")
        receipt = registry.get_freeze_result(request.request_id, journal_root=request.journal_root)
        assert receipt.request_sha256 is None
    assert receipt.status is (FreezeStatus.FAILED if failure == "commit" else FreezeStatus.UNKNOWN)
    assert receipt.version is None
    assert registry.freeze_version(request) == receipt
    assert registry.get_freeze_result(request.request_id, journal_root=request.journal_root) == receipt
    if failure == "corrupt_request":
        assert journal.read_text(encoding="utf-8") == "{malformed"
        assert registry.get_version("S900", "v1") == request.version
    else:
        assert registry.versions("S900") == ()
        if failure == "commit":
            assert "disk failure" in receipt.reason


def test_publication_conflicting_version_is_rejected(publication):
    registry, request = publication
    assert registry.freeze_version(request).status is FreezeStatus.COMMITTED
    with pytest.raises(RegistryError, match="target version"):
        registry.freeze_version(replace(request, request_id=FreezeRequestId("S900", "other")))
    assert registry.get_version("S900", "v1") == request.version


def test_public_freeze_contracts_reject_untyped_or_incomplete_inputs():
    with pytest.raises(TypeError):
        ResearchDecision("d1", "S900", "APPROVE", None, None, "reason")
    with pytest.raises(ValueError):
        FreezeReceipt(FreezeRequestId("S900", "r1"), FreezeStatus.COMMITTED, "a" * 64)
    with pytest.raises(ValidationError):
        FreezeFile("../outside.py", CandidateEvidence("source.py", "a" * 64))


def test_public_research_evidence_resolves_only_within_its_owner(tmp_path):
    evidence = tmp_path / "research/S900/decisions/selection.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"decision":"synthetic"}', encoding="utf-8")
    reference = ResearchEvidenceRef(ResearchEvidenceOwner("S900"), "decisions/selection.json", sha256(evidence.read_bytes()).hexdigest())
    assert reference.resolve(tmp_path) == evidence
    assert ResearchEvidenceRef.from_dict(reference.to_dict()) == reference
    with pytest.raises(ValidationError):
        reference.resolve(tmp_path / "strategies")
    with pytest.raises(ValidationError):
        replace(reference, path="../other.json")
    with pytest.raises(ValueError, match="owner"):
        ResearchEvidenceOwner("S900", "20261001_S901_EX01")
    with pytest.raises(ValidationError):
        replace(reference, owner=ResearchEvidenceOwner("S901")).resolve(tmp_path)
    with pytest.raises(TypeError):
        DecisionReference("selection", CandidateEvidence("arbitrary.json", "a" * 64))


def test_experiment_evidence_resolves_from_batch_without_archive_manifest(tmp_path):
    owner = ResearchEvidenceOwner("S900", "EX001_20261003")
    assert owner.repository_path == "research/S900/assets/evidence/EX001_20261003"
    evidence = tmp_path / owner.repository_path / "inspection/result.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(b'{"result":"synthetic"}')
    reference = ResearchEvidenceRef(owner, "inspection/result.json", sha256(evidence.read_bytes()).hexdigest())
    assert reference.resolve(tmp_path) == evidence
