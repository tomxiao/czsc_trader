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
    published,
)
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
from test_assessment_delivery import completed as completed


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


def test_owner_must_be_bound_and_match_strategy(context):
    with pytest.raises(ValueError, match="owner differs"):
        d.ExperimentOwner("S900", "20261001_S901_EX01")
    missing = replace(definition(), owner=d.ExperimentOwner("S900", "20261001_S900_EX99"))
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(context, Deliverable(missing, content()))
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






def test_candidate_entities_owned_by_experiment_and_old_record_rejected(completed):
    context = completed[0]
    registry = StrategyRegistry(context.research_registry_root)
    key = CandidateKey("S900", "C001")
    record = registry.get_candidate(key, experiments_root=context.experiments_root)
    root = context.experiments_root / "S900" / record.origin.experiment_id
    assert record.schema_version == 2
    assert (root / "objects").is_dir()
    assert not (context.research_registry_root / "objects").exists()
    assert load_candidate(context, key).candidate_id == "C001"
    seal(root)
    assert registry.register_candidate(record, experiments_root=context.experiments_root) == record
    validate_experiment_archive(root)
    from strategy_manager import CandidateRegistration
    for field in ("schema_version", "identity_schema_version"):
        incomplete = record.to_dict()
        del incomplete[field]
        with pytest.raises(ValidationError, match="unsupported candidate"):
            CandidateRegistration.from_dict(incomplete)
    raw = record.to_dict()
    raw["schema_version"] = 1
    registration_path = context.research_registry_root / "S900/candidates/C001.json"
    registration_path.write_text(json.dumps({"record": raw, "record_sha256": record.record_sha256}))
    before = tree(context.research_registry_root)
    with pytest.raises(ValidationError, match="unsupported candidate registration schema"):
        load_candidate(context, key)
    assert tree(context.research_registry_root) == before


def test_sealed_candidate_objects_cannot_be_extended_and_can_be_relocated(completed):
    from czsc_trader.application import (
        RepositoryContext,
        CandidateRegistrationRequest,
        register_candidate,
    )
    from strategy_manager import CandidateEvidence

    context = completed[0]
    key = CandidateKey("S900", "C001")
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
    destination = context.root.parent / (context.root.name + "-relocated")
    shutil.copytree(context.root, destination)
    restored = load_candidate(RepositoryContext.discover(destination), key)
    assert restored.runtime_identity_sha256 == original.runtime_identity_sha256
    assert restored.source_root.is_relative_to(destination)
