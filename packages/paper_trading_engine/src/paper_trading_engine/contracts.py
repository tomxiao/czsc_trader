"""Stable values crossing the strategy and runtime process boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
import math
import re
from typing import Any

from strategy_runtime import StrategyObservation, ObservationUnavailable


class AdviceContractError(ValueError):
    """The strategy CLI emitted a payload PTE cannot execute safely."""


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdviceContractError(f"{name} must be an object")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdviceContractError(f"{name} must be an integer")
    return value


def _finite_number(value: object, name: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdviceContractError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or (number < 0 if nonnegative else number <= 0):
        qualifier = "non-negative" if nonnegative else "positive"
        raise AdviceContractError(f"{name} must be {qualifier} and finite")
    return number


@dataclass(frozen=True)
class OrderSpec:
    side: str
    quantity: int
    order_type: str
    limit_price: float
    time_in_force: str

    @classmethod
    def from_payload(cls, payload: object) -> "OrderSpec":
        value = _object(payload, "order")
        price = value.get("limit_price")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise AdviceContractError("order limit price must be numeric")
        price = float(price)
        if not math.isfinite(price) or price <= 0:
            raise AdviceContractError("order limit price must be positive and finite")
        quantity = _integer(value.get("quantity"), "order quantity")
        if quantity <= 0 or quantity % 100:
            raise AdviceContractError("order quantity must use positive 100-share lots")
        side = str(value.get("side", ""))
        if side not in {"BUY", "SELL"}:
            raise AdviceContractError("order side must be BUY or SELL")
        order_type = str(value.get("order_type", ""))
        if order_type not in {"LIMIT", "MARKET"}:
            raise AdviceContractError("order type must be LIMIT or MARKET")
        if side == "BUY" and order_type != "LIMIT":
            raise AdviceContractError("buy orders must use LIMIT")
        if side == "SELL" and order_type not in {"LIMIT", "MARKET"}:
            raise AdviceContractError("sell orders must use LIMIT or MARKET")
        if value.get("time_in_force") != "DAY":
            raise AdviceContractError("order time in force must be DAY")
        return cls(side, quantity, order_type, price, "DAY")


@dataclass(frozen=True)
class PlanLegSpec:
    sequence: int
    role: str
    checkpoint: str
    submit_after: time
    submit_before: time
    dependency_sequence: int | None
    dependency_required_status: str | None
    order: OrderSpec

    @classmethod
    def from_payload(cls, payload: object) -> "PlanLegSpec":
        value = _object(payload, "execution plan leg")
        sequence = _integer(value.get("sequence"), "execution plan leg sequence")
        if sequence < 0:
            raise AdviceContractError("execution plan leg sequence must be non-negative")
        role = str(value.get("role", ""))
        checkpoint = str(value.get("checkpoint", ""))
        allowed = {
            "CORE_SETUP": "OPEN",
            "ROTATION_ENTRY": "OPEN",
            "ROTATION_EXIT": "11:30_CLOSE",
        }
        if role not in allowed or checkpoint != allowed[role]:
            raise AdviceContractError("execution plan leg role or checkpoint is invalid")
        try:
            submit_after = time.fromisoformat(str(value["submit_after"]))
            submit_before = time.fromisoformat(str(value["submit_before"]))
        except (KeyError, ValueError) as exc:
            raise AdviceContractError("execution plan times must use ISO format") from exc
        if submit_after >= submit_before:
            raise AdviceContractError("execution plan submission window is empty")
        dependency = value.get("dependency_sequence")
        if dependency is not None:
            dependency = _integer(dependency, "execution plan dependency sequence")
            if dependency < 0 or dependency >= sequence:
                raise AdviceContractError("execution plan dependency must reference an earlier leg")
        required_status = value.get("dependency_required_status")
        required_status = None if required_status is None else str(required_status)
        if (dependency is None) != (required_status is None):
            raise AdviceContractError("execution plan dependency status is incomplete")
        if required_status not in {None, "FILLED_ALL"}:
            raise AdviceContractError("execution plan dependency must require FILLED_ALL")
        order = OrderSpec.from_payload(value.get("order"))
        if role in {"CORE_SETUP", "ROTATION_ENTRY"} and order.side != "BUY":
            raise AdviceContractError("entry execution plan legs must buy")
        if role == "ROTATION_EXIT" and order.side != "SELL":
            raise AdviceContractError("exit execution plan leg must sell")
        return cls(
            sequence, role, checkpoint, submit_after, submit_before,
            dependency, required_status, order,
        )


@dataclass(frozen=True)
class AdviceDecision:
    contract_version: str
    decision_id: str
    symbol: str
    signal_date: date
    valid_session: date
    actual_quantity: int
    target_quantity: int
    cycle_target_quantity: int
    delta_quantity: int
    action: str
    strategy: dict[str, str]
    signal_reference_price: float
    execution_reference_price: float
    data_cutoff: date
    order: OrderSpec | None
    signal_identity: str
    plan_identity: str
    portfolio_revision: int
    state_revision: int
    orders: tuple[OrderSpec, ...] = ()
    available_cash: float = 0.0
    fee_rate: float = 0.0
    estimated_order_cost: float = 0.0
    unallocated_cash: float = 0.0
    capital_mode: str = "full_available_cash"
    allocation_fraction: float = 1.0
    source_decision_id: str = ""
    plan_mode: str = "NONE"
    plan_legs: tuple[PlanLegSpec, ...] = ()
    runtime_sha256: str = ""
    input_identity_hashes: dict[str, str] | None = None
    strategy_output: dict[str, Any] | None = None
    observation: dict[str, Any] | None = None

    @classmethod
    def from_cli_payload(cls, payload: object) -> "AdviceDecision":
        outer = _object(payload, "CLI payload")
        if outer.get("status") != "PASS":
            raise AdviceContractError("advice command failed")
        value = _object(outer.get("result"), "result")
        version = str(value.get("contract_version", ""))
        if version not in {"advice.v4", "advice.v5"}:
            raise AdviceContractError(f"unsupported advice contract version: {version}")
        try:
            signal_date = date.fromisoformat(str(value["signal_date"]))
            valid_session = date.fromisoformat(str(value["valid_session"]))
            data_cutoff = date.fromisoformat(str(value["data_cutoff"]))
        except (KeyError, ValueError) as exc:
            raise AdviceContractError("advice dates must use ISO format") from exc
        actual = _integer(value.get("actual_quantity"), "actual quantity")
        target = _integer(value.get("target_quantity"), "target quantity")
        cycle_target = _integer(value.get("cycle_target_quantity"), "cycle target quantity")
        delta = _integer(value.get("delta_quantity"), "delta quantity")
        if actual < 0 or target < 0 or cycle_target < 0 or any(q % 100 for q in (actual, target, cycle_target)):
            raise AdviceContractError("advice quantities must use non-negative 100-share lots")
        if target - actual != delta:
            raise AdviceContractError("delta quantity does not match target minus actual")
        order_payload = value.get("order")
        order = None if order_payload is None else OrderSpec.from_payload(order_payload)
        orders_value = value.get("orders")
        if not isinstance(orders_value, list):
            raise AdviceContractError("orders must be a list")
        orders = tuple(OrderSpec.from_payload(item) for item in orders_value)
        action = str(value.get("action", ""))
        plan_mode = str(value.get("plan_mode", "NONE"))
        plan_value = value.get("plan_legs", [])
        if not isinstance(plan_value, list):
            raise AdviceContractError("plan_legs must be a list")
        plan_legs = tuple(PlanLegSpec.from_payload(item) for item in plan_value)
        if tuple(item.sequence for item in plan_legs) != tuple(range(len(plan_legs))):
            raise AdviceContractError("execution plan leg sequences must be contiguous")
        if version == "advice.v4":
            if plan_mode != "NONE" or plan_legs:
                raise AdviceContractError("advice.v4 cannot contain an execution plan")
            if (delta == 0) != (len(orders) == 0):
                raise AdviceContractError("orders presence does not match quantity delta")
            if orders:
                expected_side = "BUY" if delta > 0 else "SELL"
                if any(item.side != expected_side for item in orders) or sum(item.quantity for item in orders) != abs(delta) or action != expected_side:
                    raise AdviceContractError("order does not match action and quantity delta")
            if (len(orders) == 1 and order != orders[0]) or (len(orders) != 1 and order is not None):
                raise AdviceContractError("order shortcut does not match orders")
        else:
            if orders or order is not None:
                raise AdviceContractError("advice.v5 planned decisions cannot contain immediate orders")
            if plan_mode == "NONE":
                if plan_legs or action not in {"HOLD", "WAIT"} or delta != 0:
                    raise AdviceContractError("empty execution plan must be a zero-delta hold")
            elif plan_mode == "CORE_SETUP":
                if (
                    action != "BUY" or delta <= 0 or len(plan_legs) != 1
                    or plan_legs[0].role != "CORE_SETUP"
                    or plan_legs[0].order.quantity != delta
                    or plan_legs[0].dependency_sequence is not None
                ):
                    raise AdviceContractError("core setup execution plan is inconsistent")
            elif plan_mode == "CORE_EVENT_INTRADAY_ROTATION":
                if (
                    action != "ROTATE" or delta != 0 or len(plan_legs) != 2
                    or tuple(item.role for item in plan_legs)
                    != ("ROTATION_ENTRY", "ROTATION_EXIT")
                    or plan_legs[1].dependency_sequence != 0
                    or plan_legs[1].dependency_required_status != "FILLED_ALL"
                    or plan_legs[0].order.quantity != plan_legs[1].order.quantity
                ):
                    raise AdviceContractError("intraday rotation execution plan is inconsistent")
            else:
                raise AdviceContractError("unsupported execution plan mode")
        strategy = _object(value.get("strategy"), "strategy")
        expected_strategy_fields = {
            "strategy_id",
            "name",
            "version",
            "release_id",
            "release_hash",
            "qualification",
        }
        if set(strategy) != expected_strategy_fields:
            raise AdviceContractError("strategy identity fields are incomplete")
        strategy_id = str(strategy["strategy_id"])
        strategy_version = str(strategy["version"])
        release_hash = str(strategy["release_hash"])
        if re.fullmatch(r"S[0-9]{3}", strategy_id) is None:
            raise AdviceContractError("strategy id has invalid format")
        if re.fullmatch(r"v[1-9][0-9]*", strategy_version) is None:
            raise AdviceContractError("strategy version has invalid format")
        if strategy["release_id"] != f"{strategy_id}-{strategy_version}":
            raise AdviceContractError("strategy release id is inconsistent")
        if re.fullmatch(r"[0-9a-f]{64}", release_hash) is None:
            raise AdviceContractError("strategy release hash has invalid format")
        if strategy["qualification"] not in {"PAPER_READY", "LIVE_READY"}:
            raise AdviceContractError("strategy qualification does not permit paper trading")
        if not str(strategy["name"]).strip():
            raise AdviceContractError("strategy name is required")
        signal_reference = _finite_number(
            value.get("signal_reference_price"), "signal reference price"
        )
        execution_reference = _finite_number(
            value.get("execution_reference_price"), "execution reference price"
        )
        available_cash = _finite_number(
            value.get("available_cash"), "available cash", nonnegative=True
        )
        fee_rate = _finite_number(value.get("fee_rate"), "fee rate", nonnegative=True)
        estimated_cost = _finite_number(
            value.get("estimated_order_cost", 0.0), "estimated order cost", nonnegative=True
        )
        unallocated_cash = _finite_number(
            value.get("unallocated_cash", available_cash),
            "unallocated cash", nonnegative=True,
        )
        capital_value = value.get(
            "capital_rule",
            {
                "mode": "full_available_cash",
                "allocation_fraction": 1.0,
                "target_scope": "entry_cycle",
            },
        )
        capital_rule = _object(capital_value, "capital rule")
        capital_mode = str(capital_rule.get("mode", ""))
        allocation_fraction = _finite_number(
            capital_rule.get("allocation_fraction"),
            "allocation fraction",
            nonnegative=True,
        )
        if capital_mode not in {"full_available_cash", "available_cash_fraction"}:
            raise AdviceContractError("capital mode is unsupported")
        if not 0 < allocation_fraction <= 1:
            raise AdviceContractError("allocation fraction must be in (0, 1]")
        if capital_rule.get("target_scope") != "entry_cycle":
            raise AdviceContractError("capital target scope is unsupported")
        if capital_mode == "full_available_cash" and allocation_fraction != 1.0:
            raise AdviceContractError("full cash mode requires allocation fraction one")
        if valid_session <= signal_date:
            raise AdviceContractError("valid session must be after signal date")
        if data_cutoff != signal_date:
            raise AdviceContractError("data cutoff must equal signal date")
        if not str(value.get("decision_id", "")).strip():
            raise AdviceContractError("decision id is required")
        signal_identity = str(value.get("signal_identity", ""))
        plan_identity = str(value.get("plan_identity", ""))
        if re.fullmatch(r"[0-9a-f]{64}", signal_identity) is None:
            raise AdviceContractError("signal identity has invalid format")
        if re.fullmatch(r"[0-9a-f]{64}", plan_identity) is None:
            raise AdviceContractError("plan identity has invalid format")
        portfolio_revision = _integer(
            value.get("portfolio_revision"), "portfolio revision"
        )
        state_revision = _integer(value.get("state_revision"), "state revision")
        if portfolio_revision < 0 or state_revision < 0:
            raise AdviceContractError("decision revisions must be non-negative")
        runtime_sha256 = str(value.get("runtime_sha256", ""))
        input_identities_value = value.get("input_identity_hashes", {})
        input_identities = _object(input_identities_value, "input identity hashes")
        if runtime_sha256 and re.fullmatch(r"[0-9a-f]{64}", runtime_sha256) is None:
            raise AdviceContractError("runtime sha256 has invalid format")
        if any(
            not isinstance(name, str)
            or re.fullmatch(r"[0-9a-f]{64}", str(identity)) is None
            for name, identity in input_identities.items()
        ):
            raise AdviceContractError("input identity hash has invalid format")
        strategy_output = _object(value.get("strategy_output"), "strategy output")
        try:
            raw_observation = value.get("observation")
            if isinstance(raw_observation, dict) and raw_observation.get('status') == 'UNAVAILABLE':
                observation = ObservationUnavailable.from_dict(raw_observation).to_dict()
            else:
                fact = StrategyObservation.from_dict(raw_observation)
                if (fact.strategy.reference_id != strategy['release_id'] or
                    fact.strategy.release_hash != release_hash or fact.strategy.symbol != value['symbol'] or
                    fact.strategy.runtime_sha256 != runtime_sha256 or fact.action != value['action'] or
                    fact.strategy.strategy_id != strategy['strategy_id'] or
                    fact.signal_identity != value['signal_identity'] or fact.plan_identity != value['plan_identity'] or
                    fact.signal_date.isoformat() != value['signal_date'] or fact.valid_session.isoformat() != value['valid_session']):
                    raise AdviceContractError('observation belongs to another decision')
                observation = fact.to_dict()
        except ValueError as exc:
            raise AdviceContractError(str(exc)) from exc
        if re.fullmatch(r"[0-9]{6}\.(SH|SZ)", str(value.get("symbol", "")).upper()) is None:
            raise AdviceContractError("advice symbol has invalid format")
        return cls(
            contract_version=version,
            decision_id=str(value.get("decision_id", "")),
            symbol=str(value.get("symbol", "")).upper(),
            signal_date=signal_date,
            valid_session=valid_session,
            actual_quantity=actual,
            target_quantity=target,
            cycle_target_quantity=cycle_target,
            delta_quantity=delta,
            action=action,
            strategy={key: str(strategy[key]) for key in expected_strategy_fields},
            signal_reference_price=signal_reference,
            execution_reference_price=execution_reference,
            data_cutoff=data_cutoff,
            order=order,
            signal_identity=signal_identity,
            plan_identity=plan_identity,
            portfolio_revision=portfolio_revision,
            state_revision=state_revision,
            orders=orders,
            available_cash=available_cash,
            fee_rate=fee_rate,
            estimated_order_cost=estimated_cost,
            unallocated_cash=unallocated_cash,
            capital_mode=capital_mode,
            allocation_fraction=allocation_fraction,
            source_decision_id=str(
                value.get("source_decision_id") or value.get("decision_id", "")
            ),
            plan_mode=plan_mode,
            plan_legs=plan_legs,
            runtime_sha256=runtime_sha256,
            input_identity_hashes={
                str(name): str(identity) for name, identity in input_identities.items()
            },
            strategy_output=dict(strategy_output),
            observation=observation,
        )
