from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, ClassVar

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


@dataclass(frozen=True, slots=True)
class PaperTradingApproval:
    """Explicit permission for the exact frozen content to enter paper trading."""

    strategy_id: str
    version: str
    expected_release_hash: str
    actor: str
    reason: str

    def __post_init__(self) -> None:
        require_strategy_id(self.strategy_id)
        require_version(self.version)
        if (
            require_sha256(self.expected_release_hash, "expected_release_hash")
            != self.expected_release_hash
        ):
            raise ValidationError("expected_release_hash must be canonical")
        require_string(self.actor, "actor")
        require_string(self.reason, "reason")


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
    source_candidate: str
    selection_data_cutoff: str
    forward_start: str
    strategy_payload: dict[str, Any]
    release_hash: str

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

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 5:
            raise ValidationError("strategy version schema_version must be 5")
        require_strategy_id(self.strategy_id)
        require_version(self.version)
        if self.release_id != f"{self.strategy_id}-{self.version}":
            raise ValidationError("release identity differs")
        if self.parent_version is not None:
            require_version(self.parent_version)
            if int(self.parent_version[1:]) >= int(self.version[1:]):
                raise ValidationError("parent version must precede release")
        for name in ("change_summary", "source_experiment", "source_candidate"):
            require_string(getattr(self, name), name)
        for name in ("selection_data_cutoff", "forward_start"):
            require_date(getattr(self, name), name)
        if self.forward_start <= self.selection_data_cutoff:
            raise ValidationError("forward window overlaps selection")
        if type(self.strategy_payload) is not dict or not self.strategy_payload:
            raise ValidationError("strategy payload must be nonempty")
        require_sha256(self.release_hash, "release_hash")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> StrategyVersion:
        if type(value.get("schema_version")) is not int or value["schema_version"] != 5:
            raise ValidationError("strategy version schema_version must be 5")
        require_exact_fields(value, cls.FIELDS)
        instance = cls(**value)
        if canonical_sha256(instance.release_payload()) != instance.release_hash:
            raise ValidationError("release_hash does not match the release payload")
        return instance

    def release_payload(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("release_hash")
        return value

    def to_dict(self) -> dict[str, Any]:
        return _enum_dict(self)


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
    calmar_ratio: float | None
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
            calmar_ratio=None
            if value["calmar_ratio"] is None
            else require_number(value["calmar_ratio"], "calmar_ratio"),
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
