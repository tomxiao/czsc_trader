"""Internal signal-calculation values shared by SRT strategy algorithms."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import math
from types import MappingProxyType
from typing import Any, Mapping

from .errors import RuntimeContractError
from .entry_cycle import CycleTarget


@dataclass(frozen=True, slots=True)
class StrategySignal:
    trading_date: date
    target_position: float
    evidence: Mapping[str, Any] = field(default_factory=dict)
    next_state: Mapping[str, Any] = field(default_factory=dict)
    cycle_target: CycleTarget | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if not math.isfinite(self.target_position):
            raise RuntimeContractError("strategy target position must be finite")
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))
        object.__setattr__(self, "next_state", MappingProxyType(dict(self.next_state)))
