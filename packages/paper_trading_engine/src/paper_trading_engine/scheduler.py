"""Independent cadences for broker reconciliation and account strategy cycles."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from threading import Event, RLock, Thread
from time import monotonic

from .audit import AuditRecorder
from .account_chart import AccountChartService
from .chart_market_data import CHART_UPDATE_TIME
from .trading_window import SHANGHAI, shanghai_now


class RuntimeScheduler:
    def __init__(
        self,
        engine,
        strategy_cycle,
        store,
        *,
        order_interval: float = 5,
        account_interval: float = 60,
        data_prepare_interval: float = 5,
        preparation_time: str = "20:30",
        audit: AuditRecorder | None = None,
        initial_observation_at: datetime | None = None,
        account_chart: AccountChartService | None = None,
    ) -> None:
        self.engine = engine
        self.strategy_cycle = strategy_cycle
        self.store = store
        self.account_chart = account_chart
        self.order_interval = float(order_interval)
        self.account_interval = float(account_interval)
        self.data_prepare_interval = float(data_prepare_interval)
        self.preparation_time = time.fromisoformat(preparation_time)
        self.audit = audit or (
            AuditRecorder(store) if hasattr(store, "append_audit_event") else None
        )
        self._last_order = initial_observation_at
        self._last_account = initial_observation_at
        self._last_heartbeat = initial_observation_at
        self._last_data_check: datetime | None = None
        self._last_chart_check: datetime | None = None
        self._daily_thread: Thread | None = None
        self._account_workers: dict[str, Thread] = {}
        self._failure_lock = RLock()
        self.shutdown_clean = True
        self._failures = self._restore_failures()
        self._retry_delays = (5, 15, 30, 60, 300)
        self.store.set_setting("scheduler_started_at", datetime.now(timezone.utc).isoformat())
        self.store.set_setting("scheduler_heartbeat_at", datetime.now(timezone.utc).isoformat())

    def _restore_failures(self) -> dict[str, dict[str, object]]:
        load = getattr(self.store, "operation_failures", None)
        if load is None:
            return {}
        restored: dict[str, dict[str, object]] = {}
        for item in load():
            try:
                restored[str(item["operation"])] = {
                    "fingerprint": str(item["fingerprint"]),
                    "count": int(item["failure_count"]),
                    "first_at": datetime.fromisoformat(str(item["first_at"])),
                    "last_at": datetime.fromisoformat(str(item["last_at"])),
                    "next_retry": datetime.fromisoformat(str(item["next_retry"])),
                }
            except (KeyError, TypeError, ValueError) as exc:
                operation = (
                    item.get("operation", "<unknown>")
                    if isinstance(item, dict)
                    else "<unknown>"
                )
                raise ValueError(
                    f"invalid persisted scheduler failure: {operation}"
                ) from exc
        return restored

    def _guard(self, name: str, now: datetime, operation) -> bool:
        with self._failure_lock:
            state = self._failures.get(name)
            if state is not None and now < state["next_retry"]:
                return False
        try:
            operation()
        except Exception as exc:
            with self._failure_lock:
                fingerprint = f"{type(exc).__name__}:{exc}"
                previous = self._failures.get(name)
                count = (
                    1
                    if previous is None or previous["fingerprint"] != fingerprint
                    else int(previous["count"]) + 1
                )
                first_at = now if count == 1 else previous["first_at"]
                delay = self._retry_delays[
                    min(count - 1, len(self._retry_delays) - 1)
                ]
                self._failures[name] = {
                    "fingerprint": fingerprint,
                    "count": count,
                    "first_at": first_at,
                    "last_at": now,
                    "next_retry": now + timedelta(seconds=delay),
                }
                persist = getattr(self.store, "set_operation_failure", None)
                if persist is not None:
                    persist(name, {
                        "error": str(exc), "fingerprint": fingerprint,
                        "failure_count": count, "first_at": first_at.isoformat(),
                        "last_at": now.isoformat(),
                        "next_retry": (now + timedelta(seconds=delay)).isoformat(),
                    })
                if count == 1:
                    details = {
                        "operation": name, "error": str(exc), "failure_count": count,
                        "first_at": now.isoformat(), "retry_after_seconds": delay,
                    }
                    if self.audit is not None:
                        self.audit.record(
                            "SCHEDULER_OPERATION_FAILED", source="scheduler",
                            outcome="FAILURE", actor_type="SCHEDULER", details=details,
                        )
                    else:
                        self.store.add_event("SCHEDULER_OPERATION_FAILED", details)
            return False
        else:
            with self._failure_lock:
                self.store.set_setting(f"last_{name}_success_at", now.isoformat())
                if name in self._failures:
                    previous = self._failures.pop(name)
                    details = {
                        "operation": name,
                        "previous_error": previous["fingerprint"],
                        "failure_count": previous["count"],
                        "first_at": previous["first_at"].isoformat(),
                        "last_at": previous["last_at"].isoformat(),
                    }
                    if self.audit is not None:
                        self.audit.record(
                            "SCHEDULER_OPERATION_RECOVERED", source="scheduler",
                            actor_type="SCHEDULER", details=details,
                        )
                    else:
                        self.store.add_event("SCHEDULER_OPERATION_RECOVERED", details)
                clear = getattr(self.store, "clear_operation_failure", None)
                if clear is not None:
                    clear(name)
            return True

    @staticmethod
    def _due(last: datetime | None, now: datetime, seconds: float) -> bool:
        return last is None or (now - last).total_seconds() >= seconds

    def tick(self, now: datetime) -> None:
        self.tick_fast(now)
        self.tick_daily(now)

    def _heartbeat(self, now: datetime) -> None:
        if self._due(self._last_heartbeat, now, 10):
            self.store.set_setting("scheduler_heartbeat_at", now.isoformat())
            self._last_heartbeat = now

    def tick_fast(self, now: datetime) -> None:
        self._heartbeat(now)
        if self._due(self._last_account, now, self.account_interval):
            self._guard("account", now, self.engine.refresh_account)
            self._last_account = now
        if self._due(self._last_order, now, self.order_interval):
            self._guard("orders", now, self.engine.refresh_orders)
            self._last_order = now

    def _account_cycle(
        self, account_id: str, signal_date, now: datetime
    ) -> None:
        self._guard(
            f"account_strategy_cycle:{account_id}",
            now,
            lambda: self.strategy_cycle.run(
                account_id, signal_date=signal_date, observed_at=now
            ),
        )

    def tick_daily(self, now: datetime) -> None:
        local_now = now if now.tzinfo is None else now.astimezone(SHANGHAI)
        if (self.account_chart is not None
                and local_now.time().replace(tzinfo=None) >= CHART_UPDATE_TIME
                and self._due(self._last_chart_check, now, self.data_prepare_interval)):
            self._guard("account_charts", now, lambda: self.account_chart.refresh_daily(now))
            self._last_chart_check = now
        if (
            local_now.time().replace(tzinfo=None) < self.preparation_time
            or not self._due(self._last_data_check, now, self.data_prepare_interval)
        ):
            return
        for account_id, worker in tuple(self._account_workers.items()):
            if not worker.is_alive():
                worker.join()
                self._account_workers.pop(account_id, None)
        signal_date = local_now.date()
        for account in self.store.strategy_virtual_accounts():
            if account.get("run_state") == "RETIRED":
                continue
            account_id = str(account["account_id"])
            if account_id in self._account_workers:
                continue
            if self.store.get_setting(
                f"last_account_decision_date:{account_id}"
            ) == signal_date.isoformat():
                continue
            if self.store.get_setting(
                f"last_account_schedule_skip_date:{account_id}"
            ) == signal_date.isoformat():
                continue
            worker = Thread(
                target=self._account_cycle,
                args=(account_id, signal_date, now),
                name=f"pte-strategy-{account_id}",
                daemon=True,
            )
            self._account_workers[account_id] = worker
            worker.start()
        self._last_data_check = now

    def run(self, stopped: Event) -> None:
        def run_daily() -> None:
            while not stopped.is_set():
                try:
                    self.tick_daily(shanghai_now())
                except Exception as exc:
                    self._record_cycle_failure(exc, "daily")
                stopped.wait(0.5)

        self._daily_thread = Thread(
            target=run_daily, name="pte-daily-scheduler", daemon=True,
        )
        self._daily_thread.start()
        while not stopped.is_set():
            try:
                self.tick_fast(shanghai_now())
            except Exception as exc:
                self._record_cycle_failure(exc, "fast")
            stopped.wait(0.5)
        self._daily_thread.join(timeout=25.0)
        deadline = monotonic() + 25.0
        for worker in tuple(self._account_workers.values()):
            worker.join(timeout=max(0.0, deadline - monotonic()))
        self.shutdown_clean = (
            not self._daily_thread.is_alive()
            and not any(worker.is_alive() for worker in self._account_workers.values())
        )

    def _record_cycle_failure(self, exc: Exception, lane: str) -> None:
        details = {
            "error": str(exc), "error_type": type(exc).__name__, "lane": lane,
        }
        if self.audit is not None:
            self.audit.record(
                "SCHEDULER_CYCLE_FAILED", source="scheduler", outcome="FAILURE",
                actor_type="SCHEDULER", details=details,
            )
        else:
            self.store.add_event("SCHEDULER_CYCLE_FAILED", details)
