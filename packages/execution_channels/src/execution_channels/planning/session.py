"""Execution channel session planner from validated runtime facts to frozen execution rules."""

from __future__ import annotations

from typing import Any, Mapping

from .session_rules import ExecutionRuleInput, build_frozen_execution_plan
from ..policy import ExecutionPolicy
from ..entry_cycle import CycleTarget, EntryCycleState


from dataclasses import dataclass
import math
from datetime import date, time
from decimal import Decimal
from types import MappingProxyType
from ..identity import freeze
from ..errors import RuntimeContractError
from ..session_contracts import (StrategyIdentity, TradingPoint, PriceReference, PortfolioSnapshot,
    ExecutionState, ExecutionPlan, ExecutionCapabilities, PlanLeg, PlannedOrder, OrderType, OrderSide,
    signal_identity_for, plan_identity_for)

def build_execution_plan(
    *,
    deployment_settings: Mapping[str, object],
    available_cash: float,
    position_quantity: int,
    target_position: float,
    policy: ExecutionPolicy,
    signal_reference_price: float,
    execution_reference_price: float,
    cycle_target: CycleTarget | None = None,
    entry_cycle: EntryCycleState | None = None,
    opening_signal_identity: str | None = None,
    account_id: str | None = None,
) -> Mapping[str, Any]:
    """Build the concrete order plan carried by an execution instruction."""

    return build_frozen_execution_plan(
        ExecutionRuleInput(
            policy_type=policy.policy_type,
            settings=policy.settings,
            deployment_settings=deployment_settings,
            available_cash=available_cash,
            position_quantity=position_quantity,
            target_position=target_position,
            signal_reference_price=signal_reference_price,
            execution_reference_price=execution_reference_price,
            cycle_target=cycle_target, entry_cycle=entry_cycle,
            opening_signal_identity=opening_signal_identity, account_id=account_id,
        )
    )


@dataclass(frozen=True, slots=True)
class SessionProposal:
    strategy: StrategyIdentity
    point: TradingPoint
    signal_date: date
    signal_identity: str
    target_position: float
    cycle_target: CycleTarget | None
    evidence: Mapping[str, Any]
    references: PriceReference
    input_identities: Mapping[str, str]
    price_identities: Mapping[str, str]
    execution_policy: ExecutionPolicy

    def __post_init__(self):
        for name, expected in (('strategy',StrategyIdentity),('point',TradingPoint),('signal_date',date),
                ('references',PriceReference),('execution_policy',ExecutionPolicy)):
            if type(getattr(self,name)) is not expected:
                raise TypeError('session proposal requires typed '+name)
        if self.cycle_target is not None and type(self.cycle_target) is not CycleTarget:
            raise TypeError('session proposal requires typed cycle target')
        if (type(self.target_position) not in (int,float)
                or not math.isfinite(self.target_position) or not 0 <= self.target_position <= 1):
            raise ValueError('session proposal target must be finite in [0,1]')
        for name in ('evidence','input_identities','price_identities'):
            object.__setattr__(self,name,freeze(getattr(self,name)))
        expected = signal_identity_for(strategy=self.strategy,signal_date=self.signal_date,
            target_position=self.target_position,input_identities=self.input_identities,
            price_identities=self.price_identities,cycle_target=self.cycle_target)
        if self.signal_identity != expected:
            raise ValueError('session proposal signal identity differs from facts')


