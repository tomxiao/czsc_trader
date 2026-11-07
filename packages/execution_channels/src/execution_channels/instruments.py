"""Execution-owned instrument and causal interval identities; no data provider dependency."""
from dataclasses import dataclass
from datetime import datetime, UTC
from enum import StrEnum
import re

class MarketId(StrEnum):
    CN = "CN"
    US = "US"


class AssetClass(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"


class BarFrequency(StrEnum):
    DAILY = "daily"
    M30 = "30m"


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("equity timestamps must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class InstrumentId:
    market: MarketId
    asset_class: AssetClass
    symbol: str

    def __post_init__(self):
        if type(self.market) is not MarketId or type(self.asset_class) is not AssetClass:
            raise TypeError("instrument requires MarketId and AssetClass")
        pattern = r"\d{6}\.(SH|SZ|BJ)" if self.market is MarketId.CN else r"[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*"
        if type(self.symbol) is not str or re.fullmatch(pattern, self.symbol) is None:
            raise ValueError("instrument symbol is not canonical for the declared market")
        if self.market is MarketId.US and (self.symbol.startswith("US.") or self.symbol.endswith(".US")):
            raise ValueError("US instrument uses the ticker without a vendor prefix or suffix")

    @property
    def timezone(self) -> str:
        return "America/New_York" if self.market is MarketId.US else "Asia/Shanghai"

    @property
    def currency(self) -> str:
        return "USD" if self.market is MarketId.US else "CNY"


@dataclass(frozen=True, slots=True)
class TimeInterval:
    start: datetime
    end: datetime

    def __post_init__(self):
        object.__setattr__(self, "start", utc(self.start))
        object.__setattr__(self, "end", utc(self.end))
        if self.start >= self.end:
            raise ValueError("interval must have start < end")
