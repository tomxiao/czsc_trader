"""Historical candidate loading used only by explicit inspection and freeze operations."""
from importlib import metadata
import json
from strategy_manager import CandidateKey, StrategyRegistry
from strategy_runtime import StrategyCandidate, StrategyRuntime, ImplementationDependency
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition
from .context import RepositoryContext
from .candidate_service import _registered_root


def _load_inspection_candidate(context: RepositoryContext, key: CandidateKey) -> StrategyCandidate:
    registry = StrategyRegistry(context.research_registry_root)
    # Runtime admission authenticates executable content, not historical research.
    record = registry.get_candidate_registration(key)
    root = _registered_root(context, record)
    for name, expected in record.dependencies:
        if metadata.version(name) != expected:
            raise ValueError(f"registered candidate dependency version differs: {name}")
    for ref in record.source_files:
        ref.resolve(root)
    payload = json.loads(record.payload.resolve(root).read_text(encoding="utf-8"))
    source = root / record.source_root
    if payload.get("runtime", {}).get("kind") in {"US_EQUITY", "ACCOUNT_REPLAY"}:
        candidate = EquityStrategyCandidate(key.strategy_id, key.candidate_id,
                                            EquityStrategyDefinition.from_dict(payload['equity_definition']), source)
        identity = candidate.content_identity
        if (identity.content_sha256, identity.source_sha256, identity.dependency_sha256) != (
            record.content_sha256, record.source_sha256, record.dependency_sha256
        ):
            raise ValueError("registered equity identity differs")
        return candidate
    candidate = StrategyCandidate(key.strategy_id, key.candidate_id, payload, source)
    identity = StrategyRuntime().identify(candidate, dependencies=tuple(
        ImplementationDependency(*item) for item in record.dependencies))
    if (identity.content_sha256, identity.source_sha256, identity.dependency_sha256) != (
        record.content_sha256, record.source_sha256, record.dependency_sha256
    ):
        raise ValueError("registered candidate content identity differs")
    return candidate
