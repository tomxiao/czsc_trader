"""Typed, append-only audit events for the PTE runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Any
from uuid import UUID, uuid4


class AuditContractError(ValueError):
    """An event cannot be admitted to the stable audit contract."""


class AuditCategory(StrEnum):
    STRATEGY = "STRATEGY"
    TRADING = "TRADING"
    SYSTEM = "SYSTEM"
    OTHER = "OTHER"


class AuditSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AuditOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"
    UNKNOWN = "UNKNOWN"


_STRATEGY_TYPES = {
    "MARKET_DATA_PUBLICATION_REQUESTED",
    "MARKET_DATA_PUBLISHED",
    "MARKET_DATA_PUBLICATION_FAILED",
    "MARKET_DATA_OBSERVED",
    "MARKET_DATA_OBSERVATION_FAILED",
    "MARKET_DATA_PREPARED",
    "DATA_PREPARATION_OBSERVATION_FAILED",
    "DECISION_GENERATED",
    "DECISION_GENERATION_FAILED",
    "ACCOUNT_DECISION_DRIVEN",
    "ACCOUNT_DECISION_DRIVE_FAILED",
    "SIGNAL_TRIGGERED",
    "SIGNAL_CLEARED",
    "DECISION_EXPIRED",
    "DECISION_SUPERSEDED",
    "CHANNEL_STRATEGY_BOUND",
    "ACCOUNT_STRATEGY_BOUND",
    "ACCOUNT_STRATEGY_NAME_UPDATED",
}
_TRADING_TYPES = {
    "EXECUTION_PLAN_LEG_READY",
    "EXECUTION_PLAN_BLOCKED",
    "ORDER_INTENT_CREATED",
    "ORDER_INTENT_RECOVERED",
    "ORDER_INTENT_SUPERSEDED",
    "ORDER_SUBMISSION_BLOCKED",
    "ORDER_SUBMITTED",
    "ORDER_SUBMISSION_FAILED",
    "ORDER_REJECTED",
    "CANCEL_REQUESTED",
    "CANCEL_SUCCEEDED",
    "CANCEL_FAILED",
    "ORDER_PARTIALLY_FILLED",
    "ORDER_FILLED",
    "ORDER_TERMINATED",
    "BROKER_FEE_RECONCILED",
    "CHANNEL_FEE_VARIANCE_RECONCILED",
    "ACCOUNT_LEDGER_REPAIRED",
    "ACCOUNT_RETIRED",
}
_SYSTEM_TYPES = {
    "SERVICE_STARTED",
    "SERVICE_STOPPED",
    "RESTART_REQUESTED",
    "ACCOUNT_PAUSED",
    "ACCOUNT_RESUMED",
    "EXTERNAL_CALL_SUCCEEDED",
    "EXTERNAL_CALL_FAILED",
    "DEPENDENCY_DEGRADED",
    "DEPENDENCY_RECOVERED",
    "SCHEDULER_OPERATION_FAILED",
    "SCHEDULER_OPERATION_RECOVERED",
    "SCHEDULER_CYCLE_FAILED",
    "VIRTUAL_ACCOUNT_FAILED",
    "ACCOUNT_CHANNEL_BOUND",
    "ACCOUNT_RECONCILIATION_FAILED",
    "ACCOUNT_RECONCILIATION_RECOVERED",
    "CHANNEL_RECONCILIATION_FAILED",
    "CHANNEL_RECONCILIATION_RECOVERED",
    "ACCOUNT_EXECUTION_MIGRATED",
    "ACCOUNT_CHART_GENERATION_FAILED",
    "ACCOUNT_CHART_RECOVERED",
    "CHANNEL_SCOPE_MIGRATED",
    "CHANNEL_RECONCILIATION_ACCOUNT_CREATED",
}
_OTHER_TYPES = {"LEGACY_EVENT", "UNCLASSIFIED_EVENT"}

EVENT_CATALOG = {
    **{name: AuditCategory.STRATEGY for name in _STRATEGY_TYPES},
    **{name: AuditCategory.TRADING for name in _TRADING_TYPES},
    **{name: AuditCategory.SYSTEM for name in _SYSTEM_TYPES},
    **{name: AuditCategory.OTHER for name in _OTHER_TYPES},
}

_DEFAULT_SEVERITY = {
    "MARKET_DATA_PUBLICATION_FAILED": AuditSeverity.ERROR,
    "MARKET_DATA_OBSERVATION_FAILED": AuditSeverity.ERROR,
    "DATA_PREPARATION_OBSERVATION_FAILED": AuditSeverity.ERROR,
    "DECISION_GENERATION_FAILED": AuditSeverity.ERROR,
    "ACCOUNT_DECISION_DRIVE_FAILED": AuditSeverity.ERROR,
    "ORDER_SUBMISSION_FAILED": AuditSeverity.ERROR,
    "ORDER_REJECTED": AuditSeverity.WARNING,
    "CANCEL_FAILED": AuditSeverity.ERROR,
    "EXTERNAL_CALL_FAILED": AuditSeverity.ERROR,
    "SCHEDULER_OPERATION_FAILED": AuditSeverity.ERROR,
    "SCHEDULER_CYCLE_FAILED": AuditSeverity.ERROR,
    "VIRTUAL_ACCOUNT_FAILED": AuditSeverity.ERROR,
    "DEPENDENCY_DEGRADED": AuditSeverity.WARNING,
    "ORDER_SUBMISSION_BLOCKED": AuditSeverity.WARNING,
    "EXECUTION_PLAN_BLOCKED": AuditSeverity.ERROR,
    "DECISION_EXPIRED": AuditSeverity.WARNING,
    "UNCLASSIFIED_EVENT": AuditSeverity.WARNING,
    "LEGACY_EVENT": AuditSeverity.WARNING,
    "ACCOUNT_RECONCILIATION_FAILED": AuditSeverity.ERROR,
    "CHANNEL_RECONCILIATION_FAILED": AuditSeverity.ERROR,
    "ACCOUNT_CHART_GENERATION_FAILED": AuditSeverity.ERROR,
}
_SENSITIVE_KEY = re.compile(r"(?:token|password|secret|credential)", re.IGNORECASE)


def redact_details(value: Any) -> Any:
    """Recursively redact values whose field names signal credentials."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else redact_details(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_details(item) for item in value]
    return value


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    occurred_at: str
    category: AuditCategory
    event_type: str
    severity: AuditSeverity
    outcome: AuditOutcome
    source: str
    correlation_id: str
    actor_type: str
    actor_id: str | None = None
    schema_version: str = "audit.v1"
    account_id: str | None = None
    strategy_id: str | None = None
    strategy_version: str | None = None
    release_hash: str | None = None
    symbol: str | None = None
    channel: str | None = None
    decision_id: str | None = None
    order_id: str | None = None
    details: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            UUID(self.event_id)
        except (ValueError, TypeError) as exc:
            raise AuditContractError("event_id must be a UUID") from exc
        if not self.source.strip() or not self.correlation_id.strip():
            raise AuditContractError("source and correlation_id are required")
        if self.actor_type not in {"ENGINE", "SCHEDULER", "OPERATOR", "EXTERNAL"}:
            raise AuditContractError("actor_type is invalid")
        if self.schema_version != "audit.v1":
            raise AuditContractError("unsupported audit schema version")
        if self.category is AuditCategory.OTHER and not self.details.get("classification_reason"):
            raise AuditContractError("OTHER events require details.classification_reason")

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["category"] = self.category.value
        value["severity"] = self.severity.value
        value["outcome"] = self.outcome.value
        return value


