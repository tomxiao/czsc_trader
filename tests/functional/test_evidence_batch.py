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


def test_single_and_batch_publication_share_dependencies_and_detect_changed_bytes(tmp_path, monkeypatch):
    """The two publication shapes share one scoped implementation and failure contract."""
    from dataclasses import replace
    from pathlib import Path
    from equity_test_support import setup_account_research
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import ResearchExecutionSession, EvaluationEvidenceWrite
    from strategy_runtime import ExecutionResources

    context, request, _, _ = setup_account_research(tmp_path)
    context.evaluation.resources = ExecutionResources(1)
    other = replace(request, candidate=replace(request.candidate, candidate_id='C0002'))
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = tuple(context.evaluation.prepare(item, execution=execution) for item in (request, other))
        outcomes = context.evaluation.evaluate_many(prepared, execution=execution)
        assert all(outcome.result is not None for outcome in outcomes)
        first, second = (EvaluationEvidenceWrite(request.experiment, 'account', handle, outcome.result)
                         for handle, outcome in zip(prepared, outcomes, strict=True))
        publish_evidence(context, first, execution=execution)
        shared = first.result.artifacts[0]
        target = tmp_path / request.experiment.repository_path.replace('/experiments/', '/assets/evidence/') / f'{shared.sha256}.json'
        reads = []
        original = Path.read_bytes
        def counted(path):
            if path == target:
                reads.append(path)
            return original(path)
        monkeypatch.setattr(Path, 'read_bytes', counted)
        published, = publish_evidence_many(context, (second,), execution=execution)
        assert published.status is PublicationStatus.PUBLISHED
        publish_evidence(context, second, execution=execution)
        assert reads == []
        target.write_bytes(b'changed shared dependency')
        damaged, = publish_evidence_many(context, (second,), execution=execution)
        assert damaged.status is PublicationStatus.UNKNOWN
        assert 'dependency differs' in damaged.error.message
        assert reads == [target]


def test_publication_read_replacement_does_not_cache_unverified_file(tmp_path, monkeypatch):
    """A cold dependency read and its cache identity must describe the same file."""
    from pathlib import Path
    from equity_test_support import setup_account_research
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import ResearchExecutionSession, EvaluationEvidenceWrite

    context, request, _, _ = setup_account_research(tmp_path)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.result is not None, outcome.error
        write = EvaluationEvidenceWrite(request.experiment, 'account', prepared, outcome.result)
        publish_evidence(context, write, execution=execution)
        artifact = outcome.result.artifacts[0]
        target = tmp_path / request.experiment.repository_path.replace('/experiments/', '/assets/evidence/') / f'{artifact.sha256}.json'
        execution._publication_artifacts.clear()
        original_read = Path.read_bytes
        replaced = []

        def read_then_replace(path):
            body = original_read(path)
            if path == target and not replaced:
                replacement = target.with_suffix('.replacement')
                replacement.write_bytes(b'corrupted while reading')
                replacement.replace(target)
                replaced.append(path)
            return body

        monkeypatch.setattr(Path, 'read_bytes', read_then_replace)
        failed, = publish_evidence_many(context, (write,), execution=execution)
        assert failed.status is PublicationStatus.UNKNOWN
        assert 'changed while reading' in failed.error.message
        assert (request.experiment, artifact.sha256) not in execution._publication_artifacts
        again, = publish_evidence_many(context, (write,), execution=execution)
        assert again.status is PublicationStatus.UNKNOWN
        assert 'dependency differs' in again.error.message


@pytest.mark.parametrize('failure', ('restore_missing_header', 'restore_existing_header', 'save'))
def test_batch_checkpoint_failure_preserves_other_publication_outcomes(tmp_path, monkeypatch, failure):
    """One interrupted checkpoint never discards earlier item outcomes or retries it."""
    from dataclasses import replace
    from equity_test_support import setup_account_research
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import (
        ResearchExecutionSession, EvaluationEvidenceWrite, ExecutionCheckpointRequest)

    context, request, _, _ = setup_account_research(tmp_path)
    other = replace(request, candidate=replace(request.candidate, candidate_id='C0002'))
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest('batch-failure')) as execution:
        prepared = tuple(context.evaluation.prepare(item, execution=execution) for item in (request, other))
        outcomes = context.evaluation.evaluate_many(prepared, execution=execution)
        assert all(item.result is not None for item in outcomes), [item.error for item in outcomes]
        first, second = (EvaluationEvidenceWrite(request.experiment, 'account', handle, item.result)
                         for handle, item in zip(prepared, outcomes, strict=True))
        second_key = evidence_service._publication_key(second)
        if failure == 'restore_existing_header':
            publish_evidence(context, second, execution=execution)
        method = 'save_publication' if failure == 'save' else 'load_publication'
        original = getattr(execution.checkpoint, method)
        failed_calls = []

        def fail_second(key, *args):
            if key == second_key:
                failed_calls.append(key)
                raise OSError('synthetic checkpoint interruption')
            return original(key, *args)

        monkeypatch.setattr(execution.checkpoint, method, fail_second)
        published, failed = publish_evidence_many(context, (first, second), execution=execution)
        assert published.status is PublicationStatus.PUBLISHED
        assert published.reference._read_verified(tmp_path)[1] == first.result.content
        expected = PublicationStatus.FAILED if failure == 'restore_missing_header' else PublicationStatus.UNKNOWN
        assert failed.status is expected
        assert failed.error.code == 'OSError'
        assert failed.reference is None and failed_calls == [second_key]


