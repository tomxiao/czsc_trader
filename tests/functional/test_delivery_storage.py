"""Publication transaction boundaries and content-addressed evidence."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from threading import Barrier

import pytest
from czsc_trader.application import assemble_delivery, publish_evidence
from czsc_trader.application import evidence_service
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evidence import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from test_research_delivery import content, attachment, context as context


def test_evidence_publication_is_explicit_idempotent_and_batch_scoped(context, monkeypatch):
    research = context
    request = MaterialEvidenceWrite(ExperimentRef("S900", "EX001_20261007"), "measurement", b"test", "text/plain", "txt")
    first = publish_evidence(research, request)
    original_open = Path.open
    temporary_root = research.repository.root / '.tmp/evidence-publication'

    def no_temporary(path, *args, **kwargs):
        assert path.parent != temporary_root, 'existing evidence must not create a temporary file'
        return original_open(path, *args, **kwargs)

    def no_new_write(*args, **kwargs):
        pytest.fail('existing evidence must not sync or link another file')

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, 'open', no_temporary)
        scoped.setattr(evidence_service.os, 'fsync', no_new_write)
        scoped.setattr(evidence_service.os, 'link', no_new_write)
        assert first == publish_evidence(research, request)
    assert first.path == f"evidence/{first.sha256}.txt"
    assert first.repository_path == f"research/S900/assets/evidence/EX001_20261007/{first.sha256}.txt"
    assert first.resolve(research.repository.root).read_bytes() == b"test"
    with pytest.raises(ValueError, match="another research batch"):
        publish_evidence(research, replace(request, experiment=ExperimentRef("S901", "EX001_20261007")))
    with pytest.raises(ValueError, match="allocated experiment"):
        publish_evidence(research, replace(request, experiment=ExperimentRef("S900", "EX002_20261007")))
    target = first.resolve(research.repository.root)
    target.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="overwritten"):
        publish_evidence(research, request)
    assert target.read_bytes() == b'tampered'
    with pytest.raises(ValueError, match="differs"):
        first.resolve(research.repository.root)


@pytest.mark.parametrize('same_content', [True, False])
def test_concurrent_evidence_install_never_overwrites_the_winner(tmp_path, monkeypatch, same_content):
    target = tmp_path / 'research/S900/assets/evidence/shared'
    values = (b'first complete content', b'first complete content' if same_content else b'other complete content')
    ready = Barrier(2, timeout=10)
    link = evidence_service.os.link
    synced = evidence_service.os.fsync
    sync_calls = []

    def sync(fd):
        synced(fd)
        sync_calls.append(fd)

    def race(source, destination):
        # Both writers must have observed the missing target and fully synced
        # their private files before the real atomic install is attempted.
        ready.wait()
        return link(source, destination)

    def publish(data):
        try:
            evidence_service._publish_bytes(tmp_path, target, data)
        except ValueError as exc:
            return str(exc)
        return None

    monkeypatch.setattr(evidence_service.os, 'fsync', sync)
    monkeypatch.setattr(evidence_service.os, 'link', race)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(publish, values))
    assert len(sync_calls) == 2
    if same_content:
        assert outcomes == (None, None)
        assert target.read_bytes() == values[0]
    else:
        assert outcomes.count(None) == 1
        assert 'published evidence cannot be overwritten' in outcomes
        assert target.read_bytes() == values[outcomes.index(None)]
    assert not list((tmp_path / '.tmp/evidence-publication').iterdir())


def test_existing_unreadable_evidence_is_not_republished(tmp_path, monkeypatch):
    target = tmp_path / 'research/S900/assets/evidence/existing'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'original')
    read = Path.read_bytes

    def unavailable(path):
        if path == target:
            raise PermissionError('evidence unreadable')
        return read(path)

    monkeypatch.setattr(Path, 'read_bytes', unavailable)
    with pytest.raises(PermissionError, match='evidence unreadable'):
        evidence_service._publish_bytes(tmp_path, target, b'original')
    assert read(target) == b'original'
    assert not (tmp_path / '.tmp/evidence-publication').exists()


def test_first_evidence_sync_failure_leaves_no_published_reference(context, monkeypatch):
    request = MaterialEvidenceWrite(ExperimentRef('S900', 'EX001_20261007'),
                                    'sync-failure', b'not yet durable', 'text/plain', 'txt')
    target = context.repository.root / request.experiment.repository_path.replace('/experiments/', '/assets/evidence/')
    target /= sha256(request.content).hexdigest() + '.txt'
    calls = []

    def fail_sync(fd):
        calls.append(fd)
        raise OSError('injected first publication sync failure')

    monkeypatch.setattr(evidence_service.os, 'fsync', fail_sync)
    with pytest.raises(OSError, match='first publication sync failure'):
        publish_evidence(context, request)
    assert len(calls) == 1
    assert not target.exists()
    assert not list((context.repository.root / '.tmp/evidence-publication').iterdir())


def test_missing_selected_evidence_leaves_no_visible_delivery(context):
    research = context
    reference = attachment(research)
    reference.resolve(research.repository.root).unlink()
    fact = d.FactValue("missing", None, "ratio", d.FactStatus.INSUFFICIENT_DATA, (reference,), "not available")
    definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 1)
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(research.repository, definition, replace(content(), facts=(fact,))).receipt
    assert not (research.repository.research_root / "S900/deliveries/COMPONENTS/1").exists()
    assert not (research.repository.research_root / "S900/assets/deliveries/COMPONENTS/1").exists()


def test_stage4_requires_its_typed_payload_before_storage(context):
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.ASSESSMENT, 1)
    with pytest.raises(TypeError, match="CandidateAssessmentDelivery"):
        assemble_delivery(context.repository, definition, content())
    assert not (context.repository.research_root / "S900/deliveries/ASSESSMENT/1").exists()
