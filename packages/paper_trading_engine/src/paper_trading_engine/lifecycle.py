"""Account lifecycle and immutable decision execution facts."""

from enum import StrEnum

from .broker import TERMINAL_INTENT_STATUSES, UNRESOLVED_INTENT_STATUSES


class RunState(StrEnum):
    PAUSED = "PAUSED"
    RUNNING = "RUNNING"
    RETIRED = "RETIRED"


class DecisionState(StrEnum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    INCOMPLETE = "INCOMPLETE"


class IntentControlState(StrEnum):
    """Only local control outcomes; broker facts use order-report APIs."""
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    CANCELLING_ALL = "CANCELLING_ALL"


TERMINAL_DECISION_STATES = frozenset({
    DecisionState.COMPLETED, DecisionState.SUPERSEDED,
    DecisionState.CANCELLED, DecisionState.INCOMPLETE,
})
_TRANSITIONS = {
    DecisionState.PENDING: frozenset({
        DecisionState.EXECUTING, DecisionState.SUPERSEDED,
        DecisionState.CANCELLED, DecisionState.INCOMPLETE,
    }),
    DecisionState.EXECUTING: frozenset({DecisionState.COMPLETED, DecisionState.INCOMPLETE}),
}


def validate_transition(previous: DecisionState, target: DecisionState, *, reason: str,
                        related_decision_id: str | None = None) -> None:
    if type(previous) is not DecisionState or type(target) is not DecisionState:
        raise TypeError("decision transitions require DecisionState values")
    if not reason or not reason.strip():
        raise ValueError("decision transition requires a reason")
    if target not in _TRANSITIONS.get(previous, frozenset()):
        raise ValueError(f"illegal decision transition: {previous} -> {target}")
    if target == DecisionState.SUPERSEDED and not related_decision_id:
        raise ValueError("superseded decision requires its replacement")


def planned_orders(payload: dict) -> list[dict]:
    if payload.get("plan_legs"):
        return [leg["order"] for leg in payload["plan_legs"]]
    if payload.get("orders"):
        return list(payload["orders"])
    return [payload["order"]] if payload.get("order") else []


def execution_state(payload: dict, baseline: DecisionState, intents: list[dict],
                    orders: list[dict], fills: list[dict]) -> tuple[DecisionState, str]:
    """Project execution from original legs and their actual channel evidence."""
    if baseline in TERMINAL_DECISION_STATES:
        return baseline, "TERMINAL"
    planned = planned_orders(payload)
    if not planned:
        return DecisionState.COMPLETED, "NO_ORDER"
    # A timeout or lost acknowledgement is unresolved, even when other legs ended.
    if any(row["status"] in UNRESOLVED_INTENT_STATUSES for row in intents):
        return DecisionState.EXECUTING, "CHANNEL_RESULT_UNCERTAIN"
    matching = []
    for sequence, leg in enumerate(planned):
        candidates = [row for row in intents if row["order_sequence"] == sequence]
        if len(candidates) != 1:
            break
        intent = candidates[0]
        details = intent["payload"]
        if (intent["side"], intent["quantity"], details.get("order_type", "LIMIT")) != (
            leg["side"], leg["quantity"], leg["order_type"],
        ):
            break
        actual = [row for row in orders if row["intent_id"] == intent["intent_id"]]
        if len(actual) != 1:
            break
        order = actual[0]
        filled = sum(row["quantity"] for row in fills if row["order_id"] == order["channel_order_id"])
        if (intent["status"] != "FILLED_ALL" or filled != leg["quantity"]
                or order["cumulative_filled_quantity"] != filled):
            break
        matching.append(intent)
    if len(matching) == len(planned):
        return DecisionState.COMPLETED, "PLAN_FILLED"
    if any(row["status"] == "FILLED_ALL" and not any(
        order["intent_id"] == row["intent_id"]
        and sum(fill["quantity"] for fill in fills if fill["order_id"] == order["channel_order_id"]) == row["quantity"]
        for order in orders
    ) for row in intents):
        return DecisionState.EXECUTING, "AWAITING_FILL_RECONCILIATION"
    if intents and all(row["status"] in TERMINAL_INTENT_STATUSES for row in intents):
        return DecisionState.INCOMPLETE, "PLAN_ENDED_WITHOUT_COMPLETION"
    if baseline == DecisionState.EXECUTING or any(
        row.get("channel_order_id") or row["status"] not in {"PENDING_SUBMIT", "WAITING_DEPENDENCY"}
        for row in intents
    ):
        return DecisionState.EXECUTING, "CHANNEL_EXECUTION"
    return DecisionState.PENDING, "AWAITING_EXECUTION"
