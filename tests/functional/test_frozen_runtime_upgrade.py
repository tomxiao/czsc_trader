"""Local publication transactions using synthetic releases in isolated repos.

Candidate sources, audit references, package construction, CAS, archives and
rollback run through the real upgrade API without completed-inspection substitutes.
"""

import ast
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
from strategy_runtime import RuntimeCompatibilityError, StrategyCandidate, implementation_sha256

from czsc_trader.application import RepositoryContext, validate_release_package
from czsc_trader.application import runtime_migration as m
from czsc_trader.application import research_evidence as e
from strategy_manager import StrategyRegistry, CandidateKey, ValidationError
from strategy_manager import freeze_contracts as f
from test_current_contracts import (
    current_frozen as current_frozen, inspection as inspection,
    managed_evaluation as managed_evaluation,
)


def _audit_ref(context, value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = sha256(data).hexdigest()
    owner = f.ResearchEvidenceOwner("S900", "EX001_20261020")
    path = context.root / owner.repository_path / (digest + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f.ResearchEvidenceRef(owner, path.name, digest)


@pytest.fixture
def upgrade(current_frozen):
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
    ref = _audit_ref(context, {"authorization": "Synthetic explicit same-version upgrade approval"})
    candidate_source = root / ".tmp/upgrade-source/strategy_runtime"
    shutil.copytree(source, candidate_source)
    payload = json.loads(json.dumps(dict(stored.strategy_payload), default=dict))
    payload["parameters"]["threshold"] = 0.75
    changed_source = candidate_source / payload["runtime"]["source_files"][0]
    changed_source.write_bytes(changed_source.read_bytes() + b"\n# Synthetic upgrade revision.\n")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        tuple(payload["runtime"]["source_files"]), source_root=candidate_source)
    candidate = StrategyCandidate("S900", "C9876", payload, candidate_source)
    request = m.FrozenRuntimeUpgradeRequest(
        original, candidate, ref,
        "Synthetic parameter and implementation revision", "synthetic-researcher", (),
        root / ".tmp/prepared",
    )
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
    candidate = request.candidate
    stage_context = replace(context, strategy_root=prepared.plan_path.parent / "staged")
    manifest, binding, staged_source = validate_release_package(stage_context, "S900-v1")
    assert manifest["package_hash"] == prepared.migrated.package_hash
    assert binding["source_files"] == list(candidate.payload["runtime"]["source_files"])
    for name in binding["source_files"]:
        assert (staged_source / name).read_bytes() == (candidate.source_root / name).read_bytes()
    plan = json.loads(prepared.plan_path.read_bytes())
    assert plan["schema_version"] == 2
    assert plan["confirmation"] == request.confirmation.to_dict()
    assert plan["change_summary"] == request.change_summary
    assert plan["operator"] == request.operator
    assert plan["evidence"] == []
    assert "inspection" not in plan
    # Application publishes the reviewed snapshot, not the mutable research workspace.
    workspace_source = candidate.source_root / binding["source_files"][0]
    workspace_source.write_bytes(workspace_source.read_bytes() + b"\n# Later workspace edit.\n")
    receipt = m.apply_frozen_runtime_upgrade(context, prepared)
    assert receipt.status == "COMMITTED"
    current = StrategyRegistry(context.strategy_root).get_version("S900", "v1")
    old, new = stored.to_dict(), current.to_dict()
    for field in ("strategy_payload", "release_hash"):
        old.pop(field)
        new.pop(field)
    assert old == new
    assert current.strategy_payload["parameters"]["threshold"] == 0.75
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


@pytest.mark.parametrize("status", ["FAIL", "INCOMPLETE", "NOT_REQUESTED"])
def test_upgrade_records_optional_evidence_without_interpreting_research_result(upgrade, status):
    context, request, _ = upgrade
    evidence = _audit_ref(context, {"status": status, "summary": "Synthetic research diagnostic"})
    request = replace(request, evidence=(evidence,))
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    plan = json.loads(prepared.plan_path.read_bytes())
    assert plan["evidence"] == [evidence.to_dict()]
    receipt = m.apply_frozen_runtime_upgrade(context, prepared)
    audit = json.loads(receipt.receipt_path.read_bytes())
    assert audit["status"] == "COMMITTED"
    assert audit["confirmation"] == request.confirmation.to_dict()
    assert audit["evidence"] == [evidence.to_dict()]
    assert audit["operator"] == request.operator
    assert audit["change_summary"] == request.change_summary
    assert json.loads(evidence.resolve(context.root).read_bytes())["status"] == status


@pytest.mark.parametrize("reference", ["confirmation", "evidence"])
def test_upgrade_rejects_corrupted_audit_reference_before_publication(upgrade, reference):
    context, request, _ = upgrade
    evidence = _audit_ref(context, {"status": "FAIL"})
    request = replace(request, evidence=(evidence,))
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    damaged = request.confirmation if reference == "confirmation" else evidence
    damaged.resolve(context.root).write_bytes(b"changed")
    before = _bytes(context.strategy_root)
    with pytest.raises(ValidationError, match="hash|digest"):
        m.apply_frozen_runtime_upgrade(context, prepared)
    assert _bytes(context.strategy_root) == before


def test_upgrade_accepts_inherited_strategy_declaration_on_both_sides(upgrade):
    context, request, _ = upgrade
    candidate = request.candidate
    payload = json.loads(json.dumps(dict(candidate.payload), default=dict))
    entry = candidate.source_root / payload["runtime"]["source_files"][0]
    tree = ast.parse(entry.read_text(encoding="utf-8"))
    name = payload["runtime"]["qualname"]
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    cls.name = "InheritedDefinitionBase"
    tree.body.extend(ast.parse(f"class {name}(InheritedDefinitionBase):\n    pass\n").body)
    entry.write_text(ast.unparse(ast.fix_missing_locations(tree)) + "\n", encoding="utf-8")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        tuple(payload["runtime"]["source_files"]), source_root=candidate.source_root)
    candidate = StrategyCandidate("S900", "C9876", payload, candidate.source_root)
    first = m.prepare_frozen_runtime_upgrade(context, replace(request, candidate=candidate))
    assert m.apply_frozen_runtime_upgrade(context, first).status.value == "COMMITTED"

    # The next upgrade starts from a frozen package whose entry class inherits its declaration.
    _, _, frozen_source = validate_release_package(context, "S900-v1")
    next_source = context.root / ".tmp/inherited-second-source/strategy_runtime"
    shutil.copytree(frozen_source, next_source)
    entry = next_source / payload["runtime"]["source_files"][0]
    entry.write_bytes(entry.read_bytes() + b"\n# Further explanation revision.\n")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        tuple(payload["runtime"]["source_files"]), source_root=next_source)
    next_request = replace(request, original=first.migrated,
        candidate=StrategyCandidate("S900", "C9878", payload, next_source),
        output_directory=context.root / ".tmp/second-prepared")
    second = m.prepare_frozen_runtime_upgrade(context, next_request)
    assert m.apply_frozen_runtime_upgrade(context, second).status.value == "COMMITTED"
    assert first.migrated != second.migrated


