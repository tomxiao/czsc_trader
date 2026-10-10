"""Batch retention keeps account authentication and single-owner atomic writes."""
from dataclasses import replace
from concurrent.futures import CancelledError
import json
import os
import shutil

import pytest

from czsc_trader.application import publish_evidence, publish_evidence_many
from czsc_trader.application import evidence_service
from czsc_trader.research_tools import (
    EvaluationEvidenceWrite, EvaluationResources, ExperimentRef, MaterialEvidenceWrite,
    PublicationError, PublicationOutcome, PublicationStatus,
)
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


@pytest.fixture
def publication(managed_evaluation):
    context, request = managed_evaluation
    bound = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(bound)
    experiment = ExperimentRef(context.strategy_id, request.experiment_id)
    return context, EvaluationEvidenceWrite(experiment, "synthetic-account", bound, result)


def terminated_serializer(payload, native_threads):
    os._exit(7)


def cancelled_serializer(payload, native_threads):
    raise CancelledError("synthetic cancellation")


@pytest.mark.parametrize("workers", [1, 2])
def test_batch_matches_single_bytes_and_only_parent_publishes(publication, monkeypatch, workers):
    context, account = publication
    single = publish_evidence(context, account)
    expected = single.resolve(context.repository.root).read_bytes()
    context.evaluation.resources = EvaluationResources(workers, 1)
    # Retention must consume authenticated facts without loading strategy files.
    shutil.rmtree(account.request.strategy.source_root)
    owners = []
    original = evidence_service._publish_bytes

    def record_owner(*args):
        owners.append(os.getpid())
        return original(*args)

    monkeypatch.setattr(evidence_service, "_publish_bytes", record_owner)
    material = MaterialEvidenceWrite(account.experiment, "note", b"synthetic", "text/plain", "txt")
    outcomes = publish_evidence_many(context, (account, material, account))
    assert [item.index for item in outcomes] == [0, 1, 2]
    assert all(item.status is PublicationStatus.PUBLISHED for item in outcomes)
    assert owners == [os.getpid()] * 3
    assert outcomes[0].reference == single == outcomes[2].reference
    assert outcomes[0].reference.resolve(context.repository.root).read_bytes() == expected
    validate_evaluation_evidence(json.loads(expected))
    assert outcomes[1].reference.resolve(context.repository.root).read_bytes() == material.content
    assert not list((context.repository.root / ".tmp/evidence-publication").iterdir())


@pytest.mark.parametrize("workers", [1, 2])
def test_partial_authentication_failure_is_an_item_result(publication, workers):
    context, account = publication
    context.evaluation.resources = EvaluationResources(workers, 1)
    bad = replace(account, result=replace(account.result, result_hash="f" * 64))
    outcomes = publish_evidence_many(context, (account, bad))
    assert [item.status for item in outcomes] == [PublicationStatus.PUBLISHED, PublicationStatus.FAILED]
    assert outcomes[1].error.code == "ValueError"
    assert outcomes[1].reference is None
    assert outcomes[0].reference.resolve(context.repository.root).is_file()
    assert len(list((context.repository.root / "research/S900/assets/evidence").rglob("*.json"))) == 1


@pytest.mark.parametrize("invalid", ["owner", "experiment", "repository", "data", "type"])
def test_invalid_batch_rejects_all_items_before_writing(publication, invalid):
    context, account = publication
    if invalid == "owner":
        bad = replace(account, experiment=ExperimentRef("S901", account.experiment.experiment_id))
    elif invalid == "experiment":
        bad = replace(account, experiment=ExperimentRef("S900", "EX002_20261007"))
    elif invalid == "data":
        bad = replace(account, request=replace(account.request, execution_data=None))
    elif invalid == "repository":
        bad = replace(account, request=replace(account.request, repository_root=context.repository.root / "foreign"))
    else:
        bad = object()
    with pytest.raises((TypeError, ValueError)):
        publish_evidence_many(context, (account, bad))
    assert not (context.repository.root / "research/S900/assets/evidence").exists()


