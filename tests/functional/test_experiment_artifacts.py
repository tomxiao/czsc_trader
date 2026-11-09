# Risk ownership: TDR-10
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
    ExperimentReportSnapshot, ExperimentValidationRequest,
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


def test_TDR_10_C01_report_independent_publication_revision_and_draft_detection(report_case):
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


def test_TDR_10_C03_report_draft_changed_during_publication_does_not_commit(report_case, monkeypatch):
    from czsc_trader.application import evidence_service
    context, _, path, request = report_case
    original = evidence_service._publish_bytes

    def change_draft(*args, **kwargs):
        original(*args, **kwargs)
        path.write_bytes(b"A concurrent draft edit.\n")

    monkeypatch.setattr(evidence_service, "_publish_bytes", change_draft)
    with pytest.raises(ReportPublicationError, match="expected digest") as caught:
        publish_evidence(context, request)
    assert caught.value.phase == "COMMIT"
    assert caught.value.reference is not None and caught.value.pointer_committed is False
    assert not (path.parent / "report_ref.json").exists()




def test_TDR_10_C04_concurrent_report_publish_preserves_one_current_reference(report_case):
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


def test_TDR_10_C05_commit_error_after_replace_is_unknown_and_cancellation_preserved(report_case, monkeypatch):
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


def test_TDR_10_C06_report_link_rejected_before_publication(report_case, monkeypatch):
    from pathlib import Path
    context, _, path, request = report_case
    original = Path.is_symlink
    def report_link(candidate):
        return candidate == path or original(candidate)
    monkeypatch.setattr(Path, 'is_symlink', report_link)
    with pytest.raises(ValueError, match='link|symlink'):
        publish_evidence(context, request)
    assert not (path.parent / 'report_ref.json').exists()


def test_TDR_10_C07_foreign_experiment_evidence_rejected_before_publication(report_case):
    from czsc_trader.research_tools import ExperimentRef
    context, _, path, request = report_case
    foreign = replace(request.evidence[0], experiment=ExperimentRef('S901', 'EX002_20261021'))
    with pytest.raises(ValueError, match='experiment|owned|belong|batch'):
        publish_evidence(context, replace(request, evidence=(foreign,)))
    assert not (path.parent / 'report_ref.json').exists()


def test_TDR_10_C02_changed_draft_remains_unpublished(report_case):
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
