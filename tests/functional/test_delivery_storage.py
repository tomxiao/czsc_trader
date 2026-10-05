from dataclasses import replace
from hashlib import sha256
import json
import shutil

import pytest

from czsc_trader.application import assemble_delivery, validate_delivery, load_candidate
from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive
from czsc_trader.research_tools import delivery as d
from strategy_manager import CandidateKey, StrategyRegistry, ValidationError
from test_research_delivery import (
    context as context,
    Deliverable,
    content,
    definition,
    owner_experiment,
    new_named_experiment,
    published,
)
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
from test_assessment_delivery import completed as completed


def test_caller_locations_support_mixed_roots_and_relocation(context):
    """A predecessor graph keeps its identity after all caller-selected roots move."""
    owner_experiment(context, 2)
    owners = (definition().owner, d.ExperimentOwner("S900", "20261001_S900_EX02"))
    sources = []
    locations = []
    for index, owner in enumerate(owners):
        path = f"caller/sources/group{index}/{owner.experiment_id}"
        source = context.root / path
        source.parent.mkdir(parents=True)
        original = context.experiments_root / "S900" / owner.experiment_id
        assert source.resolve().is_relative_to(context.root.resolve())
        original.rename(source)
        sources.append(d.ExperimentLocation(owner, path))
        locations.append(d.DeliveryLocation(owner, d.DeliveryStage.COMPONENTS, 1,
                                            f"caller/results/result{index}"))
    context = replace(context, delivery_workspace=d.DeliveryWorkspace(tuple(locations), tuple(sources)))
    first = assemble_delivery(context, Deliverable(definition(), content()))
    second_definition = replace(definition(), owner=owners[1], predecessors=(first.reference,))
    second = assemble_delivery(context, Deliverable(second_definition, content()))
    assert not (context.research_root / "S900").exists()
    assert not (context.experiments_root / "S900" / owners[0].experiment_id).exists()

    moved_deliveries = []
    moved_sources = []
    for location in (*locations, *sources):
        path = location.path.replace("caller/", "relocated/", 1)
        target = context.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        assert target.resolve().is_relative_to(context.root.resolve())
        (context.root / location.path).rename(target)
        moved = replace(location, path=path)
        (moved_deliveries if isinstance(location, d.DeliveryLocation) else moved_sources).append(moved)
    context = replace(context, delivery_workspace=d.DeliveryWorkspace(tuple(moved_deliveries), tuple(moved_sources)))
    before = tree(context.root)
    assert validate_delivery(context, second.reference).status is d.ValidationStatus.PASS
    assert assemble_delivery(context, Deliverable(second_definition, content())) == second
    assert tree(context.root) == before


@pytest.mark.parametrize("missing", ["workspace", "delivery", "experiment", "predecessor"])
def test_explicit_location_is_required_even_when_default_files_exist(context, missing):
    first = assemble_delivery(context, Deliverable(definition(), content()))
    successor = replace(definition(), revision=2, predecessors=(first.reference,))
    second = assemble_delivery(context, Deliverable(successor, content()))
    workspace = context.delivery_workspace
    if missing == "workspace":
        workspace = None
    elif missing == "experiment":
        workspace = replace(workspace, experiments=())
    else:
        revision = 2 if missing == "delivery" else 1
        workspace = replace(workspace, deliveries=tuple(
            x for x in workspace.deliveries
            if (x.owner, x.stage, x.revision) != (definition().owner, definition().stage, revision)
        ))
    context = replace(context, delivery_workspace=workspace)
    before = tree(context.root)
    validation = validate_delivery(context, second.reference)
    assert validation.status is d.ValidationStatus.FAIL
    assert validation.issues[0].code == ("EXPERIMENT_LOCATION" if missing == "experiment" else "DELIVERY_LOCATION")
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(context, Deliverable(successor, content()))
    assert tree(context.root) == before


def test_selected_source_does_not_fall_back_to_valid_default_owner(context):
    source = context.root / "caller" / definition().owner.experiment_id
    shutil.copytree(context.experiments_root / "S900" / source.name, source)
    (source / "experiment.py").write_text("changed")
    workspace = replace(context.delivery_workspace, experiments=(d.ExperimentLocation(
        definition().owner, source.relative_to(context.root).as_posix()),))
    context = replace(context, delivery_workspace=workspace)
    with pytest.raises(d.DeliveryValidationError, match="binding"):
        assemble_delivery(context, Deliverable(definition(), content()))
    location = next(x for x in workspace.deliveries
                    if (x.owner, x.stage, x.revision) == (definition().owner, definition().stage, 1))
    assert not (context.root / location.path).exists()


