"""Local publication transactions using synthetic releases in isolated repos.

The inspection trust boundary is supplied separately here; full governance and
market acceptance are exercised by their own public-path tests and evidence.
"""

from dataclasses import replace
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
from strategy_runtime import RuntimeCompatibilityError, StrategyCandidate, implementation_sha256

from czsc_trader.application import RepositoryContext, validate_release_package
from czsc_trader.application import runtime_migration as m
from czsc_trader.application import research_evidence as e
from czsc_trader.application.inspection_service import _EvidenceStore
from strategy_manager import StrategyRegistry, CandidateKey, canonical_sha256
from strategy_manager import freeze_contracts as f
from test_current_contracts import (
    current_frozen as current_frozen, inspection as inspection,
    managed_evaluation as managed_evaluation,
)


def _inspected_migration_release(context, owner, stored, candidate, manifest, binding, source):
    """Persist exact reviewed bytes at the mocked completed-inspection boundary."""
    version = replace(stored, strategy_payload=json.loads(json.dumps(dict(candidate.payload), default=dict)),
                      release_hash="0" * 64)
    version = replace(version, release_hash=canonical_sha256(version.release_payload()))
    migrated_binding = {**binding, "release_hash": version.release_hash,
                        "implementation_sha256": candidate.payload["runtime"]["source_sha256"]}
    store = _EvidenceStore(context, owner)
    package = context.strategy_root / stored.strategy_id / "releases" / stored.version
    files = []
    prefix = manifest["runtime_root"] + "/"
    for path in sorted(manifest["files"]):
        if path == "runtime_binding.json":
            ref = store.put_json(migrated_binding)
        elif path.startswith(prefix):
            relative = path.removeprefix(prefix)
            root = candidate.source_root if relative in candidate.payload["runtime"]["source_files"] else source
            ref = store.put((root / relative).read_bytes())
        else:
            ref = store.put((package / path).read_bytes())
        files.append(f.FreezeFile(path, ref))
    inspected_manifest = {key: value for key, value in manifest.items() if key != "package_hash"}
    inspected_manifest.update(strategy_version_hash=version.release_hash, candidate_package_hash="b" * 64,
                              files={item.path: item.source.sha256 for item in files})
    inspected_manifest["package_hash"] = canonical_sha256(inspected_manifest)
    return f.InspectedRelease(store.put_json(version.to_dict()), store.put_json(inspected_manifest),
                              tuple(files), version.release_hash, inspected_manifest["package_hash"])


@pytest.fixture
def upgrade(current_frozen, monkeypatch):
    context, stored = current_frozen
    root, strategies = context.root, context.strategy_root
    original_manifest, binding, source = validate_release_package(context, "S900-v1")
    stored = StrategyRegistry(strategies).get_version("S900", "v1")
    original = f.FrozenVersionReference("S900", "v1", stored.release_hash, original_manifest["package_hash"])
    lifecycle = {"schema_version": 1, "event_id": "EVT-synthetic-paper", "event_type": "PAPER_APPROVED",
        "strategy_id": "S900", "version": "v1", "release_hash": stored.release_hash,
        "from_state": "RESEARCH", "to_state": "PAPER_READY", "evidence_ids": [],
        "actor": "synthetic-fixture", "reason": "transaction qualification boundary",
        "occurred_at": "2026-10-20T00:00:00+08:00"}
    (strategies / "S900/lifecycle.jsonl").write_text(json.dumps(lifecycle) + "\n")
    ref = f.ResearchEvidenceRef(f.ResearchEvidenceOwner("S900", "EX001_20261020"), "a" * 64 + ".json", "a" * 64)
    candidate_source = root / ".tmp/upgrade-source"
    shutil.copytree(source, candidate_source)
    payload = json.loads(json.dumps(dict(stored.strategy_payload), default=dict))
    payload["parameters"]["threshold"] = 0.75
    changed_source = candidate_source / payload["runtime"]["source_files"][0]
    changed_source.write_bytes(changed_source.read_bytes() + b"\n# Synthetic upgrade revision.\n")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        tuple(payload["runtime"]["source_files"]), source_root=candidate_source)
    candidate = StrategyCandidate("S900", "C9876", payload, candidate_source)
    release = _inspected_migration_release(context, ref.owner, stored, candidate, original_manifest, binding, source)
    report = SimpleNamespace(plan=SimpleNamespace(sha256="b" * 64), release=release)
    # Only replace the completed inspection boundary. Package authentication,
    # exact source publication, CAS, archive, lifecycle and rollback stay real.
    monkeypatch.setattr(m, "_upgrade_inputs", lambda *args: (
        report, candidate, stored, original_manifest, binding, source))
    request = m.FrozenRuntimeUpgradeRequest(original, CandidateKey("S900", candidate.candidate_id),
                                           ref, ref, root / ".tmp/prepared")
    return context, request, stored


