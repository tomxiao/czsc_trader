# Risk ownership: TDR-09
"""Batch retention keeps account authentication and single-owner atomic writes."""

import pytest

from czsc_trader.application import publish_evidence_many
from czsc_trader.application import evidence_service
from czsc_trader.research_tools import (
    MaterialEvidenceWrite,
    PublicationStatus,
)
from test_research_delivery import context as context


@pytest.fixture
def publication(context):
    # Material publication owns bytes, not a strategy, replay or market feed.
    from czsc_trader.research_tools import ExperimentRef
    return context, MaterialEvidenceWrite(ExperimentRef('S900', 'EX001_20261007'),
        'material', b'{"fact": 1}', 'application/json', 'json')


def test_TDR_09_C08_post_install_exception_is_unknown_and_is_not_retried(publication, monkeypatch):
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


def test_TDR_09_C07_pre_install_write_failure_is_failed(publication, monkeypatch):
    context, account = publication

    def fail(*args):
        raise OSError("synthetic write failure")

    monkeypatch.setattr(evidence_service, "_publish_bytes", fail)
    outcome = publish_evidence_many(context, (account,))[0]
    assert outcome.status is PublicationStatus.FAILED and outcome.error.code == "OSError"
    assert not list(context.repository.root.glob("research/*/assets/evidence/**/*.json"))


def test_TDR_09_C09_unreadable_target_after_write_exception_is_unknown(publication, monkeypatch):
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
