"""Validated account-facing identity of an installed paper-trading strategy."""

from dataclasses import dataclass
from datetime import date
import math
import re

from strategy_manager import Qualification


@dataclass(frozen=True, slots=True)
class AccountStrategyBinding:
    strategy_id: str
    version: str
    release_hash: str
    name: str
    qualification: Qualification
    selection_data_cutoff: date
    symbol: str
    fee_rate: float

    def __post_init__(self) -> None:
        for name, pattern in (
            ("strategy_id", r"S[0-9]{3}"),
            ("version", r"v[1-9][0-9]*"),
            ("release_hash", r"[0-9a-f]{64}"),
            ("symbol", r"[0-9]{6}\.(SH|SZ)"),
        ):
            value = getattr(self, name)
            if type(value) is not str or re.fullmatch(pattern, value) is None:
                raise ValueError(f"invalid account binding {name}")
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("account binding requires a name")
        if type(self.qualification) is not Qualification or self.qualification not in {
            Qualification.PAPER_READY,
            Qualification.LIVE_READY,
        }:
            raise ValueError("account binding requires paper trading qualification")
        if type(self.selection_data_cutoff) is not date:
            raise TypeError("account binding requires a selection cutoff date")
        if (
            type(self.fee_rate) not in (float, int)
            or not math.isfinite(self.fee_rate)
            or not 0 <= self.fee_rate < 1
        ):
            raise ValueError("account binding requires a finite fee rate in [0, 1)")

    @property
    def release_id(self) -> str:
        return f"{self.strategy_id}-{self.version}"