def _bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_upgrade_prepares_then_preserves_history_archives_and_commits_idempotently(upgrade):
    context, request, stored = upgrade
    before = _bytes(context.strategy_root)
    assert StrategyRegistry(context.strategy_root).current_qualification("S900", "v1").value == "PAPER_READY"
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    assert _bytes(context.strategy_root) == before
    assert prepared.migrated.version == prepared.original.version == "v1"
    release = m._upgrade_inputs(context, request)[0].release
    stage = prepared.plan_path.parent / "staged/S900"
    assert (stage / "versions/v1.json").read_bytes() == release.version_record.resolve(context.root).read_bytes()
    assert (stage / "releases/v1/release_manifest.json").read_bytes() == release.manifest.resolve(context.root).read_bytes()
    for item in release.files:
        assert (stage / "releases/v1" / item.path).read_bytes() == item.source.resolve(context.root).read_bytes()
    receipt = m.apply_frozen_runtime_upgrade(context, prepared)
    assert receipt.status == "COMMITTED"
    current = StrategyRegistry(context.strategy_root).get_version("S900", "v1")
    old, new = stored.to_dict(), current.to_dict()
    for field in ("strategy_payload", "release_hash"):
        old.pop(field)
        new.pop(field)
    assert old == new
    assert current.strategy_payload["decision_feedback"] == "MARKET_INTENT"
    assert current.strategy_payload["runtime"]["contract_version"] == 2
    assert StrategyRegistry(context.strategy_root).current_qualification("S900", "v1").value == "RESEARCH"
    for name, data in before.items():
        if name.startswith("S900/releases/v1/"):
            assert (receipt.archive_path / "strategies" / name).read_bytes() == data
        elif name == "S900/versions/v1.json":
            assert (receipt.archive_path / "strategies" / name).read_bytes() == data
        elif name == "deployments/S900-v1.json":
            assert (receipt.archive_path / "strategies" / name).read_bytes() == data
        else:
            assert (context.strategy_root / name).read_bytes() == data
    committed = _bytes(context.strategy_root)
    assert m.apply_frozen_runtime_upgrade(context, prepared) == receipt
    assert _bytes(context.strategy_root) == committed
    historic, _, _, source = m._migration_original(context, request.original)
    assert historic.to_dict() == stored.to_dict()
    assert source.is_relative_to(receipt.archive_path)



@pytest.mark.parametrize("change", ["archive", "deployment"])
def test_committed_upgrade_retry_authenticates_archive_and_deployment(upgrade, change):
    context, request, _ = upgrade
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    receipt = m.apply_frozen_runtime_upgrade(context, prepared)
    if change == "archive":
        path = receipt.archive_path / "strategies/S900/versions/v1.json"
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        (context.strategy_root / "deployments/S900-v1.json").write_bytes(
            (receipt.archive_path / "strategies/deployments/S900-v1.json").read_bytes())
    with pytest.raises((ValueError, RuntimeCompatibilityError), match="archived file|archive differs|deployment|receipt"):
        m.apply_frozen_runtime_upgrade(context, prepared)


def test_upgrade_rejects_changed_staging_before_original_writes(upgrade):
    context, request, stored = upgrade
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    package = prepared.plan_path.parent / "staged/S900/releases/v1"
    manifest = json.loads((package / "release_manifest.json").read_bytes())
    source = stored.strategy_payload["runtime"]["source_files"][0]
    (package / manifest["runtime_root"] / source).write_bytes(b"changed")
    before = _bytes(context.strategy_root)
    with pytest.raises(ValueError, match="staged file identity"):
        m.apply_frozen_runtime_upgrade(context, prepared)
    assert _bytes(context.strategy_root) == before


def test_upgrade_compares_original_version_bytes_after_preparation(upgrade):
    context, request, _ = upgrade
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    path = context.strategy_root / "S900/versions/v1.json"
    path.write_bytes(path.read_bytes() + b"\n")
    before = _bytes(context.strategy_root)
    with pytest.raises(ValueError, match="changed after preparation"):
        m.apply_frozen_runtime_upgrade(context, prepared)
    assert all((context.strategy_root / name).read_bytes() == data for name, data in before.items())
    assert not (context.strategy_root / "revisions").exists()


