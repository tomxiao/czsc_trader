"""Atomic, explicit publication of research result evidence."""

from hashlib import sha256
from concurrent.futures import CancelledError
from contextlib import nullcontext
import json
import os
from pathlib import Path
from uuid import uuid4

from strategy_runtime import canonical_sha256

from ..research_tools.context import ResearchContext, ExperimentRef
from ..research_tools.evidence import (
    EvidenceRef, EvidenceWriteRequest, EvaluationEvidenceWrite, MaterialEvidenceWrite, managed_path,
    PublicationStatus, PublicationError, PublicationOutcome,
    ExperimentReportWrite,
)
from ..research_tools.execution import ResearchExecutionSession, ExecutionPhase, ExecutionProgress
from ..research_tools._execution_session import ExecutionExecutor


def _file_identity(path):
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _install_artifact(context, request, artifact, seen, *, restore=False, checkpoint=None):
    key = (request.experiment, artifact.sha256)
    target = managed_path(context.repository.root,
        f'{request.experiment.repository_path.replace("/experiments/", "/assets/evidence/")}/{artifact.sha256}.json')
    if target.exists():
        identity = _file_identity(target)
        if seen.get(key) == identity:
            return
        if target.read_bytes() != artifact.content:
            raise ValueError('published equity dependency differs from its content identity')
        if _file_identity(target) != identity:
            raise ValueError('published equity dependency changed while reading')
    elif restore:
        raise FileNotFoundError('equity publication checkpoint dependency is missing')
    else:
        if checkpoint is None:
            _publish_bytes(context.repository.root, target, artifact.content)
        else:
            _publish_checkpoint_blob(context.repository.root, target, artifact.content, artifact.sha256, checkpoint)
        identity = _file_identity(target)
    seen[key] = identity


def _publication_key(request):
    return canonical_sha256({'request_hash': request.result.request_hash,
        'result_hash': request.result.result_hash, 'experiment': request.experiment.to_dict(),
        'name': request.name, 'schema': 'equity_research', 'version': request.result.payload['schema_version']})


def _restored_publication(context, request, execution, key, seen):
    reference = execution.checkpoint.load_publication(key)
    if reference is None:
        return None
    if (reference.name != request.name or reference.experiment != request.experiment
            or (reference.schema, reference.schema_version) != ('equity_research', request.result.payload['schema_version'])
            or reference.sha256 != request.result.result_hash):
        raise ValueError('equity publication checkpoint differs from the requested result')
    # load_publication already verified the referenced header bytes. Install or
    # verify dependencies only once per unchanged file in this execution scope.
    for artifact in request.result.artifacts:
        _install_artifact(context, request, artifact, seen, restore=True)
    execution.executor.reused_publications += 1
    return reference


def _publish_bytes(repository_root: Path, target: Path, data: bytes) -> None:
    root = Path(repository_root).resolve()
    relative = Path(target).relative_to(root).as_posix()
    target = managed_path(root, relative)
    if not relative.startswith("research/"):
        raise ValueError("research evidence must stay within the research directory")
    try:
        existing = target.read_bytes()
    except FileNotFoundError:
        pass
    else:
        if existing != data:
            raise ValueError("published evidence cannot be overwritten")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = managed_path(root, ".tmp/evidence-publication")
    temporary_root.mkdir(parents=True, exist_ok=True)
    temporary = temporary_root / f"{uuid4().hex}.part"
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_bytes() != data:
                raise ValueError("published evidence cannot be overwritten") from None
    finally:
        temporary.unlink(missing_ok=True)


