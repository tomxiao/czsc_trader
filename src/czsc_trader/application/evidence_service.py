"""Atomic, explicit publication of research result evidence."""

from hashlib import sha256
from concurrent.futures import CancelledError
from contextlib import nullcontext, closing
import json
import os
from pathlib import Path
from uuid import uuid4

from threadpoolctl import threadpool_limits
from strategy_runtime import canonical_sha256

from ..research_tools.context import ResearchContext, ExperimentRef
from ..research_tools.evidence import (
    EvidenceRef, EvidenceWriteRequest, EvaluationEvidenceWrite, MaterialEvidenceWrite, managed_path,
    PublicationStatus, PublicationError, PublicationOutcome,
    ExperimentReportWrite,
)
from ..research_tools.execution import ResearchExecutionSession, ExecutionPhase, ExecutionProgress
from ..research_tools._execution_session import ExecutionExecutor


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
        from ..research_tools.equity_replay_v3 import PreparedAccountEvaluation
        if type(request.request) is PreparedAccountEvaluation:
            validate_equity_result(context.evaluation, request.request, request.result, execution=execution)
            return
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
    from ..research_tools.equity_evaluation import EquityEvaluationResult
    if type(request.result) is EquityEvaluationResult:
        return request.result.content
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
        from ..research_tools.equity_evaluation import EquityEvaluationResult
        equity = type(request.result) is EquityEvaluationResult
        version = request.result.payload["schema_version"] if equity else 8
        media_type, suffix, schema = "application/json", "json", ("equity_research" if equity else "account_evaluation")
        document = json.loads(data)
        if equity and document.get("schema") != f"equity-research/v{version}":
            raise ValueError("equity publication requires its own versioned schema")
        if not equity and (document.get("schema_version") != version
                or document.get("request_identity", {}).get("schema_version") != 7):
            raise ValueError("new account publication requires schema 8 and request identity 7")
        if equity and version in (3, 4):
            # Dependencies are immutable, content-addressed and installed before
            # the final evaluation document becomes visible.
            for artifact in request.result.artifacts:
                digest = sha256(artifact.content).hexdigest()
                target = managed_path(context.repository.root,
                    f'{request.experiment.repository_path.replace("/experiments/", "/assets/evidence/")}/{digest}.json')
                if target.exists():
                    if target.read_bytes() != artifact.content:
                        raise ValueError('published equity dependency differs from its content identity')
                else:
                    _publish_bytes(context.repository.root, target, artifact.content)
    else:
        media_type, suffix = request.media_type, request.suffix
        schema, version = None, None
    digest = sha256(data).hexdigest()
    reference = EvidenceRef(request.experiment, f"{digest}.{suffix}", digest,
                            media_type, request.name, schema, version)
    root = context.repository.root
    _publish_bytes(root, managed_path(root, reference.repository_path), data)
    return reference


def _normalize_account_write(context, request, execution):
    from dataclasses import replace
    from ..research_tools.account_preparation import PreparedAccountEvaluation, require_account
    from ..research_tools.evaluation import EvaluationRequest
    if isinstance(request, EvaluationEvidenceWrite) and type(request.request) is PreparedAccountEvaluation:
        bound = require_account(context.evaluation, request.request, execution)
        if type(bound) is EvaluationRequest:
            return replace(request, request=bound)
    return request


def publish_evidence(context: ResearchContext, request: EvidenceWriteRequest, *, execution=None) -> EvidenceRef:
    request = _normalize_account_write(context, request, execution)
    _validate_request(context, request, execution=execution)
    if isinstance(request, ExperimentReportWrite):
        from .experiment_artifact_service import _publish_report
        return _publish_report(context, request)
    data = _serialize_account(request) if isinstance(request, EvaluationEvidenceWrite) else request.content
    return _publish_serialized(context, request, data)


