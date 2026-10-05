"""Explicit immutable candidate registration and loading business operations."""

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path

from research_experiment import (
    load_experiment,
    ExperimentPreflightReport,
    ExperimentPreflightCheck,
    ExperimentPreflightStatus,
)
from strategy_runtime import StrategyCandidate, StrategyRuntime, ImplementationDependency
from strategy_manager import (
    CandidateKey,
    CandidateEvidence,
    CandidateRegistrationOrigin,
    CandidateRegistration,
    CandidateDerivation,
    StrategyRegistry,
)

from .context import RepositoryContext
from .research_paths import candidate_root, registry_root
from .delivery_service import _resolve
from ..temp_workspace import create_temporary_directory


@dataclass(frozen=True, slots=True)
class CandidateRegistrationRequest:
    candidate: StrategyCandidate
    origin: CandidateRegistrationOrigin
    dependencies: tuple[ImplementationDependency, ...]
    derivation: CandidateDerivation | None = None

    def __post_init__(self):
        if not isinstance(self.candidate, StrategyCandidate) or not isinstance(
            self.origin, CandidateRegistrationOrigin
        ):
            raise TypeError("candidate and origin must be typed")
        if not isinstance(self.dependencies, tuple) or not all(
            isinstance(item, ImplementationDependency) for item in self.dependencies
        ):
            raise TypeError("dependencies must be a tuple of ImplementationDependency")
        if self.derivation is not None and not isinstance(self.derivation, CandidateDerivation):
            raise TypeError("derivation must be CandidateDerivation")


def _publish(root: Path, relative: str, data: bytes, temporary: Path) -> CandidateEvidence:
    ref = CandidateEvidence(relative, sha256(data).hexdigest())
    target = _resolve(root, relative)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("candidate file escapes registry root")
    if target.exists():
        ref.resolve(root)
        return ref
    if (root / "experiment_manifest.json").exists():
        raise ValueError("cannot add candidate objects to a sealed experiment")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = temporary / ref.sha256
    stage.write_bytes(data)
    # Exclusive creation prevents replacing an already published content address.
    try:
        with target.open("xb") as output:
            output.write(stage.read_bytes())
    except FileExistsError:
        ref.resolve(root)
    return ref


