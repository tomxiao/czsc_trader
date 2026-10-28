"""Market-qualified equity identities and explicit, versioned source requests.

These value types have no provider, storage or execution dependencies.
"""
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
import math
import re
from zoneinfo import ZoneInfo


class MarketId(StrEnum):
    CN = "CN"
    US = "US"


class AssetClass(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"


class EquityProduct(StrEnum):
    BARS = "equity.bars"
    SESSIONS = "equity.sessions"
    ACTIONS = "equity.actions"
    CONSTRAINTS = "equity.constraints"


class BarFrequency(StrEnum):
    DAILY = "daily"
    M30 = "30m"


class PriceAdjustment(StrEnum):
    NONE = "none"
    FORWARD = "qfq"
    BACKWARD = "hfq"


class EquitySession(StrEnum):
    REGULAR = "REGULAR"


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
class SourceRef:
    provider: str
    revision: str

    def __post_init__(self):
        for value in (self.provider, self.revision):
            if type(value) is not str or not value.strip() or value != value.strip():
                raise ValueError("source name and revision must be explicit nonempty strings")


@dataclass(frozen=True, slots=True)
class ProviderKey:
    product: EquityProduct
    market: MarketId
    source: SourceRef

    def __post_init__(self):
        if type(self.product) is not EquityProduct or type(self.market) is not MarketId or type(self.source) is not SourceRef:
            raise TypeError("provider key requires equity product, market and source")


@dataclass(frozen=True, slots=True)
class TimeInterval:
    start: datetime
    end: datetime

    def __post_init__(self):
        object.__setattr__(self, "start", utc(self.start))
        object.__setattr__(self, "end", utc(self.end))
        if self.start >= self.end:
            raise ValueError("interval must have start < end")


@dataclass(frozen=True, slots=True)
class UsEquityBarPolicy:
    """Explicit research execution assumptions, never a historical halt attestation.

    Known unavailable intervals are execution facts. Their overlap blocks a bar's
    fills but must not be exposed as information known at that bar's start.
    """
    quantity_step: int
    price_tick: float
    unavailable_intervals: tuple[TimeInterval, ...] = ()

    def __post_init__(self):
        if type(self.quantity_step) is not int or self.quantity_step <= 0:
            raise ValueError("quantity step must be a positive integer")
        if type(self.price_tick) not in (int, float) or not math.isfinite(self.price_tick) or self.price_tick <= 0:
            raise ValueError("price tick must be positive and finite")
        if type(self.unavailable_intervals) is not tuple or any(type(i) is not TimeInterval for i in self.unavailable_intervals):
            raise TypeError("unavailable intervals require a tuple of TimeInterval")
        if any(right.start < left.end for left, right in zip(self.unavailable_intervals, self.unavailable_intervals[1:])):
            raise ValueError("unavailable intervals must be ordered and nonoverlapping")


@dataclass(frozen=True, slots=True)
class TradingSession:
    session_date: date
    timezone: str
    segments: tuple[TimeInterval, ...]

    def __post_init__(self):
        if type(self.session_date) is not date or type(self.segments) is not tuple or not self.segments:
            raise ValueError("trading session requires a date and nonempty segments")
        zone = ZoneInfo(self.timezone)
        previous = None
        for segment in self.segments:
            if type(segment) is not TimeInterval:
                raise TypeError("session segments require TimeInterval")
            if segment.start.astimezone(zone).date() != self.session_date or segment.end.astimezone(zone).date() != self.session_date:
                raise ValueError("session segments must belong to the declared local date")
            if previous is not None and segment.start <= previous:
                raise ValueError("session segments must be ordered and disjoint")
            previous = segment.end

    def bars(self, frequency: BarFrequency) -> tuple[TimeInterval, ...]:
        if type(frequency) is not BarFrequency:
            raise TypeError("frequency requires BarFrequency")
        if frequency is BarFrequency.DAILY:
            return (TimeInterval(self.segments[0].start, self.segments[-1].end),)
        result = []
        step = timedelta(minutes=30)
        for segment in self.segments:
            current = segment.start
            while current < segment.end:
                end = current + step
                if end > segment.end:
                    raise ValueError("session contains an incomplete 30-minute interval")
                result.append(TimeInterval(current, end))
                current = end
        return tuple(result)


@dataclass(frozen=True, slots=True)
class EquityQuery:
    product: EquityProduct
    start: date
    end: date
    frequency: BarFrequency = BarFrequency.M30
    adjustment: PriceAdjustment = PriceAdjustment.NONE
    session: EquitySession = EquitySession.REGULAR

    def __post_init__(self):
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise ValueError("equity query requires ordered local dates")
        for name, cls in (("product", EquityProduct), ("frequency", BarFrequency),
                          ("adjustment", PriceAdjustment), ("session", EquitySession)):
            if type(getattr(self, name)) is not cls:
                raise TypeError(f"equity query {name} requires {cls.__name__}")
        if self.product is not EquityProduct.BARS and self.adjustment is not PriceAdjustment.NONE:
            raise ValueError("only bars may request price adjustment")


@dataclass(frozen=True, slots=True)
class EquityParameters:
    instrument: InstrumentId
    source: SourceRef
    query: EquityQuery

    def __post_init__(self):
        if type(self.instrument) is not InstrumentId or type(self.source) is not SourceRef or type(self.query) is not EquityQuery:
            raise TypeError("equity parameters require typed instrument, source and query")

    @property
    def provider_key(self) -> ProviderKey:
        return ProviderKey(self.query.product, self.instrument.market, self.source)
