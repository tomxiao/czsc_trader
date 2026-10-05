from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from dataclasses import replace

import pytest
from strategy_manager import (
    GovernanceStage, ResearchEvidenceLocation, ResearchEvidenceOwner,
    ResearchEvidenceRef, StrategyRegistry,
)
from czsc_trader.research_tools import ResearchWorkspace
from czsc_trader.application import (
    RepositoryContext, ValidationError, create_research_batch, update_research_intent,
)


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _batch(**changes):
    return {"strategy_id": "S910", "name": "public research identity", "scope": ["588080.SH"],
            "research_intent": {"objective": "synthetic"}, "credential_id": "SGC-S910-001", **changes}


def _tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def governance(minimal_repo):
    owner = ResearchEvidenceOwner("S910")
    context = RepositoryContext.discover(minimal_repo, research_workspace=ResearchWorkspace(
        "storage/governance", evidence=(ResearchEvidenceLocation(owner, "notes/arbitrary/deep-space"),),
    ))
    material = minimal_repo / "notes/arbitrary/deep-space/approved-plan.txt"
    material.parent.mkdir(parents=True)
    material.write_bytes(b"Caller-selected research plan; approved by the user.\n")
    ref = ResearchEvidenceRef(owner, material.name, sha256(material.read_bytes()).hexdigest())
    # Existing conventional research contents must not influence registration.
    legacy = minimal_repo / "research/S910/HANDOFF.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"existing research evidence")
    return context, ref


def _create(context, material, request, **kwargs):
    return create_research_batch(context, request, material=material,
                                 actor="tester", reason="approved research", **kwargs)


def test_research_family_can_start_a_second_governed_batch(governance):
    context, material = governance
    before = _tree(context.root / "notes"), _tree(context.root / "research")
    initial = _create(context, material, _write_json(context.root / "first.json", _batch()))
    request = _write_json(context.root / "second.json", _batch(
        credential_id="SGC-S910-002", research_intent={"objective": "next version"},
    ))
    result = _create(context, material, request)
    repeated = _create(context, material, request)
    assert result.result == repeated.result
    updated = update_research_intent(
        context, "S910", _write_json(context.root / "update.json", {
            "research_intent": {"objective": "wait for new data"}, "research_state": "PAUSED",
        }), actor="tester", reason="pause for new data",
    )
    registry = StrategyRegistry(context.root / "storage/governance")
    assert registry.get_family("S910").research_intent == {"objective": "wait for new data"}
    for credential_id in ("SGC-S910-001", "SGC-S910-002"):
        credential = registry.get_governance_credential("S910", credential_id)
        assert credential.stage is GovernanceStage.RESEARCH_INITIATED
        assert credential.seals[-1].artifact_hashes["research_batch"] == material.sha256
        assert credential.seals[-1].content["material"] == material.to_dict()
    assert (initial.status, result.status, updated.status) == ("PASS", "PASS", "PASS")
    assert updated.result["family"]["research_state"] == "PAUSED"
    assert result.result["material"] == material.to_dict()
    assert (_tree(context.root / "notes"), _tree(context.root / "research")) == before
    assert not (context.root / "research/registrations").exists()
    assert not (context.strategy_root / "S910").exists()


@pytest.mark.parametrize("changes", [
    {"unexpected": True}, {"name": "conflicting name"}, {"scope": ["510500.SH"]},
    {"credential_id": "SGC-S910-001", "research_intent": {"objective": "conflict"}}, {"credential_id": None},
])
def test_research_creation_rejects_invalid_or_conflicting_batch_without_writes(governance, changes):
    context, material = governance
    _create(context, material, _write_json(context.root / "initial.json", _batch()))
    raw = _batch(credential_id="SGC-S910-002")
    raw.update(changes)
    request = _write_json(context.root / "invalid.json", raw)
    before = _tree(context.root)
    with pytest.raises(ValidationError) as error:
        _create(context, material, request)
    assert error.value.code == "research_batch_creation_failed"
    assert _tree(context.root) == before


@pytest.mark.parametrize("operation", ["create_family", "start_research_batch"])
def test_registration_failure_preserves_caller_materials(governance, monkeypatch, operation):
    context, material = governance
    raw = _batch()
    if operation == "start_research_batch":
        _create(context, material, _write_json(context.root / "initial.json", raw))
        raw = _batch(credential_id="SGC-S910-002")
    request = _write_json(context.root / "request.json", raw)
    before = _tree(context.root)
    observed = []
    def fail_registration(*args, **kwargs):
        observed.append(True)
        assert _tree(context.root) == before
        raise OSError("injected registration write failure")
    monkeypatch.setattr(StrategyRegistry, operation, fail_registration)
    with pytest.raises(ValidationError) as error:
        _create(context, material, request)
    assert error.value.code == "research_batch_creation_failed"
    assert observed == [True]
    assert _tree(context.root) == before


