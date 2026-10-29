"""Lightweight navigation authenticates only its explicit metadata scope."""
from dataclasses import FrozenInstanceError, replace
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest
from dataflows import ProviderConfig
from strategy_manager import ResearchState
from czsc_trader.application import (
    RepositoryContext, ResearchBatchRequest, ResearchIntentUpdate, ExperimentRequest,
    assemble_delivery, create_research_batch, create_research_context, create_experiment,
    publish_evidence, update_research_intent, validate_experiment,
)
from czsc_trader.application.research_overview_service import get_research_overview
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evidence import ExperimentOutcome, ExperimentReportWrite, MaterialEvidenceWrite
from czsc_trader.research_tools.experiment_artifacts import ExperimentValidationRequest, ExperimentValidationScope
from czsc_trader.research_tools.overview import (
    DeliveryMetadataState, ExperimentReportState, OverviewScope, ResearchOverview, ResearchOverviewError,
)


@pytest.fixture
def overview_context(minimal_repo):
    repository = RepositoryContext.discover(minimal_repo)
    batch = create_research_batch(repository,
        ResearchBatchRequest("S900", "snapshot facts", ("588080.SH",), {"question": "synthetic"}),
        actor="test", reason="test")
    research = create_research_context(repository, batch, providers=ProviderConfig(bindings={}))
    experiment = create_experiment(research, ExperimentRequest("Diagnostic", "Test scope", date(2026, 10, 7)))
    return research, experiment


def _content(payload):
    return d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report="Researcher statement")


def test_overview_metadata_scope_roundtrip_and_no_inferred_authorization(overview_context):
    research, experiment = overview_context
    update_research_intent(research.repository, research.batch,
        ResearchIntentUpdate(research_state=ResearchState.PAUSED), actor="test", reason="waiting")
    root = research.repository.root
    (experiment.resolve(root) / "report.md").write_text("This prose says frozen and approved")
    handoff = root / "research/S900/HANDOFF.md"
    handoff.write_text("Current handoff")
    overview = get_research_overview(research.repository, research.batch)
    assert overview.registered_state is ResearchState.PAUSED
    assert overview.experiments[0].report_state is ExperimentReportState.DRAFT
    assert not overview.deliveries
    assert overview.schema_version == 2 and overview.snapshot.scope is OverviewScope.METADATA_ONLY
    assert {x.repository_path for x in overview.task_sources} == {
        "research/registrations/S900/family.json", "research/S900/HANDOFF.md"}
    assert all(x.present for x in overview.task_sources)
    assert all(s.repository_path.startswith(("research/S900/", "research/registrations/S900/")) for s in overview.snapshot.sources)
    assert ResearchOverview.from_dict(json.loads(json.dumps(overview.to_dict()))) == overview
    assert get_research_overview(research.repository, research.batch).snapshot.content_sha256 == overview.snapshot.content_sha256
    assert not {"counts", "candidates", "handoffs", "searches", "component_tests", "prototype_panels"} & overview.to_dict().keys()
    with pytest.raises(FrozenInstanceError):
        overview.registered_state = ResearchState.RESEARCHING
    with pytest.raises(ValueError, match="schema"):
        replace(overview, schema_version=1)
    legacy = overview.to_dict()
    legacy.pop("schema_version")
    with pytest.raises(ValueError, match="fields"):
        ResearchOverview.from_dict(legacy)


def test_overview_reads_report_pointer_and_detects_unpublished_edits(overview_context):
    research, experiment = overview_context
    path = experiment.resolve(research.repository.root) / "report.md"
    path.write_bytes(b"Explicit negative finding")
    ref = publish_evidence(research, ExperimentReportWrite(experiment,
        sha256(path.read_bytes()).hexdigest(), ExperimentOutcome.COMPLETED, ()))
    first = get_research_overview(research.repository, research.batch)
    assert first.experiments[0].report == ref
    assert first.experiments[0].outcome is ExperimentOutcome.COMPLETED
    assert first.experiments[0].report_state is ExperimentReportState.PUBLISHED
    path.write_bytes(b"New conclusion, unpublished")
    second = get_research_overview(research.repository, research.batch)
    assert second.experiments[0].report_state is ExperimentReportState.UNPUBLISHED_CHANGES
    assert first.snapshot.content_sha256 != second.snapshot.content_sha256
    path.unlink()
    assert get_research_overview(research.repository, research.batch).experiments[0].report_state is ExperimentReportState.UNPUBLISHED_CHANGES


