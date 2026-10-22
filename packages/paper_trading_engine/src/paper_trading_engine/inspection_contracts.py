"""Finite, serializable inputs for isolated execution of the real PTE pipeline."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path, PurePosixPath
import re
import types
from typing import Union, get_args, get_origin, get_type_hints
from uuid import UUID

from dataflows import DataSpaceBinding, PreparedDataRef
from strategy_runtime import PlannedOrder, StrategyInputBinding
from strategy_runtime.inspection import InspectionEnvironment
from .lifecycle import AccountHealth


def _id(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError("invalid inspection business id")


def _case_id(value):
    if (type(value) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,99}", value)
            or value.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}):
        raise ValueError("invalid inspection case id or reserved directory name")


def _hash(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid inspection SHA256")


def _time(value):
    if type(value) is not datetime or value.utcoffset() is None:
        raise ValueError("inspection event requires timezone-aware datetime")


def _money(value):
    if type(value) is not Decimal or not value.is_finite() or value < 0:
        raise ValueError("inspection money requires a finite nonnegative Decimal")


def _quantity(value):
    if type(value) is not int or value < 0 or value % 100:
        raise ValueError("inspection quantity requires nonnegative 100-share lots")


def _tuple(value, kind):
    if type(value) is not tuple or any(not isinstance(x, kind) for x in value):
        raise TypeError(f"expected tuple of {kind}")


def encode(value):
    """Canonical JSON-ready records; never pickle runtime objects."""
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID, Path)):
        return str(value)
    if isinstance(value, StrategyInputBinding):
        return value.to_dict()
    if is_dataclass(value):
        return {f.name: encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (tuple, list)):
        return [encode(x) for x in value]
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    return value


def _decode(kind, value):
    origin, args = get_origin(kind), get_args(kind)
    if origin in (Union, types.UnionType):
        for member in args:
            try:
                return _decode(member, value)
            except (TypeError, ValueError, KeyError):
                pass
        raise ValueError("invalid tagged inspection value")
    if origin is tuple:
        if type(value) is not list:
            raise TypeError("serialized tuple requires array")
        return tuple(_decode(args[0], item) for item in value)
    if kind is type(None):
        if value is not None:
            raise ValueError("expected null")
        return None
    if kind in (str, int, bool, float):
        if type(value) is not kind:
            raise TypeError(f"expected {kind.__name__}")
        return value
    if kind is StrategyInputBinding:
        return kind.from_mapping(value)
    if kind in (date, datetime):
        return kind.fromisoformat(value)
    if kind in (Decimal, UUID, Path):
        return kind(value)
    if isinstance(kind, type) and issubclass(kind, StrEnum):
        return kind(value)
    if is_dataclass(kind):
        if type(value) is not dict or set(value) != {f.name for f in fields(kind)}:
            raise ValueError(f"invalid {kind.__name__} fields")
        hints = get_type_hints(kind)
        return kind(**{k: _decode(hints[k], v) for k, v in value.items()})
    raise TypeError(f"unsupported inspection type {kind}")


class Record:
    def to_dict(self):
        return encode(self)

    @classmethod
    def from_dict(cls, value):
        return _decode(cls, value)


class SubmissionOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class InspectionOrderStatus(StrEnum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class PteInspectionStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"
    INCOMPLETE = "INCOMPLETE"


class PteInspectionCapability(StrEnum):
    LOAD_PREPARE = "LOAD_PREPARE"
    ENTER_HOLD_EXIT = "ENTER_HOLD_EXIT"
    NO_OR_PARTIAL_FILL = "NO_OR_PARTIAL_FILL"
    IDEMPOTENCE = "IDEMPOTENCE"
    RECOVERY = "RECOVERY"
    RELEVANT_FAILURE = "RELEVANT_FAILURE"
    POSITION_CHANGE = "POSITION_CHANGE"


class CoverageRequirement(StrEnum):
    REQUIRED = "REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PteFault(StrEnum):
    PACKAGE_CONTENT_CHANGED = "PACKAGE_CONTENT_CHANGED"
    INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
    INPUT_AFTER_DECISION = "INPUT_AFTER_DECISION"


@dataclass(frozen=True, slots=True)
class PteEnvironmentRequirement(Record):
    platform_build_sha256: str
    pte_contract_version: str
    srt_contract_version: str

    def __post_init__(self):
        _hash(self.platform_build_sha256)
        if not self.pte_contract_version or not self.srt_contract_version:
            raise ValueError("environment contracts required")


@dataclass(frozen=True, slots=True)
class PteDecisionInput(Record):
    step_id: str
    binding: StrategyInputBinding
    decision_at: datetime
    trading_date: date
    submit_at: datetime
    repeat_decision: bool = False

    def __post_init__(self):
        _id(self.step_id)
        if ":" in self.step_id or self.step_id == "LOAD":
            raise ValueError("reserved decision step id")
        if type(self.binding) is not StrategyInputBinding or type(self.trading_date) is not date:
            raise TypeError("decision requires explicit input binding and trading date")
        _time(self.decision_at)
        _time(self.submit_at)
        if self.submit_at < self.decision_at or self.submit_at.date() != self.trading_date:
            raise ValueError("invalid decision/submission chronology")
        if self.binding.plan.tradable_window.start != self.trading_date or self.binding.plan.tradable_window.end != self.trading_date:
            raise ValueError("PTE decision binding requires exactly its trading session")
        if type(self.repeat_decision) is not bool:
            raise TypeError("repeat_decision must be bool")


@dataclass(frozen=True, slots=True)
class PteOrderKey(Record):
    decision_step_id: str
    order_ordinal: int

    def __post_init__(self):
        _id(self.decision_step_id)
        if type(self.order_ordinal) is not int or self.order_ordinal < 0:
            raise ValueError("order ordinal must be nonnegative")


@dataclass(frozen=True, slots=True)
class PteSubmissionResult(Record):
    event_id: str
    observed_at: datetime
    order: PteOrderKey
    outcome: SubmissionOutcome

    def __post_init__(self):
        _id(self.event_id)
        _time(self.observed_at)
        if type(self.order) is not PteOrderKey or type(self.outcome) is not SubmissionOutcome:
            raise TypeError("submission requires typed order and outcome")


@dataclass(frozen=True, slots=True)
class PteOrderUpdate(Record):
    event_id: str
    observed_at: datetime
    order: PteOrderKey
    status: InspectionOrderStatus
    cumulative_filled_quantity: int
    average_fill_price: Decimal
    cumulative_fee: Decimal

    def __post_init__(self):
        _id(self.event_id)
        _time(self.observed_at)
        _quantity(self.cumulative_filled_quantity)
        _money(self.average_fill_price)
        _money(self.cumulative_fee)
        if type(self.order) is not PteOrderKey or type(self.status) is not InspectionOrderStatus:
            raise TypeError("order update requires typed key/status")
        if (self.cumulative_filled_quantity == 0) != (self.average_fill_price == 0):
            raise ValueError("filled quantity and mean price disagree")
        if self.cumulative_filled_quantity == 0 and self.cumulative_fee:
            raise ValueError("unfilled order cannot charge fill fees")


@dataclass(frozen=True, slots=True)
class PteRepeatedOrderReport(Record):
    event_id: str
    observed_at: datetime
    source_event_id: str

    def __post_init__(self):
        _id(self.event_id)
        _id(self.source_event_id)
        _time(self.observed_at)


PteChannelEvent = PteSubmissionResult | PteOrderUpdate | PteRepeatedOrderReport


@dataclass(frozen=True, slots=True)
class PteCheckpointExpectation(Record):
    checkpoint_id: str
    after_event_id: str
    expected_orders: tuple[PlannedOrder, ...]
    position_quantity: int
    available_cash: Decimal
    frozen_cash: Decimal
    cycle_target_quantity: int | None
    health: AccountHealth
    cumulative_order_count: int

    def __post_init__(self):
        _id(self.checkpoint_id)
        _id(self.after_event_id)
        _tuple(self.expected_orders, PlannedOrder)
        _quantity(self.position_quantity)
        _money(self.available_cash)
        _money(self.frozen_cash)
        if self.cycle_target_quantity is not None:
            _quantity(self.cycle_target_quantity)
        if type(self.health) is not AccountHealth or type(self.cumulative_order_count) is not int or self.cumulative_order_count < 0:
            raise ValueError("invalid expected health or order count")


@dataclass(frozen=True, slots=True)
class PteInspectionScenario(Record):
    scenario_id: str
    initial_cash: Decimal
    decisions: tuple[PteDecisionInput, ...]
    channel_events: tuple[PteChannelEvent, ...]
    checkpoints: tuple[PteCheckpointExpectation, ...]
    restart_after: tuple[str, ...] = ()

    def __post_init__(self):
        _case_id(self.scenario_id)
        _money(self.initial_cash)
        _tuple(self.decisions, PteDecisionInput)
        _tuple(self.channel_events, (PteSubmissionResult, PteOrderUpdate, PteRepeatedOrderReport))
        _tuple(self.checkpoints, PteCheckpointExpectation)
        _tuple(self.restart_after, str)
        if not self.decisions or not self.checkpoints or self.initial_cash <= 0:
            raise ValueError("scenario requires cash, decisions and independent checkpoints")
        steps = {x.step_id: x for x in self.decisions}
        if len(steps) != len(self.decisions):
            raise ValueError("duplicate decision ids")
        events = {"LOAD"}
        for step in self.decisions:
            events.update((step.step_id + ":decision", step.step_id + ":submit"))
            if step.repeat_decision:
                events.add(step.step_id + ":repeat")
        updates = {}
        submissions = set()
        for event in self.channel_events:
            if event.event_id in events:
                raise ValueError("duplicate/reserved event id")
            events.add(event.event_id)
            if isinstance(event, PteRepeatedOrderReport):
                prior = updates.get(event.source_event_id)
                if prior is None or event.observed_at <= prior.observed_at:
                    raise ValueError("repeat requires earlier update")
                continue
            if event.order.decision_step_id not in steps:
                raise ValueError("channel event references missing decision")
            step = steps[event.order.decision_step_id]
            if isinstance(event, PteSubmissionResult):
                if event.observed_at != step.submit_at or event.order in submissions:
                    raise ValueError("submission must uniquely match its synchronous time")
                submissions.add(event.order)
            elif event.observed_at < step.submit_at:
                raise ValueError("order update precedes submission")
            else:
                updates[event.event_id] = event
        if len({x.checkpoint_id for x in self.checkpoints}) != len(self.checkpoints):
            raise ValueError("duplicate checkpoint ids")
        if any(x.after_event_id not in events for x in self.checkpoints) or not set(self.restart_after).issubset(events):
            raise ValueError("checkpoint/restart references missing event")
        if len(set(self.restart_after)) != len(self.restart_after):
            raise ValueError("duplicate restart boundaries")


@dataclass(frozen=True, slots=True)
class PteCoverageRequirement(Record):
    capability: PteInspectionCapability
    requirement: CoverageRequirement
    scenario_ids: tuple[str, ...]
    reason: str

    def __post_init__(self):
        if type(self.capability) is not PteInspectionCapability or type(self.requirement) is not CoverageRequirement:
            raise TypeError("typed coverage required")
        _tuple(self.scenario_ids, str)
        if not self.reason.strip() or len(set(self.scenario_ids)) != len(self.scenario_ids):
            raise ValueError("coverage requires reason and unique scenarios")
        if self.requirement is CoverageRequirement.REQUIRED and not self.scenario_ids:
            raise ValueError("required coverage needs scenarios")
        if self.requirement is CoverageRequirement.NOT_APPLICABLE and self.capability is not PteInspectionCapability.POSITION_CHANGE:
            raise ValueError("mandatory PTE coverage cannot be marked inapplicable")


@dataclass(frozen=True, slots=True)
class PteFailureCase(Record):
    case_id: str
    scenario_id: str
    fault: PteFault
    at_event_id: str

    def __post_init__(self):
        _case_id(self.case_id)
        _case_id(self.scenario_id)
        _id(self.at_event_id)
        if type(self.fault) is not PteFault:
            raise TypeError("typed failure required")
        if self.fault is PteFault.PACKAGE_CONTENT_CHANGED and self.at_event_id != "LOAD":
            raise ValueError("package failure must precede LOAD")
        if self.fault is not PteFault.PACKAGE_CONTENT_CHANGED and not self.at_event_id.endswith(":decision"):
            raise ValueError("input fault must target a decision")


@dataclass(frozen=True, slots=True)
class PteInspectionProtocol(Record):
    environment: PteEnvironmentRequirement
    scenarios: tuple[PteInspectionScenario, ...]
    coverage: tuple[PteCoverageRequirement, ...]
    failures: tuple[PteFailureCase, ...]

    def __post_init__(self):
        if type(self.environment) is not PteEnvironmentRequirement:
            raise TypeError("environment requirement required")
        _tuple(self.scenarios, PteInspectionScenario)
        _tuple(self.coverage, PteCoverageRequirement)
        _tuple(self.failures, PteFailureCase)
        ids = {x.scenario_id for x in self.scenarios}
        if not ids or len({value.casefold() for value in ids}) != len(self.scenarios):
            raise ValueError("unique scenarios required")
        if {x.capability for x in self.coverage} != set(PteInspectionCapability) or len(self.coverage) != len(PteInspectionCapability):
            raise ValueError("each coverage capability must be declared exactly once")
        if any(not set(x.scenario_ids).issubset(ids) for x in self.coverage) or any(x.scenario_id not in ids for x in self.failures):
            raise ValueError("unknown coverage/failure scenario")
        all_case_ids = [*ids, *(x.case_id for x in self.failures)]
        if len({x.casefold() for x in all_case_ids}) != len(all_case_ids):
            raise ValueError("duplicate case ids")
        for failure in self.failures:
            scenario = next(x for x in self.scenarios if x.scenario_id == failure.scenario_id)
            if (failure.fault is not PteFault.PACKAGE_CONTENT_CHANGED
                    and failure.at_event_id not in {x.step_id + ":decision" for x in scenario.decisions}):
                raise ValueError("failure references missing decision event")


@dataclass(frozen=True, slots=True)
class InputContentIdentity(Record):
    role: str
    source_sha256: str
    isolated_sha256: str

    def __post_init__(self):
        _id(self.role)
        _hash(self.source_sha256)
        _hash(self.isolated_sha256)
        if self.source_sha256 != self.isolated_sha256:
            raise ValueError("isolated input content differs")


@dataclass(frozen=True, slots=True)
class InspectionInputCopy(Record):
    source: PreparedDataRef
    isolated: PreparedDataRef
    content_mapping: tuple[InputContentIdentity, ...]

    def __post_init__(self):
        if type(self.source) is not PreparedDataRef or type(self.isolated) is not PreparedDataRef:
            raise TypeError("prepared references required")
        _tuple(self.content_mapping, InputContentIdentity)
        if not self.content_mapping or len({x.role for x in self.content_mapping}) != len(self.content_mapping):
            raise ValueError("unique input content roles required")


@dataclass(frozen=True, slots=True)
class PteReleaseInspectionRequest(Record):
    run_id: str
    isolated_repository: Path
    workspace: Path
    expected_release_id: str
    expected_release_sha256: str
    expected_package_sha256: str
    data_spaces: tuple[DataSpaceBinding, ...]
    input_copies: tuple[InspectionInputCopy, ...]
    protocol: PteInspectionProtocol

    def __post_init__(self):
        _id(self.run_id)
        if not re.fullmatch(r"S[0-9]{3}-v[1-9][0-9]*", self.expected_release_id):
            raise ValueError("invalid release id")
        _hash(self.expected_release_sha256)
        _hash(self.expected_package_sha256)
        if type(self.protocol) is not PteInspectionProtocol:
            raise TypeError("typed PTE protocol required")
        _tuple(self.data_spaces, DataSpaceBinding)
        _tuple(self.input_copies, InspectionInputCopy)
        if not isinstance(self.workspace, Path) or not isinstance(self.isolated_repository, Path):
            raise TypeError("inspection paths require Path")


@dataclass(frozen=True, slots=True)
class PteArtifact(Record):
    artifact_id: str
    path: str
    sha256: str
    schema: str
    schema_version: int

    def __post_init__(self):
        _id(self.artifact_id)
        _hash(self.sha256)
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or "\\" in self.path or ":" in self.path:
            raise ValueError("unsafe artifact path")
        if not self.schema or type(self.schema_version) is not int or self.schema_version <= 0:
            raise ValueError("artifact schema required")


@dataclass(frozen=True, slots=True)
class PteScenarioResult(Record):
    case_id: str
    status: PteInspectionStatus
    code: str
    summary: str
    artifact_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PteCoverageResult(Record):
    capability: PteInspectionCapability
    requirement: CoverageRequirement
    covered: bool
    scenario_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class PteInspectionOutcome(Record):
    run_id: str
    status: PteInspectionStatus
    environment: InspectionEnvironment
    scenarios: tuple[PteScenarioResult, ...]
    coverage: tuple[PteCoverageResult, ...]
    artifacts: tuple[PteArtifact, ...]

