"""Account-owned strategy decisions and durable Futu order intents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from threading import RLock

from .audit import AuditRecorder
from .broker import TERMINAL_INTENT_STATUSES
from .channel import FUTU_SIMULATE_CN_CHANNEL_ID
from .store import PaperStore


class AccountRefreshBatchError(RuntimeError):
    """One or more active virtual accounts failed to refresh."""


class ActiveOrderPendingError(RuntimeError):
    """A newer decision must wait until an older order reaches a known terminal state."""


class AccountDecisionBlockedError(RuntimeError):
    """The account cannot safely turn a strategy decision into durable order intents."""


@dataclass(frozen=True)
class AccountDecisionDriveResult:
    account_status: dict[str, object]
    outcome: str
    superseded_decision_id: str | None = None
    superseded_intent_ids: tuple[str, ...] = ()


class AccountEngine:
    _BEIJING = timezone(timedelta(hours=8), "Asia/Shanghai")

    @staticmethod
    def _replacement_intent_snapshot(intents) -> tuple[tuple[object, ...], ...]:
        """Capture every field that determines whether projected cash is still valid."""
        return tuple(sorted(
            (
                str(row["intent_id"]),
                str(row["decision_id"]),
                str(row["status"]),
                row.get("channel_order_id"),
                int(row.get("reservation_generation", 0)),
                str(row["side"]),
                int(row["quantity"]),
                str(row["limit_price"]),
                str(row["payload"].get("fee_rate", "0.0005")),
            )
            for row in intents
        ))

    @staticmethod
    def _cash_after_replaceable_intents(account, intents) -> Decimal:
        """Project cash after unsubmitted intents release their reservations."""
        release = Decimal("0")
        for row in intents:
            if str(row["side"]).upper() != "BUY":
                continue
            if int(row.get("reservation_generation", 0)) <= 0:
                raise AccountDecisionBlockedError(
                    "待替代买入意图缺少可核验的资金预占"
                )
            fee_rate = Decimal(str(row["payload"].get("fee_rate", "0.0005")))
            release += (
                Decimal(str(row["limit_price"]))
                * int(row["quantity"])
                * (Decimal("1") + fee_rate)
            ).quantize(Decimal("0.0001"))
        release = release.quantize(Decimal("0.0001"))
        frozen_cash = Decimal(str(account["frozen_cash"]))
        if release > frozen_cash:
            raise AccountDecisionBlockedError("待替代意图预占资金超过账户冻结资金")
        return (Decimal(str(account["cash"])) + release).quantize(Decimal("0.0001"))

    @classmethod
    def _planning_revision(cls, account, intents) -> int:
        """Fingerprint all authoritative values used to size a replacement plan."""

        facts = {
            "cash": str(account["cash"]),
            "frozen_cash": str(account["frozen_cash"]),
            "total_assets": str(account["total_assets"]),
            "quantity": int(account["quantity"]),
            "cycle_target": account.get("cycle_target"),
            "active_intents": cls._replacement_intent_snapshot(intents),
        }
        encoded = json.dumps(facts, sort_keys=True, separators=(",", ":"))
        return int(sha256(encoded.encode("utf-8")).hexdigest()[:15], 16)

    @staticmethod
    def _state_revision(account) -> int:
        encoded = json.dumps(
            {"cycle_target": account.get("cycle_target")},
            sort_keys=True,
            separators=(",", ":"),
        )
        return int(sha256(encoded.encode("utf-8")).hexdigest()[:15], 16)

    @staticmethod
    def _effective_portfolio_revision(account, available_cash: Decimal) -> int:
        """Identify the portfolio after replaceable reservations are released."""

        encoded = json.dumps(
            {
                "available_cash": str(available_cash),
                "total_assets": str(account["total_assets"]),
                "quantity": int(account["quantity"]),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return int(sha256(encoded.encode("utf-8")).hexdigest()[:15], 16)

    def __init__(
        self, store: PaperStore, advice, audit: AuditRecorder | None = None,
        now=None,
    ) -> None:
        self.store = store
        self.advice = advice
        self.audit = audit or AuditRecorder(store)
        self.now = now or (lambda: datetime.now(self._BEIJING))
        self._draining = False
        self._decision_lock = RLock()

    def begin_shutdown(self) -> None:
        # Wait for an in-flight decision to finish persisting its intents.  Once
        # draining is visible, no later decision is allowed to start.
        with self._decision_lock:
            self._draining = True

    def _assign_decision_id(self, account_id: str, previous_payload, decision):
        source_id = decision.source_decision_id or decision.decision_id
        previous = json.loads(previous_payload) if previous_payload else None
        same_plan = bool(
            previous
            and (
                previous.get("plan_identity") == decision.plan_identity
                or (
                    not previous.get("plan_identity")
                    and (
                        previous.get("source_decision_id")
                        or previous.get("decision_id")
                    ) == source_id
                )
            )
        )
        if same_plan and self.store.account_decision(account_id, str(previous["decision_id"]))["status"] in {"CANCELLED", "INCOMPLETE", "SUPERSEDED"}:
            same_plan = False
        if same_plan:
            return replace(
                decision,
                decision_id=str(previous["decision_id"]),
                source_decision_id=source_id,
            )

        generated_at = self.now()
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=self._BEIJING)
        else:
            generated_at = generated_at.astimezone(self._BEIJING)
        stamp = generated_at.strftime("%Y%m%d-%H%M")
        suffix = sha256(
            f"{account_id}\0{decision.plan_identity}\0{generated_at.isoformat()}".encode("utf-8")
        ).hexdigest()[:12].upper()
        return replace(
            decision,
            decision_id=f"DEC-{stamp}-{suffix}",
            source_decision_id=source_id,
        )

    def refresh_account(self, account_id: str, *, prepared):
        with self._decision_lock:
            return self._refresh_account(account_id, prepared=prepared)

    def drive_account_decision(self, account_id: str, *, prepared):
        """Evaluate one account and supersede only local, unsubmitted prior work."""
        with self._decision_lock:
            return self._refresh_account(
                account_id, prepared=prepared, operator_drive=True
            )

    def _refresh_account(
        self, account_id: str, *, prepared, operator_drive: bool = False
    ):
        account = self.store.virtual_account(account_id)
        if self._draining:
            raise AccountDecisionBlockedError("PTE正在停止，禁止生成新的账户决策")
        if account["run_state"] == "RETIRED":
            raise AccountDecisionBlockedError(
                f"虚拟账户状态不允许生成决策: {account['run_state']}"
            )
        if account["health"] == "BLOCKED":
            raise AccountDecisionBlockedError(
                f"虚拟账户已阻塞，禁止生成新的决策: {account.get('last_error') or account_id}"
            )
        previous_payload = account.get("last_decision_payload")
        active_intents = [
            row for row in self.store.account_intents(account_id)
            if row["status"] not in TERMINAL_INTENT_STATUSES
        ]
        if prepared is None:
            raise AccountDecisionBlockedError("PTE尚无已准备完成的策略数据")
        prepared_through = prepared.available_through.isoformat()
        try:
            datetime.strptime(str(prepared_through), "%Y-%m-%d").date()
        except ValueError as exc:
            raise AccountDecisionBlockedError("PTE数据发布日期格式无效") from exc
        window = prepared.tradable_window
        if window.start != window.end:
            raise AccountDecisionBlockedError("PTE单次决策要求单交易日策略窗口")
        source_revision = self._planning_revision(account, active_intents)
        state_revision = self._state_revision(account)
        decision_cash = Decimal(str(account["cash"]))
        replacement_snapshot: tuple[tuple[object, ...], ...] | None = None
        if active_intents:
            previous = json.loads(previous_payload) if previous_payload else {}
            replaceable = (
                operator_drive
                and bool(previous.get("decision_id"))
                and all(
                    row["decision_id"] == previous["decision_id"]
                    and row["status"] in {"PENDING_SUBMIT", "WAITING_DEPENDENCY"}
                    and row.get("channel_order_id") is None
                    for row in active_intents
                )
            )
            if operator_drive and not replaceable:
                message = "存在已提交或状态不确定的订单，禁止替换账户决策"
                self.audit.record(
                    "ORDER_SUBMISSION_BLOCKED", source="account_engine", outcome="SKIPPED",
                    account_id=account_id, strategy_id=account["strategy_id"],
                    strategy_version=account["strategy_version"],
                    release_hash=account["release_hash"], symbol=account["symbol"],
                    correlation_id=(
                        previous.get("decision_id") or active_intents[0]["intent_id"]
                    ),
                    details={
                        "reason": "manual_decision_with_nonreplaceable_order",
                        "prepared_through": prepared_through,
                        "active_intent_ids": [row["intent_id"] for row in active_intents],
                    },
                )
                raise ActiveOrderPendingError(message)
            if replaceable:
                # Size the replacement against the cash that the final atomic
                # update will release, without exposing a transient cash balance.
                replacement_snapshot = self._replacement_intent_snapshot(active_intents)
                decision_cash = self._cash_after_replaceable_intents(account, active_intents)
            if not operator_drive and prepared_through != previous.get("signal_date"):
                message = "存在未完成订单，新数据决策暂缓生成并等待对账"
                self.audit.record(
                    "ORDER_SUBMISSION_BLOCKED", source="account_engine", outcome="SKIPPED",
                    account_id=account_id, strategy_id=account["strategy_id"],
                    strategy_version=account["strategy_version"],
                    release_hash=account["release_hash"], symbol=account["symbol"],
                    correlation_id=f"prepared-data:{prepared_through}",
                    details={
                        "reason": "previous_order_active",
                        "prepared_through": prepared_through,
                        "active_intent_ids": [row["intent_id"] for row in active_intents],
                    },
                )
                raise ActiveOrderPendingError(message)
            if not operator_drive:
                return self.status(account_id)
        portfolio_revision = self._effective_portfolio_revision(account, decision_cash)
        previous_action = (
            json.loads(previous_payload).get("action") if previous_payload else None
        )
        trading_date = window.start
        decision = self.advice.get_decision(
            int(account["quantity"]), float(decision_cash),
            total_assets=float(account["total_assets"]),
            trading_date=trading_date,
            portfolio_revision=portfolio_revision,
            state_revision=state_revision,
            cycle_target_quantity=account["cycle_target"],
            strategy_id=account["strategy_id"],
            strategy_version=account["strategy_version"],
            account_id=account_id,
            symbol=account["symbol"],
            asset=account["asset_type"],
            prepared=prepared,
        )
        decision = self._assign_decision_id(account_id, previous_payload, decision)
        expected = (
            account["strategy_id"], account["strategy_version"], account["release_hash"],
        )
        actual = (
            decision.strategy.get("strategy_id"), decision.strategy.get("version"),
            decision.strategy.get("release_hash"),
        )
        if actual != expected:
            raise ValueError("advice strategy release differs from account")
        if decision.symbol != account["symbol"]:
            raise ValueError("advice symbol differs from account")
        if decision.actual_quantity != int(account["quantity"]):
            raise ValueError("advice quantity differs from account")
        if decision.portfolio_revision != portfolio_revision:
            raise ValueError("advice portfolio revision differs from account")
        if decision.state_revision != state_revision:
            raise ValueError("advice state revision differs from account")

        # Re-read the account after the potentially long-running strategy call.
        # Store-level intent creation performs the same gate inside its transaction.
        execution_account = self.store.virtual_account(account_id)
        if execution_account["run_state"] == "RETIRED":
            raise AccountDecisionBlockedError(
                f"虚拟账户状态不允许执行决策: {execution_account['run_state']}"
            )
        if execution_account["health"] == "BLOCKED":
            raise AccountDecisionBlockedError(
                "虚拟账户在策略计算期间被阻塞，决策未提交"
            )
        if self._draining:
            raise AccountDecisionBlockedError("PTE正在停止，决策未提交")
        current_intents = [
            row for row in self.store.account_intents(account_id)
            if row["status"] not in TERMINAL_INTENT_STATUSES
        ]
        if (
            replacement_snapshot is not None
            and self._replacement_intent_snapshot(current_intents)
            != replacement_snapshot
        ):
            raise ActiveOrderPendingError("订单已提交或状态已变化，禁止替换账户决策")
        if self._planning_revision(execution_account, current_intents) != source_revision:
            raise AccountDecisionBlockedError(
                "账户资金、持仓或订单状态在策略计算期间发生变化，决策未提交"
            )
        if self._state_revision(execution_account) != state_revision:
            raise AccountDecisionBlockedError(
                "账户策略状态在策略计算期间发生变化，决策未提交"
            )

        payload = asdict(decision)
        payload["prepared_data_identity"] = prepared.data_identity
        payload["prepared_data_reference"] = dict(prepared.data_reference)
        previous = json.loads(previous_payload) if previous_payload else None
        if (
            previous is not None
            and previous.get("decision_id") == payload.get("decision_id")
            and "prepared_data_identity" not in previous
        ):
            payload.pop("prepared_data_identity", None)
        previous_decision_id = previous.get("decision_id") if previous else None
        supersede_previous = bool(
            operator_drive
            and previous_decision_id
            and decision.decision_id != previous_decision_id
            and self.store.account_decision(account_id, str(previous_decision_id))["status"] == "PENDING"
            and (
                decision.valid_session.isoformat() == previous.get("valid_session")
                or decision.signal_date.isoformat() == previous.get("signal_date")
                or active_intents
            )
        )
        superseded_intent_ids: tuple[str, ...] = ()
        if supersede_previous:
            with self.store.atomic_decision_update():
                locked_account = self.store.virtual_account(account_id)
                current_active = [
                    row for row in self.store.account_intents(account_id)
                    if row["status"] not in TERMINAL_INTENT_STATUSES
                ]
                if (self._planning_revision(locked_account, current_active) != source_revision
                        or locked_account["release_hash"] != account["release_hash"]
                        or locked_account["run_state"] != execution_account["run_state"]
                        or locked_account["health"] == "BLOCKED"):
                    raise AccountDecisionBlockedError("账户在替换提交前发生变化，决策未提交")
                replacement_state_changed = (
                    bool(current_active)
                    if replacement_snapshot is None
                    else self._replacement_intent_snapshot(current_active)
                    != replacement_snapshot
                )
                if (
                    replacement_state_changed
                    or any(
                        row["decision_id"] != previous_decision_id
                        or row["status"] not in {"PENDING_SUBMIT", "WAITING_DEPENDENCY"}
                        or row.get("channel_order_id") is not None
                        for row in current_active
                    )
                ):
                    raise ActiveOrderPendingError(
                        "订单已提交或状态已变化，禁止替换账户决策"
                    )
                superseded_intent_ids = tuple(
                    str(row["intent_id"]) for row in current_active
                )
                for row in current_active:
                    intent_id = str(row["intent_id"])
                    self.store.release_account_intent(
                        intent_id, "SUPERSEDED", _in_transaction=True,
                        audit_event=self.audit.build(
                            "ORDER_INTENT_SUPERSEDED", source="account_engine",
                            account_id=account_id, strategy_id=account["strategy_id"],
                            strategy_version=account["strategy_version"],
                            release_hash=account["release_hash"], symbol=account["symbol"],
                            channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                            decision_id=str(previous_decision_id),
                            correlation_id=decision.decision_id,
                            details={
                                "intent_id": intent_id,
                                "superseded_by": decision.decision_id,
                                "previous_status": row["status"],
                            },
                        ),
                    )
                self.store.supersede_account_decision(
                    account_id, str(previous_decision_id), decision.decision_id,
                    _in_transaction=True,
                    audit_event=self.audit.build(
                        "DECISION_SUPERSEDED", source="account_engine",
                        account_id=account_id, strategy_id=account["strategy_id"],
                        strategy_version=account["strategy_version"],
                        release_hash=account["release_hash"], symbol=account["symbol"],
                        decision_id=str(previous_decision_id),
                        correlation_id=decision.decision_id,
                        details={
                            "superseded_by": decision.decision_id,
                            "signal_date": decision.signal_date.isoformat(),
                            "superseded_intent_ids": list(superseded_intent_ids),
                        },
                    ),
                )
                status = self._persist_generated_decision(
                    account_id, payload, locked_account, decision, account,
                    previous_action,
                )
        else:
            with self.store.atomic_decision_update():
                locked_account = self.store.virtual_account(account_id)
                locked_intents = [row for row in self.store.account_intents(account_id)
                                  if row["status"] not in TERMINAL_INTENT_STATUSES]
                if (self._planning_revision(locked_account, locked_intents) != source_revision
                        or locked_account["release_hash"] != account["release_hash"]
                        or locked_account["run_state"] != execution_account["run_state"]
                        or locked_account["health"] == "BLOCKED"):
                    raise AccountDecisionBlockedError("账户在提交前发生变化，决策未提交")
                status = self._persist_generated_decision(
                    account_id, payload, locked_account, decision, account, previous_action,
                )
        if not operator_drive:
            return status
        if supersede_previous:
            outcome = (
                "DECISION_AND_INTENTS_SUPERSEDED"
                if superseded_intent_ids else "DECISION_SUPERSEDED"
            )
        elif decision.decision_id == previous_decision_id:
            outcome = "DECISION_REUSED"
        else:
            outcome = "DECISION_COMPLETED"
        return AccountDecisionDriveResult(
            account_status=status,
            outcome=outcome,
            superseded_decision_id=(
                str(previous_decision_id) if supersede_previous else None
            ),
            superseded_intent_ids=superseded_intent_ids,
        )

    def _persist_generated_decision(
        self, account_id, payload, execution_account, decision, account, previous_action,
    ):
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
                        "ORDER_INTENT_CREATED", source="account_engine", channel=FUTU_SIMULATE_CN_CHANNEL_ID,
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
                    fee_rate=decision.fee_rate,
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
                        channel=FUTU_SIMULATE_CN_CHANNEL_ID, **scope,
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
                    fee_rate=decision.fee_rate,
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
        return self.status(account_id)

    def status(self, account_id: str):
        account = self.store.virtual_account(account_id)
        payload = account.pop("last_decision_payload", None)
        return {
            **account,
            "released_cash": self.store._retirement_cash(account_id),
            "last_decision": json.loads(payload) if payload else None,
            "orders": self.store.account_orders(account_id),
            "fills": self.store.account_fills(account_id),
            "snapshots": self.store.account_snapshots(account_id),
            "metrics": self.metrics(account_id),
        }

    def metrics(self, account_id: str, start: str | None = None, end: str | None = None):
        from .performance_export import calculate_metrics, closed_trade_pnl

        account = self.store.virtual_account(account_id)
        all_snapshots = self.store.account_snapshots(account_id)
        snapshots = [
            row for row in all_snapshots
            if (start is None or row["session"] >= start)
            and (end is None or row["session"] <= end)
        ]
        baseline = float(account["initial_cash"])
        if start is not None:
            prior = [row for row in all_snapshots if row["session"] < start]
            if prior:
                baseline = float(prior[-1]["total_assets"])
        effective_end = end or (snapshots[-1]["session"] if snapshots else None)

        def fill_session(row) -> str:
            value = datetime.fromisoformat(str(row["occurred_at"]).replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=self._BEIJING)
            return value.astimezone(self._BEIJING).date().isoformat()

        fills = [] if not snapshots else [
            row for row in self.store.account_fills(account_id)
            if row["side"] == "SELL"
            and (start is None or fill_session(row) >= start)
            and fill_session(row) <= effective_end
        ]
        calculated = calculate_metrics(
            baseline, snapshots, closed_trade_pnl(fills),
        )
        return {
            "observation_start": snapshots[0]["session"] if snapshots else None,
            "observation_end": snapshots[-1]["session"] if snapshots else None,
            "baseline_assets": baseline,
            **calculated,
        }