@pytest.mark.parametrize("foreign", [False, True])
def test_bound_source_location_checks_identity_without_default_layout(context, foreign):
    source, evidence = new_named_experiment(context, strategy_id="S901" if foreign else "S900")
    target = context.root / "caller" / "bound-code" / source.name
    target.parent.mkdir(parents=True)
    assert target.resolve().is_relative_to(context.root.resolve())
    source.rename(target)
    evidence = replace(evidence, workspace_path=f"{target.relative_to(context.root).as_posix()}/artifacts")
    owner = d.ExperimentOwner("S900", source.name)
    defined = d.DeliveryDefinition(owner, d.DeliveryStage.COMPONENTS, 1, experiments=(evidence,))
    workspace = d.DeliveryWorkspace(
        (d.DeliveryLocation(owner, defined.stage, 1, "caller/results/component-panel"),),
        (d.ExperimentLocation(owner, target.relative_to(context.root).as_posix()),),
    )
    context = replace(context, delivery_workspace=workspace)
    item = Deliverable(defined, content())
    if foreign:
        with pytest.raises(d.DeliveryValidationError, match="family or ID differs"):
            assemble_delivery(context, item)
        assert not (context.root / workspace.deliveries[0].path).exists()
    else:
        receipt = assemble_delivery(context, item)
        assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS


@pytest.mark.parametrize("paths", [("same", "same"), ("Case", "case"), ("a", "a/b")])
def test_workspace_rejects_conflicting_publication_locations(paths):
    owner = definition().owner
    with pytest.raises(ValueError):
        d.DeliveryWorkspace(tuple(d.DeliveryLocation(owner, d.DeliveryStage.COMPONENTS, index + 1, path)
                                  for index, path in enumerate(paths)), ())


def seal(root):
    for name in ("01_goal.md", "02_design.md", "03_execution.md", "04_conclusion.md"):
        (root / name).write_text("synthetic evidence", encoding="utf-8")
    return build_experiment_manifest(
        root,
        {
            "experiment_id": root.name,
            "strategy_id": "S900",
            "symbol": "588080.SH",
            "development_cutoff": "2026-09-30",
            "status": "COMPLETE",
        },
    )


def tree(root):
    return {
        p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }


def test_cross_experiment_revision_one_and_read_only_validation(context, monkeypatch):
    first = assemble_delivery(context, Deliverable(definition(), content()))
    owner_experiment(context, 2)
    second_definition = replace(
        definition(),
        owner=d.ExperimentOwner("S900", "20261001_S900_EX02"),
        predecessors=(first.reference,),
    )
    second = assemble_delivery(context, Deliverable(second_definition, content()))
    assert first.reference.revision == second.reference.revision == 1
    assert published(context, first) != published(context, second)
    before = tree(context.root)

    def no_execution(*args, **kwargs):
        raise AssertionError("validation must never import or execute experiment code")

    monkeypatch.setattr("research_experiment.load_experiment", no_execution)
    assert validate_delivery(context, second.reference).status is d.ValidationStatus.PASS
    assert tree(context.root) == before
    assert not (context.research_root / "S900/deliveries").exists()


@pytest.mark.parametrize("stage", list(d.DeliveryStage))
def test_owner_stage_contract(stage):
    owner = (
        d.ExperimentOwner("S900", "20261001_S900_EX01")
        if stage is d.DeliveryStage.MANDATE
        else d.MandateOwner("S900")
    )
    with pytest.raises(ValueError, match="requires"):
        d.DeliveryDefinition(owner, stage, 1)
    with pytest.raises(ValueError, match="requires"):
        d.DeliveryReference(owner, stage, 1, "a" * 64)


def test_experiment_owner_rejects_different_family_in_identity():
    with pytest.raises(ValueError, match="owner differs"):
        d.ExperimentOwner("S900", "20261001_S901_EX01")


def test_delivery_refuses_missing_source_bound_owner(context):
    missing = replace(definition(), owner=d.ExperimentOwner("S900", "20261001_S900_EX99"))
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(context, Deliverable(missing, content()))
    assert not (context.experiments_root / "S900/20261001_S900_EX99/deliveries").exists()


def test_delivery_refuses_changed_owner_source(context):
    root = context.experiments_root / "S900/20261001_S900_EX01"
    (root / "experiment.py").write_text("tampered")
    with pytest.raises(d.DeliveryValidationError, match="binding"):
        assemble_delivery(context, Deliverable(definition(), content()))
    assert not (root / "deliveries").exists()


