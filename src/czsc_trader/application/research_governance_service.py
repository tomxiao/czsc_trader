"""TDR governance at the research-batch boundary.

Research remains flexible.  This service only creates and maintains the stable
StrategyFamily identity that a human explicitly approved.
"""

from __future__ import annotations

import json
import hashlib
import shutil
from dataclasses import dataclass
from datetime import date, datetime
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
from ..research_tools.context import ResearchBatchRef, ResearchContext, ExperimentRef
from ..research_tools.evidence import managed_path
from ..research_tools.evaluation_access import EvaluationAccess, EvaluationResources
from dataflows import Dataflows, DataSpace, ProviderConfig
from strategy_runtime import StrategyRuntime
from strategy_manager.write_lock import RegistryWriteLock
from ..temp_workspace import create_temporary_directory
from .evidence_service import _publish_bytes
import re


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class ResearchBatchRequest:
    strategy_id: str
    name: str
    scope: str | tuple[str, ...] | dict[str, Any]
    research_intent: dict[str, Any]
    research_state: ResearchState = ResearchState.RESEARCHING
    credential_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.scope, (str, tuple, dict)):
            raise TypeError("scope requires text, a symbol tuple or an object")
        if isinstance(self.scope, tuple) and not all(isinstance(x, str) and x.strip() for x in self.scope):
            raise ValueError("scope symbols must be nonempty strings")
        if not isinstance(self.research_intent, dict):
            raise TypeError("research intent must be an object")
        if type(self.research_state) is not ResearchState:
            raise TypeError("research state requires ResearchState")
        if self.credential_id is not None and (not isinstance(self.credential_id, str) or
                not re.fullmatch(r"SGC-S[0-9]{3}-[0-9]{3}", self.credential_id)):
            raise ValueError("credential_id requires SGC-Sxxx-NNN")
        if self.credential_id and not self.credential_id.startswith(f"SGC-{self.strategy_id}-"):
            raise ValueError("credential belongs to another strategy")
        _family_from_request(self.as_mapping(), actor="validation")

    def as_mapping(self):
        return {"strategy_id": self.strategy_id, "name": self.name,
                "scope": list(self.scope) if isinstance(self.scope, tuple) else self.scope,
                "research_intent": self.research_intent,
                "research_state": self.research_state.value,
                "credential_id": self.credential_id}


@dataclass(frozen=True, slots=True)
class ResearchIntentUpdate:
    research_intent: dict[str, Any] | None = None
    research_state: ResearchState | None = None

    def __post_init__(self):
        if self.research_intent is None and self.research_state is None:
            raise ValueError("intent update requires an intent or state")
        if self.research_intent is not None and (not isinstance(self.research_intent, dict) or not self.research_intent):
            raise ValueError("research intent must be a nonempty object")
        if self.research_state is not None and type(self.research_state) is not ResearchState:
            raise TypeError("research state requires ResearchState")


@dataclass(frozen=True, slots=True)
class ExperimentRequest:
    title: str
    question: str
    run_date: date

    def __post_init__(self):
        if any(not isinstance(x, str) or not x.strip() for x in (self.title, self.question)):
            raise ValueError("experiment requires a title and a question")
        if type(self.run_date) is not date:
            raise TypeError("run_date requires date")


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
        "研究意图是可演化的人类语义。阶段目标和推进由用户确认；"
        "完成技术检验并取得用户对冻结计划的明确批准后，通过TDR公共冻结接口发布策略版本。\n"
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
    request: ResearchBatchRequest,
    *,
    actor: str,
    reason: str,
) -> ResearchBatchRef:
    """Human gate 1: atomically establish family identity and research space."""

    try:
        if type(request) is not ResearchBatchRequest:
            raise TypeError("research batch requires ResearchBatchRequest")
        raw = request.as_mapping()
        family = _family_from_request(raw, actor=actor)
        destination = managed_path(context.root, f"research/{family.strategy_id}")
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
            _publish_bytes(context.root, document, document_text.encode("utf-8"))
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
            _publish_bytes(context.root, document, batch_text.encode("utf-8"))
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
    reference = ResearchBatchRef(family.strategy_id)
    _publish_bytes(context.root, destination / "batch.json",
                   json.dumps(reference.to_dict(), sort_keys=True).encode("utf-8"))
    return reference


