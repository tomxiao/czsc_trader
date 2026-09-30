"""TDR governance at the research-batch boundary.

Research remains flexible.  This service only creates and maintains the stable
StrategyFamily identity that a human explicitly approved.
"""

from __future__ import annotations

import json
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from strategy_manager import (
    ResearchState,
    StrategyFamily,
    StrategyManagerError,
    StrategyRegistry,
)

from .context import RepositoryContext
from .errors import ValidationError
from .results import CommandResult


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_object(context: RepositoryContext, path: Path) -> dict[str, Any]:
    resolved = path if path.is_absolute() else context.root / path
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {resolved}")
    return value


def _family_from_request(raw: dict[str, Any], *, actor: str) -> StrategyFamily:
    allowed = {
        "strategy_id",
        "name",
        "scope",
        "research_intent",
        "research_state",
        "credential_id",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"research batch request has unknown fields: {unknown}")
    missing = sorted({"strategy_id", "name", "scope", "research_intent"} - set(raw))
    if missing:
        raise ValueError(f"research batch request is missing fields: {missing}")
    timestamp = _now()
    return StrategyFamily.from_dict(
        {
            "schema_version": 2,
            "strategy_id": raw["strategy_id"],
            "name": raw["name"],
            "scope": raw["scope"],
            "research_intent": raw["research_intent"],
            "research_state": raw.get("research_state", ResearchState.RESEARCHING.value),
            "created_at": timestamp,
            "created_by": actor,
            "updated_at": timestamp,
        }
    )


def _handoff_text(family: StrategyFamily) -> str:
    scope = json.dumps(family.scope, ensure_ascii=False)
    intent = json.dumps(family.research_intent, ensure_ascii=False, indent=2)
    return (
        f"# {family.strategy_id} 研究交接\n\n"
        "## 当前身份\n\n"
        f"- 策略族：`{family.strategy_id} / {family.name}`；\n"
        f"- 初始范围：`{scope}`；\n"
        f"- 研究状态：`{family.research_state.value}`；\n"
        "- 当前没有候选、冻结版本或PTE账户。\n\n"
        "## 研究意图\n\n"
        "```json\n"
        f"{intent}\n"
        "```\n\n"
        "研究意图是可演化的人类语义。阶段目标由用户确认，"
        "新冻结流程尚未提供。\n"
    )


def _batch_text(family: StrategyFamily, credential_id: str, reason: str) -> str:
    return (
        f"# {credential_id} 研究批次\n\n"
        f"- 策略族：`{family.strategy_id} / {family.name}`；\n"
        f"- 治理凭据：`{credential_id}`；\n"
        f"- 立项原因：{reason}；\n"
        f"- 研究状态：`{family.research_state.value}`。\n\n"
        "## 研究意图\n\n"
        "```json\n"
        f"{json.dumps(family.research_intent, ensure_ascii=False, indent=2)}\n"
        "```\n\n"
        "本文件只记录本批次立项事实。阶段目标由用户确认；该记录不授予冻结权限。\n"
    )


