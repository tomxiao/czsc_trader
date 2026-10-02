"""Public, caller-neutral contracts for Strategy Runtime (SRT)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
import math
import re
from types import MappingProxyType
from typing import Mapping, Protocol, TypeAlias, runtime_checkable

from .errors import RuntimeContractError
from .models import canonical_sha256


_SHA256 = re.compile(r"[0-9a-f]{64}")


class SignalHistoryMode(StrEnum):
    """CONTINUOUS carries warmup state; WINDOW uses window-initialized replay state."""

    CONTINUOUS = "CONTINUOUS"
    WINDOW = "WINDOW"
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


def _text(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise RuntimeContractError(f"{name} must be non-empty")
    return normalized


def _money(value: Decimal | str | int | float, name: str) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise RuntimeContractError(f"{name} must be finite and non-negative")
    return result


def _identities(values: Mapping[str, str], name: str) -> Mapping[str, str]:
    normalized = dict(sorted(values.items()))
    if not normalized or any(
        not key.strip() or _SHA256.fullmatch(value) is None
        for key, value in normalized.items()
    ):
        raise RuntimeContractError(f"{name} must contain named SHA-256 identities")
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class TradableWindow:
    """Inclusive range of execution sessions handled by one strategy instance."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if type(self.start) is not date or type(self.end) is not date:
            raise RuntimeContractError("tradable window requires date values")
        if self.start > self.end:
            raise RuntimeContractError("tradable window start must not follow end")

    def contains(self, value: date) -> bool:
        return self.start <= value <= self.end


