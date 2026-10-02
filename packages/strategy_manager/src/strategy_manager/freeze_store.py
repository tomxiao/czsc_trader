"""Research freeze persistence; publish the runtime version only after durable acceptance."""

from dataclasses import dataclass, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil

from . import freeze_contracts as f
from .candidates import CandidateEvidence, CandidateRegistration, _registration_evidence_root
from .errors import RegistryError, ValidationError
from .models import StrategyVersion, canonical_sha256

_ACTIVE: set[Path] = set()


def _bytes(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _durable(path, value, *, temporary_root):
    """Same-volume staged write; the caller owns the registry lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_root.mkdir(parents=True, exist_ok=True)
    from uuid import uuid4

    temporary = temporary_root / f"{uuid4().hex}.json"
    try:
        with temporary.open("xb") as stream:
            stream.write(_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_decision(root, ref):
    if type(ref) is not f.DecisionReference:
        raise TypeError("decision requires DecisionReference")
    decision = f.ResearchDecision.from_dict(_read(ref.evidence.resolve(root)))
    if ref.decision_id != decision.decision_id:
        raise ValueError("decision identity differs")
    decision.confirmation_source.resolve(root)
    return decision


def record_decision(registry, decision):
    if type(decision) is not f.ResearchDecision:
        raise TypeError("record_research_decision requires ResearchDecision")
    decision.confirmation_source.resolve(registry.root)
    relative = f"research_decisions/{decision.strategy_id}/{decision.decision_id}.json"
    path = registry.root / relative
    encoded = _bytes(decision.to_dict())
    ref = f.DecisionReference(
        decision.decision_id, CandidateEvidence(relative, sha256(encoded).hexdigest())
    )
    if path.exists():
        ref.evidence.resolve(registry.root)
    else:
        _durable(path, decision.to_dict(), temporary_root=registry.root.parent / ".tmp/freeze")
    return ref


def validate_inspection(root, reference):
    report = f.CandidateInspectionReport.from_dict(_read(reference.resolve(root)))
    plan = report.plan
    registration = CandidateRegistration.from_dict(_read(plan.origin.registration.resolve(root)))
    if (
        registration.key != plan.origin.candidate
        or registration.content_sha256 != plan.origin.content_sha256
        or registration.record_sha256 != plan.origin.registration_sha256
        or registration.payload.sha256 != plan.payload.sha256
        or registration.origin.experiment_id != plan.source_experiment
    ):
        raise ValueError("inspection registration origin differs")
    required = {registration.origin.preflight.sha256}
    if registration.derivation:
        required.add(registration.derivation.evidence.sha256)
    if {ref.sha256 for ref in plan.registration_evidence} != required:
        raise ValueError("inspection registration evidence closure differs")
    selection = read_decision(root, report.selection)
    if (
        selection.action is not f.DecisionAction.APPROVE
        or type(selection.subject) is not f.CandidateSelectionSubject
        or selection.subject.candidate != plan.origin.candidate
        or selection.subject.content_sha256 != plan.origin.content_sha256
    ):
        raise ValueError("inspection selection differs")
    for ref in (
        plan.payload,
        plan.runtime_binding,
        *plan.registration_evidence,
        *(x.source for x in plan.source_files),
    ):
        ref.resolve(root)
    for check in report.checks:
        for ref in check.evidence:
            ref.resolve(root)
    return report


def validate_approval(root, request):
    report = validate_inspection(root, request.inspection)
    approval = read_decision(root, request.approval)
    plan = report.plan
    expected = f.FreezeSubject(
        plan.origin.candidate,
        plan.origin.content_sha256,
        request.inspection,
        plan.sha256,
        plan.version,
    )
    if (
        report.status is not f.InspectionStatus.PASS
        or approval.action is not f.DecisionAction.APPROVE
        or approval.subject != expected
        or request.request_id.strategy_id != plan.origin.candidate.strategy_id
    ):
        raise ValueError("freeze requires matching approval and complete passing inspection")
    return report


def build_version(root, request):
    report = validate_approval(root, request)
    plan = report.plan
    candidate = plan.origin.candidate
    version = StrategyVersion(
        5,
        candidate.strategy_id,
        plan.version,
        f"{candidate.strategy_id}-{plan.version}",
        plan.parent_version,
        plan.change_summary,
        plan.source_experiment,
        candidate.candidate_id,
        plan.selection_data_cutoff,
        plan.forward_start,
        _read(plan.payload.resolve(root)),
        "0" * 64,
    )
    return StrategyVersion.from_dict(
        replace(version, release_hash=canonical_sha256(version.release_payload())).to_dict()
    )


@dataclass(frozen=True, slots=True)
class FreezeVersionRequest:
    request: f.FreezeCandidateRequest
    staged_package: Path
    candidate_registry_root: Path
    experiments_root: Path

    def __post_init__(self):
        if (
            type(self.request) is not f.FreezeCandidateRequest
            or not isinstance(self.staged_package, Path)
            or not isinstance(self.candidate_registry_root, Path)
            or not isinstance(self.experiments_root, Path)
        ):
            raise TypeError("freeze_version requires typed request and paths")


def _transaction_root(registry, request_id):
    if type(request_id) is not f.FreezeRequestId:
        raise TypeError("freeze query requires FreezeRequestId")
    return registry.root / "freeze_requests" / request_id.strategy_id / request_id.value


def _package(root, expected_version, plan):
    manifest = _read(root / "release_manifest.json")
    expected_fields = {
        "schema_version",
        "strategy_version_id",
        "strategy_version_hash",
        "source_candidate_id",
        "candidate_package_hash",
        "runtime_root",
        "runtime_binding",
        "files",
        "package_hash",
    }
    if (
        set(manifest) != expected_fields
        or type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 1
    ):
        raise ValueError("freeze package manifest fields differ")
    if (
        manifest["source_candidate_id"]
        != f"{plan.origin.candidate.strategy_id}-{plan.origin.candidate.candidate_id}"
        or manifest["candidate_package_hash"] != plan.sha256
    ):
        raise ValueError("freeze package plan/candidate differs")
    identity = dict(manifest)
    package_hash = identity.pop("package_hash")
    if (
        package_hash != canonical_sha256(identity)
        or manifest["strategy_version_hash"] != expected_version.release_hash
        or manifest["strategy_version_id"] != expected_version.release_id
    ):
        raise ValueError("freeze package identity differs")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if any(p.is_symlink() or p.is_junction() for p in root.rglob("*")):
        raise ValueError("freeze package contains links")
    if actual != set(manifest["files"]) | {"release_manifest.json"}:
        raise ValueError("freeze package file inventory differs")
    for name, digest in manifest["files"].items():
        CandidateEvidence(name, digest).resolve(root)
    if (
        manifest["runtime_root"] != "src/strategy_runtime"
        or manifest["runtime_binding"] != "runtime_binding.json"
    ):
        raise ValueError("freeze package layout differs")
    expected = {f"src/strategy_runtime/{x.path}": x.source.sha256 for x in plan.source_files}
    if manifest["files"] != {
        **expected,
        "runtime_binding.json": manifest["files"].get("runtime_binding.json"),
    }:
        raise ValueError("freeze package differs from approved file closure")
    return package_hash


def query(registry, request_id):
    root = _transaction_root(registry, request_id)
    try:
        return _query(registry, request_id)
    except (OSError, ValueError, TypeError, KeyError, ValidationError) as exc:
        request_hash = None
        try:
            request_hash = f.FreezeCandidateRequest.from_dict(_read(root / "request.json")).sha256
        except (OSError, ValueError, TypeError, KeyError, ValidationError):
            pass
        return f.FreezeReceipt(
            request_id,
            f.FreezeStatus.UNKNOWN,
            request_hash,
            reason=f"freeze evidence cannot be verified: {type(exc).__name__}: {exc}",
        )


def _query(registry, request_id):
    root = _transaction_root(registry, request_id)
    if not (root / "request.json").exists():
        if (root / "committed.json").exists() or (root / "failed.json").exists():
            raise ValueError("terminal freeze record has no request")
        return f.FreezeReceipt(request_id, f.FreezeStatus.NOT_FOUND)
    request = f.FreezeCandidateRequest.from_dict(_read(root / "request.json"))
    if request.request_id != request_id:
        raise ValueError("stored freeze request identity differs")
    if (root / "committed.json").exists():
        receipt = f.FreezeReceipt.from_dict(_read(root / "committed.json"))
        if (
            receipt.status is not f.FreezeStatus.COMMITTED
            or receipt.request_sha256 != request.sha256
            or receipt.request_id != request_id
        ):
            raise ValueError("freeze commit marker differs")
        version_path = registry._version_path(request_id.strategy_id, receipt.version.version)
        if not version_path.exists() and root.resolve() in _ACTIVE:
            return f.FreezeReceipt(request_id, f.FreezeStatus.IN_PROGRESS, request.sha256)
        version = StrategyVersion.from_dict(_read(version_path))
        expected = build_version(registry.root, request)
        if (
            version.to_dict() != expected.to_dict()
            or receipt.version.release_hash != version.release_hash
        ):
            raise ValueError("committed version differs")
        plan = validate_approval(registry.root, request).plan
        package_hash = _package(
            registry.root / request_id.strategy_id / "releases" / version.version, version, plan
        )
        if receipt.version.package_hash != package_hash:
            raise ValueError("committed package differs")
        return receipt
    if (root / "failed.json").exists():
        receipt = f.FreezeReceipt.from_dict(_read(root / "failed.json"))
        if (
            receipt.status is not f.FreezeStatus.FAILED
            or receipt.request_id != request_id
            or receipt.request_sha256 != request.sha256
        ):
            raise ValueError("failed freeze receipt differs")
        return receipt
    if root.resolve() in _ACTIVE:
        return f.FreezeReceipt(request_id, f.FreezeStatus.IN_PROGRESS, request.sha256)
    # A durable STARTED record cannot prove that its former owner is alive.
    return f.FreezeReceipt(
        request_id,
        f.FreezeStatus.UNKNOWN,
        request.sha256,
        reason="freeze has no terminal commit record; explicit investigation required",
    )


def freeze(registry, request):
    from .registry import StrategyRegistry

    if type(request) is not FreezeVersionRequest:
        raise TypeError("freeze_version requires FreezeVersionRequest")
    operation = request.request
    existing = query(registry, operation.request_id)
    if existing.status is not f.FreezeStatus.NOT_FOUND:
        if existing.request_sha256 != operation.sha256:
            raise ValueError("freeze request ID already binds different content")
        return existing
    report = validate_approval(registry.root, operation)
    plan = report.plan
    research = StrategyRegistry(request.candidate_registry_root)
    registration = research.get_candidate(
        plan.origin.candidate, experiments_root=request.experiments_root
    )
    evidence_root = _registration_evidence_root(
        registration, request.experiments_root
    )
    if (
        registration.record_sha256 != plan.origin.registration_sha256
        or registration.content_sha256 != plan.origin.content_sha256
    ):
        raise ValueError("candidate changed since inspection")
    if (
        registration.payload.resolve(evidence_root).read_bytes()
        != plan.payload.resolve(registry.root).read_bytes()
    ):
        raise ValueError("freeze payload differs from registered candidate")
    runtime = _read(plan.payload.resolve(registry.root))["runtime"]
    planned = {x.path: x.source.sha256 for x in plan.source_files}
    source_prefix = f"objects/source/{registration.source_sha256}/strategy_runtime/"
    if {x.path.removeprefix(source_prefix): x.sha256 for x in registration.source_files} != {
        name: planned.get(name) for name in runtime["source_files"]
    }:
        raise ValueError("freeze source differs from registration")
    version = build_version(registry.root, operation)
    requests_root = registry.root / "freeze_requests" / version.strategy_id
    for path in requests_root.glob("*/request.json"):
        prior = f.FreezeCandidateRequest.from_dict(_read(path))
        prior_report = validate_inspection(registry.root, prior.inspection)
        if prior_report.plan.version == version.version and query(
            registry, prior.request_id
        ).status in {f.FreezeStatus.UNKNOWN, f.FreezeStatus.IN_PROGRESS}:
            raise RegistryError("target version is reserved by an unresolved freeze request")
    package_hash = _package(request.staged_package, version, plan)
    # The inspected binding template fixes all fields except the release identity.
    binding = _read(request.staged_package / "runtime_binding.json")
    template = _read(plan.runtime_binding.resolve(registry.root))
    if binding != {
        **template,
        "release_id": version.release_id,
        "release_hash": version.release_hash,
    }:
        raise ValueError("runtime binding differs from inspected plan")
    version_path = registry._version_path(version.strategy_id, version.version)
    package_path = registry.root / version.strategy_id / "releases" / version.version
    if version_path.exists() or package_path.exists():
        raise RegistryError("target version already exists; explicit version required")
    if plan.parent_version is not None:
        registry.get_version(version.strategy_id, plan.parent_version)
    family = research.get_family(version.strategy_id)
    registered = {x.strategy_id for x in registry.list_families()}
    if family.strategy_id in registered:
        if registry.get_family(family.strategy_id).name != family.name:
            raise ValueError("research and release family identity differ")
    root = _transaction_root(registry, operation.request_id)
    _durable(
        root / "request.json",
        operation.to_dict(),
        temporary_root=registry.root.parent / ".tmp/freeze",
    )
    _ACTIVE.add(root.resolve())
    try:
        if family.strategy_id not in registered:
            registry.create_family(family, actor="TDR.freeze", reason="首次冻结登记策略族")
        package_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(request.staged_package, package_path)
        for path in package_path.rglob("*"):
            if path.is_file():
                with path.open("r+b") as stream:
                    os.fsync(stream.fileno())
        _package(package_path, version, plan)
        receipt = f.FreezeReceipt(
            operation.request_id,
            f.FreezeStatus.COMMITTED,
            operation.sha256,
            f.FrozenVersionReference(
                version.strategy_id, version.version, version.release_hash, package_hash
            ),
        )
        _durable(
            root / "committed.json",
            receipt.to_dict(),
            temporary_root=registry.root.parent / ".tmp/freeze",
        )
        # Publish the version last: registry/runtime readers need no research transaction.
        _durable(
            version_path, version.to_dict(), temporary_root=registry.root.parent / ".tmp/freeze"
        )
        return receipt
    except Exception as exc:
        if (root / "committed.json").exists():
            return query(registry, operation.request_id)
        failure = f.FreezeReceipt(
            operation.request_id,
            f.FreezeStatus.FAILED,
            operation.sha256,
            reason=f"{type(exc).__name__}: {exc}",
        )
        _durable(
            root / "failed.json",
            failure.to_dict(),
            temporary_root=registry.root.parent / ".tmp/freeze",
        )
        return failure
    finally:
        _ACTIVE.discard(root.resolve())
