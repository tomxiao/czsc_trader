"""Explicit candidate publication using source snapshots and selected evidence."""

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path

from strategy_runtime import StrategyCandidate, StrategyRuntime, ImplementationDependency
from strategy_manager import (
    CandidateKey, CandidateEvidence, CandidateRegistrationOrigin,
    CandidateRegistration, CandidateDerivation, StrategyRegistry,
)
from .context import RepositoryContext
from ..research_tools.context import ExperimentRef
from ..research_tools.evidence import EvidenceRef


@dataclass(frozen=True, slots=True)
class CandidateRegistrationRequest:
    candidate: StrategyCandidate
    experiment: ExperimentRef
    evidence: tuple[EvidenceRef, ...]
    dependencies: tuple[ImplementationDependency, ...]
    derivation: CandidateDerivation | None = None

    def __post_init__(self):
        if not isinstance(self.candidate, StrategyCandidate) or not isinstance(self.experiment, ExperimentRef):
            raise TypeError("candidate and experiment must be typed")
        if self.candidate.strategy_family_id != self.experiment.strategy_id:
            raise ValueError("candidate experiment family differs")
        if not isinstance(self.evidence, tuple) or not all(isinstance(item, EvidenceRef) for item in self.evidence):
            raise TypeError("candidate evidence requires a tuple of EvidenceRef")
        if not self.evidence or len(set(self.evidence)) != len(self.evidence):
            raise ValueError("candidate evidence must be nonempty and unique")
        if any(item.experiment.strategy_id != self.experiment.strategy_id for item in self.evidence):
            raise ValueError("candidate evidence belongs to another research batch")
        if not isinstance(self.dependencies, tuple) or not all(
            isinstance(item, ImplementationDependency) for item in self.dependencies
        ):
            raise TypeError("dependencies must be a tuple of ImplementationDependency")
        if self.derivation is not None and not isinstance(self.derivation, CandidateDerivation):
            raise TypeError("derivation must be CandidateDerivation")


def _publish(root: Path, relative: str, data: bytes, repository_root: Path) -> CandidateEvidence:
    from .evidence_service import _publish_bytes
    ref = CandidateEvidence(relative, sha256(data).hexdigest())
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("candidate file escapes evidence root")
    _publish_bytes(repository_root, target, data)
    ref.resolve(root)
    return ref


def _evaluation_support(context, ref, candidate, identity):
    """Registration accepts platform account evidence bound to the actual candidate."""
    value = json.loads(ref.resolve(context.root).read_text(encoding="utf-8"))
    if (ref.schema, ref.schema_version) != ("account_evaluation", 6) or value.get("schema_version") != 6:
        raise ValueError("candidate requires platform account evaluation evidence")
    from ..research_tools.evaluation import validate_evaluation_evidence
    validate_evaluation_evidence(value)
    if value["request_identity"]["experiment_id"] != ref.experiment.experiment_id:
        raise ValueError("candidate support evidence experiment differs")
    runs = value.get("runs", ())
    if not runs or any(
        item["identity"]["candidate"] != CandidateKey(candidate.strategy_family_id, candidate.candidate_id).to_dict()
        or item["identity"]["content_sha256"] != identity.content_sha256
        for item in runs
    ):
        raise ValueError("candidate support evidence differs from content identity")


