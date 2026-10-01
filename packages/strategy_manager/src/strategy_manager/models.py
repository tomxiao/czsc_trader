from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, ClassVar, TYPE_CHECKING

if TYPE_CHECKING:
    from .freeze_contracts import CandidateOrigin, FreezeGovernance

from .errors import ValidationError
from .validation import (
    require_date,
    require_exact_fields,
    require_identifier,
    require_number,
    require_schema_version,
    require_sha256,
    require_strategy_id,
    require_string,
    require_timestamp,
    require_version,
)


class Qualification(str, Enum):
    RESEARCH = "RESEARCH"
    PAPER_READY = "PAPER_READY"
    LIVE_READY = "LIVE_READY"
    RETIRED = "RETIRED"


class EvidencePhase(str, Enum):
    RESEARCH_BACKTEST = "RESEARCH_BACKTEST"
    PAPER_FORWARD = "PAPER_FORWARD"
    LIVE = "LIVE"


class ResearchState(str, Enum):
    RESEARCHING = "RESEARCHING"
    PAUSED = "PAUSED"
    TERMINATED = "TERMINATED"


class GovernanceStage(str, Enum):
    """Append-only stages carried by one strategy governance credential."""

    RESEARCH_INITIATED = "RESEARCH_INITIATED"
    CANDIDATE_SUBMITTED = "CANDIDATE_SUBMITTED"
    TDR_ADJUDICATED = "TDR_ADJUDICATED"
    FREEZE_APPROVED = "FREEZE_APPROVED"
    VERSION_FROZEN = "VERSION_FROZEN"
    INVALIDATED = "INVALIDATED"


class GovernanceResult(str, Enum):
    OPEN = "OPEN"
    ELIGIBLE = "ELIGIBLE"
    INCOMPLETE = "INCOMPLETE"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    FROZEN = "FROZEN"
    INVALIDATED = "INVALIDATED"


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


_GOVERNANCE_STAGE_RESULTS: dict[GovernanceStage, frozenset[GovernanceResult]] = {
    GovernanceStage.RESEARCH_INITIATED: frozenset({GovernanceResult.OPEN}),
    GovernanceStage.CANDIDATE_SUBMITTED: frozenset({GovernanceResult.OPEN}),
    GovernanceStage.TDR_ADJUDICATED: frozenset(
        {
            GovernanceResult.ELIGIBLE,
            GovernanceResult.INCOMPLETE,
            GovernanceResult.REJECTED,
        }
    ),
    GovernanceStage.FREEZE_APPROVED: frozenset({GovernanceResult.APPROVED}),
    GovernanceStage.VERSION_FROZEN: frozenset({GovernanceResult.FROZEN}),
    GovernanceStage.INVALIDATED: frozenset({GovernanceResult.INVALIDATED}),
}


def _validate_governance_transition(
    previous: StrategyGovernanceSeal | None,
    current: StrategyGovernanceSeal,
) -> None:
    if current.result not in _GOVERNANCE_STAGE_RESULTS[current.stage]:
        raise ValidationError(
            f"governance stage {current.stage.value} does not allow result {current.result.value}"
        )
    if previous is None:
        if current.stage is not GovernanceStage.RESEARCH_INITIATED:
            raise ValidationError("governance credential must start with RESEARCH_INITIATED")
        return
    if current.stage is GovernanceStage.INVALIDATED:
        if previous.stage in {GovernanceStage.VERSION_FROZEN, GovernanceStage.INVALIDATED}:
            raise ValidationError("terminal governance credential cannot be invalidated")
        return
    if (
        current.stage is GovernanceStage.CANDIDATE_SUBMITTED
        and previous.stage is GovernanceStage.TDR_ADJUDICATED
        and previous.result in {GovernanceResult.INCOMPLETE, GovernanceResult.REJECTED}
    ):
        return
    allowed: dict[GovernanceStage, GovernanceStage] = {
        GovernanceStage.RESEARCH_INITIATED: GovernanceStage.CANDIDATE_SUBMITTED,
        GovernanceStage.CANDIDATE_SUBMITTED: GovernanceStage.TDR_ADJUDICATED,
        GovernanceStage.TDR_ADJUDICATED: GovernanceStage.FREEZE_APPROVED,
        GovernanceStage.FREEZE_APPROVED: GovernanceStage.VERSION_FROZEN,
    }
    expected = allowed.get(previous.stage)
    if expected is not current.stage:
        raise ValidationError(
            f"invalid governance transition: {previous.stage.value} -> {current.stage.value}"
        )
    if (
        previous.stage is GovernanceStage.TDR_ADJUDICATED
        and previous.result is not GovernanceResult.ELIGIBLE
    ):
        raise ValidationError("only an ELIGIBLE adjudication can receive freeze approval")