def test_upgrade_rejects_stale_original_identity(upgrade):
    context, request, _ = upgrade
    before = _bytes(context.strategy_root)
    stale = replace(request, original=replace(request.original, package_hash="f" * 64))
    with pytest.raises(ValueError, match="identity"):
        m.prepare_frozen_runtime_upgrade(context, stale)
    assert _bytes(context.strategy_root) == before


@pytest.mark.parametrize("field,value", [
    ("change_summary", ""), ("operator", " "), ("evidence", []),
    ("evidence", ("not-a-reference",)), ("candidate", CandidateKey("S900", "C9876")),
])
def test_upgrade_request_rejects_missing_audit_or_untyped_inputs(upgrade, field, value):
    _, request, _ = upgrade
    with pytest.raises((TypeError, ValueError)):
        replace(request, **{field: value})


def test_committed_receipt_audit_must_match_archived_plan(upgrade):
    context, request, _ = upgrade
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    receipt = m.apply_frozen_runtime_upgrade(context, prepared)
    raw = json.loads(receipt.receipt_path.read_bytes())
    raw["operator"] = "different-operator"
    receipt.receipt_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="archive audit differs"):
        m.apply_frozen_runtime_upgrade(context, prepared)


def test_archived_audit_snapshot_remains_bound_to_original_evidence_hash(upgrade):
    context, request, _ = upgrade
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    receipt = m.apply_frozen_runtime_upgrade(context, prepared)
    name = "audit/" + request.confirmation.sha256
    changed = receipt.archive_path / name
    changed.write_bytes(b"replacement confirmation")
    # Recomputing a local file manifest must not change the evidence identity.
    snapshot_path = receipt.archive_path / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_bytes())
    snapshot["files"][name] = sha256(changed.read_bytes()).hexdigest()
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(ValueError, match="archived audit evidence differs"):
        m.apply_frozen_runtime_upgrade(context, prepared)


def test_committed_upgrade_audit_is_self_contained_after_source_evidence_is_unavailable(upgrade):
    context, request, _ = upgrade
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    receipt = m.apply_frozen_runtime_upgrade(context, prepared)
    request.confirmation.resolve(context.root).unlink()
    assert m.apply_frozen_runtime_upgrade(context, prepared) == receipt


def test_schema_one_archive_is_read_only_and_preserves_original_bytes(upgrade):
    context, request, stored = upgrade
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    receipt = m.apply_frozen_runtime_upgrade(context, prepared)
    archive = receipt.archive_path
    plan_path = archive / "upgrade_plan.json"
    plan = json.loads(plan_path.read_bytes())
    plan["schema_version"] = 1
    plan["inspection"] = request.confirmation.to_dict()
    for name in ("change_summary", "operator", "evidence", "candidate_identity", "changes"):
        plan.pop(name)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    plan_sha = sha256(plan_path.read_bytes()).hexdigest()
    raw = json.loads(receipt.receipt_path.read_bytes())
    for name in ("schema_version", "change_summary", "operator", "evidence", "committed_at"):
        raw.pop(name)
    raw.update(plan_sha256=plan_sha, inspection=plan["inspection"])
    receipt.receipt_path.write_text(json.dumps(raw), encoding="utf-8")
    snapshot_path = archive / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_bytes())
    snapshot["plan_sha256"] = plan_sha
    snapshot["files"]["upgrade_plan.json"] = plan_sha
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    before = _bytes(archive)
    original, _, _, source = m._migration_original(context, request.original)
    assert original.to_dict() == stored.to_dict()
    assert source.is_relative_to(archive)
    assert _bytes(archive) == before
    prepared.plan_path.write_bytes(plan_path.read_bytes())
    old_prepared = replace(prepared, plan_sha256=plan_sha)
    with pytest.raises(ValueError, match="historical plans are read-only"):
        m.apply_frozen_runtime_upgrade(context, old_prepared)
    assert _bytes(archive) == before
