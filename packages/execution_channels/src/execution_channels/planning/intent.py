"""Position intent received by execution channels."""
from dataclasses import dataclass
from collections.abc import Mapping
import math
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
    def __post_init__(self):
        if type(self.target) not in (int,float) or not math.isfinite(self.target) or not 0 <= self.target <= 1:
            raise ValueError('trade intent requires target in [0,1]')
        if type(self.explanation) is not DecisionExplanation:
            raise TypeError('trade intent requires typed explanation')