@dataclass(frozen=True)
class StrategyGovernanceSeal:
    """One immutable seal in a strategy governance credential hash chain."""

    schema_version: int
    credential_id: str
    strategy_id: str
    sequence: int
    stage: GovernanceStage
    result: GovernanceResult
    actor: str
    occurred_at: str
    previous_seal_hash: str | None
    content: dict[str, Any]
    content_hash: str
    artifact_hashes: dict[str, str]
    seal_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "credential_id",
        "strategy_id",
        "sequence",
        "stage",
        "result",
        "actor",
        "occurred_at",
        "previous_seal_hash",
        "content",
        "content_hash",
        "artifact_hashes",
        "seal_hash",
    )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> StrategyGovernanceSeal:
        require_exact_fields(value, cls.FIELDS)
        if value["schema_version"] != 1 or isinstance(value["schema_version"], bool):
            raise ValidationError("governance seal schema_version must be 1")
        sequence = value["sequence"]
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise ValidationError("governance seal sequence must be a positive integer")
        content = value["content"]
        if not isinstance(content, dict) or not content:
            raise ValidationError("governance seal content must be a nonempty object")
        content_hash = require_sha256(value["content_hash"], "content_hash")
        if content_hash != canonical_sha256(content):
            raise ValidationError("governance seal content_hash does not match content")
        raw_artifacts = value["artifact_hashes"]
        if not isinstance(raw_artifacts, dict):
            raise ValidationError("governance seal artifact_hashes must be an object")
        artifacts = {
            require_string(name, "artifact name"): require_sha256(digest, f"artifact {name}")
            for name, digest in raw_artifacts.items()
        }
        previous = value["previous_seal_hash"]
        if previous is not None:
            previous = require_sha256(previous, "previous_seal_hash")
        instance = cls(
            schema_version=1,
            credential_id=require_identifier(value["credential_id"], "credential_id"),
            strategy_id=require_strategy_id(value["strategy_id"]),
            sequence=sequence,
            stage=_enum(GovernanceStage, value["stage"], "stage"),
            result=_enum(GovernanceResult, value["result"], "result"),
            actor=require_string(value["actor"], "actor"),
            occurred_at=require_timestamp(value["occurred_at"], "occurred_at"),
            previous_seal_hash=previous,
            content=dict(content),
            content_hash=content_hash,
            artifact_hashes=artifacts,
            seal_hash=require_sha256(value["seal_hash"], "seal_hash"),
        )
        if instance.seal_hash != canonical_sha256(instance.seal_payload()):
            raise ValidationError("governance seal_hash does not match seal payload")
        return instance

    def seal_payload(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("seal_hash")
        return value

    def to_dict(self) -> dict[str, Any]:
        return _enum_dict(self)


@dataclass(frozen=True)
class StrategyGovernanceCredential:
    """A verified, append-only sequence of governance seals."""

    credential_id: str
    strategy_id: str
    seals: tuple[StrategyGovernanceSeal, ...]

    @classmethod
    def from_seals(cls, seals: tuple[StrategyGovernanceSeal, ...]) -> StrategyGovernanceCredential:
        if not seals:
            raise ValidationError("governance credential must contain at least one seal")
        first = seals[0]
        previous: StrategyGovernanceSeal | None = None
        for expected_sequence, seal in enumerate(seals, start=1):
            if seal.credential_id != first.credential_id or seal.strategy_id != first.strategy_id:
                raise ValidationError("governance credential seal identity differs")
            if seal.sequence != expected_sequence:
                raise ValidationError("governance credential seal sequence is not contiguous")
            expected_previous = None if previous is None else previous.seal_hash
            if seal.previous_seal_hash != expected_previous:
                raise ValidationError("governance credential hash chain is broken")
            _validate_governance_transition(previous, seal)
            previous = seal
        return cls(first.credential_id, first.strategy_id, seals)

    @property
    def credential_hash(self) -> str:
        return self.seals[-1].seal_hash

    @property
    def stage(self) -> GovernanceStage:
        return self.seals[-1].stage

    @property
    def result(self) -> GovernanceResult:
        return self.seals[-1].result


def _enum_dict(instance: object) -> dict[str, Any]:
    return {
        key: value.value if isinstance(value, Enum) else value
        for key, value in asdict(instance).items()
    }


def _enum(enum_type: type[Enum], value: Any, field: str) -> Enum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} has unsupported value: {value!r}") from exc


