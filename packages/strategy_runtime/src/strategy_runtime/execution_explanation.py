"""Immutable inputs for a frozen strategy's execution explanation."""

from dataclasses import dataclass
from datetime import date, datetime
import math


@dataclass(frozen=True, slots=True)
class ExecutionExplanation:
    summary: str
    detail: str

    def __post_init__(self):
        for text, limit in ((self.summary, 240), (self.detail, 1200)):
            if type(text) is not str or not text.strip() or len(text) > limit:
                raise ValueError("invalid strategy execution explanation text")


@dataclass(frozen=True, slots=True)
class PlannedOrderFact:
    side: str
    quantity: int

    def __post_init__(self):
        if self.side not in ("BUY", "SELL") or type(self.quantity) is not int or self.quantity <= 0:
            raise ValueError("invalid planned order fact")


@dataclass(frozen=True, slots=True)
class ExecutionIntentFact:
    intent_id: str
    status: str
    channel_order_id: str | None
    channel_status: str | None = None
    submitted_at: str | None = None

    def __post_init__(self):
        if not self.intent_id or not self.status:
            raise ValueError('execution intent requires identity and status')
        if self.channel_status is not None and not self.channel_order_id:
            raise ValueError('channel status requires a channel order')


@dataclass(frozen=True, slots=True)
class ExecutionFillFact:
    fill_id: str
    side: str
    quantity: int
    occurred_at: str

    def __post_init__(self):
        PlannedOrderFact(self.side, self.quantity)
        if not self.fill_id:
            raise ValueError("execution fill requires an identity")
        if len(self.occurred_at) == 10:
            date.fromisoformat(self.occurred_at)
        elif datetime.fromisoformat(self.occurred_at).utcoffset() is None:
            raise ValueError("execution fill timestamp requires its timezone")


@dataclass(frozen=True, slots=True)
class PreviousPlanFact:
    decision_id: str
    valid_session: str
    status: str
    reason: str
    filled_quantity: int
    intents: tuple[ExecutionIntentFact, ...]


@dataclass(frozen=True, slots=True)
class ExecutionPlanContext:
    decision_id: str
    signal_date: str
    valid_session: str
    generated_at: str
    judgment: str
    target: float
    position_at_decision: int
    orders: tuple[PlannedOrderFact, ...]
    trigger: str | None
    planning_status: str
    constraints: tuple[str, ...]
    desired_quantity: int
    planned_quantity: int
    previous: PreviousPlanFact | None

    def __post_init__(self):
        if (not self.decision_id or not self.judgment
                or datetime.fromisoformat(self.generated_at).utcoffset() is None):
            raise ValueError('execution plan requires a saved decision and aware time')
        date.fromisoformat(self.signal_date)
        date.fromisoformat(self.valid_session)
        if type(self.target) not in (float, int) or not math.isfinite(self.target) or not 0 <= self.target <= 1:
            raise ValueError('execution plan requires a target percentage')
        for quantity in (self.position_at_decision, self.desired_quantity, self.planned_quantity):
            if type(quantity) is not int or quantity < 0:
                raise ValueError('plan quantities must be nonnegative integers')


@dataclass(frozen=True, slots=True)
class ExecutionResultContext:
    plan: ExecutionPlanContext
    status: str
    reason: str
    state_at: str | None
    intents: tuple[ExecutionIntentFact, ...]
    fills: tuple[ExecutionFillFact, ...]


def explain_execution(invocation, context: ExecutionPlanContext | ExecutionResultContext) -> ExecutionExplanation:
    """Invoke an authenticated source scope with facts only."""
    if type(context) not in (ExecutionPlanContext, ExecutionResultContext):
        raise TypeError("invalid strategy execution explanation context")
    function = invocation.execution_explainer
    if function is None:
        raise ValueError("strategy has no active execution explainer")
    result = function(context)
    if type(result) is not ExecutionExplanation:
        raise TypeError("strategy execution explainer must return ExecutionExplanation")
    return result