@pytest.mark.parametrize("update", [{}, {"unexpected": True}, {"research_state": "INVALID"}])
def test_research_intent_rejects_invalid_update_without_changing_identity(governance, update):
    context, material = governance
    _create(context, material, _write_json(context.root / "initial.json", _batch()))
    request = _write_json(context.root / "update.json", update)
    before = _tree(context.root)
    with pytest.raises(ValidationError) as error:
        update_research_intent(context, "S910", request, actor="tester", reason="invalid update")
    assert error.value.code == "research_intent_update_failed"
    assert _tree(context.root) == before


def test_research_intent_reports_registration_write_failure(governance, monkeypatch):
    context, material = governance
    _create(context, material, _write_json(context.root / "initial.json", _batch()))
    request = _write_json(context.root / "update.json", {"research_intent": {"objective": "changed"}})
    before = _tree(context.root)
    def fail(*args, **kwargs):
        raise OSError("injected intent registration write failure")
    monkeypatch.setattr(StrategyRegistry, "update_family", fail)
    with pytest.raises(ValidationError) as error:
        update_research_intent(context, "S910", request, actor="tester", reason="write failure")
    assert error.value.code == "research_intent_update_failed"
    assert _tree(context.root) == before


@pytest.mark.parametrize("fault", ["workspace", "material", "owner", "credential", "hash", "outside"])
def test_batch_requires_explicit_bindings_and_valid_material_before_writing(governance, fault):
    context, material = governance
    raw = _batch()
    request = _write_json(context.root / "request.json", raw)
    if fault == "workspace":
        context = replace(context, research_workspace=None)
    elif fault == "material":
        material = None
    elif fault == "owner":
        material = replace(material, owner=ResearchEvidenceOwner("S911"))
    elif fault == "credential":
        del raw["credential_id"]
        _write_json(request, raw)
    elif fault == "hash":
        material = replace(material, sha256="0" * 64)
    elif fault == "outside":
        request = context.root.parent / "outside.json"
        _write_json(request, raw)
    before = _tree(context.root)
    with pytest.raises(ValidationError) as error:
        _create(context, material, request)
    assert error.value.code == "research_batch_creation_failed"
    assert _tree(context.root) == before


def test_batch_material_and_registry_relocate_independently(governance):
    context, material = governance
    request = _write_json(context.root / "first.json", _batch())
    first = _create(context, material, request)
    old_root = context.root / "notes/arbitrary/deep-space"
    new_root = context.root / "relocated/materials"
    new_root.parent.mkdir()
    old_root.rename(new_root)
    (context.root / "storage/governance").rename(context.root / "relocated/identity-registry")
    moved = replace(context, research_workspace=ResearchWorkspace(
        "relocated/identity-registry", evidence=(ResearchEvidenceLocation(material.owner, "relocated/materials"),),
    ))
    before = _tree(new_root), _tree(context.root / "research")
    repeated = _create(moved, material, request)
    assert repeated.result == first.result
    assert (_tree(new_root), _tree(context.root / "research")) == before
    assert not (context.root / "storage/governance").exists()


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("space", ["sealed", "runtime"])
def test_governance_write_rejects_protected_registry_space(governance, operation, space):
    context, material = governance
    if space == "sealed":
        from czsc_trader.experiment_archive import build_experiment_manifest
        parent = context.root / "caller/sealed-archive"
        parent.mkdir(parents=True)
        for name in ("01_goal.md", "02_design.md", "03_execution.md", "04_conclusion.md"):
            (parent / name).write_text("synthetic", encoding="utf-8")
        build_experiment_manifest(parent, {"experiment_id": "EX001_20261005"})
    else:
        parent = context.strategy_root
    context = replace(context, research_workspace=replace(context.research_workspace,
                      registry_path=(parent / "nested/registry").relative_to(context.root).as_posix()))
    request = _write_json(context.root / "request.json", _batch() if operation == "create" else {
        "research_intent": {"objective": "updated"},
    })
    before = _tree(context.root)
    with pytest.raises(ValidationError, match="sealed|runtime publication") as error:
        if operation == "create":
            _create(context, material, request)
        else:
            update_research_intent(context, "S910", request, actor="tester", reason="update")
    assert error.value.code == ("research_batch_creation_failed" if operation == "create" else "research_intent_update_failed")
    assert _tree(context.root) == before
