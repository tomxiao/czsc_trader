"""Planning feasibility, explicitly distinct from broker execution results."""
from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Mapping


class PlanningStatus(StrEnum):
    READY = 'READY'
    CONSTRAINED = 'CONSTRAINED'
    BLOCKED = 'BLOCKED'
    NO_CHANGE = 'NO_CHANGE'
    SUPPRESSED = 'SUPPRESSED'


class PlanningConstraint(StrEnum):
    INSUFFICIENT_CASH = 'INSUFFICIENT_CASH'
    BELOW_MINIMUM_UNIT = 'BELOW_MINIMUM_UNIT'
    BELOW_PRICE_TICK = 'BELOW_PRICE_TICK'
    INSUFFICIENT_SELLABLE_QUANTITY = 'INSUFFICIENT_SELLABLE_QUANTITY'
    ORDER_QUANTITY_LIMIT = 'ORDER_QUANTITY_LIMIT'
    DEPENDENCY_UNAVAILABLE = 'DEPENDENCY_UNAVAILABLE'


@dataclass(frozen=True, slots=True)
class PlanningResult:
    status: PlanningStatus
    reasons: tuple[PlanningConstraint, ...]
    desired_quantity: int
    planned_quantity: int

    def __post_init__(self):
        if type(self.status) is not PlanningStatus or type(self.reasons) is not tuple:
            raise TypeError('planning result requires typed status and immutable reasons')
        if any(type(x) is not PlanningConstraint for x in self.reasons) or len(set(self.reasons)) != len(self.reasons):
            raise ValueError('planning reasons require distinct typed constraints')
        if any(type(q) is not int or q < 0 for q in (self.desired_quantity,self.planned_quantity)):
            raise ValueError('planning quantities require nonnegative integers')
        if bool(self.reasons) != (self.status in {PlanningStatus.CONSTRAINED,PlanningStatus.BLOCKED}):
            raise ValueError('constrained planning requires explicit reasons')

    def to_dict(self):
        return dict(status=self.status.value, reasons=[x.value for x in self.reasons],
                    desired_quantity=self.desired_quantity, planned_quantity=self.planned_quantity)

    @classmethod
    def from_dict(cls,value):
        if not isinstance(value,Mapping) or set(value) != {'status','reasons','desired_quantity','planned_quantity'}:
            raise ValueError('invalid planning result fields')
        if not isinstance(value['reasons'],(tuple,list)):
            raise TypeError('planning reasons require a sequence')
        return cls(PlanningStatus(value['status']),tuple(PlanningConstraint(x) for x in value['reasons']),
                   value['desired_quantity'],value['planned_quantity'])
