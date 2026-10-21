"""Batch fact snapshots stay explicit, scoped and stable during a read."""

from dataclasses import FrozenInstanceError, replace
from datetime import date
from hashlib import sha256
import json
import shutil
import tracemalloc

import pytest
from dataflows import ProviderConfig
from strategy_manager import ResearchState
from test_research_contract_upgrade import managed_evaluation as managed_evaluation

from czsc_trader.application import (
    RepositoryContext, ResearchBatchRequest, ResearchIntentUpdate, ExperimentRequest,
    assemble_delivery, create_research_batch, create_research_context, create_experiment,
    publish_evidence, update_research_intent,
)
from czsc_trader.application.research_overview_service import get_research_overview
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evidence import (
    ExperimentOutcome, ExperimentReportWrite, MaterialEvidenceWrite,
)
from czsc_trader.research_tools.overview import (
    CountBasis, ExperimentReportState, ResearchCount, ResearchCountKind, ResearchOverview,
    ResearchOverviewError,
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


def _count(overview, kind):
    return next(item for item in overview.counts if item.kind is kind)


def test_overview_has_pinned_sources_and_no_inferred_authorization(overview_context):
    research, experiment = overview_context
    update_research_intent(research.repository, research.batch,
        ResearchIntentUpdate(research_state=ResearchState.PAUSED), actor="test", reason="waiting")
    (experiment.resolve(research.repository.root) / "report.md").write_text("This prose says frozen and approved")
    overview = get_research_overview(research.repository, research.batch)
    assert overview.registered_state is ResearchState.PAUSED
    assert overview.experiments[0].report_state is ExperimentReportState.DRAFT
    assert not overview.deliveries and not overview.candidates
    assert _count(overview, ResearchCountKind.REGISTERED_CANDIDATES).value == 0
    assert _count(overview, ResearchCountKind.SEARCH_EVALUATIONS).basis is CountBasis.UNKNOWN
    assert all(source.repository_path.startswith(("research/S900/", "research/registrations/S900/")) for source in overview.snapshot.sources)
    assert ResearchOverview.from_dict(json.loads(json.dumps(overview.to_dict()))) == overview
    assert get_research_overview(research.repository, research.batch).snapshot.content_sha256 == overview.snapshot.content_sha256
    with pytest.raises(FrozenInstanceError):
        overview.registered_state = ResearchState.RESEARCHING


def test_overview_reads_report_pointer_and_detects_unpublished_edits(overview_context):
    research, experiment = overview_context
    path = experiment.resolve(research.repository.root) / "report.md"
    path.write_bytes("Explicit negative finding".encode())
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


def test_overview_selects_numeric_revision_and_preserves_component_results(overview_context):
    research, experiment = overview_context
    material = publish_evidence(research, MaterialEvidenceWrite(experiment, "source", b"negative", "text/plain", "txt"))
    test = d.ComponentTestResult("check", experiment.experiment_id, material,
        d.ComponentTestStatus.INEFFECTIVE, "Researcher interpretation", (material,))
    component = d.ComponentEntry("signal", d.ExperimentDefinitionRef(material, "signal"),
        "entry", "return", "20d", "base", "before decision", "raw", "sample", "negative", (test,))
    first = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 2), _content(d.ComponentPanel((component,), "Negative")))
    last = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 10, (first.reference,)), _content(d.ComponentPanel((), "New statement")))
    # Metadata overview, like delivery validation, relies on retained snapshots.
    material.resolve(research.repository.root).unlink()
    overview = get_research_overview(research.repository, research.batch)
    assert overview.deliveries[0].reference == last.reference
    assert len(overview.component_tests) == 2
    assert any(panel.components == (component,) for panel in overview.component_tests)


def test_overview_deduplicates_search_declarations_but_never_sums_overlap(overview_context):
    research, _ = overview_context
    search = d.SearchSummary("sweep", "grid", "development", 10, 7, "researcher choice")
    for revision in (1, 2):
        assemble_delivery(research.repository,
            d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, revision),
            _content(d.CandidateSet((), (), (search,), "No handoff")))
    first = get_research_overview(research.repository, research.batch)
    assert len(first.searches) == 1 and len(first.searches[0].deliveries) == 2
    assert _count(first, ResearchCountKind.SEARCH_EVALUATIONS).value == 10
    assert _count(first, ResearchCountKind.SEARCH_EVALUATIONS).basis is CountBasis.DECLARED
    assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, 3),
        _content(d.CandidateSet((), (), (replace(search, evaluations=20),), "Cumulative declaration")))
    second = get_research_overview(research.repository, research.batch)
    assert _count(second, ResearchCountKind.SEARCH_EVALUATIONS).value is None
    assert any(item.code == "SEARCH_OVERLAP_UNKNOWN" for item in second.limitations)


def test_overview_memory_does_not_scale_with_repeated_large_evidence_copies(overview_context):
    research, experiment = overview_context
    payload = b"retained source data\n" * 210_000
    evidence = publish_evidence(research, MaterialEvidenceWrite(
        experiment, "large-source", payload, "text/plain", "txt"))
    for revision in range(1, 9):
        assemble_delivery(research.repository,
            d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, revision),
            replace(_content(d.ComponentPanel((), "Large selected source")), evidence=(evidence,)))
    # Eight independent retained copies represent the cumulative research graph.
    # Authentication must not keep their full payloads alive until the read ends.
    tracemalloc.start()
    try:
        overview = get_research_overview(research.repository, research.batch)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert overview.deliveries[0].reference.revision == 8
    assert peak < len(payload) * 6