def test_worker_loss_fails_without_serial_retry_or_formal_writes(publication, monkeypatch):
    context, account = publication
    context.evaluation.resources = EvaluationResources(2, 1)
    monkeypatch.setattr(evidence_service, "_serialize_worker", terminated_serializer)

    def no_retry(request):
        pytest.fail("failed worker must not serialize in the parent")

    monkeypatch.setattr(evidence_service, "_serialize_account", no_retry)
    outcomes = publish_evidence_many(context, (account, account))
    assert all(item.status is PublicationStatus.FAILED for item in outcomes)
    assert all(item.error.code == "BrokenProcessPool" for item in outcomes)
    assert not (context.repository.root / "research/S900/assets/evidence").exists()


def test_post_install_exception_is_unknown_and_is_not_retried(publication, monkeypatch):
    context, account = publication
    calls = []
    original = evidence_service._publish_bytes

    def installed_then_failed(*args):
        calls.append(1)
        original(*args)
        raise OSError("synthetic cleanup failure")

    monkeypatch.setattr(evidence_service, "_publish_bytes", installed_then_failed)
    outcome = publish_evidence_many(context, (account,))[0]
    assert outcome.status is PublicationStatus.UNKNOWN and outcome.reference is None
    assert outcome.error.code == "OSError"
    assert calls == [1]
    assert len(list((context.repository.root / "research/S900/assets/evidence").rglob("*.json"))) == 1


def test_pre_install_write_failure_is_failed(publication, monkeypatch):
    context, account = publication

    def fail(*args):
        raise OSError("synthetic write failure")

    monkeypatch.setattr(evidence_service, "_publish_bytes", fail)
    outcome = publish_evidence_many(context, (account,))[0]
    assert outcome.status is PublicationStatus.FAILED and outcome.error.code == "OSError"
    assert not (context.repository.root / "research/S900/assets/evidence").exists()


@pytest.mark.parametrize("workers", [1, 2])
def test_cancelled_serialization_never_publishes(publication, monkeypatch, workers):
    context, account = publication
    context.evaluation.resources = EvaluationResources(workers, 1)
    if workers == 1:
        def cancel(request):
            raise CancelledError("synthetic cancellation")
        monkeypatch.setattr(evidence_service, "_serialize_account", cancel)
    else:
        monkeypatch.setattr(evidence_service, "_serialize_worker", cancelled_serializer)
    outcome = publish_evidence_many(context, (account,))[0]
    assert outcome.status is PublicationStatus.CANCELLED and outcome.error.code == "CancelledError"
    assert not (context.repository.root / "research/S900/assets/evidence").exists()


def test_unreadable_target_after_write_exception_is_unknown(publication, monkeypatch):
    context, account = publication
    original = evidence_service.managed_path

    class UnreadableTarget:
        def read_bytes(self):
            raise PermissionError("cannot confirm evidence bytes")

    def unavailable(root, relative):
        if "/assets/evidence/" in relative:
            return UnreadableTarget()
        return original(root, relative)

    def fail(*args):
        raise OSError("synthetic write failure")

    monkeypatch.setattr(evidence_service, "managed_path", unavailable)
    monkeypatch.setattr(evidence_service, "_publish_bytes", fail)
    outcome = publish_evidence_many(context, (account,))[0]
    assert outcome.status is PublicationStatus.UNKNOWN and outcome.error.code == "OSError"


def test_publication_contracts_reject_ambiguous_outcomes(publication):
    context, account = publication
    reference = publish_evidence(context, account)
    with pytest.raises(ValueError, match="only an evidence"):
        PublicationOutcome(0, PublicationStatus.PUBLISHED)
    with pytest.raises(ValueError, match="only an error"):
        PublicationOutcome(0, PublicationStatus.UNKNOWN, reference, PublicationError("IO", "unknown"))
    with pytest.raises(TypeError, match="PublicationStatus"):
        PublicationOutcome(0, "PUBLISHED", reference)
    with pytest.raises(ValueError, match="nonnegative"):
        PublicationOutcome(True, PublicationStatus.PUBLISHED, reference)
    for requests in ((), [], [account]):
        with pytest.raises(ValueError, match="nonempty tuple"):
            publish_evidence_many(context, requests)
    context.evaluation.resources = object()
    with pytest.raises(TypeError, match="EvaluationResources"):
        publish_evidence_many(context, (account,))
