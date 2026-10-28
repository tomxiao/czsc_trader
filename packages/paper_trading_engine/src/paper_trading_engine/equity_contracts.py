"""Explicit US account and channel contracts; no broker connection or inference."""
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from dataflows import AssetClass, InstrumentId, MarketId, TimeInterval
from strategy_runtime import ResearchExecutionSpec


EQUITY_OFFLINE_CHANNEL_ID = "equity_offline_us"


@dataclass(frozen=True, slots=True)
class EquityAccountRules:
    instrument: InstrumentId
    execution: ResearchExecutionSpec

    def __post_init__(self):
        if type(self.instrument) is not InstrumentId or type(self.execution) is not ResearchExecutionSpec:
            raise TypeError("equity account requires typed instrument and execution rules")
        if self.instrument.market is not MarketId.US or self.instrument.asset_class is not AssetClass.STOCK:
            raise ValueError("equity account admits US stocks only")
        self.execution.require_instrument(self.instrument)

    @property
    def timezone(self):
        return ZoneInfo(self.instrument.timezone)

    def to_dict(self):
        return {"schema_version": 1, "instrument": asdict(self.instrument), "execution": asdict(self.execution)}

    @classmethod
    def from_dict(cls, value):
        from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, ExecutionModel, UsEquitySpec)
        from dataflows import BarFrequency
        if type(value) is not dict or set(value) != {"schema_version", "instrument", "execution"} or value["schema_version"] != 1:
            raise ValueError("unsupported equity account rules")
        instrument = dict(value["instrument"])
        instrument["market"] = MarketId(instrument["market"])
        instrument["asset_class"] = AssetClass(instrument["asset_class"])
        execution = dict(value["execution"])
        execution["market"] = UsEquitySpec(**execution["market"])
        execution["decision_clock"] = BarFrequency(execution["decision_clock"])
        account = dict(execution["account"])
        account["cash_availability"] = CashAvailabilityPolicy(account["cash_availability"])
        execution["account"] = AccountPolicy(**account)
        execution["execution"] = ExecutionModel(execution["execution"])
        return cls(InstrumentId(**instrument), ResearchExecutionSpec(**execution))


@dataclass(frozen=True, slots=True)
class EquityOrderReport:
    channel_order_id: str
    cumulative_quantity: int
    average_price: Decimal
    occurred_at: datetime
    status: str
    settlement_at: datetime | None = None

    def __post_init__(self):
        if not self.channel_order_id or type(self.cumulative_quantity) is not int or self.cumulative_quantity < 0:
            raise ValueError("invalid cumulative equity report")
        if type(self.average_price) is not Decimal or not self.average_price.is_finite() or self.average_price < 0:
            raise ValueError("invalid cumulative equity price")
        if self.cumulative_quantity and not self.average_price > 0:
            raise ValueError("filled equity report requires a positive price")
        if type(self.occurred_at) is not datetime or self.occurred_at.utcoffset() is None:
            raise ValueError("equity report requires aware time")
        if self.status not in {"SUBMITTED", "FILLED_PART", "FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FAILED"}:
            raise ValueError("unknown equity order status")
        if self.settlement_at is not None and (self.settlement_at.utcoffset() is None or self.settlement_at < self.occurred_at):
            raise ValueError("invalid settlement timestamp")


def require_equity_interval(interval: TimeInterval, instant: datetime, rules: EquityAccountRules):
    if type(interval) is not TimeInterval or instant.utcoffset() is None:
        raise ValueError("equity execution requires an explicit aware interval")
    if not interval.start <= instant < interval.end:
        raise ValueError("equity order is outside its execution interval")
    return instant.astimezone(rules.timezone).date().isoformat()
