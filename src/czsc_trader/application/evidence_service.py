"""Atomic, explicit publication of research result evidence."""

from hashlib import sha256
from concurrent.futures import CancelledError, ProcessPoolExecutor, wait, FIRST_COMPLETED
import json
from multiprocessing import get_context
import os
from pathlib import Path
from uuid import uuid4

from threadpoolctl import threadpool_limits

from ..research_tools.context import ResearchContext, ExperimentRef
from ..research_tools.evidence import (
    EvidenceRef, EvidenceWriteRequest, EvaluationEvidenceWrite, MaterialEvidenceWrite, managed_path,
    PublicationStatus, PublicationError, PublicationOutcome,
)


def _publish_bytes(repository_root: Path, target: Path, data: bytes) -> None:
    root = Path(repository_root).resolve()
    relative = Path(target).relative_to(root).as_posix()
    target = managed_path(root, relative)
    if not relative.startswith("research/"):
        raise ValueError("research evidence must stay within the research directory")
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


def _validate_request(context: ResearchContext, request: EvidenceWriteRequest) -> None:
    if type(context) is not ResearchContext or type(request) not in (
        MaterialEvidenceWrite, EvaluationEvidenceWrite,
    ):
        raise TypeError("publication requires a research context and typed evidence request")
    if request.experiment.strategy_id != context.strategy_id:
        raise ValueError("evidence experiment belongs to another research batch")
    root = context.repository.root
    experiment = request.experiment.resolve(root)
    if not (experiment / "experiment.json").is_file():
        raise ValueError("evidence must belong to a platform-allocated experiment")
    recorded = ExperimentRef.from_dict(json.loads((experiment / "experiment.json").read_text(encoding="utf-8")))
    if recorded != request.experiment:
        raise ValueError("experiment identity differs from the allocated reference")
    if isinstance(request, EvaluationEvidenceWrite):
        if request.request.experiment_id != request.experiment.experiment_id:
            raise ValueError("evaluation request belongs to another experiment")
        if request.request.strategy.strategy_family_id != context.strategy_id:
            raise ValueError("evaluation belongs to another research batch")
        if Path(request.request.repository_root).resolve() != root:
            raise ValueError("evaluation repository differs from its research context")
        if (request.request.execution_data is None or request.request.execution_data.prepared is None
            or request.request.execution_data.prepared.space_id != context.data.binding.space_id):
            raise ValueError("evaluation must bind the batch data space")
        if any(binding.prepared.space_id != context.data.binding.space_id for binding in request.request.input_bindings.values()):
            raise ValueError("evaluation input belongs to another data space")


def _serialize_account(request: EvaluationEvidenceWrite) -> bytes:
    from ..research_tools.evaluation import serialize_evaluation_evidence

    value = serialize_evaluation_evidence(request.request, request.result)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _serialize_worker(payload: bytes, native_threads: int) -> bytes:
    import pickle

    # Private parent-created transport only; no research context or publication.
    request = pickle.loads(payload)
    with threadpool_limits(limits=native_threads):
        return _serialize_account(request)


def _publish_serialized(context: ResearchContext, request: EvidenceWriteRequest, data: bytes) -> EvidenceRef:
    if isinstance(request, EvaluationEvidenceWrite):
        media_type, suffix, schema, version = "application/json", "json", "account_evaluation", 6
    else:
        media_type, suffix = request.media_type, request.suffix
        schema, version = None, None
    digest = sha256(data).hexdigest()
    reference = EvidenceRef(request.experiment, f"{digest}.{suffix}", digest,
                            media_type, request.name, schema, version)
    root = context.repository.root
    _publish_bytes(root, managed_path(root, reference.repository_path), data)
    return reference


def publish_evidence(context: ResearchContext, request: EvidenceWriteRequest) -> EvidenceRef:
    _validate_request(context, request)
    data = _serialize_account(request) if isinstance(request, EvaluationEvidenceWrite) else request.content
    return _publish_serialized(context, request, data)