class AuditRecorder:
    def __init__(self, store) -> None:
        self.store = store

    def build(
        self,
        event_type: str,
        *,
        source: str,
        outcome: AuditOutcome | str = AuditOutcome.SUCCESS,
        severity: AuditSeverity | str | None = None,
        correlation_id: str | None = None,
        actor_type: str = "ENGINE",
        actor_id: str | None = None,
        account_id: str | None = None,
        strategy_id: str | None = None,
        strategy_version: str | None = None,
        release_hash: str | None = None,
        symbol: str | None = None,
        channel: str | None = None,
        decision_id: str | None = None,
        order_id: str | None = None,
        details: dict[str, object] | None = None,
    ) -> AuditEvent:
        category = EVENT_CATALOG.get(event_type)
        if category is None:
            raise AuditContractError(f"event type is not in catalog: {event_type}")
        event_id = str(uuid4())
        clean_details = redact_details(details or {})
        event = AuditEvent(
            event_id=event_id,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            category=category,
            event_type=event_type,
            severity=AuditSeverity(severity or _DEFAULT_SEVERITY.get(event_type, AuditSeverity.INFO)),
            outcome=AuditOutcome(outcome),
            source=source,
            correlation_id=correlation_id or decision_id or order_id or event_id,
            actor_type=actor_type,
            actor_id=actor_id,
            account_id=account_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            release_hash=release_hash,
            symbol=symbol.upper() if symbol else None,
            channel=channel,
            decision_id=decision_id,
            order_id=order_id,
            details=clean_details,
        )
        return event

    def record(self, event_type: str, **kwargs) -> dict[str, object]:
        return self.store.append_audit_event(self.build(event_type, **kwargs))
