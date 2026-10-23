"""Public, caller-neutral contracts for Strategy Runtime (SRT)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import math
import re
from types import MappingProxyType
from typing import Mapping, Protocol, TypeAlias, runtime_checkable

from .errors import RuntimeContractError
from .models import canonical_sha256
from .pricing import ExecutionPriceBasis, ExecutionPricing
from .entry_cycle import CycleTarget, EntryCycleState, EntryCyclePlanStatus, EntryCyclePhase


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
    entry_cycle: EntryCycleState | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if self.entry_cycle is not None:
            if not isinstance(self.entry_cycle, EntryCycleState):
                raise RuntimeContractError("entry_cycle requires EntryCycleState")
            if self.cycle_target_quantity != self.entry_cycle.target_quantity:
                raise RuntimeContractError("cycle quantity differs from entry cycle state")
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
    pricing: ExecutionPricing = field(default_factory=ExecutionPricing, kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.pricing, ExecutionPricing):
            raise RuntimeContractError("portfolio pricing requires ExecutionPricing")
        object.__setattr__(self, "account_id", _text(self.account_id, "account_id"))
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol").upper())
        object.__setattr__(
            self, "available_cash", _money(self.available_cash, "available_cash")
        )
        object.__setattr__(self, "total_assets", _money(self.total_assets, "total_assets"))
        if self.position_quantity < 0 or self.position_quantity % 100:
            raise RuntimeContractError(
                "position quantity must use non-negative 100-unit lots"
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
    pricing: ExecutionPricing = field(default_factory=ExecutionPricing, kw_only=True)
    price_scale: Decimal = field(default=Decimal("1"), kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.pricing, ExecutionPricing):
            raise RuntimeContractError("price reference requires ExecutionPricing")
        object.__setattr__(self, "price_scale", _money(self.price_scale, "price_scale"))
        if not self.price_scale.is_finite() or self.price_scale <= 0:
            raise RuntimeContractError("price scale must be positive and finite")
        if self.pricing.basis is ExecutionPriceBasis.UNADJUSTED and self.price_scale != 1:
            raise RuntimeContractError("unadjusted price references require unit scale")
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
    cycle_target: CycleTarget | None = None,
) -> str:
    """Return the stable identity of strategy facts before account sizing."""

    if cycle_target is not None and not isinstance(cycle_target, CycleTarget):
        raise RuntimeContractError("signal identity requires typed CycleTarget")
    return canonical_sha256(
        {
            "strategy": strategy.reference_id,
            "release_hash": strategy.release_hash,
            "runtime_sha256": strategy.runtime_sha256,
            "signal_date": signal_date.isoformat(),
            "target_position": target_position,
            "inputs": dict(sorted(input_identities.items())),
            "prices": dict(sorted(price_identities.items())),
            **({"cycle_target": cycle_target.to_dict()} if cycle_target is not None else {}),
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
    cycle_target: CycleTarget | None = None,
    entry_cycle_before: EntryCycleState | None = None,
    entry_cycle_after: EntryCycleState | None = None,
    cycle_status: EntryCyclePlanStatus | None = None,
    available_cash: Decimal | None = None,
    fee_rate: Decimal | None = None,
) -> str:
    """Return the stable identity of one fully sized execution plan."""

    if cycle_target is not None:
        if not isinstance(cycle_target, CycleTarget) or not isinstance(cycle_status, EntryCyclePlanStatus):
            raise RuntimeContractError("cycle plan identity requires typed target and status")
        if available_cash is None or fee_rate is None:
            raise RuntimeContractError("cycle plan identity requires cash and fee facts")
    return canonical_sha256(
        {
            "signal_identity": signal_identity,
            "actual_quantity": actual_quantity,
            "target_quantity": target_quantity,
            "cycle_target_quantity": cycle_target_quantity,
            "plan_mode": plan_mode,
            "capital_mode": capital_mode,
            "allocation_fraction": str(allocation_fraction),
            **({"cycle_target": cycle_target.to_dict(),
                "available_cash": str(available_cash), "fee_rate": str(fee_rate),
                "entry_cycle_before": None if entry_cycle_before is None else entry_cycle_before.to_dict(),
                "entry_cycle_after": None if entry_cycle_after is None else entry_cycle_after.to_dict(),
                "cycle_status": cycle_status.value} if cycle_target is not None else {}),
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


def validate_entry_cycle_plan_facts(
    *, cycle_target: CycleTarget, entry_cycle_before: EntryCycleState | None,
    entry_cycle_after: EntryCycleState | None, cycle_status: EntryCyclePlanStatus,
    target_position: float, actual_quantity: int, target_quantity: int,
    cycle_target_quantity: int, allocation_fraction: Decimal, available_cash: Decimal,
    fee_rate: Decimal, signal_identity: str, orders: tuple[PlannedOrder, ...],
    plan_mode: str, legs: tuple[PlanLeg, ...],
) -> None:
    """Validate signal allocation semantics at SRT and account adoption boundaries."""
    if not isinstance(orders, tuple) or any(not isinstance(order, PlannedOrder) for order in orders):
        raise RuntimeContractError("entry cycle orders require typed PlannedOrder values")
    if any(type(q) is not int or q < 0 or q % 100 for q in
           (actual_quantity, target_quantity, cycle_target_quantity)):
        raise RuntimeContractError("entry cycle quantities require non-negative whole lots")
    if isinstance(target_position, bool) or type(target_position) not in (float, int):
        raise RuntimeContractError("entry cycle target requires numeric binary position")
    for name, value in (("available_cash", available_cash), ("fee_rate", fee_rate),
                        ("allocation_fraction", allocation_fraction)):
        if isinstance(value, bool):
            raise RuntimeContractError(f"{name} cannot be boolean")
        try:
            _money(value, name)
        except (InvalidOperation, TypeError) as exc:
            raise RuntimeContractError(f"{name} requires a finite decimal") from exc
    if not 0 <= Decimal(str(fee_rate)) < 1 or not 0 < Decimal(str(allocation_fraction)) <= 1:
        raise RuntimeContractError("entry cycle fee or allocation outside bounds")
    if not isinstance(cycle_target, CycleTarget) or not isinstance(cycle_status, EntryCyclePlanStatus):
        raise RuntimeContractError("signal cash fraction requires typed cycle target and status")
    if target_position not in (0., 1.) or bool(target_position) != cycle_target.active:
        raise RuntimeContractError("cycle target differs from binary target position")
    if plan_mode != "NONE" or type(legs) is not tuple or legs:
        raise RuntimeContractError("entry cycle plans require immediate orders without overlay legs")
    for state in (entry_cycle_before, entry_cycle_after):
        if state is not None and not isinstance(state, EntryCycleState):
            raise RuntimeContractError("plan cycle requires EntryCycleState")
    if entry_cycle_after is not None:
        if actual_quantity > entry_cycle_after.target_quantity:
            raise RuntimeContractError("account position exceeds locked cycle target")
        if cycle_target_quantity != entry_cycle_after.target_quantity:
            raise RuntimeContractError("plan cycle quantity differs from locked state")
        if Decimal(str(allocation_fraction)) != entry_cycle_after.allocation_fraction:
            raise RuntimeContractError("plan allocation differs from locked state")
        before, after = entry_cycle_before, entry_cycle_after
        if before is not None:
            if {k: v for k, v in before.to_dict().items() if k != "phase"} != {
                k: v for k, v in after.to_dict().items() if k != "phase"
            }:
                raise RuntimeContractError("planning cannot rewrite locked allocation or actual fills")
            if before.phase is EntryCyclePhase.EXITING and after.phase is not EntryCyclePhase.EXITING:
                raise RuntimeContractError("exiting cycle cannot become active again")
            expected_phase = (EntryCyclePhase.EXITING if not cycle_target.active
                              or before.phase is EntryCyclePhase.EXITING else EntryCyclePhase.ACTIVE)
            if after.phase is not expected_phase:
                raise RuntimeContractError("cycle phase transition differs from signal and prior phase")
        elif (not cycle_target.active or after.phase is not EntryCyclePhase.ACTIVE
              or after.buy_cost_including_fees != 0 or actual_quantity != 0
              or after.opening_signal_identity != signal_identity
              or after.allocation_fraction != cycle_target.entry_fraction
              or after.cash_budget != Decimal(str(available_cash)) * after.allocation_fraction):
            raise RuntimeContractError("invalid initial cycle allocation")
        if not cycle_target.active and after.phase is not EntryCyclePhase.EXITING:
            raise RuntimeContractError("inactive signal requires exiting cycle")
        buy_orders = [o for o in orders if o.side is OrderSide.BUY]
        sell_orders = [o for o in orders if o.side is OrderSide.SELL]
        buy_quantity = sum(o.quantity for o in buy_orders)
        sell_quantity = sum(o.quantity for o in sell_orders)
        if after.phase is EntryCyclePhase.ACTIVE:
            if sell_orders or target_quantity != actual_quantity + buy_quantity:
                raise RuntimeContractError("active cycle requires buy-only target quantities")
            if before is None and buy_quantity != after.target_quantity:
                raise RuntimeContractError("opening orders must establish the locked target")
            expected_status = (EntryCyclePlanStatus.OPEN if before is None else
                               EntryCyclePlanStatus.BUDGET_LIMIT if not buy_orders and actual_quantity < after.target_quantity
                               else EntryCyclePlanStatus.HOLD)
        else:
            if buy_orders or sell_quantity != actual_quantity or target_quantity != 0:
                raise RuntimeContractError("exiting cycle requires full liquidation orders")
            expected_status = EntryCyclePlanStatus.EXIT
        if cycle_status is not expected_status:
            raise RuntimeContractError("cycle plan status differs from execution facts")
        if buy_orders:
            if after.phase is EntryCyclePhase.EXITING or any(o.order_type is not OrderType.LIMIT or o.limit_price is None for o in buy_orders):
                raise RuntimeContractError("entry cycle buys require active limited orders")
            cost = sum((o.quantity * o.limit_price * (1 + Decimal(str(fee_rate)))
                        for o in buy_orders), Decimal(0))
            if (cost > min(after.remaining_budget, Decimal(str(available_cash)))
                    or sum(o.quantity for o in buy_orders) > after.target_quantity - actual_quantity):
                raise RuntimeContractError("entry cycle orders exceed budget or quantity")
    elif cycle_target_quantity != 0 or actual_quantity != 0 or orders:
        raise RuntimeContractError("plan without entry cycle cannot hold or trade")
    elif target_quantity != 0 or cycle_status is not (
            EntryCyclePlanStatus.INSUFFICIENT_LOT if cycle_target.active else EntryCyclePlanStatus.IDLE):
        raise RuntimeContractError("empty cycle plan has inconsistent target or status")
    if entry_cycle_before is not None and entry_cycle_after is None:
        raise RuntimeContractError("only settled account facts may release an entry cycle")


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
    cycle_target: CycleTarget | None = field(default=None, kw_only=True)
    entry_cycle_before: EntryCycleState | None = field(default=None, kw_only=True)
    entry_cycle_after: EntryCycleState | None = field(default=None, kw_only=True)
    cycle_status: EntryCyclePlanStatus | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if self.capital_mode == "signal_cash_fraction":
            validate_entry_cycle_plan_facts(
                cycle_target=self.cycle_target,
                entry_cycle_before=self.entry_cycle_before,
                entry_cycle_after=self.entry_cycle_after,
                cycle_status=self.cycle_status,
                target_position=self.target_position,
                actual_quantity=self.actual_quantity,
                target_quantity=self.target_quantity,
                cycle_target_quantity=self.cycle_target_quantity,
                allocation_fraction=self.allocation_fraction,
                available_cash=self.available_cash,
                fee_rate=self.fee_rate,
                signal_identity=self.signal_identity,
                orders=self.orders,
                plan_mode=self.plan_mode,
                legs=self.legs,
            )
        elif any(v is not None for v in (self.cycle_target, self.entry_cycle_before,
                                        self.entry_cycle_after, self.cycle_status)):
            raise RuntimeContractError("cycle allocation fields require signal cash fraction mode")
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
            raise RuntimeContractError("plan quantities must use non-negative 100-unit lots")
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
        if self.capital_mode == "target_equity_fraction":
            if isinstance(self.allocation_fraction, bool) or allocation_fraction != 1:
                raise RuntimeContractError("equity target requires allocation fraction one")
            if isinstance(self.target_position, bool) or not 0 <= self.target_position <= 1:
                raise RuntimeContractError("equity target position must be in [0, 1]")
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
            cycle_target=self.cycle_target,
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
            cycle_target=self.cycle_target,
            entry_cycle_before=self.entry_cycle_before,
            entry_cycle_after=self.entry_cycle_after,
            cycle_status=self.cycle_status,
            available_cash=self.available_cash, fee_rate=self.fee_rate,
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
