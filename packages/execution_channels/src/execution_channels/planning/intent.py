"""Execution-owned desired positions and explicit instructions."""
from dataclasses import dataclass
from collections.abc import Mapping
import math
from ..contracts import ReplayOrder, ReplayLeg, CycleBudget
from ..identity import freeze

@dataclass(frozen=True, slots=True)
class DecisionExplanation:
    facts: Mapping

    def __post_init__(self):
        object.__setattr__(self, 'facts', freeze(self.facts))

    def to_dict(self):
        from ..identity import _thaw_json
        return _thaw_json(self.facts)

@dataclass(frozen=True, slots=True)
class TradeIntent:
    target: float
    explanation: DecisionExplanation
    orders: tuple[ReplayOrder, ...] = ()
    legs: tuple[ReplayLeg, ...] = ()
    capital_mode: str = 'target_equity_fraction'
    cycle_before: CycleBudget | None = None
    cycle_after: CycleBudget | None = None

    def __post_init__(self):
        if type(self.target) not in (int,float) or not math.isfinite(self.target) or not 0 <= self.target <= 1:
            raise ValueError('trade intent requires target in [0,1]')
        if type(self.explanation) is not DecisionExplanation:
            raise TypeError('trade intent requires typed explanation')
        if type(self.orders) is not tuple or any(type(x) is not ReplayOrder for x in self.orders):
            raise TypeError('trade intent requires immutable typed orders')
        if type(self.legs) is not tuple or any(type(x) is not ReplayLeg for x in self.legs):
            raise TypeError('trade intent requires immutable typed legs')
        if self.orders and self.legs:
            raise ValueError('orders and legs are mutually exclusive')
        if self.capital_mode not in {'full_available_cash','target_equity_fraction','signal_cash_fraction'}:
            raise ValueError('unsupported capital mode')
        if any(x is not None and type(x) is not CycleBudget for x in (self.cycle_before,self.cycle_after)):
            raise TypeError('cycle budget must be typed')
        if self.capital_mode != 'signal_cash_fraction' and any(x is not None for x in (self.cycle_before,self.cycle_after)):
            raise ValueError('cycle budgets require signal_cash_fraction')