@dataclass(frozen=True, slots=True)
class StrategyIdentity:
    """Candidate, frozen strategy, or the built-in BuyHold benchmark identity."""

    strategy_id: str
    reference_id: str
    release_hash: str
    runtime_sha256: str
    symbol: str

    def __post_init__(self) -> None:
        if self.strategy_id == "BuyHold":
            if self.reference_id != "BuyHold":
                raise RuntimeContractError("benchmark reference_id must equal BuyHold")
        else:
            if not isinstance(self.strategy_id, str) or not re.fullmatch(r"S[0-9]{3}", self.strategy_id):
                raise RuntimeContractError("strategy_id must match S plus three ASCII digits")
            if not isinstance(self.reference_id, str) or not re.fullmatch(
                rf"{self.strategy_id}-(?:C[0-9]{{4}}|v[1-9][0-9]*)", self.reference_id
            ):
                raise RuntimeContractError(
                    "reference_id must identify a candidate or frozen version in this family"
                )
        for name in ("strategy_id", "reference_id", "symbol"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "symbol", self.symbol.upper())
        if _SHA256.fullmatch(self.release_hash) is None:
            raise RuntimeContractError("strategy release_hash must be lowercase SHA-256")
        if _SHA256.fullmatch(self.runtime_sha256) is None:
            raise RuntimeContractError("strategy runtime_sha256 must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class DataPreparationResult:
    """Opaque outcome of preparing one instance's calculation data."""

    strategy: StrategyIdentity
    tradable_window: TradableWindow
    available_through: date
    data_identity: str

    def __post_init__(self) -> None:
        if self.available_through >= self.tradable_window.end:
            raise RuntimeContractError(
                "prepared data cutoff must precede the final trading session"
            )
        if _SHA256.fullmatch(self.data_identity) is None:
            raise RuntimeContractError("prepared data identity must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ExecutionState:
    """Caller-owned state carried between otherwise independent plans."""

    revision: int
    as_of: datetime
    cycle_target_quantity: int | None = None

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise RuntimeContractError("execution state revision must be non-negative")
        if self.as_of.tzinfo is None:
            raise RuntimeContractError("execution state as_of must be timezone-aware")
        if self.cycle_target_quantity is not None and (
            self.cycle_target_quantity < 0 or self.cycle_target_quantity % 100
        ):
            raise RuntimeContractError(
                "cycle target quantity must use non-negative 100-share lots"
            )


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """Authoritative caller snapshot used to size one execution plan."""

    account_id: str
    symbol: str
    available_cash: Decimal
    total_assets: Decimal
    position_quantity: int
    revision: int
    as_of: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", _text(self.account_id, "account_id"))
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol").upper())
        object.__setattr__(
            self, "available_cash", _money(self.available_cash, "available_cash")
        )
        object.__setattr__(self, "total_assets", _money(self.total_assets, "total_assets"))
        if self.position_quantity < 0 or self.position_quantity % 100:
            raise RuntimeContractError(
                "position quantity must use non-negative 100-share lots"
            )
        if self.revision < 0:
            raise RuntimeContractError("portfolio revision must be non-negative")
        if self.as_of.tzinfo is None:
            raise RuntimeContractError("portfolio as_of must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TradingPoint:
    trading_date: date
    calculation_time: datetime

    def __post_init__(self) -> None:
        if type(self.trading_date) is not date or not isinstance(self.calculation_time, datetime):
            raise RuntimeContractError("trading point requires date and datetime values")
        if self.calculation_time.utcoffset() is None:
            raise RuntimeContractError("calculation_time must be timezone-aware")


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


@dataclass(frozen=True, slots=True)
class PlannedOrder:
    side: OrderSide
    quantity: int
    order_type: OrderType
    limit_price: Decimal | None

    def __post_init__(self) -> None:
        if self.quantity <= 0 or self.quantity % 100:
            raise RuntimeContractError("planned order quantity must use positive 100-share lots")
        if self.order_type is OrderType.LIMIT:
            if self.limit_price is None or _money(self.limit_price, "limit_price") <= 0:
                raise RuntimeContractError("LIMIT order requires a positive limit_price")
            object.__setattr__(self, "limit_price", _money(self.limit_price, "limit_price"))
        elif self.limit_price is not None:
            object.__setattr__(self, "limit_price", _money(self.limit_price, "limit_price"))


@dataclass(frozen=True, slots=True)
class PlanLeg:
    sequence: int
    role: str
    checkpoint: str
    submit_after: time
    submit_before: time
    order: PlannedOrder
    dependency_sequence: int | None = None
    dependency_required_status: str | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise RuntimeContractError("plan leg sequence must be non-negative")
        object.__setattr__(self, "role", _text(self.role, "plan leg role"))
        object.__setattr__(self, "checkpoint", _text(self.checkpoint, "checkpoint"))
        if self.submit_after >= self.submit_before:
            raise RuntimeContractError("plan leg submission window is invalid")
        if (self.dependency_sequence is None) != (
            self.dependency_required_status is None
        ):
            raise RuntimeContractError("plan leg dependency fields must be supplied together")
        if self.dependency_sequence is not None and self.dependency_sequence >= self.sequence:
            raise RuntimeContractError("plan leg dependency must refer to an earlier leg")


@dataclass(frozen=True, slots=True)
class ExecutionCapabilities:
    order_types: tuple[OrderType, ...]
    checkpoints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.order_types, tuple) or not all(isinstance(item, OrderType) for item in self.order_types):
            raise RuntimeContractError("execution order types must be a tuple of OrderType")
        if len(set(self.order_types)) != len(self.order_types):
            raise RuntimeContractError("execution order types must be unique")
        if len(set(self.checkpoints)) != len(self.checkpoints):
            raise RuntimeContractError("execution checkpoints must be unique")


@dataclass(frozen=True, slots=True)
class PriceReference:
    signal_price: Decimal
    execution_price: Decimal
    signal_basis: str
    execution_basis: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "signal_price", _money(self.signal_price, "signal_price"))
        object.__setattr__(
            self, "execution_price", _money(self.execution_price, "execution_price")
        )
        if self.signal_price <= 0 or self.execution_price <= 0:
            raise RuntimeContractError("reference prices must be positive")
        object.__setattr__(self, "signal_basis", _text(self.signal_basis, "signal_basis"))
        object.__setattr__(
            self, "execution_basis", _text(self.execution_basis, "execution_basis")
        )


def signal_identity_for(
    *,
    strategy: StrategyIdentity,
    signal_date: date,
    target_position: float,
    input_identities: Mapping[str, str],
    price_identities: Mapping[str, str],
) -> str:
    """Return the stable identity of strategy facts before account sizing."""

    return canonical_sha256(
        {
            "strategy": strategy.reference_id,
            "release_hash": strategy.release_hash,
            "runtime_sha256": strategy.runtime_sha256,
            "signal_date": signal_date.isoformat(),
            "target_position": target_position,
            "inputs": dict(sorted(input_identities.items())),
            "prices": dict(sorted(price_identities.items())),
        }
    )


def plan_identity_for(
    *,
    signal_identity: str,
    actual_quantity: int,
    target_quantity: int,
    cycle_target_quantity: int,
    plan_mode: str,
    capital_mode: str,
    allocation_fraction: Decimal,
    orders: tuple[PlannedOrder, ...],
    legs: tuple[PlanLeg, ...],
) -> str:
    """Return the stable identity of one fully sized execution plan."""

    return canonical_sha256(
        {
            "signal_identity": signal_identity,
            "actual_quantity": actual_quantity,
            "target_quantity": target_quantity,
            "cycle_target_quantity": cycle_target_quantity,
            "plan_mode": plan_mode,
            "capital_mode": capital_mode,
            "allocation_fraction": str(allocation_fraction),
            "orders": [
                {
                    "side": order.side.value,
                    "quantity": order.quantity,
                    "order_type": order.order_type.value,
                    "limit_price": None
                    if order.limit_price is None
                    else str(order.limit_price),
                }
                for order in orders
            ],
            "legs": [
                {
                    "sequence": leg.sequence,
                    "role": leg.role,
                    "checkpoint": leg.checkpoint,
                    "submit_after": leg.submit_after.isoformat(),
                    "submit_before": leg.submit_before.isoformat(),
                    "dependency_sequence": leg.dependency_sequence,
                    "dependency_required_status": leg.dependency_required_status,
                    "order": {
                        "side": leg.order.side.value,
                        "quantity": leg.order.quantity,
                        "order_type": leg.order.order_type.value,
                        "limit_price": None
                        if leg.order.limit_price is None
                        else str(leg.order.limit_price),
                    },
                }
                for leg in legs
            ],
        }
    )


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Complete channel-neutral plan produced by SRT for one decision point."""

    strategy: StrategyIdentity
    signal_identity: str
    plan_identity: str
    symbol: str
    signal_date: date
    trading_date: date
    generated_at: datetime
    expected_portfolio_revision: int
    expected_state_revision: int
    actual_quantity: int
    target_quantity: int
    cycle_target_quantity: int
    target_position: float
    action: str
    plan_mode: str
    capital_mode: str
    allocation_fraction: Decimal
    orders: tuple[PlannedOrder, ...]
    legs: tuple[PlanLeg, ...]
    available_cash: Decimal
    fee_rate: Decimal
    estimated_order_cost: Decimal
    unallocated_cash: Decimal
    references: PriceReference
    required_capabilities: ExecutionCapabilities
    input_identities: Mapping[str, str]
    price_identities: Mapping[str, str]
    evidence: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol").upper())
        if self.symbol != self.strategy.symbol:
            raise RuntimeContractError("plan symbol differs from strategy")
        if self.generated_at.tzinfo is None:
            raise RuntimeContractError("plan generated_at must be timezone-aware")
        if self.trading_date <= self.signal_date:
            raise RuntimeContractError("plan trading date must follow signal date")
        if self.expected_portfolio_revision < 0 or self.expected_state_revision < 0:
            raise RuntimeContractError("plan revisions must be non-negative")
        quantities = (
            self.actual_quantity,
            self.target_quantity,
            self.cycle_target_quantity,
        )
        if any(value < 0 or value % 100 for value in quantities):
            raise RuntimeContractError("plan quantities must use non-negative 100-share lots")
        if not math.isfinite(self.target_position):
            raise RuntimeContractError("plan target_position must be finite")
        object.__setattr__(self, "action", _text(self.action, "plan action"))
        object.__setattr__(self, "plan_mode", _text(self.plan_mode, "plan mode"))
        object.__setattr__(self, "capital_mode", _text(self.capital_mode, "capital mode"))
        allocation_fraction = Decimal(str(self.allocation_fraction))
        if not allocation_fraction.is_finite() or not 0 < allocation_fraction <= 1:
            raise RuntimeContractError("allocation fraction must be in (0, 1]")
        if self.capital_mode == "full_available_cash" and allocation_fraction != 1:
            raise RuntimeContractError("full cash mode requires allocation fraction one")
        object.__setattr__(self, "allocation_fraction", allocation_fraction)
        for name in (
            "available_cash",
            "fee_rate",
            "estimated_order_cost",
            "unallocated_cash",
        ):
            object.__setattr__(self, name, _money(getattr(self, name), name))
        object.__setattr__(
            self, "input_identities", _identities(self.input_identities, "input identities")
        )
        object.__setattr__(
            self, "price_identities", _identities(self.price_identities, "price identities")
        )
        evidence = MappingProxyType(dict(sorted(self.evidence.items())))
        object.__setattr__(self, "evidence", evidence)
        expected_signal = signal_identity_for(
            strategy=self.strategy,
            signal_date=self.signal_date,
            target_position=self.target_position,
            input_identities=self.input_identities,
            price_identities=self.price_identities,
        )
        if self.signal_identity != expected_signal:
            raise RuntimeContractError("signal identity differs from signal facts")
        expected_plan = plan_identity_for(
            signal_identity=self.signal_identity,
            actual_quantity=self.actual_quantity,
            target_quantity=self.target_quantity,
            cycle_target_quantity=self.cycle_target_quantity,
            plan_mode=self.plan_mode,
            capital_mode=self.capital_mode,
            allocation_fraction=self.allocation_fraction,
            orders=self.orders,
            legs=self.legs,
        )
        if self.plan_identity != expected_plan:
            raise RuntimeContractError("plan identity differs from execution facts")


class ExecutionOutcomeStatus(StrEnum):
    SETTLED = "SETTLED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    plan_identity: str
    portfolio: PortfolioSnapshot
    state: ExecutionState
    status: ExecutionOutcomeStatus

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.plan_identity) is None:
            raise RuntimeContractError("outcome plan identity must be lowercase SHA-256")
        if not isinstance(self.status, ExecutionOutcomeStatus):
            raise RuntimeContractError("execution status must be ExecutionOutcomeStatus")
        if not isinstance(self.portfolio, PortfolioSnapshot) or not isinstance(self.state, ExecutionState):
            raise RuntimeContractError("execution outcome requires typed portfolio and state")


@runtime_checkable
class WindowExecutor(Protocol):
    @property
    def capabilities(self) -> ExecutionCapabilities: ...

    def snapshot(self, point: TradingPoint) -> tuple[PortfolioSnapshot, ExecutionState]: ...

    def execute(self, plan: ExecutionPlan) -> ExecutionOutcome: ...

    def finish(self) -> object: ...
