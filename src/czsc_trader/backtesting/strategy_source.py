from __future__ import annotations

from datetime import date
from pathlib import Path

from strategy_manager import StrategyRegistry, canonical_sha256
from strategy_runtime import StrategyCandidate, StrategyRuntime, load_strategy_deployment

from czsc_trader.application.context import RepositoryContext
from czsc_trader.identity import canonical_json_sha256

from .models import StrategyIdentity, StrategySnapshot


def _registered_snapshot_hash(
    source_hash: str, strategy_payload: dict[str, object]
) -> str:
    """Identify a frozen release without asking TDR to understand its rule."""

    return canonical_json_sha256(
        {"source_hash": source_hash, "strategy_payload": strategy_payload}
    )


def resolve_registered_strategy(
    context: RepositoryContext,
    strategy_id: str,
    version: str,
) -> StrategySnapshot:
    registry = StrategyRegistry(context.strategy_root)
    release = registry.get_version(strategy_id, version)
    source_hash = release.release_hash or canonical_sha256(release.release_payload())
    research_evidence = [
        item
        for item in registry.evidence(strategy_id, version)
        if item.phase.value == "RESEARCH_BACKTEST" and item.release_hash == source_hash
    ]
    research_window = (
        (
            min(date.fromisoformat(item.period_start) for item in research_evidence),
            max(date.fromisoformat(item.period_end) for item in research_evidence),
        )
        if research_evidence
        else None
    )
    strategy_payload = dict(release.strategy_payload)
    deployment = load_strategy_deployment(context.strategy_root, release.release_id)
    return StrategySnapshot(
        identity=StrategyIdentity(
            "REGISTERED", release.release_id, str(context.strategy_root)
        ),
        source_hash=source_hash,
        content_hash=_registered_snapshot_hash(source_hash, strategy_payload),
        strategy_payload=strategy_payload,
        research_start=None if research_window is None else research_window[0],
        research_end=None if research_window is None else research_window[1],
        runtime_root=deployment.source_root,
    )


def resolve_candidate_snapshot(
    context: RepositoryContext,
    candidate_id: str,
    strategy_payload: dict[str, object],
    content_hash: str,
    source: str,
    *,
    runtime_root: Path | None = None,
) -> StrategySnapshot:
    """Resolve a family-qualified SRT candidate; old rule-only payloads are retired."""
    if content_hash != canonical_sha256(strategy_payload):
        raise ValueError("candidate content hash differs from strategy payload")
    family, separator, local_id = candidate_id.partition("-")
    if not separator:
        raise ValueError("candidate replay requires a family-qualified identity")
    candidate = StrategyCandidate(family, local_id, strategy_payload, runtime_root)
    StrategyRuntime().describe(candidate)
    return StrategySnapshot(
        identity=StrategyIdentity("CANDIDATE", candidate.reference_id, source),
        source_hash=candidate.runtime_identity_sha256,
        content_hash=content_hash,
        strategy_payload=dict(strategy_payload),
        runtime_root=runtime_root,
    )
