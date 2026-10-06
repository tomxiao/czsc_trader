from __future__ import annotations

import json
import shutil
import unicodedata
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .freeze_contracts import (
        FreezeReceipt,
        FreezeRequestId,
    )
    from .freeze_store import FreezeVersionRequest

from .errors import (
    EvidenceRequiredError,
    ImmutableVersionError,
    InvalidTransitionError,
    RegistryError,
    ValidationError,
)
from .lifecycle import qualification_is_deployable, validate_transition
from .models import (
    EvidencePhase,
    GovernanceResult,
    GovernanceStage,
    LifecycleEvent,
    PerformanceEvidence,
    Qualification,
    PaperTradingApproval,
    ResearchState,
    StrategyFamily,
    StrategyGovernanceCredential,
    StrategyGovernanceSeal,
    StrategyVersion,
    canonical_sha256,
)
from .validation import require_string
from .write_lock import RegistryWriteLock, registry_write
from .candidates import (
    CandidateKey,
    CandidateRegistration,
    CandidateIdentityConflict,
    validate_registration_files,
    _registration_evidence_root,
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _replace_file(source: Path, target: Path) -> None:
    for attempt in range(5):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            sleep(0.02 * (attempt + 1))


def _normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _canonical_json(value: Any, *, newline: bool = True) -> str:
    suffix = "\n" if newline else ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + suffix


class StrategyRegistry:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._write_lock = RegistryWriteLock(self.root)

    @registry_write
    def freeze_version(self, request: FreezeVersionRequest) -> FreezeReceipt:
        from .freeze_store import freeze

        return freeze(self, request)

    def get_freeze_result(self, request_id: FreezeRequestId, *, journal_root: Path) -> FreezeReceipt:
        from .freeze_store import query

        return query(self, request_id, journal_root=journal_root)

    @registry_write
    def register_candidate(
        self, record: CandidateRegistration, *, evidence_root: Path
    ) -> CandidateRegistration:
        if not isinstance(record, CandidateRegistration):
            raise TypeError("register_candidate requires CandidateRegistration")
        if record.schema_version != 3:
            raise ValidationError("new candidate registrations require schema 3")
        self.get_family(record.key.strategy_id)
        validate_registration_files(
            record, _registration_evidence_root(evidence_root)
        )
        path = (
            self._strategy_dir(record.key.strategy_id)
            / "candidates"
            / f"{record.key.candidate_id}.json"
        )
        if path.exists():
            existing = self.get_candidate(record.key, evidence_root=evidence_root)
            if existing.record_sha256 != record.record_sha256:
                raise CandidateIdentityConflict(
                    "candidate key is already bound to different content"
                )
            return existing
        self._atomic_write(
            path,
            _canonical_json({"record": record.to_dict(), "record_sha256": record.record_sha256}),
        )
        return record

    def get_candidate(self, key: CandidateKey, *, evidence_root: Path) -> CandidateRegistration:
        if not isinstance(key, CandidateKey):
            raise TypeError("get_candidate requires CandidateKey")
        path = self._strategy_dir(key.strategy_id) / "candidates" / f"{key.candidate_id}.json"
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise RegistryError("candidate record escapes registry")
        value = self._read_json(path)
        if set(value) != {"record", "record_sha256"}:
            raise RegistryError("invalid candidate registration envelope")
        record = CandidateRegistration.from_dict(value["record"])
        if record.key != key or record.record_sha256 != value["record_sha256"]:
            raise RegistryError("candidate registration identity differs")
        validate_registration_files(
            record, _registration_evidence_root(evidence_root)
        )
        return record

    @property
    def registry_path(self) -> Path:
        return self.root / "registry.json"

    def _load_registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {"schema_version": 1, "strategies": []}
        value = self._read_json(self.registry_path)
        if set(value) != {"schema_version", "strategies"} or value["schema_version"] != 1:
            raise RegistryError("registry.json has an unsupported schema")
        if not isinstance(value["strategies"], list):
            raise RegistryError("registry strategies must be a list")
        return value

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryError(f"cannot read JSON file: {path}") from exc
        if not isinstance(value, dict):
            raise RegistryError(f"JSON root must be an object: {path}")
        return value

    @registry_write
    def _atomic_write(self, path: Path, text: str, expected: bytes | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        current = path.read_bytes() if path.exists() else None
        if current != expected:
            raise RegistryError(f"concurrent change detected: {path}")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(text, encoding="utf-8", newline="\n")
            _replace_file(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @registry_write
    def _write_json(self, path: Path, value: dict[str, Any]) -> None:
        expected = path.read_bytes() if path.exists() else None
        self._atomic_write(path, _canonical_json(value), expected)

    @registry_write
    def _append_jsonl(self, path: Path, value: dict[str, Any]) -> None:
        expected = path.read_bytes() if path.exists() else None
        existing = expected.decode("utf-8") if expected else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        line = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self._atomic_write(path, f"{existing}{line}\n", expected)

    @registry_write
    def _restore_files(self, snapshots: list[tuple[Path, bytes | None]]) -> None:
        """Best-effort compensation for a failed multi-file governance commit."""

        failures: list[str] = []
        for path, previous in reversed(snapshots):
            try:
                if previous is None:
                    if path.exists():
                        path.unlink()
                else:
                    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.rollback")
                    temporary.write_bytes(previous)
                    _replace_file(temporary, path)
            except OSError as exc:
                failures.append(f"{path}: {exc}")
        if failures:
            raise RegistryError("governance transaction rollback failed: " + "; ".join(failures))

    def _strategy_dir(self, strategy_id: str) -> Path:
        return self.root / strategy_id

    def _version_path(self, strategy_id: str, version: str) -> Path:
        return self._strategy_dir(strategy_id) / "versions" / f"{version}.json"

    def _credential_path(self, strategy_id: str, credential_id: str) -> Path:
        return self._strategy_dir(strategy_id) / "credentials" / f"{credential_id}.jsonl"

    @staticmethod
    def _build_governance_seal(
        *,
        credential_id: str,
        strategy_id: str,
        sequence: int,
        stage: GovernanceStage,
        result: GovernanceResult,
        actor: str,
        previous_seal_hash: str | None,
        content: dict[str, Any],
        artifact_hashes: dict[str, str],
    ) -> StrategyGovernanceSeal:
        payload = {
            "schema_version": 1,
            "credential_id": credential_id,
            "strategy_id": strategy_id,
            "sequence": sequence,
            "stage": stage.value,
            "result": result.value,
            "actor": actor,
            "occurred_at": _now(),
            "previous_seal_hash": previous_seal_hash,
            "content": content,
            "content_hash": canonical_sha256(content),
            "artifact_hashes": artifact_hashes,
        }
        return StrategyGovernanceSeal.from_dict({**payload, "seal_hash": canonical_sha256(payload)})

    def get_governance_credential(
        self, strategy_id: str, credential_id: str
    ) -> StrategyGovernanceCredential:
        path = self._credential_path(strategy_id, credential_id)
        if not path.is_file():
            raise RegistryError(f"unknown governance credential: {credential_id}")
        try:
            seals = tuple(
                StrategyGovernanceSeal.from_dict(json.loads(line))
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
            return StrategyGovernanceCredential.from_seals(seals)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise RegistryError(f"invalid governance credential: {credential_id}") from exc

    @registry_write
    def open_governance_credential(
        self,
        credential_id: str,
        strategy_id: str,
        *,
        actor: str,
        content: dict[str, Any],
        artifact_hashes: dict[str, str] | None = None,
    ) -> StrategyGovernanceCredential:
        """Create the first seal for one globally unique governance credential."""

        self.get_family(strategy_id)
        path = self._credential_path(strategy_id, credential_id)
        if path.exists():
            existing = self.get_governance_credential(strategy_id, credential_id)
            first = existing.seals[0]
            if (
                first.actor == actor
                and first.content == content
                and first.artifact_hashes == (artifact_hashes or {})
            ):
                return existing
            raise RegistryError(f"governance credential already exists: {credential_id}")
        for family in self.list_families():
            other = self._credential_path(family.strategy_id, credential_id)
            if other.exists():
                raise RegistryError(
                    f"governance credential id already belongs to {family.strategy_id}: "
                    f"{credential_id}"
                )
        seal = self._build_governance_seal(
            credential_id=credential_id,
            strategy_id=strategy_id,
            sequence=1,
            stage=GovernanceStage.RESEARCH_INITIATED,
            result=GovernanceResult.OPEN,
            actor=actor,
            previous_seal_hash=None,
            content=content,
            artifact_hashes=artifact_hashes or {},
        )
        self._append_jsonl(path, seal.to_dict())
        return StrategyGovernanceCredential.from_seals((seal,))

    def list_families(self) -> list[StrategyFamily]:
        return [
            self.get_family(item["strategy_id"]) for item in self._load_registry()["strategies"]
        ]

    def get_family(self, strategy_id: str) -> StrategyFamily:
        path = self._strategy_dir(strategy_id) / "family.json"
        if not path.exists():
            raise RegistryError(f"unknown strategy family: {strategy_id}")
        return StrategyFamily.from_dict(self._read_json(path))

    def resolve_family(self, reference: str) -> StrategyFamily:
        registry = self._load_registry()
        match = next(
            (
                item
                for item in registry["strategies"]
                if reference == item["strategy_id"] or reference in item.get("aliases", [])
            ),
            None,
        )
        if match is None:
            raise RegistryError(f"unknown strategy reference: {reference}")
        return self.get_family(match["strategy_id"])

    def get_version(self, strategy_id: str, version: str) -> StrategyVersion:
        path = self._version_path(strategy_id, version)
        if not path.exists():
            raise RegistryError(f"unknown strategy version: {strategy_id}-{version}")
        raw = self._read_json(path)
        try:
            model = StrategyVersion.from_dict(raw)
        except ValidationError as exc:
            if "release_hash does not match" in str(exc):
                raise ImmutableVersionError(
                    f"release hash mismatch: {strategy_id}-{version}"
                ) from exc
            raise RegistryError(f"invalid strategy version {strategy_id}-{version}: {exc}") from exc
        return model

    def _versions(self, strategy_id: str) -> list[StrategyVersion]:
        directory = self._strategy_dir(strategy_id) / "versions"
        if not directory.exists():
            return []
        versions = []
        for path in directory.glob("v*.json"):
            versions.append(self.get_version(strategy_id, path.stem))
        return sorted(versions, key=lambda item: int(item.version[1:]))

    def versions(self, strategy_id: str) -> tuple[StrategyVersion, ...]:
        """Return registered versions, including an empty tuple for a new identity."""
        self.get_family(strategy_id)
        return tuple(self._versions(strategy_id))

    def resolve_strategy(self, reference: str, version: str | None = None) -> StrategyVersion:
        strategy = self.resolve_family(reference)
        versions = self._versions(strategy.strategy_id)
        if version is not None:
            return self.get_version(strategy.strategy_id, version)
        if not versions:
            raise RegistryError(f"strategy has no versions: {strategy.strategy_id}")
        return versions[-1]

    @registry_write
    def create_family(
        self,
        strategy: StrategyFamily | dict[str, Any],
        *,
        actor: str,
        reason: str,
        aliases: list[str] | None = None,
        credential_id: str | None = None,
        credential_content: dict[str, Any] | None = None,
        credential_artifact_hashes: dict[str, str] | None = None,
    ) -> StrategyFamily:
        require_string(actor, "actor")
        require_string(reason, "reason")
        model = (
            strategy if isinstance(strategy, StrategyFamily) else StrategyFamily.from_dict(strategy)
        )
        registry = self._load_registry()
        if any(item["strategy_id"] == model.strategy_id for item in registry["strategies"]):
            raise RegistryError(f"strategy already exists: {model.strategy_id}")
        normalized = _normalized_name(model.name)
        if any(_normalized_name(existing.name) == normalized for existing in self.list_families()):
            raise RegistryError(f"active strategy name already exists: {model.name}")
        alias_list = aliases or []
        known_references = {
            reference
            for item in registry["strategies"]
            for reference in [item["strategy_id"], *item.get("aliases", [])]
        }
        if model.strategy_id in alias_list or any(
            alias in known_references for alias in alias_list
        ):
            raise RegistryError("strategy aliases must be unique")
        registry["strategies"].append(
            {"strategy_id": model.strategy_id, "path": model.strategy_id, "aliases": alias_list}
        )
        registry["strategies"].sort(key=lambda item: item["strategy_id"])
        strategy_dir = self._strategy_dir(model.strategy_id)
        strategy_path = strategy_dir / "family.json"
        if strategy_dir.exists():
            raise RegistryError(f"strategy directory already exists: {model.strategy_id}")
        registry_before = self.registry_path.read_bytes() if self.registry_path.exists() else None
        event = self._event(
            "RESEARCH_BATCH_CREATED",
            model.strategy_id,
            None,
            None,
            Qualification.RESEARCH,
            actor,
            reason,
            [f"FAMILY:{canonical_sha256(model.to_dict())}"],
            None,
        )
        credential_path: Path | None = None
        credential_text: str | None = None
        if credential_id is not None:
            credential_id = require_string(credential_id, "credential_id")
            if not isinstance(credential_content, dict) or not credential_content:
                raise RegistryError(
                    "credential_content is required when creating a governance credential"
                )
            for family in self.list_families():
                if self._credential_path(family.strategy_id, credential_id).exists():
                    raise RegistryError(f"governance credential id already exists: {credential_id}")
            seal = self._build_governance_seal(
                credential_id=credential_id,
                strategy_id=model.strategy_id,
                sequence=1,
                stage=GovernanceStage.RESEARCH_INITIATED,
                result=GovernanceResult.OPEN,
                actor=actor,
                previous_seal_hash=None,
                content=credential_content,
                artifact_hashes=credential_artifact_hashes or {},
            )
            credential_path = self._credential_path(model.strategy_id, credential_id)
            credential_text = (
                json.dumps(
                    seal.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        try:
            self._atomic_write(strategy_path, _canonical_json(model.to_dict()), None)
            self._append_jsonl(strategy_dir / "lifecycle.jsonl", event.to_dict())
            if credential_path is not None and credential_text is not None:
                self._atomic_write(credential_path, credential_text, None)
            self._atomic_write(
                self.registry_path,
                _canonical_json(registry),
                registry_before,
            )
        except Exception:
            shutil.rmtree(strategy_dir, ignore_errors=True)
            raise
        return model

    @registry_write
    def start_research_batch(
        self,
        strategy_id: str,
        *,
        research_intent: dict[str, Any],
        research_state: ResearchState | str,
        actor: str,
        reason: str,
        credential_id: str,
        credential_content: dict[str, Any],
        credential_artifact_hashes: dict[str, str] | None = None,
    ) -> tuple[StrategyFamily, StrategyGovernanceCredential]:
        """Atomically start another governed research batch for an existing family."""

        actor = require_string(actor, "actor")
        reason = require_string(reason, "reason")
        credential_id = require_string(credential_id, "credential_id")
        if not isinstance(research_intent, dict) or not research_intent:
            raise ValidationError("research_intent must be a nonempty JSON object")
        try:
            next_state = (
                research_state
                if isinstance(research_state, ResearchState)
                else ResearchState(research_state)
            )
        except ValueError as exc:
            raise ValidationError("research_state has unsupported value") from exc
        if next_state is ResearchState.TERMINATED:
            raise ValidationError("a new research batch cannot start as TERMINATED")
        if not isinstance(credential_content, dict) or not credential_content:
            raise ValidationError("credential_content must be a nonempty object")

        current = self.get_family(strategy_id)
        credential_path = self._credential_path(strategy_id, credential_id)
        if credential_path.exists():
            existing = self.get_governance_credential(strategy_id, credential_id)
            first = existing.seals[0]
            if (
                first.actor == actor
                and first.content == credential_content
                and first.artifact_hashes == (credential_artifact_hashes or {})
            ):
                return current, existing
            raise RegistryError(f"governance credential already exists: {credential_id}")
        for family in self.list_families():
            if self._credential_path(family.strategy_id, credential_id).exists():
                raise RegistryError(
                    f"governance credential id already belongs to {family.strategy_id}: "
                    f"{credential_id}"
                )

        updated = replace(
            current,
            research_intent=dict(research_intent),
            research_state=next_state,
            updated_at=_now(),
        )
        seal = self._build_governance_seal(
            credential_id=credential_id,
            strategy_id=strategy_id,
            sequence=1,
            stage=GovernanceStage.RESEARCH_INITIATED,
            result=GovernanceResult.OPEN,
            actor=actor,
            previous_seal_hash=None,
            content=credential_content,
            artifact_hashes=credential_artifact_hashes or {},
        )
        event = self._event(
            "RESEARCH_BATCH_CREATED",
            strategy_id,
            None,
            None,
            Qualification.RESEARCH,
            actor,
            reason,
            [credential_id, f"FAMILY:{canonical_sha256(updated.to_dict())}"],
            None,
        )
        family_path = self._strategy_dir(strategy_id) / "family.json"
        lifecycle_path = self._strategy_dir(strategy_id) / "lifecycle.jsonl"
        family_before = family_path.read_bytes()
        lifecycle_before = lifecycle_path.read_bytes() if lifecycle_path.exists() else None
        lifecycle_text = lifecycle_before.decode("utf-8") if lifecycle_before else ""
        snapshots = [
            (family_path, family_before),
            (lifecycle_path, lifecycle_before),
            (credential_path, None),
        ]
        try:
            self._atomic_write(family_path, _canonical_json(updated.to_dict()), family_before)
            self._atomic_write(
                lifecycle_path,
                lifecycle_text
                + json.dumps(
                    event.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                lifecycle_before,
            )
            self._atomic_write(
                credential_path,
                json.dumps(
                    seal.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                None,
            )
        except Exception:
            self._restore_files(snapshots)
            raise
        return updated, StrategyGovernanceCredential.from_seals((seal,))

    @registry_write
    def update_family(
        self,
        strategy_id: str,
        *,
        research_intent: dict[str, Any] | None = None,
        research_state: ResearchState | str | None = None,
        actor: str,
        reason: str,
    ) -> StrategyFamily:
        actor = require_string(actor, "actor")
        reason = require_string(reason, "reason")
        current = self.get_family(strategy_id)
        next_intent = current.research_intent if research_intent is None else research_intent
        if not isinstance(next_intent, dict) or not next_intent:
            raise ValidationError("research_intent must be a nonempty JSON object")
        next_state = current.research_state
        if research_state is not None:
            try:
                next_state = (
                    research_state
                    if isinstance(research_state, ResearchState)
                    else ResearchState(research_state)
                )
            except ValueError as exc:
                raise ValidationError("research_state has unsupported value") from exc
        updated = replace(
            current,
            research_intent=dict(next_intent),
            research_state=next_state,
            updated_at=_now(),
        )
        if updated == current:
            return current
        event = self._event(
            "RESEARCH_INTENT_UPDATED",
            strategy_id,
            None,
            None,
            Qualification.RESEARCH,
            actor,
            reason,
            [f"FAMILY:{canonical_sha256(updated.to_dict())}"],
            None,
        )
        family_path = self._strategy_dir(strategy_id) / "family.json"
        lifecycle_path = self._strategy_dir(strategy_id) / "lifecycle.jsonl"
        family_before = family_path.read_bytes()
        lifecycle_before = lifecycle_path.read_bytes() if lifecycle_path.exists() else None
        try:
            self._atomic_write(family_path, _canonical_json(updated.to_dict()), family_before)
            self._append_jsonl(lifecycle_path, event.to_dict())
        except Exception:
            self._atomic_write(
                family_path,
                family_before.decode("utf-8"),
                family_path.read_bytes() if family_path.exists() else None,
            )
            if lifecycle_before is None:
                lifecycle_path.unlink(missing_ok=True)
            elif lifecycle_path.exists() and lifecycle_path.read_bytes() != lifecycle_before:
                self._atomic_write(
                    lifecycle_path,
                    lifecycle_before.decode("utf-8"),
                    lifecycle_path.read_bytes(),
                )
            raise
        return updated

    def lifecycle_events(self, strategy_id: str) -> list[LifecycleEvent]:
        path = self._strategy_dir(strategy_id) / "lifecycle.jsonl"
        if not path.exists():
            return []
        try:
            return [
                LifecycleEvent.from_dict(json.loads(line))
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RegistryError(f"invalid lifecycle history: {strategy_id}") from exc

    def current_qualification(self, strategy_id: str, version: str) -> Qualification:
        frozen = self.get_version(strategy_id, version)
        events = [
            event for event in self.lifecycle_events(strategy_id)
            if event.version == version and event.release_hash == frozen.release_hash
        ]
        if not events:
            return Qualification.RESEARCH
        return events[-1].to_state

    def evidence(self, strategy_id: str, version: str | None = None) -> list[PerformanceEvidence]:
        path = self._strategy_dir(strategy_id) / "evidence.jsonl"
        if not path.exists():
            return []
        try:
            values = [
                PerformanceEvidence.from_dict(json.loads(line))
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RegistryError(f"invalid evidence history: {strategy_id}") from exc
        return values if version is None else [item for item in values if item.version == version]

    @registry_write
    def record_evidence(
        self, evidence: PerformanceEvidence | dict[str, Any], *, source_file: Path | None = None
    ) -> PerformanceEvidence:
        model = (
            evidence
            if isinstance(evidence, PerformanceEvidence)
            else PerformanceEvidence.from_dict(evidence)
        )
        version = self.get_version(model.strategy_id, model.version)
        if not version.release_hash or model.release_hash != version.release_hash:
            raise RegistryError("evidence release_hash does not match the frozen version")
        existing = {item.evidence_id: item for item in self.evidence(model.strategy_id)}
        if model.evidence_id in existing:
            if existing[model.evidence_id] == model:
                return model
            raise RegistryError(f"evidence_id already exists: {model.evidence_id}")
        if source_file is not None:
            source = Path(source_file)
            document = json.loads(source.read_text(encoding="utf-8"))
            source_payload = document.get("source") if isinstance(document, dict) else None
            if not isinstance(source_payload, dict):
                raise RegistryError("source evidence bundle is missing its source object")
            if canonical_sha256(source_payload) != model.source_hash:
                raise RegistryError("source evidence hash mismatch")
            destination = (
                self._strategy_dir(model.strategy_id) / "evidence" / f"{model.evidence_id}.json"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and destination.read_bytes() != source.read_bytes():
                raise RegistryError(f"evidence artifact already exists: {model.evidence_id}")
            if not destination.exists():
                temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
                shutil.copyfile(source, temporary)
                temporary.replace(destination)
        self._append_jsonl(
            self._strategy_dir(model.strategy_id) / "evidence.jsonl", model.to_dict()
        )
        return model

    @registry_write
    def approve_paper_trading(self, approval: PaperTradingApproval) -> LifecycleEvent:
        """Grant paper eligibility to exact frozen content after explicit user approval."""
        if type(approval) is not PaperTradingApproval:
            raise TypeError("approve_paper_trading requires PaperTradingApproval")
        frozen = self.get_version(approval.strategy_id, approval.version)
        if frozen.release_hash != approval.expected_release_hash:
            raise RegistryError("paper approval release hash differs from frozen version")
        if (
            self.current_qualification(approval.strategy_id, approval.version)
            is not Qualification.RESEARCH
        ):
            raise InvalidTransitionError("paper approval requires RESEARCH qualification")
        return self._transition(
            approval.strategy_id, approval.version, Qualification.PAPER_READY,
            "PAPER_APPROVED", approval.actor, approval.reason, [],
        )

    @registry_write
    def promote_version(
        self,
        strategy_id: str,
        version: str,
        *,
        actor: str,
        reason: str,
        evidence_ids: list[str],
    ) -> LifecycleEvent:
        return self._transition(
            strategy_id,
            version,
            Qualification.LIVE_READY,
            "VERSION_PROMOTED",
            actor,
            reason,
            evidence_ids,
            required_phase=EvidencePhase.PAPER_FORWARD,
        )

    @registry_write
    def downgrade_version(
        self,
        strategy_id: str,
        version: str,
        *,
        actor: str,
        reason: str,
        evidence_ids: list[str],
    ) -> LifecycleEvent:
        if self.current_qualification(strategy_id, version) is not Qualification.LIVE_READY:
            raise InvalidTransitionError("downgrade requires LIVE_READY qualification")
        if not evidence_ids:
            raise EvidenceRequiredError("downgrade requires related evidence")
        return self._transition(
            strategy_id,
            version,
            Qualification.PAPER_READY,
            "VERSION_DOWNGRADED",
            actor,
            reason,
            evidence_ids,
        )

    @registry_write
    def retire_version(
        self, strategy_id: str, version: str, *, actor: str, reason: str
    ) -> LifecycleEvent:
        return self._transition(
            strategy_id,
            version,
            Qualification.RETIRED,
            "VERSION_RETIRED",
            actor,
            reason,
            [],
        )

    @registry_write
    def _transition(
        self,
        strategy_id: str,
        version: str,
        target: Qualification,
        event_type: str,
        actor: str,
        reason: str,
        evidence_ids: list[str],
        required_phase: EvidencePhase | None = None,
    ) -> LifecycleEvent:
        actor = require_string(actor, "actor")
        reason = require_string(reason, "reason")
        current = self.current_qualification(strategy_id, version)
        validate_transition(current, target)
        frozen = self.get_version(strategy_id, version)
        registered = {item.evidence_id: item for item in self.evidence(strategy_id, version)}
        if any(evidence_id not in registered for evidence_id in evidence_ids):
            raise RegistryError("lifecycle transition references unknown evidence")
        if any(registered[evidence_id].release_hash != frozen.release_hash for evidence_id in evidence_ids):
            raise RegistryError("lifecycle transition evidence differs from current content")
        if required_phase is not None and not any(
            registered[evidence_id].phase is required_phase for evidence_id in evidence_ids
        ):
            raise EvidenceRequiredError(f"transition requires {required_phase.value} evidence")
        event = self._event(
            event_type,
            strategy_id,
            version,
            current,
            target,
            actor,
            reason,
            evidence_ids,
            frozen.release_hash,
        )
        self._append_jsonl(self._strategy_dir(strategy_id) / "lifecycle.jsonl", event.to_dict())
        return event

    @staticmethod
    def _event(
        event_type: str,
        strategy_id: str,
        version: str,
        from_state: Qualification | None,
        to_state: Qualification,
        actor: str,
        reason: str,
        evidence_ids: list[str],
        release_hash: str | None,
    ) -> LifecycleEvent:
        return LifecycleEvent.from_dict(
            {
                "schema_version": 1,
                "event_id": f"EVT-{uuid.uuid4().hex}",
                "event_type": event_type,
                "strategy_id": strategy_id,
                "version": version,
                "from_state": None if from_state is None else from_state.value,
                "to_state": to_state.value,
                "occurred_at": _now(),
                "actor": actor,
                "reason": reason,
                "evidence_ids": evidence_ids,
                "release_hash": release_hash,
            }
        )

    def assert_deployable(
        self, strategy_id: str, version: str, environment: str
    ) -> StrategyVersion:
        qualification = self.current_qualification(strategy_id, version)
        if not qualification_is_deployable(qualification, environment):
            raise InvalidTransitionError(
                f"{strategy_id}-{version} is not deployable to {environment}: {qualification.value}"
            )
        release = self.get_version(strategy_id, version)
        return release

    def validate_all(self) -> dict[str, int]:
        strategies = self.list_families()
        version_count = 0
        evidence_count = 0
        event_count = 0
        credential_count = 0
        credential_ids: set[str] = set()
        names: set[str] = set()
        for strategy in strategies:
            normalized = _normalized_name(strategy.name)
            if normalized in names:
                raise RegistryError(f"duplicate active strategy name: {strategy.name}")
            names.add(normalized)
            versions = self._versions(strategy.strategy_id)
            version_count += len(versions)
            events = self.lifecycle_events(strategy.strategy_id)
            evidence = self.evidence(strategy.strategy_id)
            event_count += len(events)
            evidence_count += len(evidence)
            credential_dir = self._strategy_dir(strategy.strategy_id) / "credentials"
            for path in credential_dir.glob("*.jsonl") if credential_dir.exists() else ():
                credential = self.get_governance_credential(strategy.strategy_id, path.stem)
                if credential.credential_id in credential_ids:
                    raise RegistryError(
                        f"duplicate governance credential id: {credential.credential_id}"
                    )
                credential_ids.add(credential.credential_id)
                credential_count += 1
                if credential.stage is not GovernanceStage.RESEARCH_INITIATED:
                    raise RegistryError("historical freeze credentials are unsupported")
            for item in versions:
                self.current_qualification(item.strategy_id, item.version)
            for item in evidence:
                # Evidence retains its original content identity. Only new lifecycle
                # decisions require evidence for the current content hash.
                self.get_version(item.strategy_id, item.version)
        return {
            "strategies": len(strategies),
            "versions": version_count,
            "events": event_count,
            "evidence": evidence_count,
            "credentials": credential_count,
        }
