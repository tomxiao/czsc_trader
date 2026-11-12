"""Explicit candidate publication using source snapshots and selected evidence."""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from strategy_runtime import ImplementationDependency
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition
from strategy_manager import (
    CandidateKey, CandidateEvidence, CandidateRegistrationOrigin,
    CandidateRegistration, CandidateDerivation, StrategyRegistry,
)
from .context import RepositoryContext
from ..research_tools.context import ExperimentRef
from ..research_tools.evidence import EvidenceRef
from ..research_tools.equity_evaluation import EQUITY_EVIDENCE_VERSIONS
from ._frozen_materials import candidate_install_files


@dataclass(frozen=True, slots=True)
class CandidateRegistrationRequest:
    candidate: EquityStrategyCandidate
    experiment: ExperimentRef
    evidence: tuple[EvidenceRef, ...]
    dependencies: tuple[ImplementationDependency, ...]
    derivation: CandidateDerivation | None = None

    def __post_init__(self):
        if type(self.candidate) is not EquityStrategyCandidate or not isinstance(self.experiment, ExperimentRef):
            raise TypeError("registration requires an EquityStrategyCandidate and ExperimentRef")
        if self.candidate.definition.contract_version != 4:
            raise ValueError("new candidate registration requires account contract 4")
        if self.candidate.strategy_family_id != self.experiment.strategy_id:
            raise ValueError("candidate experiment family differs")
        if not isinstance(self.evidence, tuple) or not all(isinstance(item, EvidenceRef) for item in self.evidence):
            raise TypeError("candidate evidence requires a tuple of EvidenceRef")
        if len({item.repository_path for item in self.evidence}) != len(self.evidence):
            raise ValueError("candidate evidence paths must be unique")
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
    return ref


def _registered_root(context, record):
    return context.research_root / record.key.strategy_id


def load_candidate(context: RepositoryContext, key: CandidateKey) -> EquityStrategyCandidate:
    """Load a retained V4 implementation and admit it for execution once."""
    record = StrategyRegistry(context.research_registry_root).get_candidate_registration(key)
    root = _registered_root(context, record)
    _, data = record.payload._read_verified(root)
    payload = json.loads(data)
    if payload.get("runtime", {}).get("kind") != "ACCOUNT_REPLAY":
        raise ValueError("research candidate loading requires account contract 4")
    definition = EquityStrategyDefinition.from_dict(payload['equity_definition'])
    if definition.contract_version != 4:
        raise ValueError("research candidate loading requires account contract 4")
    install_files = (*definition.source_files, *(asset.relative_path for asset in definition.frozen_assets))
    expected_sources = {f"{record.source_root}/{name}" for name in install_files}
    if {ref.path for ref in record.source_files} != expected_sources:
        raise ValueError("registered equity source manifest differs")
    for reference in record.source_files:
        reference._resolve_path(root)
    candidate = EquityStrategyCandidate(key.strategy_id, key.candidate_id, definition, root / record.source_root)
    identity = candidate.content_identity
    if (identity.content_sha256, identity.source_sha256, identity.dependency_sha256) != (
        record.content_sha256, record.source_sha256, record.dependency_sha256
    ) or tuple((item.name, item.version) for item in definition.dependencies) != record.dependencies:
        raise ValueError("registered equity identity differs")
    return candidate