def plan_session_decision(proposal: SessionProposal, portfolio: PortfolioSnapshot,
                          state: ExecutionState) -> ExecutionPlan:
    """Size and construct the session order plan from supplied strategy facts."""
    if (type(proposal) is not SessionProposal or type(portfolio) is not PortfolioSnapshot
            or type(state) is not ExecutionState):
        raise TypeError('session planning requires channel-owned proposal and snapshots')
    if portfolio.pricing != proposal.references.pricing:
        raise RuntimeContractError('portfolio price and quantity units differ from strategy')
    if portfolio.symbol != proposal.strategy.symbol:
        raise RuntimeContractError('portfolio symbol differs from strategy')
    if portfolio.as_of > proposal.point.calculation_time or state.as_of > proposal.point.calculation_time:
        raise RuntimeContractError('planning state is newer than calculation time')
    if proposal.cycle_target is None and state.entry_cycle is not None:
        raise RuntimeContractError('entry allocation state cannot be consumed by another capital mode')
    point, signal_date = proposal.point, proposal.signal_date
    references, signal_identity = proposal.references, proposal.signal_identity
    raw = dict(
        build_execution_plan(
            deployment_settings={"cycle_target_quantity": state.cycle_target_quantity},
            available_cash=(portfolio.available_cash if proposal.cycle_target is not None
                            else float(portfolio.available_cash)),
            position_quantity=portfolio.position_quantity,
            target_position=proposal.target_position,
            policy=proposal.execution_policy,
            signal_reference_price=float(references.signal_price),
            execution_reference_price=float(references.execution_price),
            cycle_target=proposal.cycle_target, entry_cycle=state.entry_cycle,
            opening_signal_identity=signal_identity, account_id=portfolio.account_id,
        )
    )
    orders = tuple(_planned_order(value) for value in raw.get("orders", ()))
    legs = tuple(
        PlanLeg(
            sequence=int(value["sequence"]),
            role=str(value["role"]),
            checkpoint=str(value["checkpoint"]),
            submit_after=_parse_time(value["submit_after"], "submit_after"),
            submit_before=_parse_time(value["submit_before"], "submit_before"),
            dependency_sequence=(
                None
                if value.get("dependency_sequence") is None
                else int(value["dependency_sequence"])
            ),
            dependency_required_status=(
                None
                if value.get("dependency_required_status") is None
                else str(value["dependency_required_status"])
            ),
            order=_planned_order(dict(value["order"])),
        )
        for value in raw.get("plan_legs", ())
    )
    required_orders = tuple(
        sorted(
            {order.order_type for order in orders} | {leg.order.order_type for leg in legs},
            key=lambda value: value.value,
        )
    )
    required_checkpoints = tuple(sorted({leg.checkpoint for leg in legs}))
    cycle_target = int(raw["cycle_target_quantity"])
    target_quantity = int(raw["target_quantity"])
    plan_mode = str(raw.get("plan_mode", "NONE"))
    capital_mode, allocation_fraction = _capital_terms(
        raw=raw,
        execution_policy=proposal.execution_policy,
    )
    cycle_facts = {name: raw.get(name) for name in (
        "cycle_target", "entry_cycle_before", "entry_cycle_after", "cycle_status")}
    plan_identity = plan_identity_for(
        signal_identity=signal_identity,
        actual_quantity=portfolio.position_quantity,
        target_quantity=target_quantity,
        cycle_target_quantity=cycle_target,
        plan_mode=plan_mode,
        capital_mode=capital_mode,
        allocation_fraction=allocation_fraction,
        orders=orders,
        legs=legs,
        **cycle_facts,
        available_cash=portfolio.available_cash, fee_rate=Decimal(str(raw["fee_rate"])),
    )
    return ExecutionPlan(
        strategy=proposal.strategy,
        signal_identity=signal_identity,
        plan_identity=plan_identity,
        symbol=proposal.strategy.symbol,
        signal_date=signal_date,
        trading_date=point.trading_date,
        generated_at=point.calculation_time,
        expected_portfolio_revision=portfolio.revision,
        expected_state_revision=state.revision,
        actual_quantity=portfolio.position_quantity,
        target_quantity=target_quantity,
        cycle_target_quantity=cycle_target,
        target_position=proposal.target_position,
        action=str(raw["action"]),
        plan_mode=plan_mode,
        capital_mode=capital_mode,
        allocation_fraction=allocation_fraction,
        orders=orders,
        legs=legs,
        available_cash=portfolio.available_cash,
        fee_rate=Decimal(str(raw["fee_rate"])),
        estimated_order_cost=Decimal(str(raw["estimated_order_cost"])),
        unallocated_cash=Decimal(str(raw["unallocated_cash"])),
        references=references,
        required_capabilities=ExecutionCapabilities(
            required_orders,
            required_checkpoints,
        ),
        input_identities=proposal.input_identities,
        price_identities=proposal.price_identities,
        evidence=MappingProxyType(dict(proposal.evidence)),
        **cycle_facts,
    )

def _planned_order(value: dict[str, object]) -> PlannedOrder:
    order_type = OrderType(str(value["order_type"]).upper())
    raw_price = value.get("limit_price")
    return PlannedOrder(
        side=OrderSide(str(value["side"]).upper()),
        quantity=int(value["quantity"]),
        order_type=order_type,
        limit_price=None if raw_price is None else Decimal(str(raw_price)),
    )

def _parse_time(value: object, name: str) -> time:
    try:
        return time.fromisoformat(str(value))
    except ValueError as exc:
        raise RuntimeContractError(f"{name} must use ISO local time") from exc

def _capital_terms(
    *, raw: dict[str, object], execution_policy: ExecutionPolicy
) -> tuple[str, Decimal]:
    """Map one policy-specific planner result to the public plan capital terms."""

    policy_type = str(execution_policy.policy_type)
    if policy_type == "FROZEN_RULE":
        capital_rule = dict(raw["capital_rule"])
        return (
            str(capital_rule["mode"]),
            Decimal(str(capital_rule["allocation_fraction"])),
        )
    if policy_type == "INTRADAY_OVERLAY":
        plan_mode = str(raw.get("plan_mode", "NONE"))
        if plan_mode == "CORE_SETUP":
            return (
                "available_cash_fraction",
                Decimal(str(execution_policy.settings["core_fraction"])),
            )
        if plan_mode in {"NONE", "CORE_EVENT_INTRADAY_ROTATION"}:
            return "full_available_cash", Decimal("1")
        raise RuntimeContractError(f"unsupported intraday overlay plan mode: {plan_mode}")
    raise RuntimeContractError(f"unsupported execution policy: {policy_type}")