def create_research_batch(
    context: RepositoryContext,
    input_path: Path,
    *,
    actor: str,
    reason: str,
) -> CommandResult:
    """Human gate 1: atomically establish family identity and research space."""

    try:
        raw = _read_object(context, input_path)
        family = _family_from_request(raw, actor=actor)
        destination = context.research_root / family.strategy_id
        registry = StrategyRegistry(context.research_registry_root)
        family_exists = (
            context.research_registry_root / family.strategy_id / "family.json"
        ).is_file()
        if not family_exists:
            new_research_directory = not destination.exists()
            raw_credential = raw.get("credential_id")
            if new_research_directory:
                credential_id = str(raw_credential or f"SGC-{family.strategy_id}-001")
            elif not isinstance(raw_credential, str) or not raw_credential.strip():
                raise ValueError(
                    "an existing research directory requires an explicit credential_id"
                )
            else:
                credential_id = raw_credential.strip()
            if new_research_directory and credential_id != f"SGC-{family.strategy_id}-001":
                raise ValueError("the first research batch credential must end with -001")
            if new_research_directory:
                document = destination / "HANDOFF.md"
                document_text = _handoff_text(family)
                artifact_name = "research_handoff"
            else:
                document = destination / "batches" / f"{credential_id}.md"
                document_text = _batch_text(family, credential_id, reason)
                artifact_name = "research_batch"
            if document.exists():
                raise ValueError(f"research batch document already exists: {credential_id}")
            document.parent.mkdir(parents=True, exist_ok=True)
            temporary = document.with_name(f".{document.name}.tmp")
            temporary.write_text(document_text, encoding="utf-8", newline="\n")
            temporary.replace(document)
            try:
                registry.create_family(
                    family,
                    actor=actor,
                    reason=reason,
                    credential_id=credential_id,
                    credential_content={
                        "research_batch": family.to_dict(),
                        "reason": reason,
                    },
                    credential_artifact_hashes={
                        artifact_name: hashlib.sha256(document_text.encode("utf-8")).hexdigest()
                    },
                )
                credential = registry.get_governance_credential(family.strategy_id, credential_id)
            except Exception:
                document.unlink(missing_ok=True)
                if new_research_directory:
                    shutil.rmtree(destination, ignore_errors=True)
                raise
        else:
            current = registry.get_family(family.strategy_id)
            if current.name != family.name or current.scope != family.scope:
                raise ValueError("existing strategy family name or scope differs from request")
            raw_credential = raw.get("credential_id")
            if not isinstance(raw_credential, str) or not raw_credential.strip():
                raise ValueError("another research batch requires an explicit credential_id")
            credential_id = raw_credential.strip()
            document = destination / "batches" / f"{credential_id}.md"
            batch_family = StrategyFamily.from_dict(
                {
                    **current.to_dict(),
                    "research_intent": family.research_intent,
                    "research_state": family.research_state.value,
                    "updated_at": family.updated_at,
                }
            )
            batch_text = _batch_text(batch_family, credential_id, reason)
            document.parent.mkdir(parents=True, exist_ok=True)
            if document.exists():
                raise ValueError(f"research batch document already exists: {credential_id}")
            temporary = document.with_name(f".{document.name}.tmp")
            temporary.write_text(batch_text, encoding="utf-8", newline="\n")
            temporary.replace(document)
            try:
                family, credential = registry.start_research_batch(
                    family.strategy_id,
                    research_intent=family.research_intent,
                    research_state=family.research_state,
                    actor=actor,
                    reason=reason,
                    credential_id=credential_id,
                    credential_content={
                        "research_batch": batch_family.to_dict(),
                        "reason": reason,
                    },
                    credential_artifact_hashes={
                        "research_batch": hashlib.sha256(batch_text.encode("utf-8")).hexdigest()
                    },
                )
            except Exception:
                document.unlink(missing_ok=True)
                raise
    except (StrategyManagerError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "research_batch_creation_failed",
            str(exc),
            context={"command": "research.create"},
        ) from exc
    return CommandResult(
        "PASS",
        "research.create",
        {
            "family": family.to_dict(),
            "governance_credential": {
                "credential_id": credential.credential_id,
                "stage": credential.stage.value,
                "result": credential.result.value,
                "credential_hash": credential.credential_hash,
            },
            "research_directory": destination.relative_to(context.root).as_posix(),
            "research_batch_document": document.relative_to(context.root).as_posix(),
        },
    )


def update_research_intent(
    context: RepositoryContext,
    strategy_id: str,
    input_path: Path,
    *,
    actor: str,
    reason: str,
) -> CommandResult:
    """Update flexible family-level intent without changing frozen versions."""

    try:
        raw = _read_object(context, input_path)
        allowed = {"research_intent", "research_state"}
        unknown = sorted(set(raw) - allowed)
        if unknown or not raw:
            raise ValueError(f"research intent update has invalid fields: {unknown or sorted(raw)}")
        family = StrategyRegistry(context.research_registry_root).update_family(
            strategy_id,
            research_intent=raw.get("research_intent"),
            research_state=raw.get("research_state"),
            actor=actor,
            reason=reason,
        )
    except (StrategyManagerError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "research_intent_update_failed",
            str(exc),
            context={"command": "research.intent.update", "strategy_id": strategy_id},
        ) from exc
    return CommandResult("PASS", "research.intent.update", {"family": family.to_dict()})
