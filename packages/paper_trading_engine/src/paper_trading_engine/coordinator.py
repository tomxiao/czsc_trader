"""Account-centric runtime facade for scheduler, CLI, and web console."""

from threading import RLock

from .account_engine import AccountRefreshBatchError
from .audit import AuditRecorder
from .account_retirement import AccountRetirementRequest, AccountRetirementResult
from .futu_gateway import FutuGatewayError
from .channel import FUTU_SIMULATE_CN_CHANNEL_ID
from .trading_window import shanghai_now


class UnavailableExecution:
    def __init__(self, store, symbol: str, error: Exception) -> None:
        self.store, self.symbol, self.initial_error = store, symbol, str(error)

    def _raise(self, *args, **kwargs):
        raise RuntimeError(self.initial_error)

    refresh = refresh_account = refresh_orders = submit_pending = _raise

    def status(self):
        return {
            "environment": "SIMULATE", "market": "CN", "symbol": self.symbol,
            "account": None, "positions": [], "orders": self.store.account_orders(),
            "paused": self.store.is_paused(),
            "reconciliation_status": "UNAVAILABLE", "alerts": ["CHANNEL_UNAVAILABLE"],
            "scheduler_failures": self.store.operation_failures(),
        }

    def pause(self):
        self.store.set_paused(True)
        return self.status()

    def resume(self): raise RuntimeError("successful channel reconciliation required before resume")
    def issue_cancel_token(self, account_id, channel_order_id): raise RuntimeError("channel is unavailable")
    def confirm_cancel(self, account_id, channel_order_id, token): raise RuntimeError("channel is unavailable")
    def acknowledge_execution_gap(self, account_id, intent_id, resolution_note):
        raise RuntimeError("channel is unavailable")
    def repair_account_ledger(self, account_id, intent_id):
        raise RuntimeError("channel is unavailable")
    def retire_account(self, request: AccountRetirementRequest) -> AccountRetirementResult:
        raise RuntimeError("channel is unavailable")
    def begin_shutdown(self): return None
    def close(self): self.store.close()


class ReconnectableExecution:
    """Keep channel recovery inside PTE when OpenD appears after PTE startup."""

    def __init__(self, store, symbol: str, factory, *, initial=None, error=None) -> None:
        self.store = store
        self.symbol = symbol
        self.factory = factory
        self._delegate = initial
        self._last_error = None if error is None else str(error)
        self._lock = RLock()

    def _execution(self):
        with self._lock:
            if self._delegate is None:
                try:
                    self._delegate = self.factory()
                except Exception as exc:
                    self._last_error = str(exc)
                    raise
                self._last_error = None
            return self._delegate

    def _call(self, method: str, *args, **kwargs):
        delegate = self._execution()
        try:
            return getattr(delegate, method)(*args, **kwargs)
        except FutuGatewayError as exc:
            with self._lock:
                if self._delegate is delegate:
                    close = getattr(getattr(delegate, "broker", None), "close", None)
                    if close is not None:
                        close()
                    self._delegate = None
                    self._last_error = str(exc)
            raise

    def refresh(self): return self._call("refresh")
    def refresh_account(self): return self._call("refresh_account")
    def refresh_orders(self): return self._call("refresh_orders")
    def submit_pending(self, *, reconcile=True):
        return self._call("submit_pending", reconcile=reconcile)

    def status(self):
        if self._delegate is not None:
            return self._delegate.status()
        return {
            "environment": "SIMULATE", "market": "CN", "symbol": self.symbol,
            "account": None, "positions": [], "orders": self.store.account_orders(),
            "paused": self.store.is_paused(),
            "reconciliation_status": "UNAVAILABLE", "alerts": ["CHANNEL_UNAVAILABLE"],
            "scheduler_failures": self.store.operation_failures(),
            "last_error": self._last_error,
        }

    def pause(self):
        self.store.set_paused(True)
        return self.status()

    def resume(self): return self._call("resume")
    def issue_cancel_token(self, account_id, channel_order_id):
        return self._call("issue_cancel_token", account_id, channel_order_id)
    def confirm_cancel(self, account_id, channel_order_id, token):
        return self._call("confirm_cancel", account_id, channel_order_id, token)
    def acknowledge_execution_gap(self, account_id, intent_id, resolution_note):
        return self._call("acknowledge_execution_gap", account_id, intent_id, resolution_note)
    def repair_account_ledger(self, account_id, intent_id):
        return self._call("repair_account_ledger", account_id, intent_id)
    def retire_account(self, request: AccountRetirementRequest) -> AccountRetirementResult:
        return self._call("retire_account", request)
    def begin_shutdown(self):
        if self._delegate is not None:
            self._delegate.begin_shutdown()
    def close(self):
        if self._delegate is None:
            self.store.close()
        else:
            self._delegate.close()


