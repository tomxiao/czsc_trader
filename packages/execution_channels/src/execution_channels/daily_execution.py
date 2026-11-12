"""Confirmed execution results used to authorize the next daily plan."""
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


DAILY_TARGET_TRIGGER = 'daily_target_change_or_zero_fill'
INTERVAL_TARGET_TRIGGER = 'interval_target_change_or_zero_fill'
TARGET_TRIGGERS = (DAILY_TARGET_TRIGGER, INTERVAL_TARGET_TRIGGER)
ENTRY_CASH_FRACTION = 'entry_cash_fraction'


class DailyExecutionOutcome(StrEnum):
    NO_PLAN = 'NO_PLAN'
    UNRESOLVED = 'UNRESOLVED'
    ZERO_FILL = 'ZERO_FILL'
    PARTIAL_FILL = 'PARTIAL_FILL'
    FULL_FILL = 'FULL_FILL'


class DailyExecutionTrigger(StrEnum):
    INITIAL_TARGET = 'INITIAL_TARGET'
    TARGET_CHANGED = 'TARGET_CHANGED'
    PREVIOUS_ZERO_FILL = 'PREVIOUS_ZERO_FILL'
    UNCHANGED_TARGET = 'UNCHANGED_TARGET'


def daily_execution_outcome(ordered: int, filled: int, *, terminal: bool) -> DailyExecutionOutcome:
    if type(ordered) is not int or type(filled) is not int or not 0 <= filled <= ordered:
        raise ValueError('daily execution requires consistent order and fill quantities')
    if type(terminal) is not bool:
        raise TypeError('daily execution requires explicit terminal status')
    if not ordered:
        return DailyExecutionOutcome.NO_PLAN
    if not terminal:
        return DailyExecutionOutcome.UNRESOLVED
    if not filled:
        return DailyExecutionOutcome.ZERO_FILL
    return DailyExecutionOutcome.FULL_FILL if filled == ordered else DailyExecutionOutcome.PARTIAL_FILL


@dataclass(frozen=True, slots=True)
class PreviousDailyExecution:
    target: float
    outcome: DailyExecutionOutcome
    previous_session: bool
    entry_cash: Decimal | None = None
    buy_cost: Decimal = Decimal(0)

    def __post_init__(self):
        if type(self.target) not in (int, float) or not 0 <= self.target <= 1:
            raise ValueError('previous daily target must be a weight in [0,1]')
        if type(self.outcome) is not DailyExecutionOutcome or type(self.previous_session) is not bool:
            raise TypeError('previous daily execution requires typed outcome and session adjacency')
        amounts = (self.buy_cost,) if self.entry_cash is None else (self.entry_cash, self.buy_cost)
        if any(type(value) is not Decimal or not value.is_finite() or value < 0 for value in amounts):
            raise ValueError('entry cash and confirmed buy cost require nonnegative decimal amounts')

    def trigger(self, target: float) -> DailyExecutionTrigger:
        if self.outcome is DailyExecutionOutcome.UNRESOLVED:
            raise ValueError('previous execution requires confirmed order reconciliation')
        if self.target != target:
            return DailyExecutionTrigger.TARGET_CHANGED
        if self.previous_session and self.outcome is DailyExecutionOutcome.ZERO_FILL:
            return DailyExecutionTrigger.PREVIOUS_ZERO_FILL
        return DailyExecutionTrigger.UNCHANGED_TARGET