def test_report_navigation_does_not_authenticate_linked_evidence(overview_context):
    research, experiment = overview_context
    path = experiment.resolve(research.repository.root) / "report.md"
    material = publish_evidence(research, MaterialEvidenceWrite(experiment, "source", b"support", "text/plain", "txt"))
    publish_evidence(research, ExperimentReportWrite(experiment,
        sha256(path.read_bytes()).hexdigest(), ExperimentOutcome.COMPLETED, (material,)))
    material.resolve(research.repository.root).write_bytes(b"damaged support")
    overview = get_research_overview(research.repository, research.batch)
    assert overview.experiments[0].report_state is ExperimentReportState.PUBLISHED
    assert material.repository_path not in {x.repository_path for x in overview.snapshot.sources}
    assert validate_experiment(research.repository, ExperimentValidationRequest(
        experiment, ExperimentValidationScope.REPORT_PUBLICATION)).status is d.ValidationStatus.FAIL


def test_latest_receipt_only_never_opens_payloads_or_account_directories(overview_context, monkeypatch):
    research, _ = overview_context
    first = assemble_delivery(research.repository, d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 2),
        _content(d.ComponentPanel((), "prior"))).receipt
    latest = assemble_delivery(research.repository, d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 10, (first.reference,)),
        _content(d.ComponentPanel((), "latest"))).receipt
    root = research.repository.root
    def blocked(path):
        relative = path.relative_to(root).as_posix()
        return ("/assets/evidence/" in relative or "/candidates/" in relative
                or relative.endswith("delivery.json") or "/COMPONENTS/2/" in relative
                or ("/deliveries/" in relative and relative.endswith("report.md")))
    original_open, original_iterdir = Path.open, Path.iterdir
    def guarded_open(path, *args, **kwargs):
        assert not blocked(path), f"unnecessary payload read: {path}"
        return original_open(path, *args, **kwargs)
    def guarded_iterdir(path):
        assert not path.as_posix().endswith(("/assets/evidence", "/candidates"))
        return original_iterdir(path)
    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(Path, "iterdir", guarded_iterdir)
    overview = get_research_overview(research.repository, research.batch)
    item = overview.deliveries[0]
    assert item.reference == latest.reference and item.revision == 10
    assert item.metadata_state is DeliveryMetadataState.READABLE
    assert item.report_path == "research/S900/deliveries/COMPONENTS/10/report.md"
    assert not any(blocked(root / x.repository_path) for x in overview.snapshot.sources if x.kind == "FILE")


def test_unsupported_highest_receipt_never_falls_back(overview_context):
    research, _ = overview_context
    assemble_delivery(research.repository, d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 2),
        _content(d.ComponentPanel((), "readable")))
    for parent in ("deliveries", "assets/deliveries"):
        path = research.repository.root / f"research/S900/{parent}/COMPONENTS/10"
        path.mkdir(parents=True)
        (path / "receipt.json").write_text(json.dumps({"schema_version": 999, "unknown": "format"}))
        (path / "report.md").write_text("Unknown revision")
    overview = get_research_overview(research.repository, research.batch)
    assert len(overview.deliveries) == 1
    latest = overview.deliveries[0]
    assert latest.revision == 10 and latest.reference is None
    assert latest.metadata_state is DeliveryMetadataState.UNSUPPORTED
    assert any(x.code == "UNSUPPORTED_DELIVERY_SCHEMA" for x in overview.limitations)


@pytest.mark.parametrize("damage", ["missing", "missing-package", "tampered-receipt", "manifest", "foreign", "unsafe-manifest"])
def test_overview_rejects_invalid_required_metadata(overview_context, damage):
    research, experiment = overview_context
    assemble_delivery(research.repository, d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 1),
        _content(d.ComponentPanel((), "done")))
    root = research.repository.root
    public = root / "research/S900/deliveries/COMPONENTS/1/receipt.json"
    retained = root / "research/S900/assets/deliveries/COMPONENTS/1/receipt.json"
    if damage == "missing":
        public.unlink()
    elif damage == "missing-package":
        shutil.rmtree(retained.parent)
    elif damage == "tampered-receipt":
        retained.write_bytes(b"changed")
    elif damage in ("manifest", "unsafe-manifest"):
        value = json.loads(public.read_bytes())
        value["files"][0]["sha256"] = "0" * 64
        if damage == "unsafe-manifest":
            value["files"][0]["path"] = "../outside"
        for path in (public, retained):
            path.write_text(json.dumps(value))
    else:
        path = experiment.resolve(root) / "experiment.json"
        value = json.loads(path.read_text())
        value["strategy_id"] = "S901"
        path.write_text(json.dumps(value))
    with pytest.raises(ResearchOverviewError) as exc:
        get_research_overview(research.repository, research.batch)
    assert exc.value.code == "INVALID_RETAINED_RECORD"


