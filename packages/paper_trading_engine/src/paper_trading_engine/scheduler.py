"""Independent cadences for broker reconciliation and account strategy cycles."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import math
from threading import Event, RLock, Thread
from time import monotonic
from typing import Protocol
from collections.abc import Mapping

from execution_channels.futu.audit import AuditRecorder
from .account_chart import AccountChartService
from .chart_market_data import LEGACY_CHART_UPDATE_TIME
from execution_channels.futu.trading_window import SHANGHAI
from .scheduling_contracts import ScheduledDecision


class AccountScheduleProvider(Protocol):
    """Resolve actual calendar intervals and execute an account's due decision."""

    def due_decision(self, account: dict[str, object], observed_at: datetime) -> ScheduledDecision | None:
        ...

    def run_scheduled(self, account_id: str, task: ScheduledDecision, observed_at: datetime):
        ...


class ChannelOperations(Protocol):
    """The two independently retried polling operations of a channel account."""

    def refresh_account(self):
        ...

    def refresh_orders(self):
        ...


def _utc(moment: datetime, *, allow_legacy_naive: bool = False) -> datetime:
    if type(moment) is not datetime:
        raise TypeError("scheduler clock must be a datetime")
    if moment.utcoffset() is None:
        if not allow_legacy_naive:
            raise ValueError("scheduler clock must be timezone-aware")
        moment = moment.replace(tzinfo=SHANGHAI)
    return moment.astimezone(timezone.utc)


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
        schedule_provider: AccountScheduleProvider | None = None,
        max_account_workers: int = 4,
        channel_operations: Mapping[str, ChannelOperations] | None = None,
    ) -> None:
        self.engine = engine
        self.strategy_cycle = strategy_cycle
        self.store = store
        self.account_chart = account_chart
        self.schedule_provider = schedule_provider
        self.channel_operations = dict(channel_operations or {})
        if any(type(key) is not str or not key.strip() for key in self.channel_operations):
            raise ValueError("scheduled channels require explicit account identities")
        if any(not callable(getattr(operation, method, None))
               for operation in self.channel_operations.values()
               for method in ("refresh_account", "refresh_orders")):
            raise TypeError("scheduled channels must provide account and order refresh operations")
        if type(max_account_workers) is not int or max_account_workers < 1:
            raise ValueError("max_account_workers must be a positive integer")
        self.max_account_workers = max_account_workers
        self.order_interval = float(order_interval)
        self.account_interval = float(account_interval)
        self.data_prepare_interval = float(data_prepare_interval)
        if not all(math.isfinite(value) and value > 0 for value in (
            self.order_interval, self.account_interval, self.data_prepare_interval,
        )):
            raise ValueError("scheduler intervals must be positive and finite")
        # Legacy CN daily sessions close at 15:00; configuration cannot remove
        # the five-hour data completion window. Calendar providers own V4 times.
        self.preparation_time = max(time.fromisoformat(preparation_time), time(20))
        self.audit = audit or (
            AuditRecorder(store) if hasattr(store, "append_audit_event") else None
        )
        initial = None if initial_observation_at is None else self._clock(initial_observation_at)
        self._last_order = initial
        self._last_account = initial
        self._last_heartbeat = initial
        self._last_data_check: datetime | None = None
        self._last_chart_check: datetime | None = None
        self._daily_thread: Thread | None = None
        self._account_workers: dict[str, Thread] = {}
        self._schedule_lock = RLock()
        self._last_dispatched_account: str | None = None
        self._stopping = Event()
        self._failure_lock = RLock()
        self.shutdown_clean = True
        self._failures = self._restore_failures()
        self._retry_delays = (5, 15, 30, 60, 300)
        self.store.set_setting("scheduler_started_at", datetime.now(timezone.utc).isoformat())
        self.store.set_setting("scheduler_heartbeat_at", datetime.now(timezone.utc).isoformat())

    def _clock(self, moment: datetime) -> datetime:
        return _utc(moment, allow_legacy_naive=self.schedule_provider is None)

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
                    "first_at": _utc(datetime.fromisoformat(str(item["first_at"])), allow_legacy_naive=True),
                    "last_at": _utc(datetime.fromisoformat(str(item["last_at"])), allow_legacy_naive=True),
                    "next_retry": _utc(datetime.fromisoformat(str(item["next_retry"])), allow_legacy_naive=True),
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
        now = self._clock(now)
        self._heartbeat(now)
        if self._due(self._last_account, now, self.account_interval):
            if self.channel_operations:
                for channel_id, operations in self.channel_operations.items():
                    self._guard(f"account:{channel_id}", now, operations.refresh_account)
            else:
                self._guard("account", now, self.engine.refresh_account)
            self._last_account = now
        if self._due(self._last_order, now, self.order_interval):
            if self.channel_operations:
                for channel_id, operations in self.channel_operations.items():
                    self._guard(f"orders:{channel_id}", now, operations.refresh_orders)
            else:
                self._guard("orders", now, self.engine.refresh_orders)
            self._last_order = now

    def _account_cycle(
        self, account_id: str, signal_date, now: datetime
    ) -> None:
        if self.store.virtual_account(account_id)["run_state"] != "RUNNING":
            return
        self._guard(
            f"account_strategy_cycle:{account_id}",
            now,
            lambda: self.strategy_cycle.run(
                account_id, signal_date=signal_date, observed_at=now
            ),
        )

    def _scheduled_account_cycle(self, account: dict[str, object], now: datetime) -> None:
        account_id = str(account["account_id"])

        def perform():
            current = self.store.virtual_account(account_id)
            if current["run_state"] != "RUNNING":
                return
            task = self.schedule_provider.due_decision(current, now)
            if task is None:
                return
            if type(task) is not ScheduledDecision:
                raise TypeError("schedule provider must return ScheduledDecision or None")
            if not task.validity.start <= now < task.validity.end:
                raise ValueError("schedule provider returned a decision outside its valid window")
            key = f"last_account_schedule_task:{account_id}"
            if self.store.get_setting(key) == task.task_id:
                return
            previous = self.store.get_setting(f"last_account_schedule_at:{account_id}")
            if previous is not None and task.decision_at < _utc(datetime.fromisoformat(previous)):
                raise ValueError("scheduled decision cannot move backwards")
            if self.store.virtual_account(account_id)["run_state"] != "RUNNING":
                return
            self.schedule_provider.run_scheduled(account_id, task, now)
            if self.store.virtual_account(account_id)["run_state"] != "RUNNING":
                return
            self.store.set_setting(key, task.task_id)
            self.store.set_setting(f"last_account_schedule_at:{account_id}", _utc(task.decision_at).isoformat())

        self._guard(f"account_strategy_cycle:{account_id}", now, perform)

    def tick_daily(self, now: datetime) -> None:
        now = self._clock(now)
        with self._schedule_lock:
            self._tick_accounts(now)

    def _tick_accounts(self, now: datetime) -> None:
        if self._stopping.is_set():
            return
        local_now = now.astimezone(SHANGHAI)
        if (self.account_chart is not None
                and (self.schedule_provider is not None or local_now.time() >= LEGACY_CHART_UPDATE_TIME)
                and self._due(self._last_chart_check, now, self.data_prepare_interval)):
            self._guard("account_charts", now, lambda: self.account_chart.refresh_daily(now))
            self._last_chart_check = now
        if (
            (self.schedule_provider is None and local_now.time().replace(tzinfo=None) < self.preparation_time)
            or not self._due(self._last_data_check, now, self.data_prepare_interval)
        ):
            return
        for account_id, worker in tuple(self._account_workers.items()):
            if not worker.is_alive():
                worker.join()
                self._account_workers.pop(account_id, None)
        signal_date = local_now.date()
        accounts = self.store.strategy_virtual_accounts()
        identities = [str(account["account_id"]) for account in accounts]
        if self._last_dispatched_account in identities:
            offset = identities.index(self._last_dispatched_account) + 1
            accounts = accounts[offset:] + accounts[:offset]
        for account in accounts:
            if len(self._account_workers) >= self.max_account_workers:
                break
            if account["run_state"] != "RUNNING":
                continue
            account_id = str(account["account_id"])
            if account_id in self._account_workers:
                continue
            if self.schedule_provider is None:
                if self.store.get_setting(
                    f"last_account_decision_date:{account_id}"
                ) == signal_date.isoformat():
                    continue
                if self.store.get_setting(
                    f"last_account_schedule_skip_date:{account_id}"
                ) == signal_date.isoformat():
                    continue
            worker = Thread(
                target=self._account_cycle if self.schedule_provider is None else self._scheduled_account_cycle,
                args=(account_id, signal_date, now) if self.schedule_provider is None else (account, now),
                name=f"pte-strategy-{account_id}",
                daemon=True,
            )
            self._account_workers[account_id] = worker
            self._last_dispatched_account = account_id
            worker.start()
        self._last_data_check = now

    def run(self, stopped: Event) -> None:
        def run_daily() -> None:
            while not stopped.is_set():
                try:
                    self.tick_daily(datetime.now(timezone.utc))
                except Exception as exc:
                    self._record_cycle_failure(exc, "daily")
                stopped.wait(0.5)

        self._daily_thread = Thread(
            target=run_daily, name="pte-daily-scheduler", daemon=True,
        )
        self._daily_thread.start()
        while not stopped.is_set():
            try:
                self.tick_fast(datetime.now(timezone.utc))
            except Exception as exc:
                self._record_cycle_failure(exc, "fast")
            stopped.wait(0.5)
        self._stopping.set()
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
