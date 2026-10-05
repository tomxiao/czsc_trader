"""Record approved research identities using caller-owned, hash-pinned materials."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from strategy_manager import (
    ResearchEvidenceOwner, ResearchEvidenceRef, ResearchState, StrategyFamily,
    StrategyManagerError, StrategyRegistry,
)
from strategy_manager.validation import require_string

from .context import RepositoryContext
from .errors import ValidationError
from .research_paths import registry_root, repository_path, resolve_evidence
from .research_storage import require_research_write
from .results import CommandResult


def _read_object(context: RepositoryContext, path: Path) -> dict[str, Any]:
    resolved = repository_path(context, path)
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {resolved}")
    return value


def _family_from_request(raw: dict[str, Any], *, actor: str) -> StrategyFamily:
    required = {"strategy_id", "name", "scope", "research_intent", "credential_id"}
    unknown = sorted(set(raw) - required - {"research_state"})
    missing = sorted(required - set(raw))
    if unknown or missing:
        raise ValueError(f"research batch fields differ: missing={missing}, unknown={unknown}")
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    return StrategyFamily.from_dict({
        "schema_version": 2,
        "strategy_id": raw["strategy_id"], "name": raw["name"], "scope": raw["scope"],
        "research_intent": raw["research_intent"],
        "research_state": raw.get("research_state", ResearchState.RESEARCHING.value),
        "created_at": timestamp, "created_by": actor, "updated_at": timestamp,
    })


def create_research_batch(
    context: RepositoryContext,
    input_path: Path,
    *,
    material: ResearchEvidenceRef,
    actor: str,
    reason: str,
) -> CommandResult:
    """Register an approved batch; read its supplied material without organizing it."""
    try:
        root = registry_root(context)
        require_research_write(context, root)
        raw = _read_object(context, input_path)
        family = _family_from_request(raw, actor=actor)
        credential_id = require_string(raw["credential_id"], "credential_id")
        if type(material) is not ResearchEvidenceRef:
            raise TypeError("research batch material requires ResearchEvidenceRef")
        if material.owner != ResearchEvidenceOwner(family.strategy_id):
            raise ValueError("research batch material owner differs from family")
        resolve_evidence(context, material)
        registry = StrategyRegistry(root)
        # Registry owns its machine layout; research directory existence has no
        # bearing on identity creation or credential numbering.
        current = next((x for x in registry.list_families()
                        if x.strategy_id == family.strategy_id), None)
        content = {
            "research_batch": {
                "strategy_id": family.strategy_id, "name": family.name,
                "scope": family.scope, "research_intent": family.research_intent,
                "research_state": family.research_state.value,
            },
            "material": material.to_dict(), "reason": reason,
        }
        hashes = {"research_batch": material.sha256}
        if current is None:
            require_research_write(context, root)
            family = registry.create_family(
                family, actor=actor, reason=reason, credential_id=credential_id,
                credential_content=content, credential_artifact_hashes=hashes,
            )
            credential = registry.get_governance_credential(family.strategy_id, credential_id)
        else:
            if current.name != family.name or current.scope != family.scope:
                raise ValueError("existing strategy family name or scope differs from request")
            require_research_write(context, root)
            family, credential = registry.start_research_batch(
                family.strategy_id, research_intent=family.research_intent,
                research_state=family.research_state, actor=actor, reason=reason,
                credential_id=credential_id, credential_content=content,
                credential_artifact_hashes=hashes,
            )
    except (StrategyManagerError, OSError, TypeError, ValueError) as exc:
        raise ValidationError("research_batch_creation_failed", str(exc),
                              context={"command": "research.create"}) from exc
    return CommandResult("PASS", "research.create", {
        "family": family.to_dict(),
        "governance_credential": {
            "credential_id": credential.credential_id, "stage": credential.stage.value,
            "result": credential.result.value, "credential_hash": credential.credential_hash,
        },
        "material": material.to_dict(),
    })


def update_research_intent(
    context: RepositoryContext,
    strategy_id: str,
    input_path: Path,
    *,
    actor: str,
    reason: str,
) -> CommandResult:
    """Update family intent in the supplied registry without changing research materials."""
    try:
        root = registry_root(context)
        require_research_write(context, root)
        raw = _read_object(context, input_path)
        unknown = sorted(set(raw) - {"research_intent", "research_state"})
        if unknown or not raw:
            raise ValueError(f"research intent update has invalid fields: {unknown or sorted(raw)}")
        require_research_write(context, root)
        family = StrategyRegistry(root).update_family(
            strategy_id, research_intent=raw.get("research_intent"),
            research_state=raw.get("research_state"), actor=actor, reason=reason,
        )
    except (StrategyManagerError, OSError, TypeError, ValueError) as exc:
        raise ValidationError("research_intent_update_failed", str(exc),
                              context={"command": "research.intent.update", "strategy_id": strategy_id}) from exc
    return CommandResult("PASS", "research.intent.update", {"family": family.to_dict()})
