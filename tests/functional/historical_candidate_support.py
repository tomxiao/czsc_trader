"""Seed retained candidates for explicit historical inspection tests, never a TDR write API."""
from hashlib import sha256
import json
from pathlib import Path
from strategy_manager import (CandidateEvidence, CandidateKey, CandidateRegistration,
    CandidateRegistrationOrigin, StrategyRegistry)
from strategy_runtime import StrategyRuntime


def seed_historical_candidate(context, candidate, experiment, evidence=(), dependencies=()):
    identity = StrategyRuntime().identify(candidate, dependencies=dependencies)
    root = context.research_root / candidate.strategy_family_id
    prefix = f"assets/candidates/{candidate.candidate_id}"
    def retain(relative, data):
        target = root / relative
        assert target.resolve().is_relative_to(context.root.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return CandidateEvidence(relative, sha256(data).hexdigest())
    data = json.dumps(dict(candidate.payload), default=dict, sort_keys=True,
        ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    payload = retain(f"{prefix}/payload/{sha256(data).hexdigest()}.json", data)
    source_root = f"{prefix}/source/{identity.source_sha256}/strategy_runtime"
    sources = tuple(retain(f"{source_root}/{name}", (candidate.source_root / name).read_bytes())
        for name in candidate.payload["runtime"]["source_files"])
    origin = CandidateRegistrationOrigin(experiment.experiment_id, tuple(CandidateEvidence(
        Path(item.repository_path).relative_to(Path(f"research/{candidate.strategy_family_id}")).as_posix(),
        item.sha256) for item in evidence))
    record = CandidateRegistration(CandidateKey(candidate.strategy_family_id, candidate.candidate_id),
        identity.content_sha256, identity.source_sha256, identity.dependency_sha256, payload,
        sources, source_root, tuple((item.name, item.version) for item in dependencies), origin)
    return StrategyRegistry(context.research_registry_root).register_candidate(record, evidence_root=root)
