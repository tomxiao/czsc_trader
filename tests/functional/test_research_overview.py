# Risk ownership: TDR-13
"""Lightweight navigation authenticates only its explicit metadata scope."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import pytest
from dataflows import ProviderConfig
from czsc_trader.application import (
    RepositoryContext, ResearchBatchRequest, ExperimentRequest,
    assemble_delivery, create_research_batch, create_research_context, create_experiment,
    publish_evidence,
)
from czsc_trader.application.research_overview_service import get_research_overview
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evidence import ExperimentOutcome, ExperimentReportWrite
from czsc_trader.research_tools.overview import (
    DeliveryMetadataState, ExperimentReportState, ResearchOverviewError,
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


def test_TDR_13_C04_overview_reads_report_pointer_and_detects_unpublished_edits(overview_context):
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


def test_TDR_13_C01_latest_receipt_only_never_opens_payloads_or_account_directories(overview_context, monkeypatch):
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


def test_TDR_13_C03_unsupported_highest_receipt_never_falls_back(overview_context):
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


def test_TDR_13_C02_overview_does_not_enumerate_or_parse_other_batches(overview_context):
    research, _ = overview_context
    (research.repository.root / "research/S900/HANDOFF.md").unlink()
    for relative in ("research/S901/batch.json", "research/registrations/S901/family.json"):
        target = research.repository.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"not-json-and-must-not-be-read")
    overview = get_research_overview(research.repository, research.batch)
    assert all("S901" not in item.repository_path for item in overview.snapshot.sources)
    assert not next(x for x in overview.task_sources if x.repository_path.endswith("HANDOFF.md")).present


@pytest.mark.parametrize('change', ['file'])
def test_TDR_13_C05_overview_refuses_concurrent_metadata_mutation_without_retry(overview_context, monkeypatch, change):
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


@pytest.mark.parametrize('link_kind', ['is_symlink'])
def test_TDR_13_C07_overview_rejects_linked_metadata_paths(overview_context, monkeypatch, link_kind):
    research, _ = overview_context
    target = research.repository.root / "research/S900"
    original = getattr(Path, link_kind)
    monkeypatch.setattr(Path, link_kind, lambda path: path == target or original(path))
    with pytest.raises(ResearchOverviewError, match="filesystem link"):
        get_research_overview(research.repository, research.batch)




def test_TDR_13_C06_navigation_rejects_parent_path_before_read(overview_context, monkeypatch):
    from czsc_trader.application.research_overview_service import _ReadSnapshot
    research, _ = overview_context
    def forbidden(*args, **kwargs):
        raise AssertionError('unsafe path must be rejected before I/O')
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    with pytest.raises(ValueError, match='relative|unsafe|path'):
        _ReadSnapshot(research.repository.root).read('../outside')