def test_upgrade_deployment_failure_restores_original_package_version_and_receipt(upgrade, monkeypatch):
    context, request, _ = upgrade
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    before = _bytes(context.strategy_root)
    original_write = m._upgrade_write
    failed = False

    def fail_once(path, data, scratch):
        nonlocal failed
        if path.parent.name == "deployments" and not failed:
            failed = True
            raise OSError("injected deployment publication failure")
        return original_write(path, data, scratch)

    monkeypatch.setattr(m, "_upgrade_write", fail_once)
    with pytest.raises(RuntimeError, match="original content restored"):
        m.apply_frozen_runtime_upgrade(context, prepared)
    assert failed
    assert all((context.strategy_root / name).read_bytes() == data for name, data in before.items())
    manifest, _, _ = validate_release_package(context, "S900-v1")
    assert manifest["package_hash"] == request.original.package_hash
    archive = context.strategy_root / "revisions/S900-v1" / request.original.release_hash
    assert json.loads((archive / "rollback.json").read_bytes())["status"] == "ROLLED_BACK"
    assert not (archive / "upgrade_receipt.json").exists()
    with pytest.raises(ValueError, match="nonterminal archive"):
        m.apply_frozen_runtime_upgrade(context, prepared)


@pytest.mark.parametrize("terminal", [True, False])
def test_sameversion_target_distinguishes_historical_commit_from_pending_unknown(tmp_path, monkeypatch, terminal):
    context = RepositoryContext(tmp_path, tmp_path / "research", tmp_path / "research/registrations", tmp_path / "strategies")
    original = SimpleNamespace(version="v1", parent_version=None, selection_data_cutoff="2026-09-01", forward_start="2026-09-02")
    subject = SimpleNamespace(candidate=CandidateKey("S011", "C9901"))
    monkeypatch.setattr(e, "validate_migration_selection", lambda *args: original)
    request_id = f.FreezeRequestId("S011", "historical")
    journal = tmp_path / "research/S011/freeze_requests/historical"
    journal.mkdir(parents=True)
    (journal / "request.json").write_text(json.dumps({"version": {"version": "v1"},
        "request_id": request_id.to_dict(), "request_sha256": "a" * 64}))
    if terminal:
        committed = f.FreezeReceipt(request_id, f.FreezeStatus.COMMITTED, "a" * 64,
            f.FrozenVersionReference("S011", "v1", "b" * 64, "c" * 64))
        (journal / "committed.json").write_text(json.dumps(committed.to_dict()))
    monkeypatch.setattr(StrategyRegistry, "get_freeze_result", lambda *args, **kwargs:
        f.FreezeReceipt(request_id, f.FreezeStatus.UNKNOWN, "a" * 64, reason="synthetic unresolved"))
    if terminal:
        e.validate_migration_target(context, subject, "v1", None, "2026-09-01", "2026-09-02", available=True)
    else:
        with pytest.raises(ValueError, match="reserved"):
            e.validate_migration_target(context, subject, "v1", None, "2026-09-01", "2026-09-02", available=True)


def test_sameversion_parent_must_remain_original_parent(tmp_path, monkeypatch):
    original = SimpleNamespace(version="v2", parent_version="v1", selection_data_cutoff="2026-09-01", forward_start="2026-09-02")
    monkeypatch.setattr(e, "validate_migration_selection", lambda *args: original)
    with pytest.raises(ValueError, match="preserve original parent"):
        e.validate_migration_target(None, None, "v2", "v2", "2026-09-01", "2026-09-02")


def test_upgrade_preparation_and_receipt_reject_untyped_public_values():
    old = f.FrozenVersionReference("S900", "v1", "a" * 64, "b" * 64)
    new = f.FrozenVersionReference("S900", "v1", "c" * 64, "d" * 64)
    with pytest.raises(TypeError, match="plan_path"):
        m.PreparedFrozenRuntimeUpgrade(".tmp/plan", "e" * 64, old, new)
    with pytest.raises(ValueError, match="SHA-256"):
        m.PreparedFrozenRuntimeUpgrade(Path(".tmp/plan"), "invalid", old, new)
    with pytest.raises(TypeError, match="FreezeStatus"):
        m.FrozenRuntimeUpgradeReceipt("COMMITTED", old, new, Path("archive"), Path("receipt"))

    with pytest.raises(ValueError, match="four ASCII digits"):
        m.FrozenRuntimeMigrationRequest("S001-v1", "migration", Path(".tmp/new"))
    with pytest.raises(ValueError, match="no reviewed adapter"):
        m.FrozenRuntimeMigrationRequest("S099-v1", "C9899", Path(".tmp/new"))