def test_overview_reports_unsupported_delivery_without_legacy_parser(overview_context):
    research, _ = overview_context
    assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 2), _content(d.ComponentPanel((), "old readable")))
    path = research.repository.root / "research/S900/assets/deliveries/COMPONENTS/10"
    path.mkdir(parents=True)
    (path / "delivery.json").write_text(json.dumps({"schema_version": 5, "old": "not interpreted"}))
    overview = get_research_overview(research.repository, research.batch)
    assert not overview.deliveries
    assert any(item.code == "UNSUPPORTED_DELIVERY_SCHEMA" for item in overview.limitations)


def test_overview_counts_registered_candidate_and_actual_published_account(fresh_completed):
    repository, research, request, result, evaluation = fresh_completed
    # This shared fixture intentionally creates its family directly; establish a
    # public batch identity before requesting the overview's batch-scoped view.
    create_research_batch(repository, ResearchBatchRequest("S900", "Freeze fixture", "ETF",
        {"hypothesis": "synthetic"}, credential_id="SGC-S900-002"), actor="test", reason="explicit batch")
    overview = get_research_overview(repository, research.batch)
    assert len(overview.candidates) == 1
    assert overview.candidates[0].key.candidate_id == request.strategy.candidate_id
    assert overview.candidates[0].key.strategy_id == request.strategy.strategy_family_id
    assert _count(overview, ResearchCountKind.REGISTERED_CANDIDATES).value == 1
    assert _count(overview, ResearchCountKind.PUBLISHED_ACCOUNT_EVALUATIONS).value == len(result.runs)
    assert _count(overview, ResearchCountKind.PUBLISHED_ACCOUNT_EVALUATIONS).basis is CountBasis.DECLARED
    assert any(item.repository_path == evaluation.evidence.repository_path for item in overview.snapshot.sources)


def test_overview_marks_unsupported_account_total_unknown(overview_context):
    research, experiment = overview_context
    publish_evidence(research, MaterialEvidenceWrite(experiment, "historical-account",
        json.dumps({"source_kind": "published_result", "schema_version": 5}).encode(), "application/json", "json"))
    overview = get_research_overview(research.repository, research.batch)
    assert _count(overview, ResearchCountKind.PUBLISHED_ACCOUNT_EVALUATIONS).basis is CountBasis.UNKNOWN
    assert _count(overview, ResearchCountKind.PUBLISHED_ACCOUNT_EVALUATIONS).value is None


@pytest.mark.parametrize("damage", ["missing", "missing-package", "tampered", "foreign"])
def test_overview_rejects_invalid_required_identity_or_artifact(overview_context, damage):
    research, experiment = overview_context
    receipt = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 1), _content(d.ComponentPanel((), "done")))
    if damage == "missing":
        (research.repository.root / f"research/S900/deliveries/COMPONENTS/{receipt.reference.revision}/receipt.json").unlink()
    elif damage == "missing-package":
        shutil.rmtree(research.repository.root / "research/S900/assets/deliveries/COMPONENTS/1")
    elif damage == "tampered":
        (research.repository.root / "research/S900/assets/deliveries/COMPONENTS/1/report.md").write_bytes(b"changed")
    else:
        path = experiment.resolve(research.repository.root) / "experiment.json"
        value = json.loads(path.read_text())
        value["strategy_id"] = "S901"
        path.write_text(json.dumps(value))
    with pytest.raises(ResearchOverviewError) as exc:
        get_research_overview(research.repository, research.batch)
    assert exc.value.code == "INVALID_RETAINED_RECORD"


def test_overview_does_not_enumerate_or_parse_other_batches(overview_context):
    research, _ = overview_context
    for relative in ("research/S901/batch.json", "research/registrations/S901/family.json"):
        target = research.repository.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"not-json-and-must-not-be-read")
    overview = get_research_overview(research.repository, research.batch)
    assert all("S901" not in item.repository_path for item in overview.snapshot.sources)


@pytest.mark.parametrize("change", ["file", "listing"])
def test_overview_refuses_concurrent_mutation_without_retry(overview_context, monkeypatch, change):
    from czsc_trader.application import research_overview_service as service
    research, experiment = overview_context
    original = service._ReadSnapshot.finish
    def mutate(reader):
        if change == "file":
            (experiment.resolve(research.repository.root) / "report.md").write_bytes(b"concurrent write")
        else:
            (research.repository.root / "research/S900/experiments/EX002_20261007").mkdir()
        return original(reader)
    monkeypatch.setattr(service._ReadSnapshot, "finish", mutate)
    with pytest.raises(ResearchOverviewError) as exc:
        get_research_overview(research.repository, research.batch)
    assert exc.value.code == "CONCURRENT_CHANGE"


@pytest.mark.parametrize("value", [True, -1, "3"])
def test_overview_count_contract_rejects_ambiguous_values(value):
    with pytest.raises((ValueError, TypeError)):
        ResearchCount(ResearchCountKind.SEARCH_EVALUATIONS, value, CountBasis.DECLARED, ())


def test_snapshot_reuses_hash_observation_but_rechecks_content_at_finish(overview_context, monkeypatch):
    from czsc_trader.application.research_overview_service import _ReadSnapshot
    research, experiment = overview_context
    relative = f"{experiment.repository_path}/report.md"
    path = research.repository.root / relative
    expected = sha256(path.read_bytes()).hexdigest()
    reader = _ReadSnapshot(research.repository.root)
    calls = []
    read = type(path).read_bytes

    def counted(target):
        calls.append(target)
        return read(target)

    monkeypatch.setattr(type(path), "read_bytes", counted)
    for _ in range(5):
        reader.authenticate(relative, expected)
    assert calls == [path]
    with pytest.raises(ValueError, match="hash differs"):
        reader.authenticate(relative, "0" * 64)
    path.write_bytes(b"concurrent mutation")
    with pytest.raises(ResearchOverviewError) as exc:
        reader.finish()
    assert exc.value.code == "CONCURRENT_CHANGE"
