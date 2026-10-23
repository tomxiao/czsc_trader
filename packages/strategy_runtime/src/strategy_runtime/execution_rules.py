"""Frozen execution-rule algorithms shared by every SRT host.

This module contains strategy semantics only. Platform orchestration and model
adaptation belong in ``execution_planner`` and are excluded from frozen hashes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from math import isfinite
from typing import Any, Mapping

from .errors import RuntimeContractError
from .entry_cycle import CycleTarget, EntryCycleState, EntryCyclePhase, EntryCyclePlanStatus
from .models import canonical_sha256


@dataclass(frozen=True, slots=True)
class ExecutionRuleInput:
    policy_type: str
    settings: Mapping[str, Any]
    deployment_settings: Mapping[str, Any]
    available_cash: float
    position_quantity: int
    target_position: float
    signal_reference_price: float
    execution_reference_price: float
    price_scale: float = 1.0
    unadjusted_reference_price: float | None = None
    cycle_target: CycleTarget | None = None
    entry_cycle: EntryCycleState | None = None
    opening_signal_identity: str | None = None
    account_id: str | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.price_scale) or self.price_scale <= 0:
            raise RuntimeContractError("execution price scale must be positive and finite")
        if self.price_scale != 1 and self.unadjusted_reference_price is None:
            raise RuntimeContractError("scaled pricing requires its unadjusted reference")

    @property
    def quote_reference(self) -> float:
        return self.execution_reference_price if self.unadjusted_reference_price is None else self.unadjusted_reference_price


def _round_tick(value: float, tick: float, rounding: str) -> float:
    quantum = Decimal(str(tick))
    scaled = Decimal(str(value)) / quantum
    modes = {"floor": ROUND_FLOOR, "ceil": ROUND_CEILING, "half_up": ROUND_HALF_UP}
    return float(scaled.to_integral_value(rounding=modes[rounding]) * quantum)


def effective_target_order_type(settings: Mapping[str, Any], side: str) -> str:
    """Resolve the channel-neutral order type for a target-position policy.

    Historical frozen releases described an immediately marketable sell as a
    LIMIT order while also declaring ``virtual_fill.sell`` as
    ``marketable_limit_at_open``. Research and deterministic replay executed
    those exits at the opening market price. SRT treats that fill semantic as
    authoritative so live and backtest channels preserve the audited behavior.
    """

    normalized = side.upper()
    if normalized == "BUY":
        return str(dict(settings["entry"])["order_type"])
    if normalized != "SELL":
        raise RuntimeContractError(f"unsupported target order side: {side}")
    virtual_fill = dict(settings.get("virtual_fill", {}))
    if str(virtual_fill.get("sell", "")).lower() == "marketable_limit_at_open":
        return "MARKET"
    return str(dict(settings["exit"])["order_type"])


def _target_plan(
    request: ExecutionRuleInput,
) -> dict[str, Any]:
    settings = dict(request.settings)
    if settings["capital"]["mode"] == "signal_cash_fraction":
        return _signal_cash_plan(request)
    instrument = dict(settings["instrument"])
    capital = dict(settings["capital"])
    entry = dict(settings["entry"])
    exit_rule = dict(settings["exit"])
    actual = request.position_quantity
    cash = Decimal(str(request.available_cash))
    lot = int(instrument["lot_size"])
    tick = float(instrument["price_tick"])
    equity_target = capital["mode"] == "target_equity_fraction"
    if equity_target:
        if (not isinstance(request.target_position, (int, float))
                or isinstance(request.target_position, bool)
                or not isfinite(request.target_position)
                or not 0 <= request.target_position <= 1):
            raise RuntimeContractError("equity target position must be finite and in [0, 1]")
        if (capital["target_scope"] != "decision"
                or isinstance(capital.get("allocation_fraction"), bool)
                or capital.get("allocation_fraction") != 1):
            raise RuntimeContractError("equity target requires decision scope and allocation fraction one")
        if (not cash.is_finite() or cash < 0
                or type(actual) is not int or actual < 0 or actual % lot):
            raise RuntimeContractError("equity target requires non-negative cash and whole-lot position")
        if not isfinite(request.quote_reference) or request.quote_reference <= 0:
            raise RuntimeContractError("equity target requires a positive finite reference price")
        fee_value = Decimal(str(capital["fee_rate"]))
        if not fee_value.is_finite() or not 0 <= fee_value < 1:
            raise RuntimeContractError("equity target fee rate must be in [0, 1)")
    elif request.target_position not in (0.0, 1.0):
        raise RuntimeContractError(
            "FROZEN_RULE requires a binary target position"
        )
    # Keep endpoint serialization stable; fractional targets must never be truncated.
    target_position = (int(request.target_position) if request.target_position in (0.0, 1.0)
                       else float(request.target_position))
    execution_reference_price = request.quote_reference
    desired = 0
    if equity_target:
        # Size against the same causal price basis as the actual account holdings.
        # Fees, lots, limit execution and price movement can prevent exact weights.
        reference = Decimal(str(execution_reference_price)) * Decimal(str(request.price_scale))
        equity = cash + Decimal(actual) * reference
        desired = int((equity * Decimal(str(target_position)) / (reference * lot))
                      .to_integral_value(rounding=ROUND_FLOOR)) * lot
    orders: list[dict[str, object]] = []
    if (equity_target and desired >= actual) or (not equity_target and target_position):
        requested = _round_tick(
            execution_reference_price * (1 + float(entry["limit_parameter"])),
            tick,
            "floor",
        )
        upper_guard = _round_tick(
            _round_tick(
                execution_reference_price * (1 + float(instrument["price_limit_ratio"])),
                tick,
                "floor",
            )
            - tick,
            tick,
            "half_up",
        )
        price = min(requested, upper_guard) * request.price_scale
        allocation = Decimal(str(capital.get("allocation_fraction", 1.0)))
        unit_cost = Decimal(str(price)) * (1 + Decimal(str(capital["fee_rate"])))
        affordable = actual + int(
            (cash * allocation / (unit_cost * lot)).to_integral_value(rounding=ROUND_FLOOR)
        ) * lot
        previous_cycle = request.deployment_settings.get("cycle_target_quantity")
        cycle_target = desired if equity_target else (affordable if previous_cycle is None else int(previous_cycle))
        target = min(cycle_target, affordable)
        delta = max(0, target - actual)
        action = "BUY" if delta else ("HOLD" if actual else "WAIT")
        side = "BUY"
        order_type = effective_target_order_type(settings, "BUY")
    else:
        order_type = effective_target_order_type(settings, "SELL")
        limit_ratio = float(exit_rule["limit_ratio"])
        lower_guard = _round_tick(
            _round_tick(execution_reference_price * (1 - limit_ratio), tick, "ceil") + tick,
            tick,
            "half_up",
        )
        price = (
            _round_tick(execution_reference_price, tick, "half_up")
            if order_type == "MARKET"
            else lower_guard
        ) * request.price_scale
        target = desired if equity_target else 0
        delta = target - actual
        action = "SELL" if delta else ("HOLD" if actual else "WAIT")
        previous_cycle = request.deployment_settings.get("cycle_target_quantity")
        cycle_target = desired if equity_target else (0 if not actual else int(previous_cycle or actual))
        side = "SELL"
    remaining = abs(delta)
    maximum = int(instrument["maximum_order_quantity"])
    while remaining:
        quantity = min(remaining, maximum)
        orders.append(
            {
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "limit_price": price,
                "time_in_force": "DAY",
            }
        )
        remaining -= quantity
    fee = Decimal(str(capital["fee_rate"]))
    estimated = sum(
        (
            Decimal(order["quantity"])
            * Decimal(str(order["limit_price"]))
            * (1 + fee)
            for order in orders
            if order["side"] == "BUY"
        ),
        Decimal("0"),
    )
    return {
        "contract_version": "advice.v4",
        "actual_quantity": actual,
        "cycle_target_quantity": cycle_target,
        "target_quantity": target,
        "delta_quantity": delta,
        "target_position": target_position,
        "action": action,
        "order": orders[0] if len(orders) == 1 else None,
        "orders": orders,
        "available_cash": float(cash),
        "fee_rate": float(fee),
        "estimated_order_cost": float(estimated.quantize(Decimal("0.01"))),
        "unallocated_cash": float((cash - estimated).quantize(Decimal("0.01"))),
        "capital_rule": {
            "mode": capital["mode"],
            "allocation_fraction": float(capital.get("allocation_fraction", 1.0)),
            "target_scope": capital["target_scope"],
        },
    }


def _signal_cash_plan(request: ExecutionRuleInput) -> dict[str, Any]:
    """Propose a budget/quantity lock; only the account host may adopt it."""
    target, previous = request.cycle_target, request.entry_cycle
    if not isinstance(target, CycleTarget) or request.target_position not in (0., 1.) or bool(request.target_position) != target.active:
        raise RuntimeContractError("signal cash fraction requires matching typed binary cycle target")
    capital = request.settings["capital"]
    if capital.get("target_scope") != "entry_cycle" or "allocation_fraction" in capital:
        raise RuntimeContractError("signal cash fraction requires signal-owned entry allocation")
    if not request.account_id or not request.opening_signal_identity:
        raise RuntimeContractError("entry cycle requires account and signal identities")
    cash = Decimal(str(request.available_cash))
    fee = Decimal(str(capital["fee_rate"]))
    actual = request.position_quantity
    if not cash.is_finite() or cash < 0 or not fee.is_finite() or not 0 <= fee < 1:
        raise RuntimeContractError("invalid cycle cash or fee")
    if type(actual) is not int or actual < 0 or actual % 100:
        raise RuntimeContractError("invalid cycle position quantity")
    if previous is not None and not isinstance(previous, EntryCycleState):
        raise RuntimeContractError("entry cycle state requires typed facts")
    old_quantity = request.deployment_settings.get("cycle_target_quantity")
    if previous is None:
        if actual or old_quantity is not None:
            raise RuntimeContractError("new entry allocation requires flat account without legacy cycle")
    elif old_quantity != previous.target_quantity or actual > previous.target_quantity:
        raise RuntimeContractError("account quantity differs from entry cycle")

    settings = {**request.settings, "capital": {**capital, "mode": "available_cash_fraction", "allocation_fraction": 1.}}
    after = previous
    status = EntryCyclePlanStatus.IDLE
    if previous is None and target.active:
        budget = cash * target.entry_fraction
        probe = _target_plan(replace(request, settings=settings, available_cash=budget))
        quantity = int(probe["cycle_target_quantity"])
        if quantity:
            after = EntryCycleState(
                canonical_sha256({"account": request.account_id, "opening_signal": request.opening_signal_identity}),
                request.opening_signal_identity, target.entry_fraction, budget, quantity,
                Decimal(0), EntryCyclePhase.ACTIVE)
            status = EntryCyclePlanStatus.OPEN
        else:
            status = EntryCyclePlanStatus.INSUFFICIENT_LOT
    elif previous is not None:
        status = EntryCyclePlanStatus.HOLD
        if not target.active or previous.phase is EntryCyclePhase.EXITING:
            after = replace(previous, phase=EntryCyclePhase.EXITING)
            status = EntryCyclePlanStatus.EXIT

    effective = bool(after is not None and after.phase is EntryCyclePhase.ACTIVE)
    budget_cash = min(cash, after.remaining_budget) if effective else cash
    raw = _target_plan(replace(
        request, settings=settings, available_cash=budget_cash,
        target_position=float(effective),
        deployment_settings={"cycle_target_quantity": None if after is None else after.target_quantity}))
    raw["cycle_target_quantity"] = 0 if after is None else after.target_quantity
    if effective and not raw["orders"] and actual < after.target_quantity:
        status = EntryCyclePlanStatus.BUDGET_LIMIT
    fraction = after.allocation_fraction if after is not None else (target.entry_fraction or Decimal(1))
    raw.update(
        target_position=request.target_position, available_cash=float(cash),
        unallocated_cash=float((cash - Decimal(str(raw["estimated_order_cost"]))).quantize(Decimal(".01"))),
        capital_rule={"mode": "signal_cash_fraction", "target_scope": "entry_cycle", "allocation_fraction": str(fraction)},
        cycle_target=target, entry_cycle_before=previous, entry_cycle_after=after, cycle_status=status)
    return raw


def _intraday_overlay_plan(
    request: ExecutionRuleInput,
) -> dict[str, Any]:
    settings = dict(request.settings)
    actual = request.position_quantity
    cash = Decimal(str(request.available_cash))
    lot = int(settings["lot_size"])
    fee = Decimal(str(settings["one_way_cost"]))
    buy_limit = Decimal(
        str(_round_tick(request.quote_reference * 1.10, 0.001, "floor") * request.price_scale)
    )

    def affordable(budget: Decimal) -> int:
        raw = int(budget / (buy_limit * (1 + fee)))
        return raw // lot * lot

    previous_cycle = request.deployment_settings.get("cycle_target_quantity")
    plan_mode = "NONE"
    action = "HOLD"
    target = actual
    cycle_target = int(previous_cycle or 0)
    reserve = Decimal("0")
    legs: list[dict[str, object]] = []
    if previous_cycle is None:
        if actual:
            raise RuntimeContractError("intraday overlay core identity is missing")
        target = affordable(cash * Decimal(str(settings["core_fraction"])))
        if target <= 0:
            raise RuntimeContractError("intraday overlay cannot afford one core lot")
        cycle_target = target
        action = "BUY"
        plan_mode = "CORE_SETUP"
        reserve = buy_limit * target * (1 + fee)
        legs = [{
            "sequence": 0,
            "role": "CORE_SETUP",
            "checkpoint": "OPEN",
            "submit_after": "09:30:00",
            "submit_before": "09:35:00",
            "dependency_sequence": None,
            "dependency_required_status": None,
            "order": {"side": "BUY", "quantity": target, "order_type": "LIMIT", "limit_price": float(buy_limit), "time_in_force": "DAY"},
        }]
    else:
        if actual != int(previous_cycle):
            raise RuntimeContractError("intraday overlay account differs from core quantity")
        if request.target_position > 0:
            event_quantity = min(int(previous_cycle), affordable(cash))
            if event_quantity <= 0:
                raise RuntimeContractError("intraday overlay cannot afford one event lot")
            action = "ROTATE"
            plan_mode = "CORE_EVENT_INTRADAY_ROTATION"
            reserve = buy_limit * event_quantity * (1 + fee)
            legs = [
                {
                    "sequence": 0,
                    "role": "ROTATION_ENTRY",
                    "checkpoint": "OPEN",
                    "submit_after": "09:30:00",
                    "submit_before": "09:35:00",
                    "dependency_sequence": None,
                    "dependency_required_status": None,
                    "order": {"side": "BUY", "quantity": event_quantity, "order_type": "LIMIT", "limit_price": float(buy_limit), "time_in_force": "DAY"},
                },
                {
                    "sequence": 1,
                    "role": "ROTATION_EXIT",
                    "checkpoint": "11:30_CLOSE",
                    "submit_after": "11:29:00",
                    "submit_before": "11:30:00",
                    "dependency_sequence": 0,
                    "dependency_required_status": "FILLED_ALL",
                    "order": {"side": "SELL", "quantity": event_quantity, "order_type": "MARKET", "limit_price": request.execution_reference_price, "time_in_force": "DAY"},
                },
            ]
    return {
        "contract_version": "advice.v5",
        "actual_quantity": actual,
        "cycle_target_quantity": cycle_target,
        "target_quantity": target,
        "delta_quantity": target - actual,
        "target_position": request.target_position,
        "action": action,
        "order": None,
        "orders": [],
        "available_cash": float(cash),
        "fee_rate": float(fee),
        "estimated_order_cost": float(reserve.quantize(Decimal("0.0001"))),
        "unallocated_cash": float((cash - reserve).quantize(Decimal("0.0001"))),
        "plan_mode": plan_mode,
        "plan_legs": legs,
    }


def build_frozen_execution_plan(request: ExecutionRuleInput) -> Mapping[str, Any]:
    """Apply one frozen execution rule to already selected SRT facts."""

    planners = {
        "FROZEN_RULE": _target_plan,
        "INTRADAY_OVERLAY": _intraday_overlay_plan,
    }
    try:
        planner = planners[request.policy_type]
    except KeyError as exc:
        raise RuntimeContractError(
            f"unsupported execution policy: {request.policy_type}"
        ) from exc
    return planner(request)
