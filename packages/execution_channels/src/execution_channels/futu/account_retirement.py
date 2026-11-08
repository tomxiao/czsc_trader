"""Contracts for draining, liquidating and retiring a strategy account."""

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from ..instruments import TimeInterval
from enum import StrEnum
import re


@dataclass(frozen=True, slots=True)
class AccountRetirementRequest:
    account_id: str
    expected_release_hash: str
    actor: str
    reason: str

    def __post_init__(self) -> None:
        if type(self.account_id) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", self.account_id):
            raise ValueError("invalid retirement account id")
        if type(self.expected_release_hash) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.expected_release_hash):
            raise ValueError("invalid retirement release hash")
        for field in ("actor", "reason"):
            value = getattr(self, field)
            if type(value) is not str or not value.strip():
                raise ValueError(f"retirement requires {field}")


class AccountRetirementStatus(StrEnum):
    DRAINING = "DRAINING"
    WAITING_MARKET = "WAITING_MARKET"
    WAITING_SELLABLE = "WAITING_SELLABLE"
    LIQUIDATING = "LIQUIDATING"
    WAITING_SETTLEMENT = "WAITING_SETTLEMENT"
    BLOCKED = "BLOCKED"
    RETIRED = "RETIRED"


@dataclass(frozen=True, slots=True)
class AccountRetirementResult:
    status: AccountRetirementStatus
    account_id: str
    released_cash: Decimal
    remaining_strategy_accounts: int
    remaining_quantity: int = 0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RetirementSession:
    """Host-supplied actual exchange interval and model cost; never inferred by EC."""
    interval: TimeInterval
    fee_rate: Decimal
    settlement_at: datetime | None = None

    def __post_init__(self):
        if type(self.interval) is not TimeInterval:
            raise TypeError("retirement requires an actual trading interval")
        if type(self.fee_rate) is not Decimal or not self.fee_rate.is_finite() or not 0 <= self.fee_rate < 1:
            raise ValueError("retirement requires an explicit finite fee rate")
        if self.settlement_at is not None and (self.settlement_at.utcoffset() is None
                                               or self.settlement_at < self.interval.end):
            raise ValueError("retirement settlement must cover the execution interval")


@dataclass(frozen=True, slots=True)
class CapitalPoolBalance:
    registered_capital: Decimal
    allocated_capital: Decimal
    recovered_pnl: Decimal

    @property
    def unallocated_cash(self) -> Decimal:
        return self.registered_capital + self.recovered_pnl - self.allocated_capital
