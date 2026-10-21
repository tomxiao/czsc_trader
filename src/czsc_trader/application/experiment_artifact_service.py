"""Deterministic experiment material validation and report publication."""
from hashlib import sha256
import json
import os
from uuid import uuid4

from strategy_manager.write_lock import RegistryWriteLock

from .context import RepositoryContext
from ..research_tools._records import _canonical
from ..research_tools.context import ExperimentRef
from ..research_tools.delivery import ValidationStatus
from ..research_tools.evidence import EvidenceRef, managed_path
from ..research_tools.experiment_artifacts import (
    ExperimentIssue, ExperimentReportSnapshot, ExperimentValidation,
    ExperimentValidationRequest, ExperimentValidationScope, ReportPublicationError,
)


def _strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"nonfinite JSON constant: {value}")

    text = data.decode("utf-8") if type(data) is bytes else data
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def _experiment_path(root, reference):
    path = reference.resolve(root)
    source = managed_path(root, f"{reference.repository_path}/experiment.json")
    allocated = ExperimentRef.from_dict(_strict_json(source.read_bytes()))
    if allocated != reference:
        raise ValueError("allocated experiment identity differs")
    return path


def _pointer(root, experiment):
    path = managed_path(root, f"{experiment.repository_path}/report_ref.json")
    if not path.exists():
        return None
    raw = _strict_json(path.read_bytes())
    if (type(raw) is not dict or set(raw) != {"schema_version", "report"}
        or type(raw["schema_version"]) is not int or raw["schema_version"] != 1):
        raise ValueError("invalid report pointer schema")
    reference = EvidenceRef.from_dict(raw["report"])
    if reference.experiment != experiment or reference.schema != "experiment_report" or reference.schema_version != 1:
        raise ValueError("report pointer identity differs")
    return reference


def _read_report(root, reference):
    _, data = reference._read_verified(root)
    snapshot = ExperimentReportSnapshot.from_dict(_strict_json(data))
    if reference.schema != "experiment_report" or reference.schema_version != 1 or snapshot.experiment != reference.experiment:
        raise ValueError("report snapshot identity differs")
    for source in snapshot.evidence:
        source.resolve(root)
    if snapshot.previous is not None:
        snapshot.previous.resolve(root)
    return snapshot


def _validate_report_request(root, request):
    _experiment_path(root, request.experiment)
    source = managed_path(root, f"{request.experiment.repository_path}/report.md")
    data = source.read_bytes()
    if sha256(data).hexdigest() != request.expected_report_sha256:
        raise ValueError("root report differs from expected digest")
    text = data.decode("utf-8")
    if not text.strip():
        raise ValueError("root report must be nonempty")
    for reference in request.evidence:
        reference.resolve(root)
    if request.previous is not None:
        _read_report(root, request.previous)
    return data