class PteCoordinator:
    def __init__(
        self,
        accounts,
        execution,
        *,
        strategy_cycle,
        audit: AuditRecorder | None = None,
        account_chart=None,
        startup_timings: dict[str, float] | None = None,
        runtime_identity: dict[str, object] | None = None,
    ) -> None:
        self.accounts, self.execution = accounts, execution
        self.store = accounts.store
        self.audit = audit or AuditRecorder(self.store)
        self.account_chart = account_chart
        self.strategy_cycle = strategy_cycle
        self.startup_timings = dict(startup_timings or {})
        self.runtime_identity = dict(runtime_identity or {"mode": "DEV"})

    @property
    def virtual(self): return self.accounts

    @property
    def channel(self): return self.execution

    def refresh(self):
        try:
            self.execution.refresh()
        except Exception as exc:
            self.audit.record(
                "DEPENDENCY_DEGRADED", source="coordinator", outcome="FAILURE",
                actor_type="EXTERNAL", actor_id="futu", channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                details={"service": "futu", "operation": "refresh", "error": str(exc)},
            )
            raise
        observed_at = shanghai_now()
        signal_date = self.strategy_cycle.latest_completed_signal_date(observed_at)
        failures = []
        for account in self.store.strategy_virtual_accounts():
            if account.get("run_state") == "RETIRED":
                continue
            try:
                self.strategy_cycle.run(
                    str(account["account_id"]),
                    signal_date=signal_date,
                    observed_at=observed_at,
                )
            except Exception as exc:
                failures.append((str(account["account_id"]), exc))
                self.store.set_virtual_health(
                    str(account["account_id"]), "BLOCKED", str(exc)
                )
                self.audit.record(
                    "VIRTUAL_ACCOUNT_FAILED",
                    source="coordinator",
                    outcome="FAILURE",
                    account_id=str(account["account_id"]),
                    strategy_id=account.get("strategy_id"),
                    strategy_version=account.get("strategy_version"),
                    release_hash=account.get("release_hash"),
                    details={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )
        if failures:
            summary = "; ".join(
                f"{account_id}: {type(exc).__name__}: {exc}"
                for account_id, exc in failures
            )
            raise AccountRefreshBatchError(
                f"{len(failures)} virtual account refresh(es) failed: {summary}"
            )
        return self.status()

    def startup(self):
        """Reconcile and resume durable channel work without generating a new decision."""
        try:
            self.execution.refresh()
        except Exception as exc:
            # A missing OpenD connection is an explicitly supported degraded-start
            # state: ReconnectableExecution exposes it as UNAVAILABLE and retries later.
            # Once a channel delegate exists, reconciliation and ledger failures are
            # internal safety failures and must abort startup instead of looking healthy.
            if self.execution.status().get("reconciliation_status") != "UNAVAILABLE":
                raise
            self.audit.record(
                "DEPENDENCY_DEGRADED", source="coordinator", outcome="FAILURE",
                actor_type="EXTERNAL", actor_id="futu", channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                details={"service": "futu", "operation": "startup", "error": str(exc)},
            )
        return self.status()

    def refresh_account(self): return self.execution.refresh_account()

    def refresh_orders(self):
        self.execution.refresh_orders()
        return self.execution.submit_pending(reconcile=False)

    def drive_virtual_account_decision(self, account_id: str):
        """Drive one virtual account decision and return its operational identity."""
        account = None
        try:
            account = self.store.virtual_account(account_id)
            drive = self.strategy_cycle.run_latest(
                account_id, observed_at=shanghai_now()
            )
            if drive is None:
                raise RuntimeError("最近已完成日期不是交易日，未生成账户决策")
            decision = drive.account_status.get("last_decision")
            required_fields = {
                "decision_id", "signal_date", "valid_session", "action",
                "target_quantity", "execution_reference_price",
            }
            if not isinstance(decision, dict) or not required_fields.issubset(decision):
                raise RuntimeError("账户决策完成后未生成有效决策")
            reused_decision = drive.outcome == "DECISION_REUSED"
            result = {
                "status": drive.outcome,
                "account_id": account_id,
                "decision_id": decision["decision_id"],
                "signal_date": decision["signal_date"],
                "valid_session": decision["valid_session"],
                "action": decision["action"],
                "target_quantity": decision["target_quantity"],
                "execution_reference_price": decision["execution_reference_price"],
                "reused_decision": reused_decision,
            }
            if drive.superseded_decision_id is not None:
                result["superseded_decision_id"] = drive.superseded_decision_id
            if drive.superseded_intent_ids:
                result["superseded_intent_ids"] = list(drive.superseded_intent_ids)
            self.audit.record(
                "ACCOUNT_DECISION_DRIVEN", source="web.control",
                actor_type="OPERATOR", account_id=account_id,
                strategy_id=account.get("strategy_id"),
                strategy_version=account.get("strategy_version"),
                release_hash=account.get("release_hash"), symbol=account.get("symbol"),
                decision_id=decision["decision_id"], details=result,
            )
            return result
        except Exception as exc:
            self.audit.record(
                "ACCOUNT_DECISION_DRIVE_FAILED", source="web.control",
                outcome="FAILURE", actor_type="OPERATOR", account_id=account_id,
                strategy_id=account.get("strategy_id") if account else None,
                strategy_version=account.get("strategy_version") if account else None,
                release_hash=account.get("release_hash") if account else None,
                symbol=account.get("symbol") if account else None,
                details={"error": str(exc), "error_type": type(exc).__name__},
            )
            raise

    def status(self):
        channel = self.execution.status()
        accounts = [self.accounts.status(row["account_id"]) for row in self.store.strategy_virtual_accounts()]
        starts = [row["metrics"]["observation_start"] for row in accounts if row["metrics"]["observation_start"]]
        ends = [row["metrics"]["observation_end"] for row in accounts if row["metrics"]["observation_end"]]
        common_start = max(starts) if len(starts) == len(accounts) and accounts else None
        common_end = min(ends) if len(ends) == len(accounts) and accounts else None
        return {
            "environment": channel.get("environment"), "symbol": channel.get("symbol"),
            "channel": channel, "virtual_accounts": accounts,
            "default_account_id": accounts[0]["account_id"] if accounts else None,
            "comparison": {
                "common_start": common_start, "common_end": common_end,
                "priority_metrics": ["maximum_drawdown", "calmar_ratio", "win_loss_ratio", "total_return"],
                "accounts": [
                    {"account_id": row["account_id"], "name": row["name"], "metrics": row["metrics"]}
                    for row in accounts
                ],
            },
        }

    def pause(self): return self.execution.pause()
    def retire_account(self, request: AccountRetirementRequest) -> AccountRetirementResult:
        # Use the same lock order as decision generation: account engine, then store.
        with self.accounts._decision_lock:
            return self.execution.retire_account(request)
    def resume(self): return self.execution.resume()
    def issue_cancel_token(self, account_id, channel_order_id):
        return self.execution.issue_cancel_token(account_id, channel_order_id)
    def confirm_cancel(self, account_id, channel_order_id, token):
        return self.execution.confirm_cancel(account_id, channel_order_id, token)
    def acknowledge_execution_gap(self, account_id, intent_id, resolution_note):
        return self.execution.acknowledge_execution_gap(account_id, intent_id, resolution_note)
    def repair_account_ledger(self, account_id, intent_id):
        return self.execution.repair_account_ledger(account_id, intent_id)

    def _set_virtual_paused(self, account_id, paused):
        account = self.store.set_virtual_paused(account_id, paused)
        self.audit.record(
            "ACCOUNT_PAUSED" if paused else "ACCOUNT_RESUMED", source="web.control",
            actor_type="OPERATOR", account_id=account_id,
            strategy_id=account.get("strategy_id"), strategy_version=account.get("strategy_version"),
            release_hash=account.get("release_hash"), channel=FUTU_SIMULATE_CN_CHANNEL_ID,
        )
        return account

    def pause_virtual(self, account_id): return self._set_virtual_paused(account_id, True)
    def resume_virtual(self, account_id): return self._set_virtual_paused(account_id, False)

    def begin_shutdown(self):
        self.audit.record("RESTART_REQUESTED", source="web.control", actor_type="OPERATOR")
        self.accounts.begin_shutdown()
        self.execution.begin_shutdown()

    def close(self):
        if self.account_chart is not None:
            self.account_chart.close()
        self.execution.close()