def _failed(index: int, error: BaseException, status: PublicationStatus = PublicationStatus.FAILED):
    return PublicationOutcome(index, status, error=PublicationError(
        type(error).__name__, str(error) or type(error).__name__,
        getattr(error, "phase", None), getattr(error, "reference", None),
        getattr(error, "pointer_committed", None),
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
                          requests: tuple[EvidenceWriteRequest, ...], *,
                          execution: ResearchExecutionSession | None = None) -> tuple[PublicationOutcome, ...]:
    """Compute selected account evidence in parallel; only the parent publishes it."""
    if type(context) is not ResearchContext:
        raise TypeError("publication requires ResearchContext")
    if type(requests) is not tuple or not requests:
        raise ValueError("publish_evidence_many requires a nonempty tuple")
    requests = tuple(_normalize_account_write(context, item, execution) for item in requests)
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
    accounts = []
    from ..research_tools._evaluation_workers import pack

    publication_keys = {}
    for index, request in enumerate(requests):
        from ..research_tools.equity_replay_v3 import PreparedAccountEvaluation
        if (checkpoint is not None and isinstance(request, EvaluationEvidenceWrite)
                and type(request.request) is PreparedAccountEvaluation):
            key = canonical_sha256({'request_hash': request.result.request_hash,
                'result_hash': request.result.result_hash, 'experiment': request.experiment.to_dict(),
                'name': request.name, 'schema': 'equity_research', 'version': request.result.payload['schema_version']})
            publication_keys[index] = key
            reference = checkpoint.load_publication(key)
            if reference is not None:
                if (reference.name != request.name or reference.experiment != request.experiment
                        or (reference.schema, reference.schema_version) != ('equity_research', request.result.payload['schema_version'])
                        or reference.resolve(context.repository.root).read_bytes() != request.result.content):
                    raise ValueError('equity V3 publication checkpoint differs from authenticated result')
                for artifact in request.result.artifacts:
                    target = managed_path(context.repository.root,
                        f'{request.experiment.repository_path.replace("/experiments/", "/assets/evidence/")}/{sha256(artifact.content).hexdigest()}.json')
                    if target.read_bytes() != artifact.content:
                        raise ValueError('equity V3 checkpoint dependency changed')
                outcomes[index] = PublicationOutcome(index, PublicationStatus.PUBLISHED, reference)
                executor.reused_publications += 1
                continue
        elif checkpoint is not None and isinstance(request, EvaluationEvidenceWrite):
            # Names are part of the returned reference even when bytes coincide.
            key = canonical_sha256({"request_hash": request.result.request_hash,
                                    "result_hash": request.result.result_hash,
                                    "request_identity": request.request.strategy.runtime_identity_sha256,
                                    "experiment": request.experiment.to_dict(), "name": request.name,
                                    "schema": "account_evaluation", "version": 8})
            publication_keys[index] = key
            reference = checkpoint.load_publication(key)
            if reference is not None:
                # A valid reference cannot bypass request/result authentication.
                from ..research_tools.evaluation import _request_contract, _evaluation_result_hash
                if (canonical_sha256(_request_contract(request.request)[0]) != request.result.request_hash
                        or _evaluation_result_hash(request.result.request_hash, request.result.runs) != request.result.result_hash):
                    raise ValueError("publication checkpoint differs from supplied request/result")
                payload = json.loads(reference.resolve(context.repository.root).read_bytes())
                expected = {"request_hash": request.result.request_hash,
                            "result_hash": request.result.result_hash,
                            "strategy_identity": request.result.strategy_identity,
                            "runtime_binding_hash": request.result.runtime_binding_hash,
                            "data_identity": request.result.data_identity,
                            "execution_mode": request.result.execution_mode,
                            "input_bindings": {name: binding.to_dict() for name, binding in request.request.input_bindings.items()}}
                if (reference.name != request.name or reference.experiment != request.experiment
                        or (reference.schema, reference.schema_version) != ("account_evaluation", 8)
                        or payload.get("schema_version") != reference.schema_version
                        or any(payload.get(name) != value for name, value in expected.items())):
                    raise ValueError("publication checkpoint points to another evaluation")
                from ..research_tools.evaluation import validate_evaluation_evidence
                validate_evaluation_evidence(payload)
                outcomes[index] = PublicationOutcome(index, PublicationStatus.PUBLISHED, reference)
                executor.reused_publications += 1
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
            from ..research_tools.equity_replay_v3 import PreparedAccountEvaluation
            if type(request.request) is PreparedAccountEvaluation:
                with executor.measure(ExecutionPhase.PUBLISH):
                    outcomes[index] = _publish_outcome(context, index, request, request.result.content)
                if checkpoint is not None and outcomes[index].status is PublicationStatus.PUBLISHED:
                    checkpoint.save_publication(publication_keys[index], outcomes[index].reference)
            else:
                accounts.append((index, request))

    def tasks():
        for index, request in accounts:
            try:
                payload = pack(request)
            except Exception as exc:
                outcomes[index] = _failed(index, exc)
            else:
                yield index, (payload, resources.native_threads_per_worker)

    with (nullcontext(executor) if execution is not None else executor):
        with closing(executor.run(_serialize_worker, tasks(), phase=ExecutionPhase.SERIALIZE,
                                  total=len(accounts))) as completed:
            for index, data, error in completed:
                if error is not None:
                    status = (PublicationStatus.CANCELLED if isinstance(error, (CancelledError, KeyboardInterrupt, SystemExit))
                              else PublicationStatus.FAILED)
                    outcomes[index] = _failed(index, error, status)
                else:
                    with executor.measure(ExecutionPhase.PUBLISH):
                        outcomes[index] = _publish_outcome(context, index, requests[index], data)
                    if checkpoint is not None and outcomes[index].status is PublicationStatus.PUBLISHED:
                        checkpoint.save_publication(publication_keys[index], outcomes[index].reference)
        if executor.on_progress is not None:
            executor.notify(ExecutionProgress(
                ExecutionPhase.PUBLISH, len(outcomes), len(outcomes),
                sum(x.status in (PublicationStatus.FAILED, PublicationStatus.CANCELLED) for x in outcomes),
                sum(x.status is PublicationStatus.UNKNOWN for x in outcomes), executor.stats.elapsed_seconds))
    return tuple(outcomes)


def resolve_evidence(repository_root: Path, reference: EvidenceRef) -> Path:
    if type(reference) is not EvidenceRef:
        raise TypeError("reference requires EvidenceRef")
    return reference.resolve(repository_root)