@dataclass(frozen=True)
class StrategyFamily:
    schema_version: int
    strategy_id: str
    name: str
    scope: Any
    research_intent: dict[str, Any]
    research_state: ResearchState
    created_at: str
    created_by: str
    updated_at: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "strategy_id",
        "name",
        "scope",
        "research_intent",
        "research_state",
        "created_at",
        "created_by",
        "updated_at",
    )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> StrategyFamily:
        require_exact_fields(value, cls.FIELDS)
        if value["schema_version"] != 2 or isinstance(value["schema_version"], bool):
            raise ValidationError("strategy family schema_version must be 2")
        scope = value["scope"]
        if not isinstance(scope, (str, list, dict)) or not scope:
            raise ValidationError("scope must be a nonempty JSON string, list, or object")
        intent = value["research_intent"]
        if not isinstance(intent, dict) or not intent:
            raise ValidationError("research_intent must be a nonempty JSON object")
        return cls(
            schema_version=2,
            strategy_id=require_strategy_id(value["strategy_id"]),
            name=require_string(value["name"], "name"),
            scope=scope,
            research_intent=dict(intent),
            research_state=_enum(ResearchState, value["research_state"], "research_state"),
            created_at=require_timestamp(value["created_at"], "created_at"),
            created_by=require_string(value["created_by"], "created_by"),
            updated_at=require_timestamp(value["updated_at"], "updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return _enum_dict(self)


@dataclass(frozen=True)
class StrategyVersion:
    schema_version: int
    strategy_id: str
    version: str
    release_id: str
    parent_version: str | None
    change_summary: str
    source_experiment: str
    source_candidate: int | str | None
    selection_data_cutoff: str
    forward_start: str
    strategy_payload: dict[str, Any]
    release_hash: str | None
    governance: dict[str, str] | FreezeGovernance | None = None
    governance_hash: str | None = None
    origin: CandidateOrigin | None = None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "strategy_id",
        "version",
        "release_id",
        "parent_version",
        "change_summary",
        "source_experiment",
        "source_candidate",
        "selection_data_cutoff",
        "forward_start",
        "strategy_payload",
        "release_hash",
    )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> StrategyVersion:
        schema_version = value.get("schema_version")
        if schema_version == 4 and type(schema_version) is int:
            from .freeze_store import version_from_dict
            return version_from_dict(value)
        optional = ("governance", "governance_hash") if schema_version in {2, 3} else ()
        require_exact_fields(value, cls.FIELDS, optional)
        if schema_version not in {1, 2, 3} or isinstance(schema_version, bool):
            raise ValidationError("strategy version schema_version must be 1, 2 or 3")
        strategy_id = require_strategy_id(value["strategy_id"])
        version = require_version(value["version"])
        release_id = require_string(value["release_id"], "release_id")
        if release_id != f"{strategy_id}-{version}":
            raise ValidationError("release_id must equal strategy_id-version")
        parent = value["parent_version"]
        if parent is not None:
            parent = require_version(parent)
        payload = value["strategy_payload"]
        if not isinstance(payload, dict) or not payload:
            raise ValidationError("strategy_payload must be a nonempty JSON object")
        governance = value.get("governance")
        governance_hash = value.get("governance_hash")
        if schema_version in {2, 3}:
            if not isinstance(governance, dict):
                raise ValidationError(
                    f"schema v{schema_version} strategy version requires governance"
                )
            required_governance = (
                {
                    "review_id",
                    "candidate_snapshot_hash",
                    "evaluation_mandate_hash",
                    "adjudication_report_hash",
                    "human_decision_hash",
                    "runtime_acceptance_hash",
                }
                if schema_version == 2
                else {
                    "credential_id",
                    "candidate_submission_seal_hash",
                    "adjudication_seal_hash",
                    "approval_seal_hash",
                    "candidate_snapshot_hash",
                    "evaluation_mandate_hash",
                    "adjudication_report_hash",
                }
            )
            if set(governance) != required_governance:
                raise ValidationError("strategy version governance fields are incomplete")
            identity_field = "review_id" if schema_version == 2 else "credential_id"
            governance = {
                identity_field: require_identifier(governance[identity_field], identity_field),
                **{
                    name: require_sha256(governance[name], name)
                    for name in required_governance - {identity_field}
                },
            }
            governance_hash = require_sha256(governance_hash, "governance_hash")
            if governance_hash != canonical_sha256(governance):
                raise ValidationError("governance_hash does not match governance")
        elif governance is not None or governance_hash is not None:
            raise ValidationError("schema v1 strategy version must not contain governance")
        instance = cls(
            schema_version=int(schema_version),
            strategy_id=strategy_id,
            version=version,
            release_id=release_id,
            parent_version=parent,
            change_summary=require_string(value["change_summary"], "change_summary"),
            source_experiment=require_string(value["source_experiment"], "source_experiment"),
            source_candidate=value["source_candidate"],
            selection_data_cutoff=require_date(
                value["selection_data_cutoff"], "selection_data_cutoff"
            ),
            forward_start=require_date(value["forward_start"], "forward_start"),
            strategy_payload=payload,
            release_hash=require_sha256(value["release_hash"], "release_hash", allow_none=True),
            governance=governance,
            governance_hash=governance_hash,
        )
        if instance.release_hash and instance.release_hash != canonical_sha256(
            instance.release_payload()
        ):
            raise ValidationError("release_hash does not match the release payload")
        return instance

    def release_payload(self) -> dict[str, Any]:
        if self.schema_version in {2, 3}:
            return {
                "schema_version": self.schema_version,
                "strategy_id": self.strategy_id,
                "version": self.version,
                "release_id": self.release_id,
                "strategy_payload": self.strategy_payload,
            }
        value = self.to_dict()
        value.pop("release_hash")
        return value

    def to_dict(self) -> dict[str, Any]:
        value = _enum_dict(self)
        if self.schema_version == 4:
            from .freeze_contracts import CandidateOrigin, FreezeGovernance
            if not isinstance(self.origin, CandidateOrigin) or not isinstance(self.governance, FreezeGovernance):
                raise ValidationError("schema 4 requires typed origin and governance")
            value["origin"] = self.origin.to_dict()
            value["governance"] = self.governance.to_dict()
        else:
            value.pop("origin")
        if self.schema_version == 1:
            value.pop("governance")
            value.pop("governance_hash")
        return value


@dataclass(frozen=True)
class LifecycleEvent:
    schema_version: int
    event_id: str
    event_type: str
    strategy_id: str
    version: str | None
    from_state: Qualification | None
    to_state: Qualification
    occurred_at: str
    actor: str
    reason: str
    evidence_ids: list[str]
    release_hash: str | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "event_id",
        "event_type",
        "strategy_id",
        "version",
        "from_state",
        "to_state",
        "occurred_at",
        "actor",
        "reason",
        "evidence_ids",
        "release_hash",
    )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> LifecycleEvent:
        require_exact_fields(value, cls.FIELDS)
        version = value["version"]
        if version is not None:
            version = require_version(version)
        from_state = value["from_state"]
        evidence_ids = value["evidence_ids"]
        if not isinstance(evidence_ids, list) or any(
            not isinstance(item, str) or not item for item in evidence_ids
        ):
            raise ValidationError("evidence_ids must be a list of nonblank strings")
        return cls(
            schema_version=require_schema_version(value["schema_version"]),
            event_id=require_identifier(value["event_id"], "event_id"),
            event_type=require_identifier(value["event_type"], "event_type"),
            strategy_id=require_strategy_id(value["strategy_id"]),
            version=version,
            from_state=None
            if from_state is None
            else _enum(Qualification, from_state, "from_state"),
            to_state=_enum(Qualification, value["to_state"], "to_state"),
            occurred_at=require_timestamp(value["occurred_at"], "occurred_at"),
            actor=require_string(value["actor"], "actor"),
            reason=require_string(value["reason"], "reason"),
            evidence_ids=list(evidence_ids),
            release_hash=require_sha256(value["release_hash"], "release_hash", allow_none=True),
        )

    def to_dict(self) -> dict[str, Any]:
        return _enum_dict(self)


