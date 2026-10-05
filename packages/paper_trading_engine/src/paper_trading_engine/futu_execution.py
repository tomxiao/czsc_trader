"""Shared Futu execution and reconciliation for account-owned orders."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import json
import math
import secrets

from .audit import AuditRecorder
from .account_retirement import AccountRetirementRequest, AccountRetirementResult
from .broker import (
    BrokerOrderRejectedError,
    KNOWN_ORDER_STATUSES,
    OrderIntent,
    PaperTradingSafetyError,
    TERMINAL_INTENT_STATUSES,
    TERMINAL_ORDER_STATUSES,
)
from .channel import FUTU_SIMULATE_CN_CHANNEL_ID, require_futu_simulate_cn_broker
from .trading_window import SHANGHAI, is_submission_window, shanghai_now


FUTU_CN_MAX_VARIABLE_FEE_RATE = Decimal("0.005")
FUTU_CN_MAX_FIXED_FEE_PER_ORDER = Decimal("20")
FUTU_CN_FEE_ROUNDING_TOLERANCE = Decimal("1")


class ChannelReconciliationError(RuntimeError):
    pass


class OrderSubmissionBatchError(RuntimeError):
    """One or more deterministic order submissions failed in this cycle."""


class FutuExecution:
    def __init__(
        self, store, broker, *, symbol: str | None = None, today=None, now=None, audit=None,
    ) -> None:
        self.store = store
        self.broker = broker
        self.symbol = symbol.upper() if symbol else None
        if now is None and today is not None:
            def test_clock():
                return datetime.combine(today(), time(10, 0), SHANGHAI)

            now = test_clock
        self.now = now or shanghai_now
        self.audit = audit or AuditRecorder(store)
        self._snapshot = None
        self._orders = ()
        self._draining = False

    def begin_shutdown(self) -> None:
        self._draining = True

    def refresh_account(self):
        require_futu_simulate_cn_broker(self.broker)
        method = getattr(self.broker, "account_snapshot", None)
        snapshot = method() if method is not None else self.broker.snapshot()
        if snapshot.account.environment != "SIMULATE":
            raise PaperTradingSafetyError("broker environment must be SIMULATE")
        if snapshot.account.market != "CN":
            raise PaperTradingSafetyError("broker market must be CN")
        pool = self.store.capital_pool_balance()
        if pool.registered_capital <= 0 or pool.unallocated_cash < Decimal("-0.01"):
            raise ChannelReconciliationError("虚拟账户分配资金超过PTE登记的Futu资金池")
        self._snapshot = snapshot
        self.store.mark_reconciled()
        return self.status()

    def _owned_intent(self, remark: str):
        return self.store.account_intent(remark) if remark.startswith("PTE-") else None

    def _block_reconciliation(
        self, reason: str, message: str, *, intent=None, order_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        self.store.set_setting("channel_reconciliation_status", "BLOCKED")
        account_id = None if intent is None else intent["account_id"]
        if account_id:
            self.store.set_virtual_health(account_id, "BLOCKED", message)
        self.audit.record(
            "CHANNEL_RECONCILIATION_FAILED", source="futu_execution",
            outcome="FAILURE", channel=FUTU_SIMULATE_CN_CHANNEL_ID, account_id=account_id,
            decision_id=None if intent is None else intent["decision_id"],
            order_id=order_id,
            details={"reason": reason, **(details or {})},
        )
        raise ChannelReconciliationError(message)

    def _order_snapshot(self):
        by_id = {row.channel_order_id: row for row in self.broker.order_snapshot()}
        unresolved = self.store.unresolved_account_intents()
        active_orders = [
            row for row in self.store.account_orders()
            if row.get("status") not in TERMINAL_ORDER_STATUSES
        ]
        history = getattr(self.broker, "historical_order_snapshot", None)
        if history is not None and (unresolved or active_orders):
            dates = [str(row["valid_session"]) for row in unresolved]
            for row in active_orders:
                intent = self.store.account_intent(str(row["intent_id"]))
                if intent is not None:
                    dates.append(str(intent["valid_session"]))
            start = min(dates) if dates else (
                self.now().astimezone(SHANGHAI).date() - timedelta(days=30)
            ).isoformat()
            end = self.now().astimezone(SHANGHAI).date().isoformat()
            for row in history(start, end):
                by_id.setdefault(row.channel_order_id, row)
        return tuple(by_id.values())

    def _recover_transient_account_health(self, account_id: str) -> None:
        account = self.store.virtual_account(account_id)
        transient_prefixes = (
            "Futu下单结果不确定",
            "Futu已返回订单，但本地绑定失败",
            "Futu已返回订单，但订单回报与意图不一致",
            "Futu订单状态未知",
            "存在未完成订单",
        )
        if (
            account["health"] == "BLOCKED"
            and str(account.get("last_error") or "").startswith(transient_prefixes)
            and not any(
                row["status"] not in TERMINAL_INTENT_STATUSES
                for row in self.store.account_intents(account_id)
            )
            and not self.store.attention_account_intents(account_id)
        ):
            self.store.set_virtual_health(account_id, "OK")
            self.audit.record(
                "ACCOUNT_RECONCILIATION_RECOVERED", source="futu_execution",
                account_id=account_id, strategy_id=account.get("strategy_id"),
                strategy_version=account.get("strategy_version"),
                release_hash=account.get("release_hash"), channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                details={"reason": "transient_order_state_resolved"},
            )

    @staticmethod
    def _planned_clock(intent, field: str) -> time | None:
        value = intent["payload"].get(field)
        return None if value is None else time.fromisoformat(str(value))

    def _expire_planned_intent(self, intent, message: str) -> None:
        self.store.release_account_intent(
            intent["intent_id"], "EXPIRED", attention_reason=message,
        )
        self.store.set_virtual_health(intent["account_id"], "BLOCKED", message)
        self.audit.record(
            "EXECUTION_PLAN_BLOCKED", source="futu_execution", outcome="FAILURE",
            account_id=intent["account_id"], channel=FUTU_SIMULATE_CN_CHANNEL_ID,
            decision_id=intent["decision_id"], correlation_id=intent["decision_id"],
            details={
                "intent_id": intent["intent_id"],
                "role": intent["payload"].get("role"),
                "reason": message,
            },
        )

    def _recover_future_plan_expiries(self, moment: datetime) -> None:
        session = moment.astimezone(SHANGHAI).date().isoformat()
        recovered_accounts: set[str] = set()
        for intent in self.store.attention_account_intents():
            if (
                intent["status"] != "EXPIRED"
                or intent.get("channel_order_id")
                or intent["valid_session"] <= session
                or intent.get("attention_reason") != "计划订单错过提交截止时间"
                or not intent["payload"].get("plan_mode")
            ):
                continue
            account = self.store.virtual_account(intent["account_id"])
            event = self.audit.build(
                "ORDER_INTENT_RECOVERED", source="futu_execution",
                account_id=intent["account_id"], strategy_id=account.get("strategy_id"),
                strategy_version=account.get("strategy_version"),
                release_hash=account.get("release_hash"), channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                decision_id=intent["decision_id"], correlation_id=intent["decision_id"],
                details={
                    "intent_id": intent["intent_id"],
                    "reason": "future_session_deadline_comparison_repaired",
                    "valid_session": intent["valid_session"],
                },
            )
            self.store.recover_future_planned_intent(intent["intent_id"], event)
            recovered_accounts.add(intent["account_id"])
        for account_id in recovered_accounts:
            if not self.store.attention_account_intents(account_id):
                self.store.set_virtual_health(account_id, "OK")

    def _expire_unsubmitted_intents(self, moment: datetime) -> None:
        """Terminate stale local intents before broker or account health gates run."""
        local = moment.astimezone(SHANGHAI)
        session = local.date().isoformat()
        clock = local.time().replace(tzinfo=None)
        for intent in self.store.pending_account_intents():
            if intent["valid_session"] < session:
                message = "订单未在有效交易日内提交，已形成前瞻执行缺口"
                self.store.release_account_intent(
                    intent["intent_id"], "EXPIRED", attention_reason=message,
                )
                self.store.set_virtual_health(intent["account_id"], "BLOCKED", message)
                self.audit.record(
                    "DECISION_EXPIRED", source="futu_execution", outcome="SKIPPED",
                    account_id=intent["account_id"], channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                    decision_id=intent["decision_id"], correlation_id=intent["decision_id"],
                    details={
                        "intent_id": intent["intent_id"],
                        "valid_session": intent["valid_session"],
                    },
                )
                continue
            if intent["valid_session"] > session:
                continue
            deadline = self._planned_clock(intent, "submit_before")
            if deadline is not None and clock > deadline:
                self._expire_planned_intent(intent, "计划订单错过提交截止时间")

    def _activate_dependency_intents(self, moment: datetime) -> None:
        local = moment.astimezone(SHANGHAI)
        session = local.date().isoformat()
        clock = local.time().replace(tzinfo=None)
        for intent in self.store.waiting_dependency_intents():
            if intent["valid_session"] < session:
                self._expire_planned_intent(intent, "依赖订单未在计划交易日完成")
                continue
            if intent["valid_session"] > session:
                continue
            deadline = self._planned_clock(intent, "submit_before")
            if deadline is not None and clock > deadline:
                self._expire_planned_intent(intent, "依赖订单未在计划退出截止前完成")
                continue
            dependency_id = intent["payload"].get("dependency_intent_id")
            dependency = self.store.account_intent(str(dependency_id))
            if dependency is None:
                self._block_reconciliation(
                    "plan_dependency_missing",
                    f"执行计划依赖意图不存在: {dependency_id}",
                    intent=intent,
                )
            required = intent["payload"].get("dependency_required_status")
            if dependency["status"] == required:
                if self.store.activate_dependency_intent(intent["intent_id"]):
                    self.audit.record(
                        "EXECUTION_PLAN_LEG_READY", source="futu_execution",
                        account_id=intent["account_id"], channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                        decision_id=intent["decision_id"],
                        correlation_id=intent["decision_id"],
                        details={
                            "intent_id": intent["intent_id"],
                            "dependency_intent_id": dependency_id,
                            "role": intent["payload"].get("role"),
                        },
                    )
            elif dependency["status"] in TERMINAL_INTENT_STATUSES:
                self._expire_planned_intent(
                    intent,
                    f"依赖订单未完整成交（{dependency['status']}），计划退出不得执行",
                )

    def _cancel_expired_planned_orders(self, moment: datetime) -> None:
        local = moment.astimezone(SHANGHAI)
        session = local.date().isoformat()
        clock = local.time().replace(tzinfo=None)
        cancellable = {
            "UNSUBMITTED", "WAITING_SUBMIT", "SUBMITTED", "FILLED_PART",
        }
        for intent in self.store.account_intents():
            deadline = self._planned_clock(intent, "submit_before")
            if (
                deadline is None
                or intent["valid_session"] != session
                or clock <= deadline
                or intent["status"] not in cancellable
                or not intent.get("channel_order_id")
            ):
                continue
            account = self.store.virtual_account(intent["account_id"])
            try:
                self.broker.cancel_order(intent["channel_order_id"])
            except Exception as exc:
                self.store.set_virtual_health(
                    intent["account_id"], "BLOCKED",
                    "计划订单到期但撤单结果不确定，等待渠道对账",
                )
                self.audit.record(
                    "CANCEL_FAILED", source="futu_execution", outcome="FAILURE",
                    account_id=intent["account_id"], channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                    decision_id=intent["decision_id"],
                    order_id=intent["channel_order_id"],
                    correlation_id=intent["decision_id"],
                    details={"reason": "planned_deadline", "error": str(exc)},
                )
                raise
            self.store.update_account_intent_status(intent["intent_id"], "CANCELLING_ALL")
            self.audit.record(
                "CANCEL_REQUESTED", source="futu_execution",
                account_id=intent["account_id"], channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                strategy_id=account["strategy_id"],
                strategy_version=account["strategy_version"],
                release_hash=account["release_hash"],
                decision_id=intent["decision_id"], order_id=intent["channel_order_id"],
                correlation_id=intent["decision_id"],
                details={"reason": "planned_deadline", "deadline": deadline.isoformat()},
            )

    def _reconcile_broker_fees(self) -> None:
        """Reconcile verified aggregate Futu fees without altering strategy PnL."""
        if self._snapshot is None:
            return
        accounts = [row for row in self.store.virtual_accounts() if row.get("status") != "RETIRED"]
        if self.store.unresolved_account_intents() or any(
            Decimal(row["frozen_cash"]) != 0 for row in accounts
        ):
            return
        pool = self.store.capital_pool_balance()
        capital_pool = pool.registered_capital
        logical_cash = pool.unallocated_cash + sum(
            (Decimal(row["cash"]) for row in accounts), Decimal("0")
        )
        broker_cash = Decimal(str(self._snapshot.account.cash)).quantize(Decimal("0.0001"))
        difference = (broker_cash - logical_cash).quantize(Decimal("0.0001"))

        raw_checkpoint = self.store.get_setting("futu_cash_reconciliation_checkpoint")
        checkpoint = json.loads(raw_checkpoint) if raw_checkpoint else {}
        fill_rowid = int(checkpoint.get("fill_rowid", 0))
        fills = self.store.account_fills_after_rowid(fill_rowid)
        latest_rowid = fills[-1]["fill_rowid"] if fills else fill_rowid
        if abs(difference) <= Decimal("0.01"):
            self.store.set_setting(
                "futu_cash_reconciliation_checkpoint",
                json.dumps({
                    "schema": "futu_cash_reconciliation.v1",
                    "fill_rowid": latest_rowid, "broker_cash": str(broker_cash),
                    "reconciled_at": datetime.now(timezone.utc).isoformat(),
                }),
            )
            self.store.set_setting("futu_cash_reconciliation_status", "OK")
            return
        if not fills:
            self.store.set_setting("futu_cash_reconciliation_status", "UNATTRIBUTED")
            return
        turnover = sum(
            (Decimal(str(fill["price"])) * int(fill["quantity"]) for fill in fills),
            Decimal("0"),
        )
        broker_order_count = len({str(fill["order_id"]) for fill in fills})
        modeled_fee = sum((Decimal(fill["fee"]) for fill in fills), Decimal("0"))
        previous_broker_cash = Decimal(str(checkpoint.get("broker_cash", capital_pool)))
        gross_cash_change = sum(
            (
                Decimal(str(fill["price"])) * int(fill["quantity"])
                * (Decimal("-1") if str(fill["side"]).upper() == "BUY" else Decimal("1"))
                for fill in fills
            ),
            Decimal("0"),
        )
        actual_fee = (gross_cash_change - (broker_cash - previous_broker_cash)).quantize(
            Decimal("0.0001")
        )
        # This is a safety envelope, not a broker fee calculator.  Futu CN fees
        # include per-order fixed/minimum charges, so a turnover-only bound rejects
        # legitimate small orders.  Keep the variable allowance deliberately broad
        # while bounding the fixed allowance by the number of broker orders.
        maximum_fee = (
            turnover * FUTU_CN_MAX_VARIABLE_FEE_RATE
            + FUTU_CN_MAX_FIXED_FEE_PER_ORDER * broker_order_count
            + FUTU_CN_FEE_ROUNDING_TOLERANCE
        ).quantize(Decimal("0.0001"))
        if actual_fee < Decimal("-0.01") or actual_fee > maximum_fee:
            self.store.set_setting("futu_cash_reconciliation_status", "OUT_OF_RANGE")
            return
        reference = f"futu:{fill_rowid + 1}-{latest_rowid}:{broker_cash}"
        account_ids = {str(fill["account_id"]) for fill in fills}
        # Strategy accounts retain their modeled fee.  Every verified broker
        # variance belongs to the dedicated channel account, including a
        # one-account batch, so comparison metrics never depend on batching.
        reconciliation = self.store.channel_reconciliation_account(FUTU_SIMULATE_CN_CHANNEL_ID)
        if reconciliation is None:
            self.store.set_setting("futu_cash_reconciliation_status", "AMBIGUOUS")
            return
        event = self.audit.build(
            "CHANNEL_FEE_VARIANCE_RECONCILED", source="futu_execution",
            account_id=reconciliation["account_id"], channel=FUTU_SIMULATE_CN_CHANNEL_ID,
            correlation_id=reference,
            details={
                "adjustment": str(difference), "modeled_fee": str(modeled_fee),
                "actual_fee": str(actual_fee), "maximum_fee": str(maximum_fee),
                "fill_count": len(fills), "broker_order_count": broker_order_count,
                "fill_rowid_from": fill_rowid + 1, "fill_rowid_to": latest_rowid,
                "strategy_account_ids": sorted(account_ids),
                "treatment": "CHANNEL_RECONCILIATION_ACCOUNT",
            },
        )
        try:
            self.store.apply_channel_fee_variance(
                adjustment=difference, reference=reference,
                occurred_at=datetime.now(timezone.utc).isoformat(), event=event,
            )
        except ValueError:
            self.store.set_setting("futu_cash_reconciliation_status", "OUT_OF_RANGE")
            return
        self.store.set_setting(
            "futu_cash_reconciliation_checkpoint",
            json.dumps({
                "schema": "futu_cash_reconciliation.v1",
                "fill_rowid": latest_rowid, "broker_cash": str(broker_cash),
                "reconciled_at": datetime.now(timezone.utc).isoformat(),
            }),
        )
        self.store.set_setting("futu_cash_reconciliation_status", "OK")

    def _require_cash_reconciliation(self) -> None:
        status = self.store.get_setting("futu_cash_reconciliation_status")
        if status in {"UNATTRIBUTED", "OUT_OF_RANGE", "AMBIGUOUS"}:
            message = f"Futu现金对账未闭合: {status}"
            self._block_reconciliation(
                "cash_reconciliation_failed",
                message,
                details={"cash_reconciliation_status": status},
            )

    @staticmethod
    def _validate_order(intent, order) -> None:
        intent_order_type = str(intent["payload"].get("order_type", "LIMIT")).upper()
        if order.status not in KNOWN_ORDER_STATUSES:
            raise ValueError(f"unknown Futu order status: {order.status}")
        if order.remark != intent["intent_id"]:
            raise ValueError("order remark differs from intent")
        if order.symbol.upper() != intent["symbol"].upper():
            raise ValueError("order symbol differs from intent")
        if order.side.upper() != intent["side"].upper():
            raise ValueError("order side differs from intent")
        if order.quantity != int(intent["quantity"]):
            raise ValueError("order quantity differs from intent")
        if order.order_type != intent_order_type:
            raise ValueError("order type differs from intent")
        if intent_order_type == "LIMIT" and not math.isclose(
            order.limit_price, float(intent["limit_price"]), abs_tol=1e-9,
        ):
            raise ValueError("order limit price differs from intent")
        if order.cumulative_filled_quantity < 0:
            raise ValueError("order cumulative fill cannot be negative")
        if order.cumulative_filled_quantity > int(intent["quantity"]):
            raise ValueError("order cumulative fill exceeds intent quantity")
        if order.cumulative_filled_quantity and (
            not math.isfinite(order.average_fill_price) or order.average_fill_price <= 0
        ):
            raise ValueError("filled order average price must be positive and finite")
        if (
            order.cumulative_filled_quantity
            and intent_order_type == "LIMIT"
            and order.side.upper() == "BUY"
            and order.average_fill_price > order.limit_price + 1e-9
        ):
            raise ValueError("buy average fill price exceeds limit")
        if (
            order.cumulative_filled_quantity
            and intent_order_type == "LIMIT"
            and order.side.upper() == "SELL"
            and order.average_fill_price < order.limit_price - 1e-9
        ):
            raise ValueError("sell average fill price is below limit")

    def refresh_orders(self):
        return self._refresh_orders(expire_orders=True)

    def _refresh_orders(self, *, expire_orders: bool):
        require_futu_simulate_cn_broker(self.broker)
        moment = self.now()
        if moment.tzinfo is None:
            raise ValueError("reconciliation clock must be timezone-aware")
        if expire_orders:
            self._expire_unsubmitted_intents(moment)
        previous_reconciliation = self.store.get_setting("channel_reconciliation_status")
        orders = self._order_snapshot()
        seen_intents: set[str] = set()
        touched_accounts: set[str] = set()
        for order in orders:
            intent = self._owned_intent(order.remark)
            if intent is None:
                if order.status not in TERMINAL_ORDER_STATUSES:
                    self._block_reconciliation(
                        "unowned_order", f"Futu订单无法归属虚拟账户: {order.channel_order_id}",
                        order_id=order.channel_order_id, details={"remark": order.remark},
                    )
                continue
            try:
                self._validate_order(intent, order)
            except ValueError as exc:
                self._block_reconciliation(
                    "order_mismatch", f"Futu订单与本地意图不一致: {order.channel_order_id}",
                    intent=intent, order_id=order.channel_order_id,
                    details={"error": str(exc)},
                )
            seen_intents.add(intent["intent_id"])
            touched_accounts.add(intent["account_id"])
            previous_status = None
            try:
                previous_status = self.store.account_order(order.channel_order_id).get("status")
            except KeyError:
                account = self.store.virtual_account(intent["account_id"])
                recovered = self.audit.build(
                    "ORDER_INTENT_RECOVERED", source="futu_execution",
                    account_id=intent["account_id"], strategy_id=account["strategy_id"],
                    strategy_version=account["strategy_version"],
                    release_hash=account["release_hash"], channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                    decision_id=intent["decision_id"], order_id=order.channel_order_id,
                    correlation_id=intent["decision_id"],
                    details={"intent_id": intent["intent_id"], "status": order.status},
                )
                self.store.bind_channel_order(
                    intent["intent_id"], order.channel_order_id, asdict(order), recovered,
                )
            self.store.apply_fill_increment(
                order.channel_order_id,
                cumulative_quantity=order.cumulative_filled_quantity,
                average_price=order.average_fill_price,
                occurred_at=self.store.get_setting("clock_override")
                or datetime.now(timezone.utc).isoformat(),
            )
            self.store.update_channel_order_report(order.channel_order_id, asdict(order))
            if order.status == "TIMEOUT":
                self.store.set_virtual_health(
                    intent["account_id"], "BLOCKED",
                    "Futu订单状态未知（TIMEOUT），等待后续订单对账确认",
                )
            if order.status in {"CANCELLED_PART", "CANCELLED_ALL"} and (
                previous_status not in TERMINAL_ORDER_STATUSES
            ):
                account = self.store.virtual_account(intent["account_id"])
                self.audit.record(
                    "CANCEL_SUCCEEDED", source="futu_execution",
                    account_id=intent["account_id"], channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                    strategy_id=account["strategy_id"],
                    strategy_version=account["strategy_version"],
                    release_hash=account["release_hash"],
                    decision_id=intent["decision_id"], order_id=order.channel_order_id,
                    correlation_id=intent["decision_id"],
                    details={"status": order.status},
                )
            if (
                order.status in TERMINAL_ORDER_STATUSES
                and order.status != "FILLED_ALL"
                and previous_status not in TERMINAL_ORDER_STATUSES
            ):
                account = self.store.virtual_account(intent["account_id"])
                self.store.set_virtual_health(
                    intent["account_id"], "BLOCKED",
                    f"Futu订单未完整执行（{order.status}），需要人工确认该次前瞻执行缺口",
                )
                self.audit.record(
                    "ORDER_TERMINATED", source="futu_execution",
                    account_id=intent["account_id"], strategy_id=account["strategy_id"],
                    strategy_version=account["strategy_version"],
                    release_hash=account["release_hash"], channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                    decision_id=intent["decision_id"], order_id=order.channel_order_id,
                    correlation_id=intent["decision_id"],
                    details={
                        "status": order.status,
                        "cumulative_quantity": order.cumulative_filled_quantity,
                    },
                )
        if expire_orders:
            self._cancel_expired_planned_orders(self.now())
        missing = [
            row for row in self.store.account_intents()
            if row["status"] not in TERMINAL_INTENT_STATUSES
            and row["status"] not in {"PENDING_SUBMIT", "WAITING_DEPENDENCY"}
            and row["intent_id"] not in seen_intents
        ]
        if missing:
            intent = missing[0]
            self._block_reconciliation(
                "broker_order_missing",
                f"本地活动订单在Futu当前及历史订单中不存在: {intent['intent_id']}",
                intent=intent, order_id=intent.get("channel_order_id"),
                details={"intent_status": intent["status"]},
            )
        self._orders = orders
        # Positions and cash can change with the order fills processed above.
        self.refresh_account()
        if self._snapshot is not None:
            accounts = [
                account for account in self.store.strategy_virtual_accounts()
                if account.get("status") != "RETIRED"
            ]
            owned_symbols = {str(account["symbol"]).upper() for account in accounts}
            foreign_positions = [
                position for position in self._snapshot.positions
                if position.symbol not in owned_symbols and position.quantity != 0
            ]
            if foreign_positions:
                self.store.set_setting("channel_reconciliation_status", "BLOCKED")
                self.audit.record(
                    "CHANNEL_RECONCILIATION_FAILED", source="futu_execution",
                    outcome="FAILURE", channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                    details={
                        "reason": "unowned_position",
                        "positions": [asdict(position) for position in foreign_positions],
                    },
                )
                raise ChannelReconciliationError("Futu账户存在PTE无法归属的持仓")
            for symbol in sorted(owned_symbols):
                broker_quantity = sum(
                    position.quantity for position in self._snapshot.positions
                    if position.symbol == symbol
                )
                logical_quantity = sum(
                    int(account["quantity"]) for account in accounts
                    if account["symbol"] == symbol
                )
                if broker_quantity != logical_quantity:
                    self.store.set_setting("channel_reconciliation_status", "BLOCKED")
                    self.audit.record(
                        "CHANNEL_RECONCILIATION_FAILED", source="futu_execution",
                        outcome="FAILURE", channel=FUTU_SIMULATE_CN_CHANNEL_ID, symbol=symbol,
                        details={
                            "reason": "position_mismatch", "broker_quantity": broker_quantity,
                            "logical_quantity": logical_quantity,
                        },
                    )
                    raise ChannelReconciliationError(
                        f"Futu持仓与虚拟账户分账不一致({symbol}): "
                        f"{broker_quantity}!={logical_quantity}"
                    )
        self._reconcile_broker_fees()
        self._require_cash_reconciliation()
        violations = self.store.account_invariant_violations()
        if violations:
            first = violations[0]
            account_id = str(first["account_id"])
            self.store.set_virtual_health(
                account_id, "BLOCKED", f"虚拟账户账本与余额不一致: {account_id}",
            )
            intent = next(
                (row for row in self.store.account_intents(account_id)
                 if row["status"] not in TERMINAL_INTENT_STATUSES),
                None,
            )
            self._block_reconciliation(
                "account_ledger_mismatch",
                f"虚拟账户账本与余额不一致: {account_id}",
                intent=intent, details={"violations": violations},
            )
        self.store.set_setting("channel_reconciliation_status", "OK")
        if previous_reconciliation == "BLOCKED":
            self.audit.record(
                "CHANNEL_RECONCILIATION_RECOVERED", source="futu_execution",
                channel=FUTU_SIMULATE_CN_CHANNEL_ID, details={"reason": "orders_and_positions_reconciled"},
            )
        for account_id in sorted(touched_accounts):
            self._recover_transient_account_health(account_id)
        return self.status()

    def submit_pending(self, *, reconcile: bool = True):
        require_futu_simulate_cn_broker(self.broker)
        if self._draining:
            return self.status()
        moment = self.now()
        if moment.tzinfo is None:
            raise ValueError("submission clock must be timezone-aware")
        self._expire_unsubmitted_intents(moment)
        if reconcile:
            self.refresh_orders()
        elif self._snapshot is None:
            self.refresh_account()
        if self.store.is_paused():
            return self.status()
        if self.store.get_setting("channel_reconciliation_status") == "BLOCKED":
            raise ChannelReconciliationError("Futu渠道对账已阻塞，禁止提交订单")
        self._require_cash_reconciliation()
        session = moment.astimezone(SHANGHAI).date().isoformat()
        self._recover_future_plan_expiries(moment)
        self._activate_dependency_intents(moment)
        deterministic_failures: list[tuple[str, Exception]] = []
        for row in self.store.pending_account_intents():
            account = self.store.virtual_account(row["account_id"])
            local_clock = moment.astimezone(SHANGHAI).time().replace(tzinfo=None)
            submit_after = self._planned_clock(row, "submit_after")
            if row["valid_session"] > session:
                continue
            if (
                bool(account["paused"])
                or account["status"] != "RUNNING"
                or account["health"] not in {"READY", "OK"}
            ):
                continue
            if (
                (submit_after is not None and local_clock < submit_after)
                or not is_submission_window(moment)
            ):
                continue
            if not self.store.claim_account_intent(row["intent_id"]):
                continue
            intent = OrderIntent(
                row["intent_id"], row["decision_id"], row["symbol"], row["side"],
                int(row["quantity"]), float(row["limit_price"]),
                order_type=str(row["payload"].get("order_type", "LIMIT")),
                account_id=row["account_id"],
            )
            try:
                order = self.broker.place_order(intent)
            except BrokerOrderRejectedError as exc:
                self.store.release_account_intent(
                    row["intent_id"], "REJECTED", attention_reason=f"Futu明确拒单：{exc}",
                )
                self.store.set_virtual_health(
                    row["account_id"], "BLOCKED", f"Futu明确拒单：{exc}",
                )
                self.audit.record(
                    "ORDER_REJECTED", source="futu_execution", outcome="REJECTED",
                    account_id=row["account_id"], channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                    decision_id=row["decision_id"], correlation_id=row["decision_id"],
                    details={"side": row["side"], "quantity": row["quantity"], "error": str(exc)},
                )
                deterministic_failures.append((row["intent_id"], exc))
                continue
            except PaperTradingSafetyError as exc:
                self.store.release_account_intent(
                    row["intent_id"], "SUBMISSION_FAILED", attention_reason=str(exc),
                )
                self.store.set_virtual_health(row["account_id"], "BLOCKED", str(exc))
                self.audit.record(
                    "ORDER_SUBMISSION_FAILED", source="futu_execution", outcome="FAILURE",
                    account_id=row["account_id"], channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                    decision_id=row["decision_id"], correlation_id=row["decision_id"],
                    details={"side": row["side"], "quantity": row["quantity"], "error": str(exc)},
                )
                deterministic_failures.append((row["intent_id"], exc))
                continue
            except Exception as exc:
                self.store.update_account_intent_status(
                    row["intent_id"], "SUBMISSION_UNCERTAIN"
                )
                self.store.set_virtual_health(
                    row["account_id"], "BLOCKED",
                    "Futu下单结果不确定，已保留冻结资金并等待订单对账",
                )
                self.audit.record(
                    "ORDER_SUBMISSION_FAILED", source="futu_execution", outcome="FAILURE",
                    account_id=row["account_id"], channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                    decision_id=row["decision_id"], correlation_id=row["decision_id"],
                    details={"side": row["side"], "quantity": row["quantity"], "error": str(exc)},
                )
                raise
            try:
                self._validate_order(row, order)
            except ValueError as exc:
                self.store.update_account_intent_status(
                    row["intent_id"], "SUBMISSION_UNCERTAIN"
                )
                self.store.set_virtual_health(
                    row["account_id"], "BLOCKED",
                    f"Futu已返回订单，但订单回报与意图不一致：{exc}",
                )
                raise
            submitted_event = self.audit.build(
                "ORDER_SUBMITTED", source="futu_execution", account_id=row["account_id"],
                strategy_id=account["strategy_id"], strategy_version=account["strategy_version"],
                release_hash=account["release_hash"], channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                decision_id=row["decision_id"], order_id=order.channel_order_id,
                correlation_id=row["decision_id"],
                details={
                    "side": row["side"], "quantity": row["quantity"],
                    "order_type": row["payload"].get("order_type", "LIMIT"),
                    "limit_price": row["limit_price"], "status": order.status,
                },
            )
            try:
                self.store.bind_channel_order(
                    row["intent_id"], order.channel_order_id, asdict(order), submitted_event,
                )
            except Exception:
                self.store.update_account_intent_status(
                    row["intent_id"], "SUBMISSION_UNCERTAIN"
                )
                self.store.set_virtual_health(
                    row["account_id"], "BLOCKED",
                    "Futu已返回订单，但本地绑定失败，等待双向对账",
                )
                raise
        if deterministic_failures:
            summary = "; ".join(
                f"{intent_id}: {type(exc).__name__}: {exc}"
                for intent_id, exc in deterministic_failures
            )
            raise OrderSubmissionBatchError(
                f"{len(deterministic_failures)} order submission(s) failed: {summary}"
            )
        return self.status()

    def acknowledge_execution_gap(
        self, account_id: str, intent_id: str, resolution_note: str,
    ):
        """Resolve one reviewed execution gap after a fresh broker reconciliation."""
        self.refresh_orders()
        intent = self.store.account_intent(intent_id)
        if intent is None or intent["account_id"] != account_id:
            raise KeyError(intent_id)
        resolved = self.store.resolve_account_intent_attention(intent_id, resolution_note)
        if (
            not self.store.unresolved_account_intents(account_id)
            and not self.store.attention_account_intents(account_id)
        ):
            self.store.set_virtual_health(account_id, "OK")
        account = self.store.virtual_account(account_id)
        self.audit.record(
            "ACCOUNT_RECONCILIATION_RECOVERED", source="operator.reconciliation",
            actor_type="OPERATOR", account_id=account_id,
            strategy_id=account.get("strategy_id"),
            strategy_version=account.get("strategy_version"),
            release_hash=account.get("release_hash"), channel=FUTU_SIMULATE_CN_CHANNEL_ID,
            decision_id=intent["decision_id"],
            details={
                "reason": "execution_gap_acknowledged", "intent_id": intent_id,
                "resolution_note": resolution_note,
            },
        )
        return resolved

    def repair_account_ledger(self, account_id: str, intent_id: str):
        """Repair only a proven missing release after a fresh broker account snapshot."""
        self.refresh_account()
        account = self.store.virtual_account(account_id)
        if account is None:
            raise KeyError(account_id)
        symbol = str(account["symbol"])
        broker_quantity = sum(
            int(row.quantity) for row in self._snapshot.positions if row.symbol == symbol
        )
        logical_quantity = sum(
            int(row["quantity"]) for row in self.store.strategy_virtual_accounts()
            if row["symbol"] == symbol and row.get("status") != "RETIRED"
        )
        if broker_quantity != logical_quantity:
            raise ValueError("broker quantity differs from logical quantity; ledger repair blocked")
        intent = self.store.account_intent(intent_id)
        if intent is None or intent["account_id"] != account_id:
            raise KeyError(intent_id)
        event = self.audit.build(
            "ACCOUNT_LEDGER_REPAIRED", source="operator.ledger_repair",
            actor_type="OPERATOR", account_id=account_id,
            strategy_id=account.get("strategy_id"),
            strategy_version=account.get("strategy_version"),
            release_hash=account.get("release_hash"), symbol=symbol, channel=FUTU_SIMULATE_CN_CHANNEL_ID,
            decision_id=intent["decision_id"], correlation_id=intent_id,
            details={
                "intent_id": intent_id,
                "reason": "missing_reservation_generation_release",
                "reservation_generation": intent["reservation_generation"],
            },
        )
        return self.store.repair_released_intent_ledger(account_id, intent_id, event)

    def refresh(self):
        self.refresh_orders()
        self.submit_pending(reconcile=False)
        return self.status()

    def retire_account(self, request: AccountRetirementRequest) -> AccountRetirementResult:
        """Reconcile live channel facts, then return an idle account's cash atomically."""
        if type(request) is not AccountRetirementRequest:
            raise TypeError("retirement requires AccountRetirementRequest")
        if self._draining:
            raise RuntimeError("PTE is stopping; account retirement is unavailable")
        with self.store._lock:
            account = self.store.virtual_account(request.account_id)
            if account["status"] != "RUNNING" or not account["paused"]:
                raise ValueError("retirement requires a paused running account")
            if account["release_hash"] != request.expected_release_hash:
                raise ValueError("retirement release hash differs from account")
            if account["quantity"] or Decimal(account["frozen_cash"]) != 0:
                raise ValueError("retirement requires no position or frozen cash")
            # Reconcile only. Retirement must never submit or liquidate orders.
            self._refresh_orders(expire_orders=False)
            accounts = [row for row in self.store.virtual_accounts() if row["status"] != "RETIRED"]
            expected_cash = self.store.capital_pool_balance().unallocated_cash + sum(
                (Decimal(row["cash"]) + Decimal(row["frozen_cash"]) for row in accounts), Decimal("0"),
            )
            actual_cash = Decimal(str(self._snapshot.account.cash))
            if not actual_cash.is_finite() or abs(actual_cash - expected_cash) > Decimal("0.01"):
                raise ChannelReconciliationError("cash reconciliation differs before retirement")
            return self.store._retire_account(request)

    def status(self):
        account = None if self._snapshot is None else asdict(self._snapshot.account)
        positions = [] if self._snapshot is None else [asdict(row) for row in self._snapshot.positions]
        reconciliation = self.store.get_setting("channel_reconciliation_status")
        symbols = sorted({row["symbol"] for row in self.store.strategy_virtual_accounts()})
        actual_by_symbol = {
            symbol: sum(row["quantity"] for row in positions if row["symbol"] == symbol)
            for symbol in symbols
        }
        cash_reconciliation = self.store.get_setting("futu_cash_reconciliation_status")
        alerts = ["CHANNEL_RECONCILIATION_BLOCKED"] if reconciliation == "BLOCKED" else []
        if cash_reconciliation in {"UNATTRIBUTED", "OUT_OF_RANGE", "AMBIGUOUS"}:
            alerts.append(f"FUTU_CASH_RECONCILIATION_{cash_reconciliation}")
        return {
            "environment": None if account is None else account["environment"],
            "market": None if account is None else account["market"],
            "symbol": symbols[0] if len(symbols) == 1 else None,
            "symbols": symbols,
            "account": account, "positions": positions,
            "actual_quantity": sum(actual_by_symbol.values()),
            "actual_quantity_by_symbol": actual_by_symbol,
            "orders": self.store.account_orders(),
            "paused": self.store.is_paused(),
            "reconciliation_status": reconciliation,
            "cash_reconciliation_status": cash_reconciliation,
            "last_reconcile_at": self.store.get_setting("last_reconcile_at"),
            "alerts": alerts,
            "scheduler_failures": self.store.operation_failures(),
        }

    def pause(self):
        self.store.set_paused(True)
        return self.status()

    def resume(self):
        self.refresh_account()
        self.refresh_orders()
        self.store.set_paused(False)
        return self.status()

    def issue_cancel_token(self, account_id: str, channel_order_id: str) -> str:
        order = self.store.account_order(channel_order_id)
        if order["account_id"] != account_id:
            raise ChannelReconciliationError("撤单账户与订单归属不一致")
        token = secrets.token_urlsafe(24)
        expires = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
        self.store.save_cancel_token(token, channel_order_id, expires)
        return token

    def confirm_cancel(self, account_id: str, channel_order_id: str, token: str):
        order = self.store.account_order(channel_order_id)
        if order["account_id"] != account_id:
            raise ChannelReconciliationError("撤单账户与订单归属不一致")
        now = datetime.now(timezone.utc).isoformat()
        result = self.store.consume_cancel_token(token, channel_order_id, now)
        if result != "ok":
            raise ValueError("cancel token is invalid, expired, used, or belongs to another order")
        account = self.store.virtual_account(account_id)
        self.audit.record(
            "CANCEL_REQUESTED", source="futu_execution", actor_type="OPERATOR",
            account_id=account_id, channel=FUTU_SIMULATE_CN_CHANNEL_ID, decision_id=order["decision_id"],
            strategy_id=account["strategy_id"],
            strategy_version=account["strategy_version"],
            release_hash=account["release_hash"],
            order_id=channel_order_id, correlation_id=order["decision_id"], details={},
        )
        try:
            self.broker.cancel_order(channel_order_id)
        except Exception as exc:
            self.audit.record(
                "CANCEL_FAILED", source="futu_execution", outcome="FAILURE",
                actor_type="OPERATOR", account_id=account_id, channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                strategy_id=account["strategy_id"],
                strategy_version=account["strategy_version"],
                release_hash=account["release_hash"],
                decision_id=order["decision_id"], order_id=channel_order_id,
                correlation_id=order["decision_id"],
                details={"error_type": type(exc).__name__, "error": str(exc)},
            )
            raise
        return self.status()

    def close(self):
        close = getattr(self.broker, "close", None)
        if close is not None:
            close()
        self.store.close()
