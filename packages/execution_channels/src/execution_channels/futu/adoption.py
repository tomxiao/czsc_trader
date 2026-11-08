"""Atomic channel adoption of an approved decision and its resource reservations."""
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
import json
import math

from .audit import AuditRecorder
from .store import PaperStore


@dataclass(frozen=True, slots=True)
class AdoptionOrder:
    side: str
    quantity: int
    order_type: str
    limit_price: float
    time_in_force: str

    def __post_init__(self):
        if self.side not in {"BUY", "SELL"} or self.order_type not in {"LIMIT", "MARKET"} or self.time_in_force != "DAY":
            raise ValueError("invalid adopted order policy")
        if type(self.quantity) is not int or self.quantity <= 0 or not math.isfinite(self.limit_price) or self.limit_price <= 0:
            raise ValueError("invalid adopted order quantity or price")


@dataclass(frozen=True, slots=True)
class AdoptionLeg:
    sequence: int
    role: str
    checkpoint: str
    submit_after: datetime | time
    submit_before: datetime | time
    dependency_sequence: int | None
    dependency_required_status: str | None
    order: AdoptionOrder


@dataclass(frozen=True, slots=True)
class DecisionAdoption:
    """Immutable JSON decision facts validated again by the owning account ledger."""
    account_id: str
    document: bytes
    previous_action: str | None = None

    def __post_init__(self):
        if type(self.account_id) is not str or not self.account_id or type(self.document) is not bytes:
            raise TypeError("adoption requires account identity and immutable decision document")
        payload = json.loads(self.document)
        if type(payload) is not dict or type(payload.get("decision_id")) is not str:
            raise ValueError("adoption requires an explicit decision identity")


@dataclass(frozen=True, slots=True)
class AdoptionResult:
    account_id: str
    decision_id: str
    intent_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Decision:
    decision_id: str
    symbol: str
    action: str
    actual_quantity: int
    target_quantity: int
    delta_quantity: int
    execution_reference_price: float
    capital_mode: str
    allocation_fraction: float
    plan_mode: str
    signal_date: date
    valid_session: date
    orders: tuple[AdoptionOrder, ...]
    plan_legs: tuple[AdoptionLeg, ...]

    @classmethod
    def from_payload(cls, payload):
        value = {key: payload[key] for key in cls.__dataclass_fields__}
        for key in ("signal_date", "valid_session"):
            value[key] = date.fromisoformat(value[key])
        value["orders"] = tuple(AdoptionOrder(**item) for item in value["orders"])
        legs = []
        for item in value["plan_legs"]:
            fields = dict(item)
            for key in ("submit_after", "submit_before"):
                fields[key] = (datetime if "T" in fields[key] or " " in fields[key] else time).fromisoformat(fields[key])
            fields["order"] = AdoptionOrder(**fields["order"])
            legs.append(AdoptionLeg(**fields))
        value["plan_legs"] = tuple(legs)
        return cls(**value)