def test_overview_does_not_enumerate_or_parse_other_batches(overview_context):
    research, _ = overview_context
    (research.repository.root / "research/S900/HANDOFF.md").unlink()
    for relative in ("research/S901/batch.json", "research/registrations/S901/family.json"):
        target = research.repository.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"not-json-and-must-not-be-read")
    overview = get_research_overview(research.repository, research.batch)
    assert all("S901" not in item.repository_path for item in overview.snapshot.sources)
    assert not next(x for x in overview.task_sources if x.repository_path.endswith("HANDOFF.md")).present


@pytest.mark.parametrize("change", ["file", "listing", "handoff"])
def test_overview_refuses_concurrent_metadata_mutation_without_retry(overview_context, monkeypatch, change):
    from czsc_trader.application import research_overview_service as service
    research, experiment = overview_context
    original = service._ReadSnapshot.finish
    if change == "handoff":
        (research.repository.root / "research/S900/HANDOFF.md").unlink()
    def mutate(reader):
        if change == "file":
            (experiment.resolve(research.repository.root) / "report.md").write_bytes(b"concurrent write")
        elif change == "listing":
            (research.repository.root / "research/S900/experiments/EX002_20261007").mkdir()
        else:
            (research.repository.root / "research/S900/HANDOFF.md").write_text("New handoff")
        return original(reader)
    monkeypatch.setattr(service._ReadSnapshot, "finish", mutate)
    with pytest.raises(ResearchOverviewError) as exc:
        get_research_overview(research.repository, research.batch)
    assert exc.value.code == "CONCURRENT_CHANGE"


@pytest.mark.parametrize("link_kind", ["is_symlink", "is_junction"])
def test_overview_rejects_linked_metadata_paths(overview_context, monkeypatch, link_kind):
    research, _ = overview_context
    target = research.repository.root / "research/S900"
    original = getattr(Path, link_kind)
    monkeypatch.setattr(Path, link_kind, lambda path: path == target or original(path))
    with pytest.raises(ResearchOverviewError, match="filesystem link"):
        get_research_overview(research.repository, research.batch)


@pytest.mark.parametrize("damage", ["hash", "foreign-pointer", "bad-schema"])
def test_report_snapshot_identity_is_still_authenticated(overview_context, damage):
    research, experiment = overview_context
    path = experiment.resolve(research.repository.root) / "report.md"
    ref = publish_evidence(research, ExperimentReportWrite(experiment,
        sha256(path.read_bytes()).hexdigest(), ExperimentOutcome.COMPLETED, ()))
    if damage == "hash":
        ref.resolve(research.repository.root).write_bytes(b"changed")
    else:
        pointer = experiment.resolve(research.repository.root) / "report_ref.json"
        value = json.loads(pointer.read_bytes())
        if damage == "foreign-pointer":
            value["report"]["experiment"]["strategy_id"] = "S901"
        else:
            value["schema_version"] = True
        pointer.write_text(json.dumps(value))
    with pytest.raises(ResearchOverviewError):
        get_research_overview(research.repository, research.batch)


def test_overview_rechecks_unread_navigation_target_link_at_finish(overview_context, monkeypatch):
    from czsc_trader.application import research_overview_service as service
    research, _ = overview_context
    assemble_delivery(research.repository, d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 1),
        _content(d.ComponentPanel((), "done")))
    target = research.repository.root / "research/S900/deliveries/COMPONENTS/1/report.md"
    original_finish, original_link = service._ReadSnapshot.finish, Path.is_symlink
    def change_link(reader):
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original_link(path))
        return original_finish(reader)
    monkeypatch.setattr(service._ReadSnapshot, "finish", change_link)
    with pytest.raises(ResearchOverviewError) as exc:
        get_research_overview(research.repository, research.batch)
    assert exc.value.code == "CONCURRENT_CHANGE"
    assert exc.value.repository_path.endswith("COMPONENTS/1/report.md")