def register_candidate(
    context: RepositoryContext, request: CandidateRegistrationRequest
) -> CandidateRegistration:
    """Source/identity validation and persistence; never called implicitly by evaluation."""
    if not isinstance(request, CandidateRegistrationRequest):
        raise TypeError("register_candidate requires CandidateRegistrationRequest")
    candidate = request.candidate
    if candidate.source_root is None or not candidate.source_root.is_relative_to(
        context.root.resolve()
    ):
        raise ValueError("registration requires candidate sources inside repository")
    origin = request.origin
    experiment_root = candidate_root(context, CandidateKey(candidate.strategy_family_id, candidate.candidate_id),
                                     experiment_id=origin.experiment_id)
    loaded = load_experiment(experiment_root)
    binding_path = loaded.root / "experiment_binding.json"
    if (
        loaded.definition.schema_version != 2
        or loaded.definition.strategy_id != candidate.strategy_family_id
        or loaded.definition.experiment_id != origin.experiment_id
        or loaded.definition.sha256 != origin.definition_sha256
        or sha256(binding_path.read_bytes()).hexdigest() != origin.binding_sha256
    ):
        raise ValueError("candidate origin differs from bound experiment")
    declared = tuple(
        sorted(
            ImplementationDependency(item.name, item.version)
            for item in loaded.definition.dependencies
        )
    )
    if tuple(sorted(request.dependencies)) != declared:
        raise ValueError("candidate dependencies differ from experiment declaration")
    preflight_path = origin.preflight.resolve(context.root)
    report_payload = json.loads(preflight_path.read_text(encoding="utf-8"))
    report_payload.pop("passed", None)
    report_payload["checks"] = tuple(
        ExperimentPreflightCheck(
            item["code"],
            ExperimentPreflightStatus(item["status"]),
            item["message"],
        )
        for item in report_payload["checks"]
    )
    report = ExperimentPreflightReport(**report_payload)
    report.require_pass()
    required_checks = {
        "SOURCE_BOUND",
        "DEFINITION_BOUND",
        "RESOURCE_CONTRACT",
        "PREDECESSOR_CONTRACT",
        "ARCHIVE_IDENTITY",
    }
    if not required_checks.issubset({item.code for item in report.checks}):
        raise ValueError("candidate preflight report is incomplete")
    if (report.experiment_id, report.definition_sha256, report.source_sha256) != (
        origin.experiment_id,
        loaded.definition.sha256,
        loaded.binding.source_sha256,
    ):
        raise ValueError("preflight does not bind the candidate origin")
    runtime = StrategyRuntime()
    identity = runtime.identify(candidate, dependencies=request.dependencies)
    registry = StrategyRegistry(registry_root(context))
    registry.get_family(candidate.strategy_family_id)
    temporary = create_temporary_directory(context.root, "candidate-registration")
    root = loaded.root

    def copy_evidence(ref):
        data = ref.resolve(context.root).read_bytes()
        return _publish(root, f"objects/evidence/{ref.sha256}.json", data, temporary)

    payload_data = json.dumps(
        dict(candidate.payload),
        default=dict,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    payload = _publish(
        root, f"objects/payload/{sha256(payload_data).hexdigest()}.json", payload_data, temporary
    )
    source_files = []
    prefix = f"objects/source/{identity.source_sha256}/strategy_runtime"
    for name in candidate.payload["runtime"]["source_files"]:
        source = (candidate.source_root / name).resolve()
        if not source.is_relative_to(candidate.source_root):
            raise ValueError("candidate source escapes source_root")
        source_files.append(_publish(root, f"{prefix}/{name}", source.read_bytes(), temporary))
    saved_candidate = StrategyCandidate(
        candidate.strategy_family_id, candidate.candidate_id, candidate.payload, root / prefix
    )
    if (
        runtime.identify(saved_candidate, dependencies=request.dependencies) != identity
        or runtime.identify(candidate, dependencies=request.dependencies) != identity
    ):
        raise ValueError("candidate sources changed during registration")
    derivation = request.derivation
    if derivation is not None:
        from research_experiment import EvaluationRecord, EvaluationAttemptStatus

        parent = EvaluationRecord.from_dict(
            json.loads(derivation.evidence.resolve(context.root).read_text(encoding="utf-8"))
        )
        if (
            parent.status is not EvaluationAttemptStatus.SUCCEEDED
            or parent.candidate_id
            != f"{derivation.parent.strategy_id}-{derivation.parent.candidate_id}"
            or parent.content_sha256 != derivation.parent_content_sha256
        ):
            raise ValueError("derivation evidence differs from parent identity")
        derivation = replace(derivation, evidence=copy_evidence(derivation.evidence))
    record = CandidateRegistration(
        CandidateKey(candidate.strategy_family_id, candidate.candidate_id),
        identity.content_sha256,
        identity.source_sha256,
        identity.dependency_sha256,
        payload,
        tuple(source_files),
        tuple((item.name, item.version) for item in request.dependencies),
        replace(origin, preflight=copy_evidence(origin.preflight)),
        derivation,
    )
    return registry.register_candidate(record, evidence_root=loaded.root)


def _registered_root(context, record):
    return candidate_root(context, record.key, experiment_id=record.origin.experiment_id)


def _registration(context, key):
    record = StrategyRegistry(registry_root(context)).get_candidate(
        key, evidence_root=candidate_root(context, key)
    )
    _registered_root(context, record)
    return record


def load_candidate(context: RepositoryContext, key: CandidateKey) -> StrategyCandidate:
    record = _registration(context, key)
    evidence_root = _registered_root(context, record)
    payload = json.loads(record.payload.resolve(evidence_root).read_text(encoding="utf-8"))
    root = evidence_root / f"objects/source/{record.source_sha256}/strategy_runtime"
    candidate = StrategyCandidate(key.strategy_id, key.candidate_id, payload, root)
    identity = StrategyRuntime().identify(
        candidate,
        dependencies=tuple(ImplementationDependency(*item) for item in record.dependencies),
    )
    if (identity.content_sha256, identity.source_sha256, identity.dependency_sha256) != (
        record.content_sha256,
        record.source_sha256,
        record.dependency_sha256,
    ):
        raise ValueError("registered candidate content identity differs")
    return candidate
