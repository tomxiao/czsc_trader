"""Typed signal allocation and account-owned entry-cycle facts."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import re
from collections.abc import Mapping

from .errors import RuntimeContractError


def _decimal(value, name, *, fraction=False):
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int, float)):
        raise RuntimeContractError(f"{name} requires a decimal value")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise RuntimeContractError(f"{name} requires a decimal value") from exc
    if not number.is_finite() or number < 0 or (fraction and not 0 < number <= 1):
        raise RuntimeContractError(f"{name} is outside its finite bounds")
    return number


@dataclass(frozen=True, slots=True)
class CycleTarget:
    active: bool
    entry_fraction: Decimal | None

    def __post_init__(self):
        if type(self.active) is not bool:
            raise RuntimeContractError("cycle active requires bool")
        if self.active:
            object.__setattr__(self, "entry_fraction", _decimal(
                self.entry_fraction, "entry fraction", fraction=True))
        elif self.entry_fraction is not None:
            raise RuntimeContractError("inactive cycle target requires no entry fraction")

    def to_dict(self):
        return {"active": self.active, "entry_fraction": (
            None if self.entry_fraction is None else str(self.entry_fraction))}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping) or set(value) != {"active", "entry_fraction"}:
            raise RuntimeContractError("invalid cycle target fields")
        if value["entry_fraction"] is not None and not isinstance(value["entry_fraction"], str):
            raise RuntimeContractError("serialized entry fraction requires a decimal string")
        return cls(**value)


class EntryCyclePhase(StrEnum):
    ACTIVE = "ACTIVE"
    EXITING = "EXITING"


class EntryCyclePlanStatus(StrEnum):
    OPEN = "OPEN"
    HOLD = "HOLD"
    EXIT = "EXIT"
    IDLE = "IDLE"
    INSUFFICIENT_LOT = "INSUFFICIENT_LOT"
    BUDGET_LIMIT = "BUDGET_LIMIT"


@dataclass(frozen=True, slots=True)
class EntryCycleState:
    cycle_id: str
    opening_signal_identity: str
    allocation_fraction: Decimal
    cash_budget: Decimal
    target_quantity: int
    buy_cost_including_fees: Decimal
    phase: EntryCyclePhase

    def __post_init__(self):
        for name in ("cycle_id", "opening_signal_identity"):
            value = getattr(self, name)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise RuntimeContractError(f"{name} requires SHA-256")
        for name in ("allocation_fraction", "cash_budget", "buy_cost_including_fees"):
            object.__setattr__(self, name, _decimal(
                getattr(self, name), name, fraction=name == "allocation_fraction"))
        if self.cash_budget <= 0:
            raise RuntimeContractError("cycle cash budget must be positive")
        if type(self.target_quantity) is not int or self.target_quantity <= 0 or self.target_quantity % 100:
            raise RuntimeContractError("cycle target requires positive 100-share lots")
        if not isinstance(self.phase, EntryCyclePhase):
            raise RuntimeContractError("cycle phase requires EntryCyclePhase")

    @property
    def remaining_budget(self):
        # Actual fills remain facts even if a channel charges an unexpected fee.
        return max(Decimal(0), self.cash_budget - self.buy_cost_including_fees)

    def to_dict(self):
        return {"cycle_id": self.cycle_id,
                "opening_signal_identity": self.opening_signal_identity,
                "allocation_fraction": str(self.allocation_fraction),
                "cash_budget": str(self.cash_budget), "target_quantity": self.target_quantity,
                "buy_cost_including_fees": str(self.buy_cost_including_fees),
                "phase": self.phase.value}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise RuntimeContractError("invalid entry cycle state fields")
        if any(not isinstance(value[name], str) for name in (
            "allocation_fraction", "cash_budget", "buy_cost_including_fees"
        )):
            raise RuntimeContractError("serialized cycle amounts require decimal strings")
        try:
            return cls(**{**value, "phase": EntryCyclePhase(value["phase"])})
        except (ValueError, TypeError) as exc:
            raise RuntimeContractError("invalid entry cycle state") from exc