@dataclass(frozen=True)
class PerformanceEvidence:
    schema_version: int
    evidence_id: str
    strategy_id: str
    version: str
    release_hash: str
    phase: EvidencePhase
    period_start: str
    period_end: str
    data_identity: dict[str, Any]
    initial_capital: float
    fee_rate: float
    maximum_drawdown: float
    calmar_ratio: float
    win_loss_ratio: float | None
    win_loss_ratio_status: str
    total_return: float
    sharpe_ratio: float | None
    closed_trades: int
    source_path: str
    source_hash: str
    recorded_at: str
    recorded_by: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "evidence_id",
        "strategy_id",
        "version",
        "release_hash",
        "phase",
        "period_start",
        "period_end",
        "data_identity",
        "initial_capital",
        "fee_rate",
        "maximum_drawdown",
        "calmar_ratio",
        "win_loss_ratio",
        "win_loss_ratio_status",
        "total_return",
        "sharpe_ratio",
        "closed_trades",
        "source_path",
        "source_hash",
        "recorded_at",
        "recorded_by",
    )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PerformanceEvidence:
        require_exact_fields(value, cls.FIELDS)
        data_identity = value["data_identity"]
        if not isinstance(data_identity, dict) or not data_identity:
            raise ValidationError("data_identity must be a nonempty JSON object")
        closed_trades = value["closed_trades"]
        if (
            isinstance(closed_trades, bool)
            or not isinstance(closed_trades, int)
            or closed_trades < 0
        ):
            raise ValidationError("closed_trades must be a nonnegative integer")
        win_loss_ratio = value["win_loss_ratio"]
        sharpe_ratio = value["sharpe_ratio"]
        instance = cls(
            schema_version=require_schema_version(value["schema_version"]),
            evidence_id=require_identifier(value["evidence_id"], "evidence_id"),
            strategy_id=require_strategy_id(value["strategy_id"]),
            version=require_version(value["version"]),
            release_hash=require_sha256(value["release_hash"], "release_hash"),
            phase=_enum(EvidencePhase, value["phase"], "phase"),
            period_start=require_date(value["period_start"], "period_start"),
            period_end=require_date(value["period_end"], "period_end"),
            data_identity=data_identity,
            initial_capital=require_number(value["initial_capital"], "initial_capital", minimum=0),
            fee_rate=require_number(value["fee_rate"], "fee_rate", minimum=0),
            maximum_drawdown=require_number(value["maximum_drawdown"], "maximum_drawdown"),
            calmar_ratio=require_number(value["calmar_ratio"], "calmar_ratio"),
            win_loss_ratio=None
            if win_loss_ratio is None
            else require_number(win_loss_ratio, "win_loss_ratio", minimum=0),
            win_loss_ratio_status=require_identifier(
                value["win_loss_ratio_status"], "win_loss_ratio_status"
            ),
            total_return=require_number(value["total_return"], "total_return"),
            sharpe_ratio=None
            if sharpe_ratio is None
            else require_number(sharpe_ratio, "sharpe_ratio"),
            closed_trades=closed_trades,
            source_path=require_string(value["source_path"], "source_path"),
            source_hash=require_sha256(value["source_hash"], "source_hash"),
            recorded_at=require_timestamp(value["recorded_at"], "recorded_at"),
            recorded_by=require_string(value["recorded_by"], "recorded_by"),
        )
        if instance.period_end < instance.period_start:
            raise ValidationError("period_end must not precede period_start")
        return instance

    def to_dict(self) -> dict[str, Any]:
        return _enum_dict(self)
