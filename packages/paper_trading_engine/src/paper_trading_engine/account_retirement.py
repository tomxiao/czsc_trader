"""Contracts for withdrawing an idle account's cash and detaching its strategy."""

from dataclasses import dataclass
from decimal import Decimal
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
    RETIRED = "RETIRED"


@dataclass(frozen=True, slots=True)
class AccountRetirementResult:
    status: AccountRetirementStatus
    account_id: str
    released_cash: Decimal
    remaining_strategy_accounts: int


@dataclass(frozen=True, slots=True)
class CapitalPoolBalance:
    registered_capital: Decimal
    allocated_capital: Decimal
    recovered_pnl: Decimal

    @property
    def unallocated_cash(self) -> Decimal:
        return self.registered_capital + self.recovered_pnl - self.allocated_capital
