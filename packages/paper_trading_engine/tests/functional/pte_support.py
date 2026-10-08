from __future__ import annotations

from dataclasses import replace
from datetime import date
from hashlib import sha256
from types import SimpleNamespace

from paper_trading_engine.contracts import AdviceDecision, OrderSpec
from paper_trading_engine.broker import (
    BrokerAccount,
    BrokerOrder,
    BrokerSnapshot,
)


def adopt_test_decision(store, *, account_id, decision_id, valid_session, orders=None, legs=None):
    """Persist an explicit synthetic plan through the real decision adoption API."""
    from dataclasses import asdict
    from datetime import timedelta

    try:
        return store.account_decision(account_id, decision_id)
    except KeyError:
        pass
    account = store.virtual_account(account_id)
    payload = asdict(decision())
    planned = [leg["order"] if "order" in leg else leg for leg in (legs or orders or [])]
    delta = sum(order["quantity"] * (1 if order["side"] == "BUY" else -1) for order in planned)
    normalized_legs = [{**leg, "order": {key: leg[key] for key in ("side", "quantity", "order_type", "limit_price")}}
                       if "order" not in leg else leg for leg in (legs or [])]
    payload.update(
        decision_id=decision_id, symbol=account["symbol"],
        strategy={"strategy_id": account["strategy_id"], "version": account["strategy_version"],
                  "release_hash": account["release_hash"]},
        signal_date=(date.fromisoformat(valid_session)-timedelta(days=1)).isoformat(),
        valid_session=valid_session, actual_quantity=account["quantity"],
        available_cash=float(account["cash"]) + float(account["frozen_cash"]),
        orders=planned if not legs else [], plan_legs=normalized_legs,
        target_quantity=account["quantity"] + delta, delta_quantity=delta,
        cycle_target_quantity=account["quantity"] + delta,
        action=planned[0]["side"] if planned else "HOLD",
        plan_identity=sha256(repr((decision_id, valid_session, planned)).encode()).hexdigest(),
    )
    return store.save_account_decision(account_id, payload)


def claim_test_intent(store, intent_id):
    """Claim after a deterministic successful channel/cash reconciliation fixture."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    store.set_setting("channel_reconciliation_status", "OK")
    store.set_setting("futu_cash_reconciliation_status", "OK")
    intent = store.account_intent(intent_id)
    return store.claim_account_intent(
        intent_id, moment=datetime.fromisoformat(intent["valid_session"] + "T09:30:00").replace(tzinfo=ZoneInfo("Asia/Shanghai")),
    )


def preparation(value: AdviceDecision, identity: str = "c" * 64):
    return SimpleNamespace(
        strategy=SimpleNamespace(
            reference_id=(
                f"{value.strategy['strategy_id']}-{value.strategy['version']}"
            ),
            release_hash=value.strategy["release_hash"],
        ),
        tradable_window=SimpleNamespace(
            start=value.valid_session,
            end=value.valid_session,
        ),
        available_through=value.signal_date,
        data_identity=identity,
        data_reference={"space_id": "11111111-1111-1111-1111-111111111111",
                        "preparation_id": "22222222-2222-2222-2222-222222222222",
                        "manifest_sha256": "a" * 64},
    )


def decision(order: OrderSpec | None = None) -> AdviceDecision:
    orders = () if order is None else (order,)
    target = 0 if order is None else order.quantity
    return AdviceDecision(
        contract_version="advice.v4",
        decision_id="DEC-ONE",
        symbol="588080.SH",
        signal_date=date(2026, 9, 1),
        valid_session=date(2026, 9, 2),
        actual_quantity=0,
        target_quantity=target,
        cycle_target_quantity=target,
        delta_quantity=target,
        action="WAIT" if order is None else order.side,
        strategy={
            "strategy_id": "S001",
            "name": "综合基线策略",
            "version": "v1",
            "release_id": "S001-v1",
            "release_hash": "b" * 64,
            "qualification": "PAPER_READY",
        },
        signal_reference_price=1.7,
        execution_reference_price=1.68,
        data_cutoff=date(2026, 9, 1),
        order=order,
        signal_identity="1" * 64,
        plan_identity="2" * 64,
        portfolio_revision=0,
        state_revision=0,
        orders=orders,
        available_cash=1_000_000,
        fee_rate=0.0005,
    )


def broker_snapshot(*, orders=(), quantity=0, symbol="588080.SH") -> BrokerSnapshot:
    from paper_trading_engine.broker import BrokerPosition

    positions = () if quantity == 0 else (BrokerPosition(symbol, quantity),)
    cash = 1_000_000.0
    fees = 0.0
    for order in orders:
        filled = int(order.cumulative_filled_quantity)
        price = float(order.average_fill_price)
        turnover = filled * price
        cash += turnover if order.side == "SELL" else -turnover
        fees += turnover * 0.0005
    cash -= fees
    return BrokerSnapshot(
        BrokerAccount("SIMULATE", "CN", cash, 1_000_000 - fees, 0),
        positions,
        tuple(orders),
    )


class FakeAdvice:
    def __init__(self, value: AdviceDecision):
        self.value = value
        self.calls = []

    def get_decision(self, actual_quantity, available_cash, **kwargs):
        self.calls.append((actual_quantity, available_cash, kwargs))
        value = replace(
            self.value,
            actual_quantity=actual_quantity,
            available_cash=available_cash,
            valid_session=kwargs.get("trading_date", self.value.valid_session),
            portfolio_revision=kwargs.get(
                "portfolio_revision", self.value.portfolio_revision
            ),
            state_revision=kwargs.get("state_revision", self.value.state_revision),
            plan_identity=sha256(
                (
                    f"{self.value.signal_identity}:{self.value.signal_date}:"
                    f"{self.value.target_quantity}:{self.value.action}:"
                    f"{self.value.orders}:{self.value.plan_legs}:"
                    f"{actual_quantity}:{available_cash}"
                ).encode("utf-8")
            ).hexdigest(),
            source_decision_id=self.value.source_decision_id or self.value.decision_id,
        )
        return value


class FakeBroker:
    channel_id = "futu_simulate_cn"
    def __init__(self):
        self.value = broker_snapshot()
        self.placed = []
        self.cancelled = []

    def snapshot(self):
        return self.value

    def account_snapshot(self):
        return self.value

    def order_snapshot(self):
        return self.value.orders

    def historical_order_snapshot(self, start, end):
        return self.value.orders

    def place_order(self, intent):
        self.placed.append(intent)
        order = BrokerOrder(
            str(1000 + len(self.placed)), intent.symbol, intent.side, intent.quantity,
            intent.limit_price, "SUBMITTED", 0, 0, intent.intent_id,
            order_type=intent.order_type,
        )
        self.value = replace(self.value, orders=(*self.value.orders, order))
        return order

    def cancel_order(self, channel_order_id):
        self.cancelled.append(channel_order_id)

    def close(self):
        return None