class AccountAdoption:
    """Channel account mutation; strategy computation and retries stay with the host."""
    def __init__(self, store: PaperStore, audit: AuditRecorder):
        self.store, self.audit = store, audit

    def adopt(self, request: DecisionAdoption, *, in_transaction: bool = False) -> AdoptionResult:
        if type(request) is not DecisionAdoption:
            raise TypeError("account adoption requires DecisionAdoption")
        with self.store._write_context(in_transaction):
            return self._adopt(request)

    def _adopt(self, request: DecisionAdoption) -> AdoptionResult:
        account_id = request.account_id
        payload = json.loads(request.document)
        decision = _Decision.from_payload(payload)
        previous_action = request.previous_action
        account = self.store.virtual_account(account_id)
        if account['run_state'] != 'RUNNING':
            raise RuntimeError('strategy decision adoption requires a RUNNING account')
        execution_account = account
        self.store.save_account_decision(account_id, payload)
        valued_account = self.store.virtual_account(account_id)
        close = Decimal(str(decision.execution_reference_price))
        cash = Decimal(valued_account["cash"])
        frozen_cash = Decimal(valued_account["frozen_cash"])
        market_value = (close * int(valued_account["quantity"])).quantize(Decimal("0.0001"))
        total_assets = (cash + frozen_cash + market_value).quantize(Decimal("0.0001"))
        self.store.save_account_snapshot(
            account_id, decision.signal_date.isoformat(),
            {
                "cash": str(cash), "frozen_cash": str(frozen_cash),
                "quantity": int(valued_account["quantity"]), "close": str(close),
                "market_value": str(market_value), "total_assets": str(total_assets),
                "decision_id": decision.decision_id,
            },
        )
        scope = {
            "account_id": account_id, "strategy_id": account["strategy_id"],
            "strategy_version": account["strategy_version"],
            "release_hash": account["release_hash"], "symbol": account["symbol"],
            "decision_id": decision.decision_id, "correlation_id": decision.decision_id,
        }
        if not self.store.has_audit_event(
            "DECISION_GENERATED", account_id=account_id,
            decision_id=decision.decision_id, channel_is_null=True,
        ):
            self.audit.record(
                "DECISION_GENERATED", source="account_engine", **scope,
                details={
                    "action": decision.action,
                    "actual_quantity": decision.actual_quantity,
                    "target_quantity": decision.target_quantity,
                    "execution_reference_price": decision.execution_reference_price,
                    "capital_mode": decision.capital_mode,
                    "allocation_fraction": decision.allocation_fraction,
                    "signal_date": decision.signal_date.isoformat(),
                    "valid_session": decision.valid_session.isoformat(),
                },
            )
            if decision.action in {"BUY", "SELL", "ROTATE"}:
                self.audit.record(
                    "SIGNAL_TRIGGERED", source="account_engine", **scope,
                    details={
                        "side": decision.action,
                        "quantity": (
                            decision.plan_legs[0].order.quantity
                            if decision.plan_legs else abs(decision.delta_quantity)
                        ),
                        "target_quantity": decision.target_quantity,
                        "valid_session": decision.valid_session.isoformat(),
                    },
                )
            elif decision.action in {"WAIT", "HOLD"} and previous_action in {
                "BUY", "SELL", "ROTATE",
            }:
                self.audit.record(
                    "SIGNAL_CLEARED", source="account_engine", **scope,
                    details={
                        "previous_action": previous_action,
                        "target_quantity": decision.target_quantity,
                        "valid_session": decision.valid_session.isoformat(),
                    },
                )

        if execution_account["run_state"] == "RUNNING" and self.store.account_decision(account_id, decision.decision_id)["status"] == "PENDING":
            if decision.plan_legs:
                plan_events = []
                plan_rows = []
                for leg in decision.plan_legs:
                    order = leg.order
                    plan_events.append(self.audit.build(
                        "ORDER_INTENT_CREATED", source="account_engine", channel=self.store.virtual_account(account_id)["channel_id"],
                        **scope,
                        details={
                            "side": order.side,
                            "quantity": order.quantity,
                            "order_type": order.order_type,
                            "limit_price": order.limit_price,
                            "valid_session": decision.valid_session.isoformat(),
                            "order_sequence": leg.sequence,
                            "plan_mode": decision.plan_mode,
                            "role": leg.role,
                            "checkpoint": leg.checkpoint,
                            "submit_after": leg.submit_after.isoformat(),
                            "submit_before": leg.submit_before.isoformat(),
                            "dependency_sequence": leg.dependency_sequence,
                        },
                    ))
                    plan_rows.append({
                        "sequence": leg.sequence,
                        "plan_mode": decision.plan_mode,
                        "role": leg.role,
                        "checkpoint": leg.checkpoint,
                        "submit_after": leg.submit_after.isoformat(),
                        "submit_before": leg.submit_before.isoformat(),
                        "dependency_sequence": leg.dependency_sequence,
                        "dependency_required_status": leg.dependency_required_status,
                        "side": order.side,
                        "quantity": order.quantity,
                        "order_type": order.order_type,
                        "limit_price": order.limit_price,
                    })
                self.store.create_account_plan_intents(
                    account_id=account_id,
                    decision_id=decision.decision_id,
                    symbol=decision.symbol,
                    valid_session=decision.valid_session.isoformat(),
                    fee_rate=payload["fee_rate"],
                    legs=plan_rows,
                    audit_events=plan_events,
                )
            if decision.orders:
                immediate_rows = []
                immediate_events = []
                for sequence, order in enumerate(decision.orders):
                    immediate_rows.append({
                        "sequence": sequence,
                        "side": order.side,
                        "quantity": order.quantity,
                        "order_type": order.order_type,
                        "limit_price": order.limit_price,
                    })
                    immediate_events.append(self.audit.build(
                        "ORDER_INTENT_CREATED", source="account_engine",
                        channel=self.store.virtual_account(account_id)["channel_id"], **scope,
                        details={
                            "side": order.side, "quantity": order.quantity,
                            "order_type": order.order_type,
                            "limit_price": order.limit_price,
                            "valid_session": decision.valid_session.isoformat(),
                            "order_sequence": sequence,
                        },
                    ))
                self.store.create_account_immediate_intents(
                    account_id=account_id,
                    decision_id=decision.decision_id,
                    symbol=decision.symbol,
                    valid_session=decision.valid_session.isoformat(),
                    fee_rate=payload["fee_rate"],
                    orders=immediate_rows,
                    audit_events=immediate_events,
                )
        elif decision.action in {"BUY", "SELL", "ROTATE"}:
            self.audit.record(
                "ORDER_SUBMISSION_BLOCKED", source="account_engine", outcome="SKIPPED",
                account_id=account_id, strategy_id=account["strategy_id"],
                strategy_version=account["strategy_version"],
                release_hash=account["release_hash"], symbol=account["symbol"],
                decision_id=decision.decision_id, correlation_id=decision.decision_id,
                details={"reason": "account_paused", "action": decision.action},
            )
        return AdoptionResult(account_id, decision.decision_id,
            tuple(row["intent_id"] for row in self.store.account_intents(account_id, decision.decision_id)))