def _failed(index: int, error: BaseException, status: PublicationStatus = PublicationStatus.FAILED):
    return PublicationOutcome(index, status, error=PublicationError(
        type(error).__name__, str(error) or type(error).__name__,
    ))


def _publish_outcome(context, index, request, data):
    if type(data) is not bytes or not data:
        return _failed(index, TypeError("publication requires nonempty serialized bytes"))
    try:
        return PublicationOutcome(index, PublicationStatus.PUBLISHED,
                                  _publish_serialized(context, request, data))
    except BaseException as exc:
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
                          requests: tuple[EvidenceWriteRequest, ...]) -> tuple[PublicationOutcome, ...]:
    """Compute selected account evidence in parallel; only the parent publishes it."""
    if type(context) is not ResearchContext:
        raise TypeError("publication requires ResearchContext")
    if type(requests) is not tuple or not requests:
        raise ValueError("publish_evidence_many requires a nonempty tuple")
    # Every ownership/contract error rejects the entire call before any write.
    for request in requests:
        _validate_request(context, request)
    resources = context.evaluation.resources
    from ..research_tools.evaluation_access import EvaluationResources

    if type(resources) is not EvaluationResources:
        raise TypeError("publication resources require EvaluationResources")
    outcomes = [None] * len(requests)
    accounts = []
    from ..research_tools._evaluation_workers import pack

    for index, request in enumerate(requests):
        if isinstance(request, MaterialEvidenceWrite):
            outcomes[index] = _publish_outcome(context, index, request, request.content)
        else:
            try:
                if resources.max_workers == 1:
                    with threadpool_limits(limits=resources.native_threads_per_worker):
                        data = _serialize_account(request)
                    outcomes[index] = _publish_outcome(context, index, request, data)
                else:
                    accounts.append((index, request))
            except BaseException as exc:
                status = (PublicationStatus.CANCELLED if isinstance(exc, (CancelledError, KeyboardInterrupt, SystemExit))
                          else PublicationStatus.FAILED)
                outcomes[index] = _failed(index, exc, status)
    if accounts:
        try:
            with ProcessPoolExecutor(max_workers=min(len(accounts), resources.max_workers),
                                     mp_context=get_context("spawn")) as pool:
                pending = {}
                remaining = iter(accounts)
                exhausted = False
                while pending or not exhausted:
                    while not exhausted and len(pending) < resources.max_workers:
                        try:
                            index, request = next(remaining)
                        except StopIteration:
                            exhausted = True
                            break
                        try:
                            # Bound transport memory and overlap packing with computation.
                            payload = pack(request)
                            future = pool.submit(_serialize_worker, payload, resources.native_threads_per_worker)
                            pending[future] = (index, request)
                        except Exception as exc:
                            outcomes[index] = _failed(index, exc)
                    if not pending:
                        continue
                    completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in completed:
                        index, request = pending.pop(future)
                        try:
                            data = future.result()
                        except BaseException as exc:
                            status = (PublicationStatus.CANCELLED if isinstance(exc, (CancelledError, KeyboardInterrupt, SystemExit))
                                      else PublicationStatus.FAILED)
                            outcomes[index] = _failed(index, exc, status)
                        else:
                            outcomes[index] = _publish_outcome(context, index, request, data)
        except BaseException as exc:
            status = (PublicationStatus.CANCELLED if isinstance(exc, (CancelledError, KeyboardInterrupt, SystemExit))
                      else PublicationStatus.FAILED)
            for index, _ in accounts:
                if outcomes[index] is None:
                    outcomes[index] = _failed(index, exc, status)
    return tuple(outcomes)


def resolve_evidence(repository_root: Path, reference: EvidenceRef) -> Path:
    if type(reference) is not EvidenceRef:
        raise TypeError("reference requires EvidenceRef")
    return reference.resolve(repository_root)