def test_seal_includes_deliveries_and_blocks_append_and_overwrite(context):
    item = Deliverable(definition(), content())
    receipt = assemble_delivery(context, item)
    root = context.experiments_root / "S900/20261001_S900_EX01"
    manifest = seal(root)
    assert "deliveries/COMPONENTS/1/receipt.json" in manifest["files"]
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    before = tree(root)
    assert assemble_delivery(context, item) == receipt
    with pytest.raises(d.DeliveryValidationError, match="sealed"):
        assemble_delivery(context, Deliverable(replace(definition(), revision=2), content()))
    metadata = {k: v for k, v in manifest.items() if k not in ("schema_version", "files")}
    assert build_experiment_manifest(root, metadata) == manifest
    with pytest.raises(ValueError, match="cannot be overwritten"):
        build_experiment_manifest(root, {**metadata, "status": "CHANGED"})
    assert tree(root) == before
    (published(context, receipt) / "report.md").write_text("tampered")
    with pytest.raises(ValueError):
        build_experiment_manifest(root, metadata)
    assert json.loads((root / "experiment_manifest.json").read_text()) == manifest
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.FAIL






def test_candidate_objects_are_owned_and_sealed_with_experiment(candidate_archive):
    context = candidate_archive
    registry = StrategyRegistry(context.research_registry_root)
    key = CandidateKey("S900", "C0001")
    record = registry.get_candidate(key, experiments_root=context.experiments_root)
    root = context.experiments_root / "S900" / record.origin.experiment_id
    assert record.schema_version == 2
    assert (root / "objects").is_dir()
    assert not (context.research_registry_root / "objects").exists()
    assert load_candidate(context, key).candidate_id == "C0001"
    seal(root)
    assert registry.register_candidate(record, experiments_root=context.experiments_root) == record
    validate_experiment_archive(root)


def test_loading_retired_registration_keeps_archive_read_only(candidate_archive):
    context = candidate_archive
    registry = StrategyRegistry(context.research_registry_root)
    key = CandidateKey("S900", "C0001")
    record = registry.get_candidate(key, experiments_root=context.experiments_root)
    raw = record.to_dict()
    raw["schema_version"] = 1
    registration_path = context.research_registry_root / "S900/candidates/C0001.json"
    registration_path.write_text(json.dumps({"record": raw, "record_sha256": record.record_sha256}))
    before = tree(context.research_registry_root)
    with pytest.raises(ValidationError, match="unsupported candidate registration schema"):
        load_candidate(context, key)
    assert tree(context.research_registry_root) == before


def test_sealed_candidate_owner_refuses_new_registered_content(candidate_archive):
    from czsc_trader.application import (
        CandidateRegistrationRequest,
        register_candidate,
    )
    from strategy_manager import CandidateEvidence

    context = candidate_archive
    key = CandidateKey("S900", "C0001")
    record = StrategyRegistry(context.research_registry_root).get_candidate(
        key, experiments_root=context.experiments_root
    )
    root = context.experiments_root / "S900" / record.origin.experiment_id
    original = load_candidate(context, key)
    payload = json.loads(record.payload.resolve(root).read_text())
    payload["parameters"]["threshold"] = 0.8
    preflight = record.origin.preflight.resolve(root)
    request = CandidateRegistrationRequest(
        replace(original, payload=payload),
        replace(
            record.origin,
            preflight=CandidateEvidence(
                preflight.relative_to(context.root).as_posix(), record.origin.preflight.sha256
            ),
        ),
        (),
    )
    seal(root)
    before = tree(root)
    with pytest.raises(ValueError, match="sealed"):
        register_candidate(context, request)
    assert tree(root) == before


def test_registered_candidate_can_be_loaded_after_repository_relocation(candidate_archive):
    from czsc_trader.application import RepositoryContext

    context = candidate_archive
    key = CandidateKey("S900", "C0001")
    original = load_candidate(context, key)
    record = StrategyRegistry(context.research_registry_root).get_candidate(
        key, experiments_root=context.experiments_root
    )
    seal(context.experiments_root / "S900" / record.origin.experiment_id)
    destination = context.root.parent / (context.root.name + "-relocated")
    shutil.copytree(context.root, destination)
    restored = load_candidate(RepositoryContext.discover(destination), key)
    assert restored.runtime_identity_sha256 == original.runtime_identity_sha256
    assert restored.source_root.is_relative_to(destination)


@pytest.fixture
def candidate_archive(request, tmp_path, frozen_seed_root):
    from czsc_trader.application import RepositoryContext

    seed = frozen_seed_root / "research-registration-seed"
    if not seed.exists():
        context = request.getfixturevalue("completed")[0]
        shutil.copytree(context.root, seed)
    repository = tmp_path / "candidate-archive"
    shutil.copytree(seed, repository)
    return RepositoryContext.discover(repository)
