"""Signal calculation output, independent of account sizing and execution."""
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping

from .contracts import StrategyIdentity, TradingPoint, PriceReference
from .models import ExecutionPolicy
from .signals import StrategySignal


@dataclass(frozen=True, slots=True)
class SessionProposal:
    strategy: StrategyIdentity
    point: TradingPoint
    signal_date: date
    signal: StrategySignal
    references: PriceReference
    input_identities: Mapping[str, str]
    price_identities: Mapping[str, str]
    execution_policy: ExecutionPolicy
    signal_identity: str

    def __post_init__(self):
        for name, kind in (("strategy", StrategyIdentity), ("point", TradingPoint),
                           ("signal", StrategySignal), ("references", PriceReference),
                           ("execution_policy", ExecutionPolicy)):
            if type(getattr(self, name)) is not kind:
                raise TypeError("session proposal requires typed " + name)
        if type(self.signal_date) is not date or self.signal.trading_date != self.point.trading_date:
            raise ValueError("session proposal dates do not agree")
        for name in ("input_identities", "price_identities"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