def _replace_pointer(root, experiment, reference):
    # The pointer is the only mutable publication commit point. Never rewrite draft.
    target = managed_path(root, f"{experiment.repository_path}/report_ref.json")
    temporary_root = managed_path(root, ".tmp/experiment-report-publication")
    temporary_root.mkdir(parents=True, exist_ok=True)
    temporary = temporary_root / f"{uuid4().hex}.part"
    try:
        with temporary.open("xb") as stream:
            stream.write(json.dumps({"schema_version": 1, "report": reference.to_dict()},
                                    sort_keys=True, separators=(",", ":")).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _publish_report(context, request):
    from .evidence_service import _publish_bytes
    root = context.repository.root
    lock_root = managed_path(root, f".tmp/experiment-report-locks/{request.experiment.strategy_id}/{request.experiment.experiment_id}")
    reference = None
    pointer_committed = False
    phase = "LOCK"
    try:
        with RegistryWriteLock(lock_root).hold():
            phase = "PREPARE"
            data = _validate_report_request(root, request)
            snapshot = ExperimentReportSnapshot(1, request.experiment, data.decode("utf-8"),
                request.expected_report_sha256, request.outcome, request.evidence, request.previous)
            serialized = _canonical(snapshot)
            digest = sha256(serialized).hexdigest()
            proposed = EvidenceRef(request.experiment, f"{digest}.json", digest,
                "application/json", "experiment-report", "experiment_report", 1)
            current = _pointer(root, request.experiment)
            if current == proposed:
                _read_report(root, current)
                return current
            if current != request.previous:
                raise ValueError("report revision conflict: current pointer differs from previous")
            phase = "SNAPSHOT"
            try:
                _publish_bytes(root, managed_path(root, proposed.repository_path), serialized)
            except BaseException:
                try:
                    proposed.resolve(root)
                    reference = proposed
                except (OSError, ValueError):
                    pass
                raise
            reference = proposed
            phase = "COMMIT"
            # Detect edits during publication; no implicit rewrite or retry.
            _validate_report_request(root, request)
            try:
                _replace_pointer(root, request.experiment, reference)
            except BaseException:
                # Inspect before releasing ownership: another revision may be
                # committed as soon as this experiment lock is released.
                try:
                    pointer_committed = _pointer(root, request.experiment) == reference
                except (OSError, ValueError, TypeError):
                    pointer_committed = None
                raise
            pointer_committed = True
            return reference
    except BaseException as exc:
        if not isinstance(exc, Exception):
            # Preserve cancellation identity while exposing any durable side effect.
            exc.phase = phase
            exc.reference = reference
            exc.pointer_committed = pointer_committed
            raise
        raise ReportPublicationError(phase, str(exc) or type(exc).__name__, reference, pointer_committed) from exc


def validate_experiment(repository: RepositoryContext,
                        request: ExperimentValidationRequest) -> ExperimentValidation:
    if type(repository) is not RepositoryContext or type(request) is not ExperimentValidationRequest:
        raise TypeError("experiment validation requires RepositoryContext and ExperimentValidationRequest")
    issues = []
    report = None
    root = repository.root
    try:
        _experiment_path(root, request.experiment)
        for name in ("src", "protocols", "others"):
            if not managed_path(root, f"{request.experiment.repository_path}/{name}").is_dir():
                raise ValueError(f"missing experiment directory: {name}")
        draft = managed_path(root, f"{request.experiment.repository_path}/report.md").read_bytes()
        if not draft.decode("utf-8").strip():
            raise ValueError("root report is empty")
    except (OSError, ValueError, TypeError) as exc:
        issues.append(ExperimentIssue("INVALID_STRUCTURE", str(exc)))
    for item in request.artifacts:
        try:
            _experiment_path(root, item.owner)
            source = managed_path(root, f"{item.owner.repository_path}/{item.path}")
            if sha256(source.read_bytes()).hexdigest() != item.sha256:
                raise ValueError("declared material hash differs")
        except (OSError, ValueError, TypeError) as exc:
            issues.append(ExperimentIssue("INVALID_ARTIFACT", f"{item.path}: {exc}"))
    if request.scope is ExperimentValidationScope.REPORT_PUBLICATION:
        try:
            report = _pointer(root, request.experiment)
            if report is None:
                issues.append(ExperimentIssue("REPORT_UNPUBLISHED", "experiment has no published report"))
            else:
                snapshot = _read_report(root, report)
                source = managed_path(root, f"{request.experiment.repository_path}/report.md")
                if sha256(source.read_bytes()).hexdigest() != snapshot.report_sha256:
                    issues.append(ExperimentIssue("REPORT_MODIFIED", "root report contains unpublished changes"))
        except (OSError, ValueError, TypeError) as exc:
            issues.append(ExperimentIssue("INVALID_REPORT_PUBLICATION", str(exc)))
    return ExperimentValidation(ValidationStatus.FAIL if issues else ValidationStatus.PASS,
                                request.scope, tuple(issues), report)
