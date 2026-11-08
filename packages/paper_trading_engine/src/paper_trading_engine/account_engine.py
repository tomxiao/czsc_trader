"""Account-owned strategy decisions and durable Futu order intents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from threading import RLock

from strategy_runtime import EntryCycleState

from execution_channels.futu.audit import AuditRecorder
from execution_channels.futu.broker import IntentTerminationReason, TERMINAL_INTENT_STATUSES
from execution_channels.futu.store import PaperStore
from execution_channels.futu.lifecycle import AccountHealth


_NORMAL_ATTEMPT_REASONS = frozenset(IntentTerminationReason) | {
    "PLANNING_BLOCKED", "OBSERVATION_SUPPRESSED",
}


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
            "entry_cycle_json": account.get("entry_cycle_json"),
            "active_intents": cls._replacement_intent_snapshot(intents),
        }
        if account.get("account_v4_json") is not None:
            facts["account_v4_json"] = account["account_v4_json"]
        encoded = json.dumps(facts, sort_keys=True, separators=(",", ":"))
        return int(sha256(encoded.encode("utf-8")).hexdigest()[:15], 16)

    @staticmethod
    def _state_revision(account) -> int:
        facts = {"cycle_target": account.get("cycle_target"), "entry_cycle_json": account.get("entry_cycle_json")}
        if account.get("account_v4_json") is not None:
            facts["account_v4_json"] = account["account_v4_json"]
        encoded = json.dumps(
            facts,
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
        previous_record = None if previous is None else self.store.account_decision(
            account_id, str(previous["decision_id"]),
        )
        # A legacy entry-cycle or partial fill can change the order plan while
        # retaining the same signal/session. It must not rearm an ended attempt.
        same_legacy_signal = bool(
            previous and previous.get("signal_identity") == decision.signal_identity
            and previous.get("plan_mode", "NONE") == decision.plan_mode
            and (previous_record["state_reason"] == IntentTerminationReason.NORMAL_PARTIAL or (
                previous.get("orders", []) == [asdict(order) for order in decision.orders]
                and previous.get("order") == (None if decision.order is None else asdict(decision.order))
                and previous.get("plan_legs", []) == json.loads(json.dumps(
                    [asdict(leg) for leg in decision.plan_legs], default=str,
                ))
            ))
        )
        normal_repeat = bool(
            previous_record and previous_record["state_reason"] in _NORMAL_ATTEMPT_REASONS
            and previous.get("valid_session") == decision.valid_session.isoformat()
            and same_legacy_signal
        )
        same_plan = bool(
            previous
            and previous.get("valid_session") == decision.valid_session.isoformat()
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
        same_plan = same_plan or normal_repeat
        if same_plan:
            if (previous_record["status"] in {"CANCELLED", "INCOMPLETE", "SUPERSEDED"}
                    and previous_record["state_reason"] not in _NORMAL_ATTEMPT_REASONS):
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

    def refresh_account(self, account_id: str, *, prepared, require_paused: bool = False):
        with self._decision_lock:
            return self._refresh_account(account_id, prepared=prepared, require_paused=require_paused)

    def drive_account_decision(self, account_id: str, *, prepared):
        """Evaluate one account and supersede only local, unsubmitted prior work."""
        with self._decision_lock:
            return self._refresh_account(
                account_id, prepared=prepared, operator_drive=True
            )

    def _refresh_account(
        self, account_id: str, *, prepared, operator_drive: bool = False, require_paused: bool = False
    ):
        account = self.store.virtual_account(account_id)
        if require_paused and account["run_state"] != "PAUSED":
            raise AccountDecisionBlockedError("manual V4 validation requires a paused strategy account")
        if self._draining:
            raise AccountDecisionBlockedError("PTE正在停止，禁止生成新的账户决策")
        if account["run_state"] == "RETIRED":
            raise AccountDecisionBlockedError(
                f"虚拟账户状态不允许生成决策: {account['run_state']}"
            )
        if account["health"] != AccountHealth.OK:
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
        # Re-reading an ended V4 interval is a read, not a calculation using
        # today's fills at the earlier decision point. Keep the observation
        # integrity checks, but do not run strategy or planning again.
        from .equity_advice import PreparedEquityDecision
        previous = json.loads(previous_payload) if previous_payload else None
        if previous and not active_intents and type(prepared) is PreparedEquityDecision:
            prior = self.store.account_decision(account_id, previous['decision_id'])
            interval = {'start': prepared.interval.start.isoformat(), 'end': prepared.interval.end.isoformat()}
            if (prior['state_reason'] in _NORMAL_ATTEMPT_REASONS
                    and previous.get('contract_version') == 'advice.equity.v4'
                    and previous.get('prepared_data_identity') == prepared.data_identity
                    and previous.get('equity_execution_interval') == interval
                    and previous.get('equity_observed_through') == prepared.execution_reference.observed_through.isoformat()
                    and previous['strategy']['release_hash'] == account['release_hash']
                    and previous.get('runtime_sha256') == prepared.candidate.implementation_hash):
                prepared.validate_unchanged()
                status = self.status(account_id)
                if operator_drive:
                    return AccountDecisionDriveResult(account_status=status, outcome="DECISION_REUSED")
                return status
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
            entry_cycle=None if account.get("entry_cycle_json") is None else EntryCycleState.from_dict(json.loads(account["entry_cycle_json"])),
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
        if require_paused and execution_account["run_state"] != "PAUSED":
            raise AccountDecisionBlockedError("account resumed during manual V4 validation")
        if execution_account["run_state"] == "RETIRED":
            raise AccountDecisionBlockedError(
                f"虚拟账户状态不允许执行决策: {execution_account['run_state']}"
            )
        if execution_account["health"] != AccountHealth.OK:
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

        previous = json.loads(previous_payload) if previous_payload else None
        if (previous is not None and decision.decision_id == previous.get("decision_id")
                and self.store.account_decision(account_id, decision.decision_id)["state_reason"] in _NORMAL_ATTEMPT_REASONS):
            # Ended normally for this plan/session. Reading it again is not an
            # instruction to rearm the same order; keep the terminal Store gate.
            status = self.status(account_id)
            if operator_drive:
                return AccountDecisionDriveResult(account_status=status, outcome="DECISION_REUSED")
            return status

        payload = decision.to_store_payload()
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
                        or locked_account["health"] != AccountHealth.OK):
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
                            channel=self.store.virtual_account(account_id)["channel_id"],
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
                        or locked_account["health"] != AccountHealth.OK):
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
        from execution_channels.futu.adoption import AccountAdoption, DecisionAdoption
        AccountAdoption(self.store, self.audit).adopt(DecisionAdoption(
            account_id, json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"), previous_action),
            in_transaction=True)
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
            rules = self.store.equity_account_rules(account_id)
            zone = self._BEIJING if rules is None else rules.timezone
            if value.tzinfo is None:
                if rules is not None:
                    raise ValueError("US fills require timezone-aware channel timestamps")
                value = value.replace(tzinfo=zone)
            return value.astimezone(zone).date().isoformat()

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