def update_research_intent(
    context: RepositoryContext,
    batch: ResearchBatchRef,
    request: ResearchIntentUpdate,
    *,
    actor: str,
    reason: str,
) -> ResearchBatchRef:
    """Update flexible family-level intent without changing frozen versions."""

    try:
        if type(batch) is not ResearchBatchRef or type(request) is not ResearchIntentUpdate:
            raise TypeError("intent update requires a batch reference and ResearchIntentUpdate")
        strategy_id = batch.strategy_id
        raw = {"research_intent": request.research_intent, "research_state": request.research_state}
        allowed = {"research_intent", "research_state"}
        unknown = sorted(set(raw) - allowed)
        if unknown or not raw:
            raise ValueError(f"research intent update has invalid fields: {unknown or sorted(raw)}")
        StrategyRegistry(context.research_registry_root).update_family(
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
            context={"command": "research.intent.update", "strategy_id": batch.strategy_id},
        ) from exc
    return batch


def create_research_context(
    repository: RepositoryContext, batch: ResearchBatchRef, *,
    resources: EvaluationResources | None = None, providers: ProviderConfig | None = None,
) -> ResearchContext:
    """Bind one registered research batch to its shared DFLS and runtime capabilities."""
    if type(repository) is not RepositoryContext or type(batch) is not ResearchBatchRef:
        raise TypeError("context requires RepositoryContext and ResearchBatchRef")
    StrategyRegistry(repository.research_registry_root).get_family(batch.strategy_id)
    managed_path(repository.root, f"research/{batch.strategy_id}/assets/data")
    data = Dataflows(base_dir=repository.root,
                    space=DataSpace(Path(f"research/{batch.strategy_id}/assets/data")),
                    providers=providers if providers is not None else ProviderConfig(env_file=repository.root / ".env"))
    return ResearchContext(batch, repository, data, StrategyRuntime(repository.strategy_root, dataflows=data),
                           EvaluationAccess(dataflows=data, resources=resources, strategy_id=batch.strategy_id))


def create_experiment(context: ResearchContext, request: ExperimentRequest) -> ExperimentRef:
    """Allocate an editable experiment; subsequent fixes reuse the same reference."""
    if type(context) is not ResearchContext or type(request) is not ExperimentRequest:
        raise TypeError("allocation requires ResearchContext and ExperimentRequest")
    root = context.repository.root
    parent = managed_path(root, f"research/{context.strategy_id}/experiments")
    lock = managed_path(root, f".tmp/research-allocation/{context.strategy_id}")
    with RegistryWriteLock(lock).hold():
        numbers = []
        for source in (parent, managed_path(root, f"experiments/{context.strategy_id}")):
            if source.is_dir():
                for child in source.iterdir():
                    match = re.match(r"EX([0-9]{3})_", child.name)
                    if match:
                        numbers.append(int(match.group(1)))
        number = max(numbers, default=0) + 1
        if number > 999:
            raise ValueError("experiment sequence exhausted")
        reference = ExperimentRef(context.strategy_id, f"EX{number:03}_{request.run_date:%Y%m%d}")
        staging = create_temporary_directory(root, "research-allocation")
        try:
            for name in ("src", "protocols", "others"):
                (staging / name).mkdir()
            (staging / "experiment.json").write_text(json.dumps(reference.to_dict(), sort_keys=True), encoding="utf-8")
            (staging / "notes.md").write_text(f"# {request.title}\n\n{request.question}\n", encoding="utf-8")
            parent.mkdir(parents=True, exist_ok=True)
            staging.rename(reference.resolve(root))
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return reference
