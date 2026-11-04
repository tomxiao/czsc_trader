"""Batch retention keeps account authentication and single-owner atomic writes."""

import pytest

from czsc_trader.application import publish_evidence, publish_evidence_many
from czsc_trader.application import evidence_service
from czsc_trader.research_tools import (
    MaterialEvidenceWrite,
    PublicationError, PublicationOutcome, PublicationStatus,
)
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


@pytest.fixture
def publication(tmp_path):
    from equity_test_support import setup_account_research
    context, request, _, _ = setup_account_research(tmp_path)
    return context, MaterialEvidenceWrite(request.experiment, 'material', b'{"fact": 1}', 'application/json', 'json')


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
    assert len(list(context.repository.root.glob("research/*/assets/evidence/**/*.json"))) == 1


def test_pre_install_write_failure_is_failed(publication, monkeypatch):
    context, account = publication

    def fail(*args):
        raise OSError("synthetic write failure")

    monkeypatch.setattr(evidence_service, "_publish_bytes", fail)
    outcome = publish_evidence_many(context, (account,))[0]
    assert outcome.status is PublicationStatus.FAILED and outcome.error.code == "OSError"
    assert not list(context.repository.root.glob("research/*/assets/evidence/**/*.json"))




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
    with pytest.raises(TypeError, match="ExecutionResources"):
        publish_evidence_many(context, (account,))