def _publish_checkpoint_blob(repository_root: Path, target: Path, data: bytes,
                             digest: str, checkpoint) -> None:
    """Explicitly publish a durable checkpoint blob without copying its bytes."""
    root = Path(repository_root).resolve()
    if checkpoint.repository_root != root:
        raise ValueError('publication checkpoint belongs to another repository')
    relative = Path(target).relative_to(root).as_posix()
    target = managed_path(root, relative)
    if not relative.startswith('research/'):
        raise ValueError('research evidence must stay within the research directory')
    source = checkpoint.publication_blob(digest, data)
    before = _file_identity(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except FileExistsError:
        existing = _file_identity(target)
        if target.read_bytes() != data:
            raise ValueError('published evidence cannot be overwritten') from None
        if _file_identity(target) != existing:
            raise ValueError('published evidence changed while reading')
        return
    # Creating the hard link legitimately changes ctime. The linked inode,
    # size and mtime must still identify the checked source bytes.
    if _file_identity(source)[:4] != before[:4] or _file_identity(target)[:4] != before[:4]:
        raise ValueError('checkpoint blob changed during publication')


def _validate_request(context: ResearchContext, request: EvidenceWriteRequest, *, execution=None) -> None:
    if type(context) is not ResearchContext or type(request) not in (
        MaterialEvidenceWrite, EvaluationEvidenceWrite, ExperimentReportWrite,
    ):
        raise TypeError("publication requires a research context and typed evidence request")
    if request.experiment.strategy_id != context.strategy_id:
        raise ValueError("evidence experiment belongs to another research batch")
    root = context.repository.root
    experiment = request.experiment.resolve(root)
    if not (experiment / "experiment.json").is_file():
        raise ValueError("evidence must belong to a platform-allocated experiment")
    from .experiment_artifact_service import _strict_json
    identity = managed_path(root, f"{request.experiment.repository_path}/experiment.json")
    recorded = ExperimentRef.from_dict(_strict_json(identity.read_bytes()))
    if recorded != request.experiment:
        raise ValueError("experiment identity differs from the allocated reference")
    if isinstance(request, ExperimentReportWrite):
        from .experiment_artifact_service import _validate_report_request
        _validate_report_request(root, request)
    if isinstance(request, EvaluationEvidenceWrite):
        from ..research_tools.equity_evaluation import validate_equity_result
        validate_equity_result(context.evaluation, request.request, request.result, execution=execution)


def _publish_serialized(context: ResearchContext, request: EvidenceWriteRequest, data: bytes, *,
                        artifacts_seen=None, checkpoint=None) -> EvidenceRef:
    if isinstance(request, EvaluationEvidenceWrite):
        from ..research_tools.equity_evaluation import EQUITY_EVIDENCE_VERSIONS
        media_type, suffix, schema = "application/json", "json", "equity_research"
        document = json.loads(data)
        version = document.get("schema_version")
        if version not in EQUITY_EVIDENCE_VERSIONS or document.get("schema") != f"equity-research/v{version}":
            raise ValueError("equity publication requires its own versioned schema")
        # Install each immutable dependency once before exposing the result.
        seen = {} if artifacts_seen is None else artifacts_seen
        for artifact in request.result.artifacts:
            _install_artifact(context, request, artifact, seen, checkpoint=checkpoint)
    else:
        media_type, suffix = request.media_type, request.suffix
        schema, version = None, None
    digest = sha256(data).hexdigest()
    reference = EvidenceRef(request.experiment, f"{digest}.{suffix}", digest,
                            media_type, request.name, schema, version)
    root = context.repository.root
    target = managed_path(root, reference.repository_path)
    if checkpoint is not None and isinstance(request, EvaluationEvidenceWrite):
        _publish_checkpoint_blob(root, target, data, digest, checkpoint)
    else:
        _publish_bytes(root, target, data)
    return reference


def publish_evidence(context: ResearchContext, request: EvidenceWriteRequest, *, execution=None) -> EvidenceRef:
    _validate_request(context, request, execution=execution)
    if execution is None and context.evaluation._active_execution is not None:
        raise RuntimeError("pass the active execution session explicitly")
    if execution is not None:
        if type(execution) is not ResearchExecutionSession:
            raise TypeError("execution requires ResearchExecutionSession")
        execution.require(context.evaluation, request.experiment.experiment_id)
    if isinstance(request, ExperimentReportWrite):
        from .experiment_artifact_service import _publish_report
        return _publish_report(context, request)
    data = request.result.content if isinstance(request, EvaluationEvidenceWrite) else request.content
    seen = {} if execution is None else execution._publication_artifacts
    key = (_publication_key(request) if isinstance(request, EvaluationEvidenceWrite)
           and execution is not None and execution.checkpoint is not None else None)
    with (execution.executor.measure(ExecutionPhase.PUBLISH) if execution is not None else nullcontext()):
        if key is not None:
            reference = _restored_publication(context, request, execution, key, seen)
            if reference is not None:
                return reference
        reference = _publish_serialized(context, request, data, artifacts_seen=seen,
            checkpoint=None if execution is None else execution.checkpoint)
        if key is not None:
            execution.checkpoint.save_publication(key, reference)
        return reference


def _failed(index: int, error: BaseException, status: PublicationStatus = PublicationStatus.FAILED):
    return PublicationOutcome(index, status, error=PublicationError(
        type(error).__name__, str(error) or type(error).__name__,
        getattr(error, "phase", None), getattr(error, "reference", None),
        getattr(error, "pointer_committed", None),
    ))


def _publish_outcome(context, index, request, data, *, artifacts_seen=None, checkpoint=None):
    if type(data) is not bytes or not data:
        return _failed(index, TypeError("publication requires nonempty serialized bytes"))
    try:
        return PublicationOutcome(index, PublicationStatus.PUBLISHED,
                                  _publish_serialized(context, request, data,
                                      artifacts_seen=artifacts_seen, checkpoint=checkpoint))
    except BaseException as exc:
        return _publication_failure(context, index, request, data, exc)


def _publication_failure(context, index, request, data, exc):
    # A failure after the atomic link (for example temporary-file cleanup)
    # must not claim that no evidence was installed. Never retry publication.
    suffix = "json" if isinstance(request, EvaluationEvidenceWrite) else request.suffix
    digest = sha256(data).hexdigest()
    relative = (f"research/{request.experiment.strategy_id}/assets/evidence/"
                f"{request.experiment.experiment_id}/{digest}.{suffix}")
    try:
        target = managed_path(context.repository.root, relative)
        installed = target.read_bytes() == data
        status = PublicationStatus.UNKNOWN if installed else PublicationStatus.FAILED
    except FileNotFoundError:
        status = PublicationStatus.FAILED
    except (OSError, ValueError):
        status = PublicationStatus.UNKNOWN
    return _failed(index, exc, status)


def publish_evidence_many(context: ResearchContext,
                          requests: tuple[EvidenceWriteRequest, ...], *,
                          execution: ResearchExecutionSession | None = None) -> tuple[PublicationOutcome, ...]:
    """Publish existing result bytes; account computation belongs to evaluation."""
    if type(context) is not ResearchContext:
        raise TypeError("publication requires ResearchContext")
    if type(requests) is not tuple or not requests:
        raise ValueError("publish_evidence_many requires a nonempty tuple")
    # Every ownership/contract error rejects the entire call before any write.
    for request in requests:
        _validate_request(context, request, execution=execution)
    if execution is None and context.evaluation._active_execution is not None:
        raise RuntimeError("pass the active execution session explicitly")
    if execution is not None:
        if type(execution) is not ResearchExecutionSession:
            raise TypeError("execution requires ResearchExecutionSession")
        for request in requests:
            execution.require(context.evaluation, request.experiment.experiment_id)
    resources = context.evaluation.resources
    executor = execution.executor if execution is not None else ExecutionExecutor(resources)
    checkpoint = None if execution is None else execution.checkpoint
    outcomes = [None] * len(requests)

    publication_keys = {}
    artifacts_seen = {} if execution is None else execution._publication_artifacts
    for index, request in enumerate(requests):
        from ..research_tools.equity_replay import PreparedAccountEvaluation
        if (checkpoint is not None and isinstance(request, EvaluationEvidenceWrite)
                and type(request.request) is PreparedAccountEvaluation):
            key = _publication_key(request)
            publication_keys[index] = key
            try:
                with executor.measure(ExecutionPhase.PUBLISH):
                    reference = _restored_publication(context, request, execution, key, artifacts_seen)
            except BaseException as exc:
                outcomes[index] = _publication_failure(context, index, request, request.result.content, exc)
                continue
            if reference is not None:
                outcomes[index] = PublicationOutcome(index, PublicationStatus.PUBLISHED, reference)
                continue
        if isinstance(request, ExperimentReportWrite):
            from .experiment_artifact_service import _publish_report
            try:
                with executor.measure(ExecutionPhase.PUBLISH):
                    outcomes[index] = PublicationOutcome(index, PublicationStatus.PUBLISHED,
                                                         _publish_report(context, request))
            except BaseException as exc:
                if isinstance(exc, (CancelledError, KeyboardInterrupt, SystemExit)):
                    status = (PublicationStatus.CANCELLED if getattr(exc, "pointer_committed", False) is False
                              else PublicationStatus.UNKNOWN)
                else:
                    status = (PublicationStatus.FAILED if getattr(exc, "pointer_committed", False) is False
                              else PublicationStatus.UNKNOWN)
                outcomes[index] = _failed(index, exc, status)
        elif isinstance(request, MaterialEvidenceWrite):
            with executor.measure(ExecutionPhase.PUBLISH):
                outcomes[index] = _publish_outcome(context, index, request, request.content)
        else:
            with executor.measure(ExecutionPhase.PUBLISH):
                outcomes[index] = _publish_outcome(context, index, request, request.result.content,
                                                 artifacts_seen=artifacts_seen, checkpoint=checkpoint)
            if checkpoint is not None and outcomes[index].status is PublicationStatus.PUBLISHED:
                try:
                    with executor.measure(ExecutionPhase.CHECKPOINT):
                        checkpoint.save_publication(publication_keys[index], outcomes[index].reference)
                except BaseException as exc:
                    outcomes[index] = _publication_failure(context, index, request, request.result.content, exc)

    with (nullcontext(executor) if execution is not None else executor):
        if executor.on_progress is not None:
            executor.notify(ExecutionProgress(
                ExecutionPhase.PUBLISH, len(outcomes), len(outcomes),
                sum(x.status in (PublicationStatus.FAILED, PublicationStatus.CANCELLED) for x in outcomes),
                sum(x.status is PublicationStatus.UNKNOWN for x in outcomes), executor.stats.elapsed_seconds))
    return tuple(outcomes)