def register_candidate(context: RepositoryContext, request: CandidateRegistrationRequest) -> CandidateRegistration:
    """Retain a V4 implementation and its declared evidence, without result auditing."""
    if type(context) is not RepositoryContext or type(request) is not CandidateRegistrationRequest:
        raise TypeError("register_candidate requires RepositoryContext and CandidateRegistrationRequest")
    candidate = request.candidate
    if candidate.definition.contract_version != 4:
        raise ValueError('new equity registration requires account contract 4')
    if not candidate.source_root.is_relative_to(context.root.resolve()):
        raise ValueError("registration requires sources inside repository")
    if tuple(sorted(request.dependencies)) != tuple(sorted(candidate.definition.dependencies)):
        raise ValueError("equity identity dependency declaration differs")
    identity = candidate.content_identity
    # Capture the exact source bytes being published, without executing or admitting code.
    source_bytes = {}
    source_digest = sha256()
    for name in sorted(candidate.definition.source_files):
        path = candidate.source_root / name
        if (any(item.is_symlink() or item.is_junction() for item in (path, *path.parents)
                if item.is_relative_to(candidate.source_root))
            or not path.resolve().is_relative_to(candidate.source_root)):
            raise ValueError("candidate source escapes source root")
        data = path.read_bytes()
        source_bytes[name] = data
        source_digest.update(name.encode())
        source_digest.update(b"\0")
        source_digest.update(data)
        source_digest.update(b"\0")
    if source_digest.hexdigest() != identity.source_sha256:
        raise ValueError("equity source closure changed")
    for asset in candidate.definition.frozen_assets:
        path = asset.resolve(candidate.source_root)
        data = path.read_bytes()
        if sha256(data).hexdigest() != asset.sha256:
            raise ValueError('candidate data resource changed during publication')
        source_bytes[asset.relative_path] = data
    root = context.research_root / candidate.strategy_id
    experiment = request.experiment.resolve(context.root)
    if not experiment.is_dir():
        raise ValueError('candidate experiment does not exist')
    for path in (experiment, experiment.parent, root, context.research_root):
        if path.is_symlink() or path.is_junction():
            raise ValueError('equity candidate root contains a link')
    for ref in request.evidence:
        _, data = ref._read_verified(context.root)
        if ref.schema != 'equity_research' or ref.schema_version not in EQUITY_EVIDENCE_VERSIONS:
            raise ValueError('equity registration requires supported equity_research evidence')
        value = json.loads(data)
        if value.get('schema_version') != ref.schema_version:
            raise ValueError('equity support schema differs from its reference')
        from ..research_tools.equity_replay import validate_result_structure
        validate_result_structure(value)
        declaration = value['request']
        if declaration.get('candidate_id') != candidate.candidate_id or declaration.get('implementation_hash') != identity.content_sha256:
            raise ValueError('equity support differs from candidate content')
        owner = declaration.get('experiment', {})
        if (owner.get('strategy_id'), owner.get('experiment_id')) != (
            ref.experiment.strategy_id, ref.experiment.experiment_id
        ):
            raise ValueError('equity support experiment differs')
    if request.derivation is not None and request.derivation.child_content_sha256 != identity.content_sha256:
        raise ValueError('equity derivation identity differs')
    registry = StrategyRegistry(context.research_registry_root)
    registry.get_family(candidate.strategy_id)
    prefix = f'assets/candidates/{candidate.candidate_id}'
    payload_data = json.dumps(candidate.payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    payload = _publish(root, f'{prefix}/payload/{sha256(payload_data).hexdigest()}.json', payload_data, context.root)
    snapshot_identity = identity.content_sha256 if candidate.definition.frozen_assets else identity.source_sha256
    source_prefix = f'{prefix}/source/{snapshot_identity}/strategy_runtime'
    sources = tuple(_publish(root, f'{source_prefix}/{name}', source_bytes[name], context.root)
                    for name in candidate_install_files(candidate))
    origin = CandidateRegistrationOrigin(request.experiment.experiment_id, tuple(
        CandidateEvidence(Path(ref.repository_path).relative_to(Path(f'research/{candidate.strategy_id}')).as_posix(), ref.sha256)
        for ref in request.evidence))
    record = CandidateRegistration(candidate.key, identity.content_sha256, identity.source_sha256,
        identity.dependency_sha256, payload, sources, source_prefix,
        tuple((x.name, x.version) for x in candidate.definition.dependencies), origin, request.derivation)
    return registry.register_candidate(record, evidence_root=root)