def register_candidate(context: RepositoryContext, request: CandidateRegistrationRequest) -> CandidateRegistration:
    """Validate and persist a candidate independently from research execution history."""
    if not isinstance(request, CandidateRegistrationRequest):
        raise TypeError("register_candidate requires CandidateRegistrationRequest")
    candidate = request.candidate
    if candidate.source_root is None or not candidate.source_root.is_relative_to(context.root.resolve()):
        raise ValueError("registration requires candidate sources inside repository")
    root = context.research_root / request.experiment.strategy_id
    prefix_root = f"assets/candidates/{candidate.candidate_id}"
    experiment_root = request.experiment.resolve(context.root)
    for path in (experiment_root, experiment_root.parent, root, context.research_root):
        if path.is_symlink() or path.is_junction():
            raise ValueError("candidate experiment root contains a link")
    if not experiment_root.is_dir():
        raise ValueError("candidate experiment does not exist")
    runtime = StrategyRuntime()
    identity = runtime.identify(candidate, dependencies=request.dependencies)
    for ref in request.evidence:
        _evaluation_support(context, ref, candidate, identity)
    registry = StrategyRegistry(context.research_registry_root)
    registry.get_family(candidate.strategy_family_id)
    payload_data = json.dumps(dict(candidate.payload), default=dict, sort_keys=True,
                              ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    payload = _publish(root, f"{prefix_root}/payload/{sha256(payload_data).hexdigest()}.json", payload_data, context.root)
    source_files = []
    prefix = f"{prefix_root}/source/{identity.source_sha256}/strategy_runtime"
    for name in candidate.payload["runtime"]["source_files"]:
        source = (candidate.source_root / name).resolve()
        if not source.is_relative_to(candidate.source_root):
            raise ValueError("candidate source escapes source_root")
        source_files.append(_publish(root, f"{prefix}/{name}", source.read_bytes(), context.root))
    saved = StrategyCandidate(candidate.strategy_family_id, candidate.candidate_id, candidate.payload, root / prefix)
    if runtime.identify(saved, dependencies=request.dependencies) != identity or runtime.identify(
        candidate, dependencies=request.dependencies
    ) != identity:
        raise ValueError("candidate sources changed during registration")
    origin = CandidateRegistrationOrigin(request.experiment.experiment_id,
        tuple(CandidateEvidence(Path(ref.repository_path).relative_to(
            Path(f"research/{request.experiment.strategy_id}")).as_posix(), ref.sha256) for ref in request.evidence))
    derivation = request.derivation
    if derivation is not None:
        parent = json.loads(derivation.evidence.resolve(context.root).read_text(encoding="utf-8"))
        from ..research_tools.evaluation import validate_evaluation_evidence
        validate_evaluation_evidence(parent)
        if any(run["identity"]["candidate"] != derivation.parent.to_dict()
               or run["identity"]["content_sha256"] != derivation.parent_content_sha256
               for run in parent["runs"]):
            raise ValueError("derivation evidence differs from parent identity")
        derivation = replace(derivation, evidence=_publish(root,
            f"{prefix_root}/derivation/{derivation.evidence.sha256}.json",
            derivation.evidence.resolve(context.root).read_bytes(), context.root))
    record = CandidateRegistration(CandidateKey(candidate.strategy_family_id, candidate.candidate_id),
        identity.content_sha256, identity.source_sha256, identity.dependency_sha256, payload,
        tuple(source_files), prefix, tuple((item.name, item.version) for item in request.dependencies), origin, derivation)
    return registry.register_candidate(record, evidence_root=root)


def _registered_root(context, record):
    return context.research_root / record.key.strategy_id


def load_candidate(context: RepositoryContext, key: CandidateKey) -> StrategyCandidate:
    registry = StrategyRegistry(context.research_registry_root)
    record = registry.get_candidate(key, evidence_root=context.research_root / key.strategy_id)
    root = _registered_root(context, record)
    payload = json.loads(record.payload.resolve(root).read_text(encoding="utf-8"))
    source = root / record.source_root
    candidate = StrategyCandidate(key.strategy_id, key.candidate_id, payload, source)
    identity = StrategyRuntime().identify(candidate, dependencies=tuple(
        ImplementationDependency(*item) for item in record.dependencies))
    if (identity.content_sha256, identity.source_sha256, identity.dependency_sha256) != (
        record.content_sha256, record.source_sha256, record.dependency_sha256
    ):
        raise ValueError("registered candidate content identity differs")
    return candidate
