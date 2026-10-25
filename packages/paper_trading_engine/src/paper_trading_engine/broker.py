"""Broker-neutral values used by the Futu execution adapter."""

from dataclasses import dataclass
from enum import StrEnum


TERMINAL_ORDER_STATUSES = {
    "SUBMIT_FAILED", "FILLED_ALL", "CANCELLED_PART", "CANCELLED_ALL", "FAILED",
    "DISABLED", "DELETED", "FILL_CANCELLED",
}

# Futu explicitly defines TIMEOUT as an unknown result.  It must remain visible to
# reconciliation and must never be treated as either success or a safe terminal state.
UNRESOLVED_INTENT_STATUSES = {
    "SUBMITTING", "SUBMISSION_UNCERTAIN", "TIMEOUT",
}

ACTIVE_ORDER_STATUSES = {
    "UNSUBMITTED", "WAITING_SUBMIT", "SUBMITTING", "SUBMITTED", "FILLED_PART",
    "CANCELLING_PART", "CANCELLING_ALL", "TIMEOUT",
}

KNOWN_ORDER_STATUSES = TERMINAL_ORDER_STATUSES | ACTIVE_ORDER_STATUSES

# These terminal outcomes leave the strategy decision incompletely executed.  They
# require acknowledgement unless a persisted, verified normal-unfilled disposition exists.
ATTENTION_REQUIRED_INTENT_STATUSES = TERMINAL_ORDER_STATUSES - {"FILLED_ALL"} | {
    "REJECTED", "SUBMISSION_FAILED", "EXPIRED",
}

TERMINAL_INTENT_STATUSES = TERMINAL_ORDER_STATUSES | {
    "REJECTED", "SUBMISSION_FAILED", "EXPIRED", "SUPERSEDED", "SKIPPED_DEPENDENCY",
}


class IntentTerminationReason(StrEnum):
    """Local interpretation of confirmed execution facts; never a broker status."""

    NORMAL_UNFILLED = "NORMAL_UNFILLED"
    DEPENDENCY_NOT_TRIGGERED = "DEPENDENCY_NOT_TRIGGERED"


class PaperTradingSafetyError(RuntimeError):
    pass


class BrokerOrderRejectedError(RuntimeError):
    """The broker definitively rejected an order before accepting it."""


class BrokerSubmissionUncertainError(RuntimeError):
    """The submit call may have reached the broker but no result was confirmed."""


@dataclass(frozen=True)
class BrokerAccount:
    environment: str
    market: str
    cash: float
    total_assets: float
    frozen_cash: float
    market_value: float = 0.0


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    quantity: int


@dataclass(frozen=True)
class BrokerOrder:
    channel_order_id: str
    symbol: str
    side: str
    quantity: int
    limit_price: float
    status: str
    cumulative_filled_quantity: int
    average_fill_price: float
    remark: str
    last_error: str = ""
    created_at: str = ""
    updated_at: str = ""
    order_type: str = "LIMIT"


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    decision_id: str
    symbol: str
    side: str
    quantity: int
    limit_price: float
    order_type: str = "LIMIT"
    time_in_force: str = "DAY"
    account_id: str | None = None


@dataclass(frozen=True)
class BrokerSnapshot:
    account: BrokerAccount
    positions: tuple[BrokerPosition, ...]
    orders: tuple[BrokerOrder, ...]