def test_checkpoint_publication_links_raw_bytes_and_survives_cache_removal(tmp_path, monkeypatch):
    """Publication owns separate names for the same durable, immutable blobs."""
    import os
    from equity_test_support import setup_account_research
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import (
        ResearchExecutionSession, EvaluationEvidenceWrite, ExecutionCheckpointRequest)
    context, request, _, _ = setup_account_research(tmp_path)
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest('linked-blobs')) as execution:
        handle = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((handle,), execution=execution)
        assert outcome.result is not None, outcome.error
        result = outcome.result
        folder = tmp_path/request.experiment.repository_path.replace('/experiments/', '/assets/evidence/')
        assert not folder.exists()
        blobs = execution.checkpoint.root/'blobs'
        def unexpected_copy(*args, **kwargs):
            raise AssertionError('checkpoint-backed publication must link existing durable bytes')
        monkeypatch.setattr(evidence_service, '_publish_bytes', unexpected_copy)
        reference = publish_evidence(context, EvaluationEvidenceWrite(request.experiment,'account',handle,result),
            execution=execution)
        expected = [(a.sha256,a.content) for a in result.artifacts]+[(result.result_hash,result.content)]
        for digest, content in expected:
            cached, published = blobs/f'{digest}.json', folder/f'{digest}.json'
            assert cached.read_bytes() == published.read_bytes() == content
            assert cached.stat().st_size == len(content)
            assert os.path.samefile(cached,published)
    for cached in blobs.glob('*.json'):
        cached.unlink()
    assert reference._read_verified(tmp_path)[1] == result.content
    for digest, content in expected:
        assert (folder/f'{digest}.json').read_bytes() == content


@pytest.mark.parametrize('after_link', [False, True])
def test_checkpoint_link_failure_preserves_publication_status(tmp_path, monkeypatch, after_link):
    from dataclasses import replace
    from pathlib import Path
    from equity_test_support import setup_account_research
    from czsc_trader.research_tools import (
        ResearchExecutionSession, EvaluationEvidenceWrite, ExecutionCheckpointRequest)
    context, request, _, _ = setup_account_research(tmp_path)
    other = replace(request,candidate=replace(request.candidate,candidate_id='C0002'))
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest('link-failure')) as execution:
        handles = tuple(context.evaluation.prepare(r,execution=execution) for r in (request,other))
        outcomes = context.evaluation.evaluate_many(handles,execution=execution)
        assert all(o.result is not None for o in outcomes)
        writes = tuple(EvaluationEvidenceWrite(request.experiment,'account',h,o.result)
            for h,o in zip(handles,outcomes,strict=True))
        original = evidence_service.os.link
        calls = []
        def fail_second_header(source,target):
            if Path(target).name == writes[1].result.result_hash+'.json':
                calls.append(target)
                if after_link:
                    original(source,target)
                raise OSError('synthetic link failure')
            return original(source,target)
        monkeypatch.setattr(evidence_service.os,'link',fail_second_header)
        first, second = publish_evidence_many(context,writes,execution=execution)
        assert first.status is PublicationStatus.PUBLISHED
        assert second.status is (PublicationStatus.UNKNOWN if after_link else PublicationStatus.FAILED)
        assert second.error.code == 'OSError' and len(calls)==1


def test_changed_checkpoint_blob_blocks_publication(tmp_path):
    from equity_test_support import setup_account_research
    from czsc_trader.research_tools import (
        ResearchExecutionSession, EvaluationEvidenceWrite, ExecutionCheckpointRequest)
    context, request, _, _ = setup_account_research(tmp_path)
    with ResearchExecutionSession(context,experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest('changed-blob')) as execution:
        handle = context.evaluation.prepare(request,execution=execution)
        outcome, = context.evaluation.evaluate_many((handle,),execution=execution)
        assert outcome.result is not None
        artifact = outcome.result.artifacts[0]
        (execution.checkpoint.root/'blobs'/f'{artifact.sha256}.json').write_bytes(b'corrupt blob')
        failed, = publish_evidence_many(context,(EvaluationEvidenceWrite(request.experiment,'account',handle,outcome.result),),execution=execution)
        assert failed.status is PublicationStatus.FAILED
        assert 'authenticate checkpoint blob' in failed.error.message
