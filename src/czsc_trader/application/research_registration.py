"""Read and authenticate historical research registration evidence."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from strategy_manager import (
    GovernanceResult,
    GovernanceStage,
    StrategyRegistry,
)

from .context import RepositoryContext


_BACKFILL_FIELDS = {
    "schema_version",
    "strategy_id",
    "mode",
    "state",
    "backfilled_at",
    "credential_policy",
    "sources",
    "versions_at_backfill",
}


def _read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _require_sha256(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


def validate_registration_origin(
    context: RepositoryContext,
    strategy_id: str,
) -> dict | None:
    """Validate one immutable historical registration statement, when present."""

    path = context.research_registry_root / strategy_id / "registration_origin.json"
    if not path.is_file():
        return None
    origin = _read_object(path)
    if set(origin) != _BACKFILL_FIELDS or origin.get("schema_version") != 1:
        raise ValueError("historical registration origin fields are invalid")
    if (
        origin.get("strategy_id") != strategy_id
        or origin.get("mode") != "LEGACY_BACKFILL"
        or origin.get("state") != "PROMOTED_CLOSED"
        or origin.get("credential_policy") != "NO_RETROACTIVE_OPEN_CREDENTIAL"
    ):
        raise ValueError("historical registration origin identity is invalid")
    try:
        backfilled_at = datetime.fromisoformat(str(origin["backfilled_at"]))
    except ValueError as exc:
        raise ValueError("historical registration backfill time is invalid") from exc
    if backfilled_at.tzinfo is None:
        raise ValueError("historical registration backfill time must include a timezone")
    research = StrategyRegistry(context.research_registry_root)
    if research.get_family(strategy_id).strategy_id != strategy_id:
        raise ValueError("historical registration family identity is invalid")

    sources = origin.get("sources")
    expected_sources = {"governance_family", "governance_lifecycle", "research_handoff"}
    expected_paths = {
        "governance_family": f"strategies/{strategy_id}/family.json",
        "governance_lifecycle": f"strategies/{strategy_id}/lifecycle.jsonl",
        "research_handoff": f"research/{strategy_id}/HANDOFF.md",
    }
    if not isinstance(sources, dict) or set(sources) != expected_sources:
        raise ValueError("historical registration sources are invalid")
    for name, source in sources.items():
        if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
            raise ValueError(f"historical registration source is invalid: {name}")
        if source["path"] != expected_paths[name]:
            raise ValueError(f"historical registration source path is invalid: {name}")
        if not (context.root / source["path"]).is_file():
            raise ValueError(f"historical registration source is unavailable: {name}")
        _require_sha256(source["sha256"], f"sources.{name}.sha256")

    versions = origin.get("versions_at_backfill")
    if not isinstance(versions, list) or not versions:
        raise ValueError("historical registration must identify frozen versions")
    governance = StrategyRegistry(context.strategy_root)
    seen: set[str] = set()
    for item in versions:
        if not isinstance(item, dict) or set(item) != {
            "strategy_version_id",
            "strategy_version_hash",
        }:
            raise ValueError("historical registration version identity is invalid")
        reference = item["strategy_version_id"]
        if not isinstance(reference, str) or reference in seen:
            raise ValueError("historical registration repeats a strategy version")
        family, separator, version = reference.rpartition("-")
        if not separator or family != strategy_id:
            raise ValueError("historical registration version belongs to another strategy")
        stored = governance.get_version(strategy_id, version)
        if stored.release_id != reference or stored.release_hash != _require_sha256(
            item["strategy_version_hash"], "strategy_version_hash"
        ):
            raise ValueError("historical registration differs from frozen strategy version")
        seen.add(reference)

    directory = context.research_registry_root / strategy_id / "credentials"
    if directory.is_dir():
        for credential_path in sorted(directory.glob("*.jsonl")):
            credential = research.get_governance_credential(strategy_id, credential_path.stem)
            if (
                credential.stage is GovernanceStage.RESEARCH_INITIATED
                and credential.result is GovernanceResult.OPEN
                and datetime.fromisoformat(credential.seals[0].occurred_at) <= backfilled_at
            ):
                raise ValueError(
                    "historical registration cannot expose a retroactive open credential"
                )
    return origin
