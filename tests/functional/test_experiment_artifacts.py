"""Independent experiment reports and explicit material ownership."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from hashlib import sha256
import json

import pytest

from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence, publish_evidence_many
from czsc_trader.application.experiment_artifact_service import validate_experiment
from czsc_trader.research_tools.delivery import ValidationStatus
from czsc_trader.research_tools.evidence import (
    ExperimentOutcome, ExperimentReportWrite, MaterialEvidenceWrite, PublicationStatus,
)
from czsc_trader.research_tools.experiment_artifacts import (
    ExperimentArtifactRef, ExperimentReportSnapshot, ExperimentValidationRequest,
    ExperimentValidationScope, ReportPublicationError,
)


@pytest.fixture
def report_case(minimal_repo):
    from evaluation_seed_support import restored_context
    context = restored_context(minimal_repo)
    experiment = create_experiment(context, ExperimentRequest("Negative experiment", "Does it work?", date(2026, 10, 21)))
    path = experiment.resolve(context.repository.root) / "report.md"
    path.write_bytes(b"A negative result.\r\n")
    source = publish_evidence(context, MaterialEvidenceWrite(experiment, "observation", b"data", "text/plain", "txt"))
    request = ExperimentReportWrite(experiment, sha256(path.read_bytes()).hexdigest(),
                                    ExperimentOutcome.FAILED, (source,))
    return context, experiment, path, request


def check(context, experiment, scope=ExperimentValidationScope.REPORT_PUBLICATION, artifacts=()):
    return validate_experiment(context.repository, ExperimentValidationRequest(experiment, scope, artifacts))


def test_report_independent_publication_revision_and_draft_detection(report_case):
    context, experiment, path, request = report_case
    assert check(context, experiment).issues[0].code == "REPORT_UNPUBLISHED"
    assert check(context, experiment, ExperimentValidationScope.STRUCTURE).status is ValidationStatus.PASS
    first = publish_evidence(context, request)
    assert publish_evidence(context, request) == first
    snapshot = ExperimentReportSnapshot.from_dict(json.loads(first.resolve(context.repository.root).read_bytes()))
    assert snapshot.report.encode() == path.read_bytes()
    assert snapshot.outcome is ExperimentOutcome.FAILED
    assert check(context, experiment).status is ValidationStatus.PASS
    path.write_bytes(b"Revised result.\n")
    assert check(context, experiment).issues[0].code == "REPORT_MODIFIED"
    next_request = replace(request, expected_report_sha256=sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ReportPublicationError, match="revision conflict"):
        publish_evidence(context, next_request)
    second = publish_evidence(context, replace(next_request, previous=first))
    assert second != first
    assert first.resolve(context.repository.root).exists()
    assert check(context, experiment).report == second


def test_create_report_placeholder_and_shared_material_ownership(report_case):
    context, experiment, _, _ = report_case
    second = create_experiment(context, ExperimentRequest("Shared", "A question", date(2026, 10, 21)))
    assert "IN_PROGRESS" in (second.resolve(context.repository.root) / "report.md").read_text()
    source = experiment.resolve(context.repository.root) / "others/result.txt"
    source.write_bytes(b"a result")
    artifact = ExperimentArtifactRef(experiment, "others/result.txt", sha256(source.read_bytes()).hexdigest())
    assert check(context, second, ExperimentValidationScope.STRUCTURE, (artifact,)).status is ValidationStatus.PASS
    source.write_bytes(b"changed")
    assert check(context, second, ExperimentValidationScope.STRUCTURE, (artifact,)).issues[0].code == "INVALID_ARTIFACT"
    for path in ("../materials/x", "C:/x", "others/../../x", "others\\x"):
        with pytest.raises(ValueError):
            ExperimentArtifactRef(experiment, path, "0" * 64)


def test_batch_preflight_and_report_parent_publication(report_case):
    context, experiment, path, request = report_case
    malformed = replace(request, expected_report_sha256="0" * 64)
    with pytest.raises(ValueError, match="expected digest"):
        publish_evidence_many(context, (request, malformed))
    assert not (path.parent / "report_ref.json").exists()
    outcomes = publish_evidence_many(context, (request, request))
    assert all(item.status is PublicationStatus.PUBLISHED for item in outcomes)
    assert outcomes[0].reference == outcomes[1].reference
    request.evidence[0].resolve(context.repository.root).write_bytes(b"tampered")
    assert check(context, experiment).issues[0].code == "INVALID_REPORT_PUBLICATION"
    with pytest.raises(ValueError, match="content differs"):
        publish_evidence(context, request)


def test_partial_report_commit_preserves_known_snapshot(report_case, monkeypatch):
    from czsc_trader.application import experiment_artifact_service as service
    context, experiment, path, request = report_case
    def fail(*args):
        raise OSError("injected commit failure")
    monkeypatch.setattr(service, "_replace_pointer", fail)
    with pytest.raises(ReportPublicationError) as caught:
        publish_evidence(context, request)
    assert caught.value.phase == "COMMIT"
    reference = caught.value.reference
    assert reference.resolve(context.repository.root).exists()
    assert not (path.parent / "report_ref.json").exists()
    outcome = publish_evidence_many(context, (request,))[0]
    assert outcome.status is PublicationStatus.FAILED
    assert outcome.error.phase == "COMMIT" and outcome.error.reference == reference
    assert outcome.error.pointer_committed is False
    assert check(context, experiment).issues[0].code == "REPORT_UNPUBLISHED"


def test_concurrent_report_publish_preserves_one_current_reference(report_case):
    context, experiment, _, request = report_case
    requests = (request, replace(request, outcome=ExperimentOutcome.COMPLETED))
    def publish(value):
        try:
            return publish_evidence(context, value)
        except ReportPublicationError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(publish, requests))
    assert sum(value is not None for value in results) == 1
    assert check(context, experiment).report in results


def test_commit_error_after_replace_is_unknown_and_cancellation_preserved(report_case, monkeypatch):
    from czsc_trader.application import experiment_artifact_service as service
    context, experiment, _, request = report_case
    original = service._replace_pointer
    def fail_after(*args):
        original(*args)
        raise OSError("error after commit")
    monkeypatch.setattr(service, "_replace_pointer", fail_after)
    outcome = publish_evidence_many(context, (request,))[0]
    assert outcome.status is PublicationStatus.UNKNOWN
    assert outcome.error.pointer_committed is True
    assert check(context, experiment).report == outcome.error.reference
    # A safe caller may explicitly replay; the implementation never retries.
    assert publish_evidence(context, request) == outcome.error.reference
    def interrupt(*args):
        raise KeyboardInterrupt("cancel")
    monkeypatch.setattr(service, "_replace_pointer", interrupt)
    revised = replace(request, previous=outcome.error.reference, outcome=ExperimentOutcome.CANCELLED)
    with pytest.raises(KeyboardInterrupt):
        publish_evidence(context, revised)
    cancelled = publish_evidence_many(context, (revised,))[0]
    assert cancelled.status is PublicationStatus.CANCELLED
    assert cancelled.error.reference is not None and cancelled.error.pointer_committed is False


def test_report_pointer_and_owned_symlink_are_rejected(report_case):
    context, experiment, path, request = report_case
    publish_evidence(context, request)
    pointer = path.parent / "report_ref.json"
    pointer.write_text('{"schema_version":2,"report":{}}')
    assert check(context, experiment).issues[0].code == "INVALID_REPORT_PUBLICATION"
    link = path.parent / "others/link.txt"
    try:
        link.symlink_to(path)
    except OSError:
        # Windows junctions exercise the same managed-path policy without symlink privilege.
        import subprocess
        link = path.parent / "others/link-dir"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(path.parent)], check=True, capture_output=True)
        relative = "others/link-dir/report.md"
    else:
        relative = "others/link.txt"
    artifact = ExperimentArtifactRef(experiment, relative, sha256(path.read_bytes()).hexdigest())
    result = check(context, experiment, ExperimentValidationScope.STRUCTURE, (artifact,))
    assert result.issues[0].code == "INVALID_ARTIFACT"


@pytest.mark.parametrize("version", ["true", "1,\"schema_version\":1", "NaN", "Infinity"])
def test_invalid_report_pointer_metadata_is_rejected(report_case, version):
    context, experiment, path, request = report_case
    reference = publish_evidence(context, request)
    raw = '{"schema_version":' + version + ',"report":' + json.dumps(reference.to_dict()) + '}'
    (path.parent / "report_ref.json").write_text(raw, encoding="utf-8")
    result = check(context, experiment)
    assert result.status is ValidationStatus.FAIL
    assert result.issues[0].code == "INVALID_REPORT_PUBLICATION"


def test_duplicate_experiment_identity_rejects_publication_before_writes(report_case):
    context, experiment, path, request = report_case
    identity = json.dumps(experiment.to_dict())
    (path.parent / "experiment.json").write_text(identity[:-1] + ',"strategy_id":"S900"}', encoding="utf-8")
    assert check(context, experiment, ExperimentValidationScope.STRUCTURE).status is ValidationStatus.FAIL
    with pytest.raises(ValueError, match="duplicate JSON key"):
        publish_evidence(context, request)
    assert not (path.parent / "report_ref.json").exists()
